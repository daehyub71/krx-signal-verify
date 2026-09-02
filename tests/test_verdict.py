"""verdict — 신호 검증 판정과 점수 (SPEC F18, v3.0). 순수 함수.

**점수는 코드가 낸다.** LLM에 숫자를 물으면 지어낸다 — 2026-08-30에 플래그 1건인 종목의
요약이 "위험 유형 2건"이라 적었다. 그래서 산식을 여기서 고정한다.

가중치를 바꾸면 이 테스트가 깨진다. 그것이 목적이다 — 점수가 조용히 달라지면
어제의 60과 오늘의 60이 다른 뜻이 된다.
"""

from __future__ import annotations

from datetime import date

import pytest

from verify import verdict
from verify.models import (
    Anomaly,
    Disclosure,
    EventBody,
    Flag,
    FlowDay,
    InvestorFlows,
    VerdictInput,
)

D = date(2026, 8, 26)


def brief(level: str = "none", **kw: object) -> VerdictInput:
    """판정 입력 하나. 선행 테스트를 그대로 옮기되 입력 타입만 바꿨다 (V11)."""
    base: dict[str, object] = {
        "level": level,
        "disclosures": (
            Disclosure(rcept_dt=D, report_nm="반기보고서 (2026.06)", rcept_no="p1", flr_nm="x"),
        ),
    }
    base.update(kw)
    return VerdictInput(**base)  # type: ignore[arg-type]


CB = Disclosure(
    rcept_dt=D, report_nm="주요사항보고서(전환사채권발행결정)", rcept_no="cb1", flr_nm="x"
)
CB_FLAG = Flag(rule="cb", level="red", rcept_no="cb1", report_nm=CB.report_nm)


def flows(*rows: tuple[int, int, int]) -> InvestorFlows:
    return InvestorFlows(
        days=tuple(FlowDay(d=date(2026, 8, day), inst=i, foreign=f) for day, i, f in rows)
    )


# ── 판정 세 가지 ─────────────────────────────────────────────────


def test_no_evidence_at_all_is_silent_at_neutral() -> None:
    """모르는 것을 낮은 점수로 바꾸지 않는다."""
    v = verdict.judge(brief(disclosures=()))
    assert v.stand == verdict.STAND_SILENT
    assert v.score == verdict.NEUTRAL
    assert v.parts == ()


def test_a_clean_filing_history_corroborates() -> None:
    v = verdict.judge(brief())
    assert v.stand == verdict.STAND_CORROBORATES
    assert v.score == verdict.NEUTRAL + verdict.W_NO_RISK


def test_a_big_overhang_contradicts() -> None:
    """엔투텍 08/26 — 잠재 물량 18.63%."""
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=18.63),),
        )
    )
    assert v.stand == verdict.STAND_CONTRADICTS
    assert v.score == verdict.NEUTRAL - 8 - 19  # 🔴 하나 + 오버행 19


def test_the_same_filing_title_scores_differently_by_its_body() -> None:
    """씨피시스템 08/26 — 5.10%. 엔투텍과 **제목이 같은데** 점수가 14점 벌어진다.

    판정은 둘 다 `불일치`지만 점수가 다르다. 그 차이가 본문을 읽는 이유다.
    """
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=5.10),),
        )
    )
    assert v.score == verdict.NEUTRAL - 8 - 5  # 37
    assert v.stand == verdict.STAND_CONTRADICTS
    assert v.score - (verdict.NEUTRAL - 8 - 19) == 14  # 엔투텍 23과의 거리


# ── 산식 고정 ────────────────────────────────────────────────────


def test_flag_penalty_has_a_floor() -> None:
    """플래그가 열 건이어도 감산은 하한에서 멈춘다 — 건수가 곧 위험도는 아니다."""
    flags = tuple(
        Flag(rule="cb", level="red", rcept_no=str(i), report_nm="x") for i in range(10)
    )
    v = verdict.judge(brief("red", disclosures=(CB,), flags=flags))
    (part,) = [p for p in v.parts if "위험 유형" in p.label]
    assert part.delta == verdict.FLAG_FLOOR


