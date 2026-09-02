"""analysis — LLM 분석의 입력 구성과 응답 검증 (SPEC F19·N13 v2, v3.0). 순수 함수.

v2.0의 `summary.py`는 공시 제목을 80자로 압축했다. v3.0은 세 갈래 증거로 신호를
검증한 **근거 서술**을 만든다 — 입력에 공시 본문·수급·코드가 낸 판정이 들어간다.

**LLM은 판정을 설명할 뿐 바꾸지 않는다.** 검증이 그 경계를 지킨다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from verify import analysis, verdict
from verify.models import (
    Anomaly,
    Disclosure,
    EventBody,
    Flag,
    FlowDay,
    InvestorFlows,
    NewsItem,
    SignalRow,
    VerdictInput,
)

D = date(2026, 8, 26)
EV = {
    "conditions": [{"label": "월봉 종가 > MA20", "ok": True, "actual": "9,500 vs 4,581"}],
    "price": {"close": 3980, "change_pct": 19.16},
}
CB = Disclosure(
    rcept_dt=D, report_nm="주요사항보고서(전환사채권발행결정)", rcept_no="cb1", flr_nm="씨피시스템"
)
QUARTERLY = Disclosure(rcept_dt=D, report_nm="반기보고서 (2026.06)", rcept_no="p1", flr_nm="x")
CB_FLAG = Flag(rule="cb", level="red", rcept_no="cb1", report_nm=CB.report_nm)
BODY = EventBody(
    rcept_no="cb1",
    event_type="cb_issuance",
    amount=10_000_000_000,
    use_of_funds=(("시설자금", 10_000_000_000),),
    method="사모",
    coupon_rate=0.0,
    conv_price=5106,
    overhang_pct=5.10,
    outstanding=23_420_000_000,
)
NEWS = (
    NewsItem(
        title="씨피시스템, 100억 규모 CB 발행…전액 제2공장 투입",
        link="https://n.news.naver.com/x",
        published=D,
        summary="조달자금은 전액 제2공장 설립에 필요한 시설투자에 사용될 예정이다.",
    ),
)
FLOWS = InvestorFlows(
    days=(
        FlowDay(d=date(2026, 8, 25), inst=64_565, foreign=56_140_446, indiv=-56_426_416),
        FlowDay(d=D, inst=-104_295, foreign=-1_139_791_314, indiv=1_131_306_196),
    )
)


SIG = SignalRow(d=D, strategy="mtf", ticker="413630", name="씨피시스템", evidence=EV)


def brief(level: str = "none", **kw: object) -> VerdictInput:
    """증거 한 종목. 선행은 `Briefing` 하나였고 여기서는 신호와 증거가 나뉜다 (V11)."""
    base: dict[str, object] = {"level": level, "disclosures": (QUARTERLY,)}
    base.update(kw)
    return VerdictInput(**base)  # type: ignore[arg-type]


def red() -> VerdictInput:
    return brief("red", disclosures=(CB, QUARTERLY), flags=(CB_FLAG,), bodies=(BODY,),
                 news=NEWS, flows=FLOWS, anomaly=Anomaly(score=0, verdict="clean"))


def one(b: VerdictInput) -> dict[str, Any]:
    (item,) = analysis.build_input([(SIG, b, verdict.judge(b))])
    return item


# ── 입력 구성 (F19) ──────────────────────────────────────────────


def test_skips_stocks_with_nothing_to_check() -> None:
    assert analysis.build_input([(SIG, brief(disclosures=()), None)]) == []


def test_skips_stocks_we_could_not_look_up() -> None:
    assert analysis.build_input([(SIG, brief("error"), None), (SIG, brief("unknown"), None)]) == []


def test_carries_the_chart_signal_being_checked() -> None:
    """무엇을 검증하는지 모르면 검증할 수 없다."""
    item = one(brief())
    assert item["signal"]["strategy"] == "mtf"
    assert item["signal"]["conditions"][0]["label"] == "월봉 종가 > MA20"


def test_marks_which_disclosures_were_flagged() -> None:
    item = one(red())
    flagged = [d for d in item["disclosures"] if d.get("flag")]
    assert [d["title"] for d in flagged] == [CB.report_nm]
    assert item["risk_count"] == 1


def test_carries_the_filing_body_in_units_a_model_can_hold() -> None:
    """원 단위 큰 숫자를 그대로 주면 모델이 자릿수를 흘린다 — 억으로 바꿔 준다."""
    (body,) = one(red())["bodies"]
    assert body["amount_eok"] == 100.0
    assert body["use_of_funds"] == [["시설자금", 100.0]]
    assert body["overhang_pct"] == 5.10
    assert body["outstanding_eok"] == 234.2
    assert body["method"] == "사모"


def test_bodies_come_biggest_overhang_first() -> None:
    small = EventBody(rcept_no="cb2", event_type="cb_issuance", overhang_pct=1.0)
    b = brief("red", disclosures=(CB,), flags=(CB_FLAG,), bodies=(small, BODY))
    assert [x["overhang_pct"] for x in one(b)["bodies"]] == [5.10, 1.0]


def test_carries_news_with_its_summary() -> None:
    """기사 요약이 분석의 주재료다 — 자금 용도가 거기 있다."""
    (news,) = one(red())["news"]
    assert "제2공장" in news["summary"]


def test_carries_flows_as_totals_and_recent_days() -> None:
    flows = one(red())["flows"]
    assert flows["unit"] == "억원"
    assert flows["total_30d"]["foreign"] == round(
        (56_140_446 - 1_139_791_314) / 1e8, 1
    )
    assert [x["date"] for x in flows["recent"]] == ["08/25", "08/26"]


def test_carries_the_verdict_the_code_computed() -> None:
    """모델은 이것을 설명한다 — 다시 계산하지 않는다."""
    item = one(red())
    assert item["verdict"]["stand"] in verdict.STANDS
    assert isinstance(item["verdict"]["score"], int)
    assert item["verdict"]["parts"]


def test_omits_absent_layers_rather_than_sending_empty_shells() -> None:
    item = one(brief())
    for key in ("bodies", "news", "flows", "risk_count"):
        assert key not in item


def test_caps_the_disclosure_list() -> None:
    many = tuple(
        Disclosure(rcept_dt=D, report_nm=f"공시{i}", rcept_no=str(i), flr_nm="x")
        for i in range(30)
    )
    assert len(one(brief(disclosures=many))["disclosures"]) == analysis.MAX_DISCLOSURES


# ── 프롬프트 (R21) ───────────────────────────────────────────────


def test_the_prompt_says_the_cap_is_not_a_target() -> None:
    """재료가 얇은데 2,000자를 채우려 들면 지어낸다 — 건수를 날조한 것과 같은 실패."""
    assert "상한이지 목표가 아니다" in analysis.SYSTEM_PROMPT


def test_the_prompt_forbids_changing_the_verdict() -> None:
    assert "바꾸지 않는다" in analysis.SYSTEM_PROMPT


def test_the_prompt_lists_every_forbidden_word() -> None:
    """프롬프트가 규칙을 말하지 않으면 **검증기가 뒤에서 계속 버리기만 한다.**

    N1(매매 판단)과 N2(적중 문구) **둘 다** 적혀 있어야 한다 — 규칙이 세 곳에
    같은 내용으로 있어야 한다: 프롬프트 · 출력 검증 · 렌더 (N1).
    """
    from verify.wording import FORBIDDEN, FORBIDDEN_OUTCOME

    for word in FORBIDDEN:
        assert word in analysis.SYSTEM_PROMPT, f"N1 금지어가 프롬프트에 없다: {word}"
    for word in FORBIDDEN_OUTCOME:
        assert word in analysis.SYSTEM_PROMPT, f"N2 금지어가 프롬프트에 없다: {word}"


def test_the_schema_asks_for_a_reason_per_ticker() -> None:
    props = analysis.OUTPUT_SCHEMA["properties"]["items"]["items"]["properties"]
    assert set(props) == {"ticker", "reason"}


# ── 검증 (N13 v2) ────────────────────────────────────────────────


def ok_payload(text: str, ticker: str = "413630") -> dict[str, Any]:
    return {"items": [{"ticker": ticker, "reason": text}]}


def test_keeps_a_clean_reason() -> None:
    kept, dropped = analysis.validate(ok_payload("08/26 전환사채 100억 발행 결정."), ["413630"])
    assert kept == {"413630": "08/26 전환사채 100억 발행 결정."} and dropped == []


@pytest.mark.parametrize("word", ["매수", "매도", "목표가", "손절", "진입", "비중", "보류"])
def test_drops_a_reason_that_gives_trade_advice(word: str) -> None:
    kept, dropped = analysis.validate(ok_payload(f"근거는 충분하다. {word} 판단."), ["413630"])
    assert kept == {} and word in dropped[0]


def test_allows_direction_words_that_v2_forbade() -> None:
    """`호재`·`악재`는 근거의 방향을 말하는 데 필요하다 (N1 v2·D24)."""
    kept, _ = analysis.validate(ok_payload("수급은 악재로 읽힌다."), ["413630"])
    assert kept


def test_drops_a_reason_longer_than_the_cap() -> None:
    kept, dropped = analysis.validate(ok_payload("가" * (analysis.MAX_LEN + 1)), ["413630"])
    assert kept == {} and "길이" in dropped[0]


def test_a_long_but_allowed_reason_survives() -> None:
    kept, _ = analysis.validate(ok_payload("가" * analysis.MAX_LEN), ["413630"])
    assert kept


def test_drops_an_unknown_ticker() -> None:
    kept, dropped = analysis.validate(ok_payload("x", "999999"), ["413630"])
    assert kept == {} and "미지 티커" in dropped[0]


def test_drops_an_empty_reason() -> None:
    kept, dropped = analysis.validate(ok_payload("   "), ["413630"])
    assert kept == {} and "빈 문자열" in dropped[0]


# ── 판정을 바꾸면 버린다 (F18) ───────────────────────────────────


def test_drops_a_reason_that_states_a_different_verdict() -> None:
    """LLM은 설명한다. 결론을 바꾸면 그 서술은 쓸 수 없다."""
    kept, dropped = analysis.validate(
        ok_payload("세 갈래가 신호와 정합이다."), ["413630"], stands={"413630": "불일치"}
    )
    assert kept == {} and "판정을" in dropped[0]


def test_keeps_a_reason_that_repeats_the_code_verdict() -> None:
    kept, _ = analysis.validate(
        ok_payload("수급이 거스른다 — 불일치."), ["413630"], stands={"413630": "불일치"}
    )
    assert kept


# ── 숫자 대조 ────────────────────────────────────────────────────


def test_drops_a_fabricated_risk_count() -> None:
    """2026-08-30: 플래그 1건인 종목의 요약이 '위험 유형 2건'이라고 적었다."""
    kept, dropped = analysis.validate(
        ok_payload("최근 30일 위험 유형 2건."), ["413630"], risk_counts={"413630": 1}
    )
    assert kept == {} and "건수" in dropped[0]


def test_keeps_a_correct_risk_count() -> None:
    kept, _ = analysis.validate(
        ok_payload("최근 30일 위험 유형 1건."), ["413630"], risk_counts={"413630": 1}
    )
    assert kept


def test_drops_an_overhang_percent_that_was_never_in_the_input() -> None:
    kept, dropped = analysis.validate(
        ok_payload("전환 시 발행주식의 18.63%가 늘어난다."),
        ["413630"],
        overhangs={"413630": {5.10}},
    )
    assert kept == {} and "18.63" in dropped[0]


def test_keeps_the_overhang_percent_that_was_in_the_input() -> None:
    kept, _ = analysis.validate(
        ok_payload("전환 시 발행주식의 5.10%가 늘어난다."),
        ["413630"],
        overhangs={"413630": {5.10}},
    )
    assert kept


def test_a_percent_unrelated_to_overhang_is_left_alone() -> None:
    """퍼센트는 등락률·지분율에도 쓰인다. 아무 `%`나 잡으면 멀쩡한 서술을 버린다."""
    kept, _ = analysis.validate(
        ok_payload("당일 주가가 19.16% 올랐다."), ["413630"], overhangs={"413630": {5.10}}
    )
    assert kept


def test_a_malformed_payload_yields_nothing() -> None:
    assert analysis.validate({"items": "x"}, ["413630"]) == ({}, [])
    kept, dropped = analysis.validate({"items": ["x"]}, ["413630"])
    assert kept == {} and dropped


# ── 사실 표현은 금지어가 아니다 (2026-08-30 실호출) ──────────────


def test_net_buying_and_selling_are_not_trade_advice() -> None:
    """`순매도`가 `매도`에 걸려 분석문이 통째로 버려졌다 — 수급을 말하는 유일한 말이다."""
    for text in (
        "30일 기관·외국인 순매도(-8)다.",
        "공시일에 기관이 순매수했다.",
        "매수세가 유입됐다.",
        "상위 20개 계좌 매수관여율 31.45%",
    ):
        kept, dropped = analysis.validate(ok_payload(text), ["413630"])
        assert kept, f"버려지면 안 된다: {text} · {dropped}"


def test_trade_advice_is_still_blocked_even_next_to_a_fact() -> None:
    """예외는 합성어 형태에만 준다 — 판단은 그대로 막힌다."""
    kept, dropped = analysis.validate(
        ok_payload("외국인 순매도가 이어진다. 지금은 매도 판단이 맞다."), ["413630"]
    )
    assert kept == {} and "매도" in dropped[0]


def test_a_coupon_rate_beside_a_conversion_word_is_not_an_overhang() -> None:
    """"표면이자 4.0%에 시가하락 시 전환가 조정 조항"이 버려졌다 (2026-08-31 실호출).

    `전환사채`·`전환가`에도 `전환`이 있어 단서가 되지 못한다.
    """
    kept, _ = analysis.validate(
        ok_payload("표면이자 4.0%에 시가하락 시 전환가 조정 조항이 붙어 있다."),
        ["413630"],
        overhangs={"413630": {18.63}},
    )
    assert kept


def test_an_overhang_percent_is_still_checked() -> None:
    kept, dropped = analysis.validate(
        ok_payload("잠재 물량 9.99%가 발생한다."), ["413630"], overhangs={"413630": {18.63}}
    )
    assert kept == {} and "9.99" in dropped[0]


def test_two_percentages_in_one_sentence_are_told_apart() -> None:
    """한 문장에 오버행과 이자율이 함께 있어도 오버행만 검사한다 (2026-08-31 실호출)."""
    said = (
        "하나는 120억원 사모 CB로 전환가 1,519원, 발행주식 대비 18.63%다. "
        "두 건 모두 표면이자 4.0%에 시가하락 시 전환가 조정 조항이 붙어 있다."
    )
    kept, dropped = analysis.validate(
        ok_payload(said), ["413630"], overhangs={"413630": {18.63}}
    )
    assert kept, dropped
