"""문구 규칙 — **사실과 근거 정합성은 되고 매매 판단은 안 된다** (N1).

이식하면서 선행의 사고를 그대로 잠근다: `순매도`가 `매도`에 걸려
**분석문 15개가 통째로 버려졌다** (2026-08-30 실호출).
"""

from __future__ import annotations

import pytest

from verify.wording import ALLOWED_COMPOUNDS, FORBIDDEN, has_forbidden


# ── 막아야 하는 것 ───────────────────────────────────────────────


@pytest.mark.parametrize("word", FORBIDDEN)
def test_every_forbidden_word_is_caught(word: str) -> None:
    """목록에 있는 말은 하나도 빠짐없이 걸려야 한다."""
    assert has_forbidden(f"이 종목은 {word} 구간이다") == word


@pytest.mark.parametrize(
    "sentence",
    [
        "지금이 매수 시점이다",
        "매도 판단이 필요하다",
        "목표가 12만원",
        "손절 라인을 지킨다",
        "진입 보류",
        "비중을 늘린다",
        "상승 여력이 있다",
        "지지선 이탈",
    ],
)
def test_trading_calls_are_blocked(sentence: str) -> None:
    """매매 판단은 어떤 형태로 와도 막힌다 — 여기가 유사투자자문업 경계다 (R1)."""
    assert has_forbidden(sentence) != ""


# ── 막으면 안 되는 것 — 이 파일의 존재 이유 ──────────────────────


@pytest.mark.parametrize("compound", ALLOWED_COMPOUNDS)
def test_supply_and_demand_words_survive(compound: str) -> None:
    """`순매도`가 `매도`에 걸리면 **수급을 말할 수 없다.** 선행에서 15개가 버려졌다."""
    assert has_forbidden(f"30일 기관·외국인 {compound}") == ""


def test_a_real_evidence_sentence_passes() -> None:
    """실제로 쓸 문장이 통과하는지 본다 — 규칙이 일을 못 하게 만들면 안 된다."""
    text = (
        "08/22 전환사채권발행결정 — 본문의 유통물량 대비 비율은 18.63%다. "
        "같은 기간 외국인은 1,482억, 기관은 306억을 순매도했다."
    )
    assert has_forbidden(text) == ""


def test_direction_words_are_allowed() -> None:
    """`호재`·`악재`는 금지어가 아니다 — **근거의 방향**을 말하는 데 필요하다 (D24 계승)."""
    assert has_forbidden("호재로 읽히는 공시다") == ""
    assert has_forbidden("악재 요인이 확인된다") == ""


# ── 어떻게 막는가 ────────────────────────────────────────────────


def test_it_returns_the_word_not_a_boolean() -> None:
    """무엇이 걸렸는지 알아야 고칠 수 있다."""
    assert has_forbidden("추천 종목") == "추천"
    assert has_forbidden("") == ""


def test_compounds_are_stripped_before_the_check_not_after() -> None:
    """검사 뒤에 지우면 이미 걸린 뒤다. **순서가 규칙의 전부다.**"""
    assert has_forbidden("순매도 전환") == ""
    assert has_forbidden("순매도 뒤 매도 판단") == "매도", "합성어만 지우고 나머지는 검사해야 한다"


def test_only_the_listed_compounds_are_exempt() -> None:
    """`매도우위` 같은 말은 예외가 아니다 — 목록에 적힌 형태만 통과한다."""
    assert has_forbidden("매도우위 흐름") == "매도"


# ── 원문은 검사 대상이 아니다 ────────────────────────────────────


def test_source_titles_would_trip_the_rule_which_is_why_they_are_excluded() -> None:
    """공시 원문에는 금지어가 실제로 들어 있다 — 그래서 **원문에는 이 함수를 쓰지 않는다.**

    이 테스트는 규칙을 검사하는 게 아니라 **왜 원문을 제외해야 하는지**를 기록한다.
    """
    assert has_forbidden("자기주식취득신탁계약체결결정") == ""
    assert has_forbidden("주식등의대량보유상황보고서 — 매수 목적") == "매수"
