"""정형·정기 공시 판정 — **도메인 층 · 순수 함수.**

선행 `krx-signal-briefing`에서 **테스트와 함께 이식**했다 (V11).
키워드 목록은 실데이터 101건을 보고 뽑은 것이라 다시 만들지 않는다.

**전체 공시의 65%가 정형이다** (2026-08-30 실측: 101건 중 66건). 반기보고서·IR개최·
대량보유보고 같은 것들이다. 이것들을 목록에 그대로 늘어놓으면 읽을 것이 묻힌다 —
15종목 중 13종목은 카드 전체가 이 목록이었고, 사용자는 "의미없는 공시의 나열"이라고 했다.

여기서 판정한 것은 본문에서 `정기·정형 공시 N건` 한 줄로 접는다. **지우지 않는다** —
접힌 건수는 항상 보이고, 웹 대시보드의 종목 화면(F52)에는 그대로 나온다.

## 두 가지 안전장치

1. **`주요사항보고서(…)`는 무슨 일이 있어도 정형이 아니다.** 전환사채·유상증자·합병·
   자산양수도가 전부 이 형식으로 온다. 키워드가 우연히 겹쳐도 여기서 막는다.
2. **플래그된 공시는 접지 않는다** — `fold()`가 받은 `flagged`를 먼저 본다.
   규칙표가 걸었다는 것은 그것 때문에 메일을 보낸다는 뜻이다.

판정은 `flags.normalize()`를 거친 이름으로 한다. `[기재정정]반기보고서`도 정형이고,
`ㆍ`와 공백이 섞인 제목도 같은 것으로 본다.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from verify.flags import normalize
from verify.models import Disclosure

# 어떤 키워드가 있어도 정형이 아닌 것. **1번 안전장치.**
NEVER_ROUTINE: tuple[str, ...] = ("주요사항보고서",)

# 정형·정기 공시 키워드. 정규화된 이름에 이 중 하나가 있으면 접는다.
# 2026-08-26 실데이터 101건에서 뽑았다 — 늘릴 때는 표본을 먼저 보고 늘린다.
ROUTINE_KEYWORDS: tuple[str, ...] = (
    # 정기보고서
    "사업보고서",
    "반기보고서",
    "분기보고서",
    "감사보고서제출",
    "연결감사보고서제출",
    # 지분 변동 보고 (사후 보고 서식이다 — 최대주주'변경'은 별도 규칙이 잡는다)
    "임원·주요주주특정증권등소유상황보고서",
    "주식등의대량보유상황보고서",
    "최대주주등소유주식변동신고서",
    # 실적·IR·안내
    "연결재무제표기준영업",
    "영업(잠정)실적",
    "기업설명회",
    "지속가능경영보고서등관련사항",
    "지급수단별·지급기간별지급금액및분쟁조정기구에관한사항",
    "기타안내사항",
    "기타경영사항",
    "소속부변경",
    # 발행 절차 서류 (발행 '결정'은 주요사항보고서로 따로 온다)
    "증권발행실적보고서",
    "투자설명서",
    "일괄신고서",
    "일괄신고추가서류",
    # 주주총회·명부 절차
    "주주총회소집결의",
    "주주총회소집공고",
    "주주명부폐쇄기간또는기준일설정",
)

FOLD_WORDING = "정기·정형 공시 {n}건"


def is_routine(report_nm: str) -> bool:
    """이 공시가 정형·정기 공시인가.

    Args:
        report_nm: DART `report_nm` 원문.

    Returns:
        접어도 되면 True. `주요사항보고서(…)`는 언제나 False.
    """
    name = normalize(report_nm).name
    if any(mark in name for mark in NEVER_ROUTINE):
        return False
    return any(word in name for word in ROUTINE_KEYWORDS)


def fold(
    disclosures: Sequence[Disclosure], flagged: Iterable[str] = ()
) -> tuple[list[Disclosure], list[Disclosure]]:
    """공시를 (보여줄 것, 접을 것)으로 나눈다.

    **플래그된 공시는 정형 키워드와 겹쳐도 접지 않는다** — 그것 때문에 보내는 메일이다.

    Args:
        disclosures: 공시 목록. 원래 순서를 유지한다.
        flagged: 규칙에 걸린 공시의 `rcept_no`.

    Returns:
        `(보여줄 공시, 접을 공시)`.
    """
    keep_nos = set(flagged)
    shown: list[Disclosure] = []
    folded: list[Disclosure] = []
    for d in disclosures:
        if d.rcept_no not in keep_nos and is_routine(d.report_nm):
            folded.append(d)
        else:
            shown.append(d)
    return shown, folded
