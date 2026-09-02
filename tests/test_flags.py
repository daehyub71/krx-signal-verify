"""flags — report_nm 정규화 · 규칙표 · 판정. 순수 함수.

원칙: **규칙마다 양성 1 + 헷갈리는 음성 1.**
키워드 하나를 지워도 통과하면 그 규칙은 검증되지 않은 것이다.
제목은 전부 `tests/fixtures/report_names.txt`(2026-08-29 실표본)에 있는 실제 형태다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from verify import flags
from verify.flags import RULES, Match, classify, match, normalize
from verify.models import Disclosure

FIXTURES = Path(__file__).parent / "fixtures"


def disc(report_nm: str, rcept_no: str = "20260822000123", day: int = 22) -> Disclosure:
    return Disclosure(
        rcept_dt=date(2026, 8, day), report_nm=report_nm, rcept_no=rcept_no, flr_nm="x"
    )


# ── normalize ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "name", "corrected", "note"),
    [
        ("유상증자결정", "유상증자결정", False, ""),
        ("[기재정정]주요사항보고서(유상증자결정)", "주요사항보고서(유상증자결정)", True, ""),
        ("[정정]유상증자결정", "유상증자결정", True, ""),
        ("[첨부정정]주요사항보고서(회사합병결정)", "주요사항보고서(회사합병결정)", True, ""),
        ("[정정제출요구]증권신고서(합병)", "증권신고서(합병)", True, ""),
        # 정정이 아닌 접두 — 떼되 corrected는 아니다
        (
            "[발행조건확정]주요사항보고서(전환사채권발행결정)",
            "주요사항보고서(전환사채권발행결정)",
            False,
            "",
        ),
        ("[첨부추가]주요사항보고서(회사합병결정)", "주요사항보고서(회사합병결정)", False, ""),
        # 공백은 전부 지운다 — "유상증자 결정"도 같은 것
        ("유상증자 결정", "유상증자결정", False, ""),
        ("분기보고서 (2026.03)", "분기보고서(2026.03)", False, ""),
        # 가운뎃점은 하나로 통일
        ("횡령ㆍ배임혐의발생", "횡령·배임혐의발생", False, ""),
        ("횡령·배임혐의발생", "횡령·배임혐의발생", False, ""),
        # 뒤에 공백 여러 칸 + 괄호 설명 → note로 분리
        ("주권매매거래정지              (무상증자)", "주권매매거래정지", False, "무상증자"),
        (
            "기타시장안내(관리종목지정우려종목)              (시가총액 200억원 미달)",
            "기타시장안내(관리종목지정우려종목)",
            False,
            "시가총액 200억원 미달",
        ),
        (
            "감사보고서제출              (감사의견 의견거절)",
            "감사보고서제출",
            False,
            "감사의견 의견거절",
        ),
        ("  앞뒤공백  ", "앞뒤공백", False, ""),
    ],
)
def test_normalize(raw: str, name: str, corrected: bool, note: str) -> None:
    n = normalize(raw)
    assert (n.name, n.corrected, n.note) == (name, corrected, note)


# ── 규칙표 — 규칙당 양성 1 + 음성 1 ─────────────────────────────

# rule → (양성 제목, 헷갈리는 음성 제목).
# 음성은 "이 규칙에는 걸리면 안 되는" 것이지 무해하다는 뜻이 아니다.
SAMPLES: dict[str, tuple[str, str]] = {
    # 🔴
    "cb": (
        "[기재정정]주요사항보고서(전환사채권발행결정)",
        "전환사채(해외전환사채포함)발행후만기전사채취득",
    ),
    "bw": ("주요사항보고서(신주인수권부사채권발행결정)", "신주인수권행사              (제15회차)"),
    "eb": ("주요사항보고서(교환사채권발행결정)", "전환청구권ㆍ신주인수권ㆍ교환청구권행사"),
    "rights_issue": (
        "주요사항보고서(유상증자결정)",
        "유상증자또는주식관련사채등의발행결과(자율공시)",
    ),
    "controller_change": ("최대주주변경", "최대주주등소유주식변동신고서"),
    "admin_issue": ("관리종목지정", "기타시장안내(관리종목지정우려종목)"),
    "caution_issue": ("투자주의환기종목지정", "투자주의환기종목지정해제"),
    "unfaithful": ("불성실공시법인지정", "불성실공시법인지정예고              (공시불이행)"),
    "delisting": ("상장폐지결정", "상장폐지사유해소"),
    "embezzlement": ("횡령ㆍ배임혐의발생", "임원ㆍ주요주주특정증권등소유상황보고서"),
    "rehabilitation": ("회생절차개시신청", "회생절차종결"),
    "audit": ("감사보고서제출              (감사의견 의견거절)", "감사보고서제출"),
    # 🟡
    "trading_halt": (
        "주권매매거래정지              (자본감소)",
        "주권매매거래정지해제              (감자 주권 변경상장)",
    ),
    "lawsuit": ("소송등의제기ㆍ신청(경영권분쟁소송)", "소송등의판결ㆍ결정"),
    "treasury_sale": ("주요사항보고서(자기주식처분결정)", "자기주식처분결과보고서"),
    "pledge": ("최대주주변경을수반하는주식담보제공계약체결", "최대주주변경"),
    "admin_warning": (
        "기타시장안내(관리종목지정우려종목)              (주가 1,000원 미달)",
        "관리종목지정",
    ),
    "unfaithful_warning": (
        "불성실공시법인지정예고              (공시불이행 2건)",
        "불성실공시법인미지정              (지정유예)",
    ),
    "market_warning": ("투자경고종목지정", "투자경고종목지정해제"),
    "capital_reduction": ("주요사항보고서(감자결정)", "감자완료"),
}


def test_every_rule_has_samples() -> None:
    """규칙을 추가하면 표본도 추가해야 한다 — 검증되지 않은 규칙이 규칙표에 들어오지 못하게."""
    assert {r.id for r in RULES} == set(SAMPLES)


@pytest.mark.parametrize("rule_id", list(SAMPLES))
def test_rule_positive(rule_id: str) -> None:
    positive, _ = SAMPLES[rule_id]
    m = match(positive)
    assert m is not None, f"{rule_id}: 양성이 걸리지 않았다 — {positive!r}"
    assert m.rule == rule_id, f"{rule_id}: 다른 규칙({m.rule})에 먼저 걸렸다"
    expected = next(r.level for r in RULES if r.id == rule_id)
    assert m.level == expected


@pytest.mark.parametrize("rule_id", list(SAMPLES))
def test_rule_negative(rule_id: str) -> None:
    _, negative = SAMPLES[rule_id]
    m = match(negative)
    assert m is None or m.rule != rule_id, f"{rule_id}: 음성이 걸렸다 — {negative!r}"


# ── 참고(note) 등급 — 플래그를 만들지 않는다 ────────────────────


@pytest.mark.parametrize(
    "title",
    [
        "단일판매ㆍ공급계약체결",
        "[기재정정]단일판매ㆍ공급계약체결(자율공시)",
        "현금ㆍ현물배당결정",
        "주요사항보고서(무상증자결정)",
        "주요사항보고서(자기주식취득결정)",
        "주요사항보고서(자기주식취득신탁계약체결결정)",
        "분기보고서 (2026.03)",
        "기업설명회(IR)개최(안내공시)",
    ],
)
def test_reference_titles_do_not_flag(title: str) -> None:
    assert match(title) is None


# ── 자회사·종속회사 (표본 발견 — 모회사 희석이 아니다) ──────────


@pytest.mark.parametrize(
    "title",
    [
        "유상증자결정(종속회사의주요경영사항)",
        "유상증자결정(자회사의 주요경영사항)",
        "주요사항보고서(회사합병결정)(자회사의 주요경영사항)",
    ],
)
def test_subsidiary_disclosure_is_downgraded_to_amber(title: str) -> None:
    m = match(title)
    if m is None:  # 합병 같은 비규칙 제목은 애초에 안 걸린다
        return
    assert m.level == "amber" and m.subsidiary is True


def test_subsidiary_cb_is_amber_not_red() -> None:
    m = match("주요사항보고서(전환사채권발행결정)(종속회사의주요경영사항)")
    assert m is not None and m.rule == "cb" and m.level == "amber" and m.subsidiary


# ── 리츠 예외 (D9) ──────────────────────────────────────────────


def test_reit_rights_issue_is_amber() -> None:
    m = match("주요사항보고서(유상증자결정)", company_name="코람코더원리츠")
    assert m == Match(rule="rights_issue", level="amber", subsidiary=False)


def test_non_reit_rights_issue_stays_red() -> None:
    m = match("주요사항보고서(유상증자결정)", company_name="가비아")
    assert m is not None and m.level == "red"


def test_reit_exception_only_touches_rights_issue() -> None:
    """리츠라도 CB 발행은 🔴 그대로다."""
    m = match("주요사항보고서(전환사채권발행결정)", company_name="코람코더원리츠")
    assert m is not None and m.level == "red"


@pytest.mark.parametrize(
    ("name", "is_reit"),
    [
        ("코람코더원리츠", True),
        ("ESR켄달스퀘어리츠", True),
        ("리츠산업", True),
        ("가비아", False),
        ("", False),
    ],
)
def test_is_reit(name: str, is_reit: bool) -> None:
    assert flags.is_reit(name) is is_reit


# ── classify — 등급 최댓값 · none · corrected 표시 ───────────────


def test_classify_level_is_max_and_flags_list_causes() -> None:
    v = classify(
        [
            disc("분기보고서 (2026.03)", "1"),
            disc("[기재정정]주요사항보고서(자기주식처분결정)", "2"),
            disc("주요사항보고서(전환사채권발행결정)", "3"),
        ],
        company_name="가비아",
    )
    assert v.level == "red"
    assert [(f.rule, f.level, f.rcept_no) for f in v.flags] == [
        ("treasury_sale", "amber", "2"),
        ("cb", "red", "3"),
    ]
    assert v.flags[0].report_nm == "[기재정정]주요사항보고서(자기주식처분결정)"  # 원문 그대로


def test_classify_amber_only() -> None:
    v = classify([disc("소송등의제기ㆍ신청(일정금액이상의청구)")])
    assert v.level == "amber" and len(v.flags) == 1


def test_classify_none_when_nothing_flagged() -> None:
    """'없다'가 아니라 '확인된 위험 유형 없음'이다 — 공시는 그대로 남는다."""
    v = classify([disc("분기보고서 (2026.03)"), disc("단일판매ㆍ공급계약체결", "2")])
    assert v.level == "none" and v.flags == () and len(v.disclosures) == 2


def test_classify_empty_is_none() -> None:
    v = classify([])
    assert v.level == "none" and v.flags == () and v.disclosures == ()


def test_classify_marks_corrected_and_keeps_order() -> None:
    v = classify(
        [disc("[기재정정]단일판매ㆍ공급계약체결", "1"), disc("단일판매ㆍ공급계약체결", "2")]
    )
    assert [d.corrected for d in v.disclosures] == [True, False]
    assert [d.rcept_no for d in v.disclosures] == ["1", "2"]


# ── 실표본 회귀 — 352종 전부를 돌려도 죽지 않고, 알려진 것은 맞게 ──


@pytest.fixture(scope="module")
def sample_titles() -> list[str]:
    lines = (FIXTURES / "report_names.txt").read_text(encoding="utf-8").splitlines()
    return [ln.split("\t", 1)[1] for ln in lines if ln and not ln.startswith("#")]


def test_sample_titles_all_classifiable(sample_titles: list[str]) -> None:
    assert len(sample_titles) > 300
    for t in sample_titles:
        match(t)  # 예외 없이


def test_sample_known_verdicts(sample_titles: list[str]) -> None:
    expected = {
        "[기재정정]주요사항보고서(유상증자결정)": ("rights_issue", "red"),
        "주요사항보고서(전환사채권발행결정)": ("cb", "red"),
        "유상증자결정(종속회사의주요경영사항)": ("rights_issue", "amber"),
        "최대주주변경": ("controller_change", "red"),
        "[기재정정]최대주주변경을수반하는주식담보제공계약체결": ("pledge", "amber"),
        "주권매매거래정지해제              (감자 주권 변경상장)": None,  # 위험이 끝난 공시
        "자기주식처분결과보고서": None,
        "현금ㆍ현물배당결정": None,
        "임원ㆍ주요주주특정증권등소유상황보고서": None,
    }
    for title, exp in expected.items():
        assert title in sample_titles, f"표본에 없음: {title}"
        m = match(title)
        got = None if m is None else (m.rule, m.level)
        assert got == exp, f"{title}: {got} != {exp}"


# ── 🟡 insider_sell_cluster — 제목이 아니라 insider_signal 입력으로 붙는 플래그 (F4b·D13 ③) ──

from verify.flags import INSIDER_RULE, insider_flag  # noqa: E402
from verify.models import Insider  # noqa: E402

INSIDER_SAMPLES: dict[str, tuple[Insider, bool]] = {
    "strong_sell": (
        Insider(
            signal="strong_sell_cluster",
            sell_events=29,
            unique_sellers=28,
            net_change_shares=-16835,
        ),
        True,
    ),
    "sell": (Insider(signal="sell_cluster", sell_events=5, unique_sellers=3), True),
    "buy": (Insider(signal="buy_cluster", buy_events=5, unique_buyers=3), False),
    "strong_buy": (Insider(signal="strong_buy_cluster"), False),
    "none": (Insider(signal="none"), False),
}


@pytest.mark.parametrize("key", list(INSIDER_SAMPLES))
def test_insider_flag_only_for_sell_clusters(key: str) -> None:
    insider, expected = INSIDER_SAMPLES[key]
    f = insider_flag(insider)
    if expected:
        assert f is not None and f.rule == INSIDER_RULE and f.level == "amber"
        assert f.rcept_no == "" and "매도" in f.report_nm
    else:
        assert f is None


def test_insider_flag_report_nm_carries_evidence() -> None:
    """점수가 아니라 근거 — 몇 명이 얼마나 팔았는지."""
    f = insider_flag(
        Insider(signal="sell_cluster", sell_events=29, unique_sellers=28, net_change_shares=-16835)
    )
    assert f is not None and "28명" in f.report_nm and "16,835주" in f.report_nm


def test_classify_appends_insider_flag_and_raises_level_to_amber() -> None:
    v = classify(
        [disc("분기보고서 (2026.03)")],
        company_name="가비아",
        insider=Insider(signal="sell_cluster", sell_events=4, unique_sellers=3),
    )
    assert v.level == "amber" and [f.rule for f in v.flags] == [INSIDER_RULE]


def test_classify_insider_does_not_lower_red() -> None:
    v = classify(
        [disc("주요사항보고서(전환사채권발행결정)")], insider=Insider(signal="sell_cluster")
    )
    assert v.level == "red" and [f.rule for f in v.flags] == ["cb", INSIDER_RULE]


def test_classify_without_insider_unchanged() -> None:
    v = classify([disc("분기보고서 (2026.03)")], insider=None)
    assert v.level == "none" and v.flags == ()


def test_insider_rule_is_not_a_title_rule() -> None:
    """제목 규칙표(RULES)에는 없다 — 표본은 INSIDER_SAMPLES가 담당한다."""
    assert INSIDER_RULE not in {r.id for r in RULES}