def test_overhang_penalty_has_a_cap() -> None:
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=90.0),),
        )
    )
    (part,) = [p for p in v.parts if "잠재 물량" in p.label]
    assert part.delta == verdict.W_OVERHANG_CAP


def test_refix_and_private_placement_each_subtract() -> None:
    body = EventBody(
        rcept_no="cb1", event_type="cb_issuance", refix_floor=1064, method="사모"
    )
    v = verdict.judge(brief("red", disclosures=(CB,), flags=(CB_FLAG,), bodies=(body,)))
    labels = {p.label: p.delta for p in v.parts}
    assert labels["시가하락 시 전환가 조정 조항"] == verdict.W_REFIX
    assert labels["사모 발행"] == verdict.W_PRIVATE


@pytest.mark.parametrize(
    ("state", "delta"), [("warning", -6), ("watch", -3), ("red_flag", -10), ("clean", 0)]
)
def test_anomaly_verdict_weights(state: str, delta: int) -> None:
    v = verdict.judge(brief(anomaly=Anomaly(score=1, verdict=state)))
    got = {p.label: p.delta for p in v.parts}
    if delta:
        assert got[f"공시 이상 {state}"] == delta
    else:
        assert not [p for p in v.parts if "공시 이상" in p.label]


def test_score_never_leaves_the_scale() -> None:
    flags = tuple(
        Flag(rule="cb", level="red", rcept_no=str(i), report_nm="x") for i in range(50)
    )
    body = EventBody(rcept_no="cb1", event_type="cb_issuance", overhang_pct=99.0, method="사모")
    v = verdict.judge(brief("red", disclosures=(CB,), flags=flags, bodies=(body,)))
    assert 0 <= v.score <= 100


# ── 수급 (F17) ───────────────────────────────────────────────────


def test_thirty_day_net_buying_adds() -> None:
    v = verdict.judge(brief(flows=flows((25, 10, 20), (26, 5, 5))))
    assert {p.label: p.delta for p in v.parts}["30일 기관·외국인 순매수"] == verdict.W_FLOW_30D


def test_thirty_day_net_selling_subtracts() -> None:
    v = verdict.judge(brief(flows=flows((25, -10, -20))))
    assert {p.label: p.delta for p in v.parts}["30일 기관·외국인 순매도"] == -verdict.W_FLOW_30D


def test_the_filing_day_is_weighed_separately() -> None:
    """씨피시스템: 5일 내내 외국인이 사다가 CB 공시일에 정확히 뒤집혔다."""
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            flows=flows((25, 0, 100), (26, -104_295, -1_139_791_314)),
        )
    )
    labels = {p.label: p.delta for p in v.parts}
    # 상수로 검사하면 자기참조가 된다 — 값을 바꿔도 양쪽이 함께 움직여 통과한다
    assert labels["08/26 공시일 기관·외국인 순매도"] == -6


def test_a_day_with_no_flow_row_is_simply_skipped() -> None:
    v = verdict.judge(brief("red", disclosures=(CB,), flags=(CB_FLAG,), flows=flows((20, 1, 1))))
    assert not [p for p in v.parts if "공시일" in p.label]


# ── 사각지대 — 항상 함께 나간다 (R20) ────────────────────────────


def test_blind_spots_always_name_what_no_score_can_see() -> None:
    v = verdict.judge(brief())
    for word in verdict.ALWAYS_BLIND:
        assert word in v.blind_spots


def test_blind_spots_name_the_missing_layers_first() -> None:
    """빠진 층을 앞에 둔다. **이 프로젝트에서 재무·공매도 둘이 늘었다** (F30·F32)."""
    v = verdict.judge(brief())
    assert v.blind_spots[:5] == ("재무", "공매도", "수급", "뉴스", "공시 이상 점수")


