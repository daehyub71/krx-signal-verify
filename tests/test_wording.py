"""문구 규칙 — **사실과 근거 정합성은 되고 매매 판단은 안 된다** (N1).

이식하면서 선행의 사고를 그대로 잠근다: `순매도`가 `매도`에 걸려
**분석문 15개가 통째로 버려졌다** (2026-08-30 실호출).
"""

from __future__ import annotations

import pytest

from verify import wording
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


def test_short_selling_is_a_fact_not_a_trade() -> None:
    """**`공매도`가 `매도`에 걸린다.** 선행에는 이 갈래가 없어 목록에 없었다 (2026-09-05).

    F32가 요구하는 「거래량·비중(%)」을 못 쓰게 되는 셈이었다.
    """
    assert has_forbidden("공매도 비중 3.2%") == ""
    assert has_forbidden("공매도 거래량이 늘었다") == ""
    assert has_forbidden("공매도비중 3.2%") == ""


def test_longer_compounds_are_removed_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """`공매도`를 먼저 지우면 `비중`이 남아 걸린다.

    목록에 **짧은 것이 앞에 오도록 뒤집어도** 통과해야 한다 — 순서를 사람이 지키게 두지 않고
    `has_forbidden`이 길이순으로 정렬하기 때문이다. 정렬을 빼면 여기가 깨진다.
    """
    assert has_forbidden("공매도 비중이 높다") == ""
    monkeypatch.setattr(
        wording, "ALLOWED_COMPOUNDS", ("공매도", "공매도비중", "공매도 비중", "순매수")
    )
    assert has_forbidden("공매도 비중이 높다") == ""


def test_position_sizing_is_still_blocked() -> None:
    """`비중`을 통째로 열면 「비중을 늘려라」가 통과한다 — 그것이 막을 말이다."""
    assert has_forbidden("비중을 늘릴 만하다") == "비중"
    assert has_forbidden("매도 판단") == "매도"
    assert has_forbidden("공매도 뒤 매도 판단") == "매도"


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


# ── N2 적중 문구 — 이 프로젝트에서 신설 (SPEC R2 · 최대 리스크) ──
#
# 「불일치」는 "근거가 신호와 어긋난다"이지 "떨어진다"가 아니다.
# 개별 종목에 「맞았다/틀렸다」를 매기는 순간 하지 않기로 한 일(예측)을 하게 된다.

from verify.wording import (  # noqa: E402
    ALLOWED_OUTCOME_COMPOUNDS,
    FORBIDDEN_OUTCOME,
    first_violation,
    has_forbidden_outcome,
)


@pytest.mark.parametrize("word", FORBIDDEN_OUTCOME)
def test_every_outcome_word_is_caught(word: str) -> None:
    assert has_forbidden_outcome(f"이번 판정은 {word}다") == word


@pytest.mark.parametrize(
    "sentence",
    [
        "불일치 적중률 68%",
        "판정 승률 3할",
        "평균 수익률 2.4%",
        "정확도가 높다",
        "이 종목은 맞았다",
        "지난 판정은 틀렸다",
        "예상이 빗나갔다",
    ],
)
def test_performance_claims_are_blocked(sentence: str) -> None:
    """「불일치 적중률 68%」 한 줄이면 다음 판정을 **예측으로 읽는다** (R2)."""
    assert has_forbidden_outcome(sentence) != ""


@pytest.mark.parametrize(
    "sentence",
    [
        "정합군과 불일치군의 초과수익 분포",
        "중앙값 차이 +2.3%p · 분포 겹침 68%",
        "표본 부족 (n=12)",
        "기준선 대비 초과수익 2.1%p",
        "분별력을 재는 관측치다",
    ],
)
def test_the_words_we_must_use_survive(sentence: str) -> None:
    """막기만 하고 **쓸 말을 남기지 않으면** 규칙이 일을 못 하게 만든다."""
    assert has_forbidden_outcome(sentence) == ""


@pytest.mark.parametrize("compound", ALLOWED_OUTCOME_COMPOUNDS)
def test_excess_return_is_not_a_rate_claim(compound: str) -> None:
    """`초과수익`은 **관측치의 이름**이다 — `수익률`에 걸리면 관측 결과를 말할 수 없다."""
    assert has_forbidden_outcome(f"{compound} 중앙값") == ""


def test_excess_return_rate_survives_by_name() -> None:
    """말을 **그대로 적는다.**

    위 테스트는 목록을 `parametrize`에 쓰므로 **목록을 비우면 실패가 아니라 건너뛴다** —
    자기참조와 같은 계열의 구멍이다 (2026-09-02 변이 검사에서 드러났다).
    그리고 예외가 실제로 일하는 자리는 `초과수익률`이다: `초과수익 분포`에는 `률`이 없어
    예외가 없어도 통과한다.
    """
    assert has_forbidden_outcome("지수 대비 초과수익률 2.1%") == ""


def test_prediction_itself_is_not_banned() -> None:
    """`예측`은 막지 않는다 — **한계 문구가 「예측이 아니다」라고 말해야** 하기 때문이다."""
    assert has_forbidden_outcome("이것은 예측이 아니다") == ""
    assert has_forbidden_outcome("앞으로의 주가를 말하지 않는다") == ""


# ── 두 규칙을 한 번에 ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("지금이 매수 시점이다", ("N1", "매수")),
        ("불일치 적중률 68%", ("N2", "적중")),
        ("30일 기관·외국인 순매도 · 초과수익 분포", ("", "")),
    ],
)
def test_first_violation_names_the_rule(text: str, expected: tuple[str, str]) -> None:
    """**어느 규칙인지까지** 돌려준다 — 고치는 방향이 다르다(N1은 사실로, N2는 분포로)."""
    assert first_violation(text) == expected


def test_the_two_rules_do_not_overlap() -> None:
    """같은 말이 두 목록에 있으면 어느 쪽으로 고쳐야 할지 모호해진다."""
    assert not set(FORBIDDEN) & set(FORBIDDEN_OUTCOME)


def test_the_limit_note_itself_passes_both_rules() -> None:
    """**우리가 가장 자주 내보내는 문장**이 규칙에 걸리면 안 된다."""
    from verify.models import Verdict

    note = Verdict(stand="정합", score=72, blind_spots=("업황", "시장 전체 흐름")).limit_note
    assert first_violation(note) == ("", "")
