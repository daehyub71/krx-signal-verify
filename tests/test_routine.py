"""routine — 정형·정기 공시 판정 (SPEC F16, v3.0). 순수 함수.

표본은 **2026-08-26 실데이터 101건**에서 왔다. 그중 66건(65%)이 정형이었고,
15종목 중 13종목은 카드 전체가 그 목록이었다 — 사용자가 "의미없는 공시의 나열"이라 한 이유다.

규칙표의 위험은 두 방향이다: 접지 말아야 할 것을 접으면 **읽을 것이 사라지고**,
접어야 할 것을 못 접으면 **문제가 그대로 남는다**. 그래서 양성 표본과
"닮았지만 접으면 안 되는" 표본을 함께 둔다.
"""

from __future__ import annotations

from datetime import date

import pytest

from verify import routine
from verify.models import Disclosure

# ── 접어야 하는 것 (실데이터에서 그대로) ─────────────────────────

ROUTINE_SAMPLES = [
    "반기보고서 (2026.06)",
    "[기재정정]분기보고서 (2026.03)",
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "주식등의대량보유상황보고서(일반)",
    "주식등의대량보유상황보고서(약식)",
    "[기재정정]주식등의대량보유상황보고서(일반)",
    "연결재무제표기준영업(잠정)실적(공정공시)",
    "기업설명회(IR)개최(안내공시)",
    "지속가능경영보고서등관련사항(자율공시)",
    "지급수단별ㆍ지급기간별지급금액및분쟁조정기구에관한사항",
    "증권발행실적보고서",
    "투자설명서(일괄신고)",
    "일괄신고추가서류",
    "[기재정정]일괄신고서",
    "기타안내사항(안내공시)",
    "기타경영사항(자율공시)",
    "소속부변경",
    "[기재정정]감사보고서제출",
    "[기재정정]주주총회소집결의              (임시주주총회)",
    "[기재정정]주주명부폐쇄기간또는기준일설정",
    "최대주주등소유주식변동신고서",
]

# ── 접으면 안 되는 것 — 닮았지만 실질이 있는 공시 ────────────────

MATERIAL_SAMPLES = [
    # 규칙표가 잡는 것들 — 정형과 절대 섞이면 안 된다
    "주요사항보고서(전환사채권발행결정)",
    "[기재정정]주요사항보고서(전환사채권발행결정)",
    "[첨부정정]주요사항보고서(회사합병결정)",
    "주요사항보고서(유상증자결정)",
    "주요사항보고서(자기전환사채만기전취득결정)",
    "주요사항보고서(자기주식취득신탁계약체결결정)(자회사의 주요경영사항)",
    "주요사항보고서(유형자산양수결정)",
    # 규칙에는 안 걸리지만 사실로서 값이 있는 것들
    "단일판매ㆍ공급계약체결",
    "[기재정정]단일판매ㆍ공급계약체결",
    "타인에대한채무보증결정",
    "주식소각결정",
    "주식소각결정(자회사의 주요경영사항)",
    "신규시설투자등(자회사의 주요경영사항)",
    "현금ㆍ현물배당결정",
    "현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정",
    "전환가액의조정",
    "[기재정정]타법인주식및출자증권취득결정(자회사의 주요경영사항)",
    "최대주주변경",
    "관리종목지정",
    "매매거래정지",
]


@pytest.mark.parametrize("title", ROUTINE_SAMPLES)
def test_routine_samples_are_folded(title: str) -> None:
    assert routine.is_routine(title), f"접어야 하는데 안 접힌다: {title}"


@pytest.mark.parametrize("title", MATERIAL_SAMPLES)
def test_material_samples_are_never_folded(title: str) -> None:
    assert not routine.is_routine(title), f"접으면 안 되는데 접힌다: {title}"


def test_a_major_report_is_never_routine_whatever_it_contains() -> None:
    """`주요사항보고서(…)`는 실질 사건이 오는 서식이다. 키워드가 겹쳐도 접지 않는다."""
    assert not routine.is_routine("주요사항보고서(반기보고서관련)")
    assert not routine.is_routine("주요사항보고서(주주총회소집결의)")


def test_title_wobble_does_not_change_the_verdict() -> None:
    """`ㆍ`·공백·정정 접두가 붙어도 같은 것으로 본다 (`flags.normalize`)."""
    for title in (
        "임원ㆍ주요주주특정증권등소유상황보고서",
        "임원·주요주주 특정증권등 소유상황보고서",
        "[기재정정]임원ㆍ주요주주특정증권등소유상황보고서",
    ):
        assert routine.is_routine(title), title


def test_an_unknown_title_is_not_folded() -> None:
    """모르는 것은 접지 않는다 — 접어서 사라지는 쪽이 나쁘다."""
    assert not routine.is_routine("무상감자결정")
    assert not routine.is_routine("횡령ㆍ배임혐의발생")


# ── fold: 플래그된 공시는 절대 접지 않는다 ───────────────────────


def d(report_nm: str, no: str) -> Disclosure:
    return Disclosure(
        rcept_dt=date(2026, 8, 26), report_nm=report_nm, rcept_no=no, flr_nm="가비아"
    )


def test_fold_separates_routine_from_the_rest_keeping_order() -> None:
    items = [
        d("반기보고서 (2026.06)", "1"),
        d("단일판매ㆍ공급계약체결", "2"),
        d("기업설명회(IR)개최(안내공시)", "3"),
    ]
    shown, folded = routine.fold(items)
    assert [x.rcept_no for x in shown] == ["2"]
    assert [x.rcept_no for x in folded] == ["1", "3"]


def test_fold_never_folds_a_flagged_disclosure() -> None:
    """규칙이 걸었다는 것은 그것 때문에 메일을 보낸다는 뜻이다."""
    items = [d("주주총회소집결의", "1"), d("반기보고서 (2026.06)", "2")]
    shown, folded = routine.fold(items, flagged={"1", "2"})
    assert folded == []
    assert [x.rcept_no for x in shown] == ["1", "2"]


def test_fold_on_an_empty_list() -> None:
    assert routine.fold([]) == ([], [])


def test_real_day_folds_about_two_thirds() -> None:
    """2026-08-26 실데이터의 비율을 잠근다 — 규칙표를 넓히다 과하게 접으면 여기서 걸린다."""
    items = [d(t, str(i)) for i, t in enumerate(ROUTINE_SAMPLES + MATERIAL_SAMPLES)]
    shown, folded = routine.fold(items)
    assert len(folded) == len(ROUTINE_SAMPLES)
    assert len(shown) == len(MATERIAL_SAMPLES)