def test_a_full_briefing_reports_only_the_permanent_blind_spots() -> None:
    v = verdict.judge(
        brief(
            "red",
            disclosures=(CB,),
            flags=(CB_FLAG,),
            bodies=(EventBody(rcept_no="cb1", event_type="cb_issuance"),),
            news=("뉴스 한 건",),
            flows=flows((26, 1, 1)),
            anomaly=Anomaly(score=0, verdict="clean"),
            financial=object(),
            shorting=object(),
        )
    )
    assert v.blind_spots == verdict.ALWAYS_BLIND


def test_the_price_after_the_disclosure_is_no_longer_a_blind_spot() -> None:
    """**F10b — 이제 우리가 그것을 본다** (F22~F24).

    선행은 「공시 이후의 주가」를 못 보는 것으로 적었다. 이 프로젝트는 5·20·60거래일 뒤
    초과수익으로 그것을 재므로 목록에서 뺐다 — 빠진 만큼 **나머지를 더 분명히** 적는다.
    """
    assert "공시 이후의 주가" not in verdict.ALWAYS_BLIND
    v = verdict.judge(brief())
    assert "공시 이후의 주가" not in v.blind_spots
    assert "공시 이후의 주가" not in v.limit_note


def test_new_lanes_are_named_but_not_scored_yet() -> None:
    """재무·공매도는 **아직 점수에 넣지 않는다** — 가중치는 M2에서 정한다.

    없는 근거를 만들지 않는다: 지금은 「보지 않았다」고만 적는다.
    """
    without = verdict.judge(brief())
    with_lanes = verdict.judge(brief(financial=object(), shorting=object()))
    assert with_lanes.score == without.score
    assert "재무" in without.blind_spots and "재무" not in with_lanes.blind_spots


def test_the_limit_note_is_always_available() -> None:
    note = verdict.judge(brief()).limit_note
    assert "근거를 재며" in note and "실적·밸류에이션" in note


# ── 조회 실패·코드 미확인 ────────────────────────────────────────


@pytest.mark.parametrize("level", ["error", "unknown"])
def test_a_stock_we_could_not_look_up_is_silent(level: str) -> None:
    """공시를 못 봤으면 판정하지 않는다 — 침묵을 불일치로 바꾸지 않는다."""
    v = verdict.judge(brief(level))
    assert v.stand == verdict.STAND_SILENT and v.score == verdict.NEUTRAL and v.parts == ()


def test_the_stand_is_one_of_three() -> None:
    assert set(verdict.STANDS) == {"정합", "불일치", "무관"}


# ── 산식이 곧 SPEC이다 — 가중치를 바꾸면 여기가 먼저 깨진다 ──────
#
# 2026-09-02 변이 검사에서 **14개 상수 중 10개를 이식된 테스트가 못 잡았다.**
# 원인 둘: ① 그 지렛대를 건드리는 표본이 없었다 ② `v.score == verdict.NEUTRAL`처럼
# **상수를 상수로 검사**해 자기참조가 됐다 — 값을 바꾸면 양쪽이 함께 움직여 통과한다.
#
# 그래서 아래는 **숫자를 그대로 적는다.** 읽기 불편해도 이게 잠금장치다.


def _one_body(**kw: object) -> tuple[EventBody, ...]:
    return (EventBody(rcept_no="cb1", event_type="cb_issuance", **kw),)  # type: ignore[arg-type]


def test_neutral_is_fifty() -> None:
    """증거가 하나도 없으면 중립. **모르는 것을 낮은 점수로 바꾸지 않는다.**"""
    v = verdict.judge(VerdictInput())
    assert v.score == 50
    assert v.stand == "무관"


def test_overhang_subtracts_one_point_per_percent_and_stops_at_25() -> None:
    """잠재 물량 1%당 1점. 하한 -25 — 건수가 많다고 무한히 내려가지 않는다.

    `disclosures=()`로 둔다 — 공시가 있으면 `W_NO_RISK`(+10)가 함께 걸려 지렛대가 섞인다.
    """
    v9 = verdict.judge(brief(disclosures=(), bodies=_one_body(overhang_pct=9.0)))
    assert v9.score == 50 - 9
    v40 = verdict.judge(brief(disclosures=(), bodies=_one_body(overhang_pct=40.0)))
    assert v40.score == 50 - 25, "하한이 -25가 아니다"


