"""공시 제목 판정 — 정규화 · 규칙표 · 등급. **도메인 층 · 순수 함수.**

선행 `krx-signal-briefing`에서 **테스트와 함께 이식**했다 (V11).
실표본 3,000건으로 세우고 DART 원문 손검증 11/12를 통과한 규칙표라 다시 만들지 않는다.

**규칙표가 곧 SPEC이다.** 바꾸면 SPEC을 먼저 고치고(N12) `tests/test_flags.py`의 `SAMPLES`에
양성·음성 표본을 함께 넣는다 — **표본 없는 규칙은 테스트가 막는다.**

실표본(`tests/fixtures/report_names.txt`, 2026-08-29)에서 배운 것:
- 결정 공시는 `주요사항보고서(유상증자결정)`처럼 **래퍼 안**에 온다 → 부분 일치
- `[기재정정]`·`[첨부정정]`·`[발행조건확정]`·`[첨부추가]`·`[정정제출요구]` 접두가 붙는다
- 제목 뒤에 **공백 여러 칸 + (설명)** 이 붙는다 → note로 분리
- `유상증자결정(종속회사의주요경영사항)`은 **자회사** 공시 — 모회사 희석이 아니다 → 🔴를 🟡로 내린다
- `…결과보고서`·`…해지`·`…행사`·`…해제`는 결정이 아니다 → 제외어
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from verify.models import Disclosure, Flag, FlagLevel, Insider

Verdict_Level = Literal["red", "amber", "none"]

_PREFIX = re.compile(r"^\[([^\]]*)\]\s*")
_NOTE_SPLIT = re.compile(r"\s{2,}")
_WS = re.compile(r"\s+")

# 정정을 뜻하는 접두. 그 밖의 접두(발행조건확정·첨부추가)는 떼되 corrected로 보지 않는다.
CORRECTION_MARK = "정정"

# 자회사·종속회사 공시 표시 — 정규화 후(공백 제거) 형태
SUBSIDIARY_MARKERS = ("자회사의주요경영사항", "종속회사의주요경영사항")

REIT_MARK = "리츠"


@dataclass(frozen=True, slots=True)
class Normalized:
    """정규화된 제목."""

    name: str  # 접두·공백 제거, 가운뎃점 통일. 괄호는 남긴다
    corrected: bool  # `[정정]`·`[기재정정]`·`[첨부정정]`·`[정정제출요구]`가 있었는가
    note: str  # 공백 여러 칸 뒤의 괄호 설명 (없으면 "")


@dataclass(frozen=True, slots=True)
class Rule:
    """규칙 하나. `keywords` 중 하나라도 있고 `exclude`가 하나도 없으면 걸린다."""

    id: str
    level: FlagLevel
    keywords: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    on_note: bool = False  # True면 note까지 본다 (감사의견은 note에만 온다)


@dataclass(frozen=True, slots=True)
class Match:
    """제목 하나의 판정."""

    rule: str
    level: FlagLevel
    subsidiary: bool


@dataclass(frozen=True, slots=True)
class Verdict:
    """종목 하나의 판정 (F5)."""

    level: Verdict_Level
    flags: tuple[Flag, ...]
    disclosures: tuple[Disclosure, ...]  # corrected가 채워진 원본 순서


# ── 규칙표 — 순서가 의미를 갖는다: 🔴 먼저, 같은 등급 안에서는 좁은 것 먼저 ──
RULES: tuple[Rule, ...] = (
    # 🔴 물량 — 주식 수 증가·오버행
    Rule("cb", "red", ("전환사채권발행결정",)),
    Rule("bw", "red", ("신주인수권부사채권발행결정",)),
    Rule("eb", "red", ("교환사채권발행결정",)),
    Rule("rights_issue", "red", ("유상증자결정",)),
    # 🔴 지배구조 — 담보제공계약은 변경이 아니라 변경 '가능성' → 🟡 pledge로
    Rule("controller_change", "red", ("최대주주변경",), exclude=("담보제공",)),
    # 🔴 거래 제약 — '우려'·'예고'는 🟡, '해제'는 제외
    Rule("admin_issue", "red", ("관리종목지정",), exclude=("우려", "해제")),
    Rule("caution_issue", "red", ("투자주의환기종목지정",), exclude=("해제",)),
    Rule("unfaithful", "red", ("불성실공시법인지정",), exclude=("예고", "미지정")),
    Rule("delisting", "red", ("상장폐지",), exclude=("해소",)),
    # 🔴 거래정지·상장폐지 사유
    Rule("embezzlement", "red", ("횡령", "배임")),
    Rule("rehabilitation", "red", ("회생절차",), exclude=("종결", "폐지")),
    Rule("audit", "red", ("의견거절", "범위제한", "비적정", "부적정"), on_note=True),
    # 🟡 사실만 보여 준다 — 규모·방향에 따라 다르다
    Rule("trading_halt", "amber", ("매매거래정지",), exclude=("해제",)),
    Rule("lawsuit", "amber", ("소송등의제기",)),
    Rule("treasury_sale", "amber", ("자기주식처분결정",)),
    Rule("pledge", "amber", ("최대주주변경을수반하는주식담보제공",)),
    Rule("admin_warning", "amber", ("관리종목지정우려",)),
    Rule("unfaithful_warning", "amber", ("불성실공시법인지정예고",)),
    Rule("market_warning", "amber", ("투자경고종목지정", "투자위험종목지정"), exclude=("해제",)),
    Rule("capital_reduction", "amber", ("감자결정",)),
)


def normalize(report_nm: str) -> Normalized:
    """제목을 판정 가능한 형태로 만든다.

    Args:
        report_nm: DART `report_nm` 원문.

    Returns:
        접두를 떼고 공백을 전부 지운 `name`, 정정 여부, 뒤에 붙은 설명 `note`.
    """
    s = report_nm.strip()
    corrected = False
    while (m := _PREFIX.match(s)) is not None:
        corrected = corrected or CORRECTION_MARK in m.group(1)
        s = s[m.end() :]
    parts = _NOTE_SPLIT.split(s, 1)
    head = parts[0]
    note = parts[1].strip() if len(parts) > 1 else ""
    if note.startswith("(") and note.endswith(")"):
        note = note[1:-1].strip()
    name = _WS.sub("", head).replace("ㆍ", "·")
    return Normalized(name=name, corrected=corrected, note=note)


def is_reit(company_name: str) -> bool:
    """리츠인가 (D9) — 종목명에 `리츠`."""
    return REIT_MARK in company_name


def match(report_nm: str, company_name: str = "") -> Match | None:
    """제목 하나를 규칙표에 대본다. 안 걸리면 None (참고·무해).

    Args:
        report_nm: DART `report_nm` 원문.
        company_name: 종목명 — 리츠 예외(D9)에 쓴다.

    Returns:
        걸린 규칙과 등급. 자회사·종속회사 공시는 🔴를 🟡로, 리츠의 유상증자도 🟡로 내린다.
    """
    n = normalize(report_nm)
    note_key = _WS.sub("", n.note)
    subsidiary = any(marker in n.name for marker in SUBSIDIARY_MARKERS)
    for rule in RULES:
        hay = f"{n.name}|{note_key}" if rule.on_note else n.name
        if any(k in hay for k in rule.keywords) and not any(x in hay for x in rule.exclude):
            level: FlagLevel = rule.level
            if subsidiary and level == "red":
                level = "amber"
            if rule.id == "rights_issue" and is_reit(company_name):
                level = "amber"
            return Match(rule=rule.id, level=level, subsidiary=subsidiary)
    return None


# ── 🟡 insider_sell_cluster — 제목이 아니라 korean-dart-mcp insider_signal 입력 (F4b·D13 ③) ──

INSIDER_RULE = "insider_sell_cluster"


def insider_flag(insider: Insider | None) -> Flag | None:
    """임원·주요주주 **매도 군집**이면 🟡 플래그. 매수 군집·신호 없음은 플래그 없음 (참고 표시만).

    근거를 남긴다 — 몇 명이 얼마나 팔았는지. 접수번호는 없다(여러 보고서의 집계).
    """
    if insider is None or not insider.sell_cluster:
        return None
    text = (
        f"임원·주요주주 매도 군집 — 매도 {insider.sell_events}건 · {insider.unique_sellers}명"
        f" · 순변동 {insider.net_change_shares:+,}주"
    )
    return Flag(rule=INSIDER_RULE, level="amber", rcept_no="", report_nm=text)


def classify(
    disclosures: list[Disclosure] | tuple[Disclosure, ...],
    *,
    company_name: str = "",
    insider: Insider | None = None,
) -> Verdict:
    """종목 하나의 공시 목록을 판정한다 (F5·F6).

    Args:
        disclosures: 창 안의 공시 (DART 순서).
        company_name: 종목명 — 리츠 예외.

    Returns:
        등급은 걸린 플래그의 **최댓값**. 하나도 없으면 `none` —
        "없다"가 아니라 "확인된 위험 유형 없음"이다.
        공시 목록은 순서를 지키고 `corrected`가 채워진다.
    """
    annotated = tuple(replace(d, corrected=normalize(d.report_nm).corrected) for d in disclosures)
    flags: list[Flag] = []
    for d in annotated:
        m = match(d.report_nm, company_name)
        if m is None:
            continue
        rule = f"{m.rule}(자회사)" if m.subsidiary else m.rule
        flags.append(Flag(rule=rule, level=m.level, rcept_no=d.rcept_no, report_nm=d.report_nm))
    if (extra := insider_flag(insider)) is not None:
        flags.append(extra)
    level: Verdict_Level = "none"
    if any(f.level == "red" for f in flags):
        level = "red"
    elif flags:
        level = "amber"
    return Verdict(level=level, flags=tuple(flags), disclosures=annotated)