def test_refix_clause_subtracts_five() -> None:
    """시가가 내리면 전환가도 내린다 — 물량이 더 늘 수 있다는 조항."""
    v = verdict.judge(brief(disclosures=(), bodies=_one_body(refix_floor=700)))
    assert v.score == 50 - 5


def test_private_placement_subtracts_three() -> None:
    v = verdict.judge(brief(disclosures=(), bodies=_one_body(method="무보증 사모 전환사채")))
    assert v.score == 50 - 3


def test_thirty_day_flow_moves_eight_either_way() -> None:
    """수급은 **방향만** 본다 — 금액의 크기는 점수에 넣지 않는다."""
    buy = verdict.judge(brief(disclosures=(), flows=flows((20, 5_000_000_000, 0))))
    assert buy.score == 50 + 8
    sell = verdict.judge(brief(disclosures=(), flows=flows((20, -5_000_000_000, 0))))
    assert sell.score == 50 - 8
    big = verdict.judge(brief(disclosures=(), flows=flows((20, 900_000_000_000, 0))))
    assert big.score == 50 + 8, "금액 크기가 점수를 움직인다"


def test_no_confirmed_risk_adds_ten() -> None:
    """「위험 유형 없음」은 **「리스크 없음」이 아니다** — 확인된 유형이 없다는 사실이다."""
    assert verdict.judge(brief()).score == 50 + 10


def test_news_explaining_a_flagged_disclosure_adds_three() -> None:
    v = verdict.judge(brief("red", disclosures=(CB,), flags=(CB_FLAG,), news=("설명하는 기사",)))
    assert v.score == 50 - 8 + 3


def test_corroborates_threshold_is_sixty() -> None:
    """60 이상이면 정합. **59는 아니다.**"""
    at60 = brief()  # 위험 유형 없음 +10
    assert verdict.judge(at60).score == 60
    assert verdict.judge(at60).stand == "정합"
    at59 = brief(bodies=_one_body(overhang_pct=1.0))  # +10 -1
    assert verdict.judge(at59).score == 59
    assert verdict.judge(at59).stand == "무관", "경계가 60이 아니다"


def test_contradicts_threshold_is_forty() -> None:
    """40 이하면 불일치. **41은 아니다.**"""
    at40 = brief("red", disclosures=(CB,), flags=(CB_FLAG,), bodies=_one_body(overhang_pct=2.0))
    assert verdict.judge(at40).score == 40
    assert verdict.judge(at40).stand == "불일치"
    at41 = brief("red", disclosures=(CB,), flags=(CB_FLAG,), bodies=_one_body(overhang_pct=1.0))
    assert verdict.judge(at41).score == 41
    assert verdict.judge(at41).stand == "무관", "경계가 40이 아니다"


def test_amber_flag_subtracts_four() -> None:
    """🟡 하나당 -4. 🔴(-8)의 절반이다."""
    amber = Flag(rule="lawsuit", level="amber", rcept_no="a1", report_nm="소송등의제기")
    v = verdict.judge(brief("amber", disclosures=(), flags=(amber,)))
    assert v.score == 50 - 4


def test_flag_subtraction_stops_at_the_floor() -> None:
    """🔴 넷이면 -32이지만 **하한 -24에서 멈춘다** — 건수가 많다고 무한히 내려가지 않는다.

    셋(-24)까지는 하한과 값이 같아 구분이 안 된다. **넷이어야 하한이 드러난다.**
    """
    title = "주요사항보고서(전환사채권발행결정)"
    four = tuple(
        Flag(rule="cb", level="red", rcept_no=f"r{i}", report_nm=title) for i in range(4)
    )
    v = verdict.judge(brief("red", disclosures=(), flags=four))
    assert v.score == 50 - 24, "하한이 -24가 아니다"
    assert [p.delta for p in v.parts] == [-24]
