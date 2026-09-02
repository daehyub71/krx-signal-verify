"""모델 — `evidence`는 우리가 통제하지 않는 계약이다 (SPEC R12).

상위가 키를 바꾸거나 값 모양을 바꿔도 **그 줄만 비고 나머지는 나가야 한다.**
실제로 있었던 모양: `evidence`가 통째로 `null` · 종가가 `"8,420"`(쉼표 낀 문자열) ·
`conditions`가 목록이 아닌 문자열 · 조건 항목에 `label`이 없음.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from verify.models import (
    Evidence,
    Outcome,
    RunRecord,
    SendResult,
    SignalRow,
    Verdict,
    VerdictPart,
    dart_link,
)


def row(evidence: Any = None, **kw: Any) -> SignalRow:
    base: dict[str, Any] = dict(
        d=date(2026, 9, 1), strategy="vcp", ticker="042700", name="한미반도체"
    )
    base.update(kw)
    return SignalRow(evidence=evidence, **base)


# ── SignalRow — 깨진 evidence를 견딘다 ──────────────────────────


@pytest.mark.parametrize("bad", [None, "문자열", 42, [], 0])
def test_ev_falls_back_to_empty_dict(bad: Any) -> None:
    assert row(bad).ev == {}


@pytest.mark.parametrize("bad", [None, "정배열", {"a": 1}, 7])
def test_conditions_not_a_list_gives_empty_tuple(bad: Any) -> None:
    assert row({"conditions": bad}).conditions == ()


def test_conditions_missing_keys_blank_only_that_slot() -> None:
    r = row({"conditions": [{"ok": True}, {"label": "거래량비"}, "목록 아님"]})
    assert r.conditions == (("", True, ""), ("거래량비", False, ""))


def test_close_accepts_int_and_rejects_comma_string() -> None:
    """`int("8,420")`은 예외를 던진다. 0으로 떨어져 그 줄만 비어야 한다."""
    assert row({"price": {"close": 96400}}).close == 96400
    assert row({"price": {"close": "8,420"}}).close == 0
    assert row({"price": {"close": None}}).close == 0
    assert row({"price": "숫자아님"}).close == 0


def test_change_pct_coerces_or_zero() -> None:
    assert row({"price": {"change_pct": 1.8}}).change_pct == pytest.approx(1.8)
    assert row({"price": {"change_pct": "1.8"}}).change_pct == pytest.approx(1.8)
    assert row({"price": {"change_pct": "+1.8%"}}).change_pct == 0.0


def test_in_progress_only_when_meta_says_so() -> None:
    assert row({"meta": {"in_progress": True}}).in_progress is True
    assert row({"meta": "문자열"}).in_progress is False
    assert row(None).in_progress is False


def test_ticker_may_contain_letters() -> None:
    """`0126Z0`이 실재한다. 숫자로 가정하면 종목이 조용히 누락된다."""
    assert row(None, ticker="0126Z0").ticker == "0126Z0"


# ── Verdict — 판정은 코드가 낸다 ────────────────────────────────


def test_verdict_stand_must_be_one_of_three() -> None:
    for stand in ("정합", "불일치", "무관"):
        assert Verdict(stand=stand, score=50).stand == stand
    with pytest.raises(ValueError, match="stand"):
        Verdict(stand="호재", score=50)


def test_verdict_score_is_clamped_to_0_100() -> None:
    assert Verdict(stand="정합", score=140).score == 100
    assert Verdict(stand="불일치", score=-30).score == 0


def test_verdict_limit_note_always_names_blind_spots() -> None:
    """점수는 사실보다 그럴듯해 보인다. 무엇을 보지 않았는지 항상 함께 나간다 (F10b)."""
    v = Verdict(stand="정합", score=72, blind_spots=("업황", "시장 전체 흐름"))
    note = v.limit_note
    assert "업황" in note and "시장 전체 흐름" in note
    assert "공시 이후의 주가" not in note


def test_verdict_parts_sum_is_reported_not_recomputed() -> None:
    v = Verdict(
        stand="불일치",
        score=34,
        parts=(VerdictPart("오버행 18.63%", -25), VerdictPart("공급계약", 4)),
    )
    assert v.delta_total == -21
    assert v.score == 34


# ── Outcome — 기준선은 지수 하나뿐이다 (V12) ────────────────────


def test_outcome_pending_horizons_are_none_not_zero() -> None:
    """미도래 구간을 0으로 두면 「초과수익 0%」로 읽힌다. `null`이어야 한다 (F22)."""
    o = Outcome(d=date(2026, 9, 1), ticker="042700", h5=None, h20=None, h60=None)
    assert o.h5 is None and not o.is_filled(5)


def test_outcome_excess_is_stock_minus_index() -> None:
    o = Outcome(d=date(2026, 9, 1), ticker="042700", h5=2.4, h5_index=0.3)
    assert o.excess(5) == pytest.approx(2.1)


def test_outcome_excess_is_none_when_index_missing() -> None:
    """지수가 없으면 채우지 않는다. 프록시로 대신 재지 않는다 (F23b)."""
    o = Outcome(d=date(2026, 9, 1), ticker="042700", h5=2.4, h5_index=None)
    assert o.excess(5) is None


def test_outcome_has_no_baseline_field() -> None:
    """기준선은 소속 시장 지수 하나뿐이다 — 방식을 기록할 열을 두지 않는다 (V12)."""
    assert "baseline" not in Outcome.__dataclass_fields__


# ── 나머지 ──────────────────────────────────────────────────────


def test_evidence_lanes_default_to_absent_not_error() -> None:
    """새 갈래는 없어도 되는 층이다. 실패하면 그 줄만 비운다 (F34)."""
    e = Evidence(d=date(2026, 9, 1), ticker="042700")
    assert e.missing_lanes() == ("공시", "뉴스", "수급", "재무", "공매도")


def test_send_result_failure_carries_reason() -> None:
    assert SendResult(ok=False, reason="smtp timeout").ok is False


def test_run_record_defaults_to_failure() -> None:
    """기록이 없으면 성공으로 위장하지 않는다."""
    assert RunRecord(run_at=date(2026, 9, 1)).status == "failed"


def test_dart_link_builds_viewer_url() -> None:
    assert dart_link("20260822000123").endswith("rcpNo=20260822000123")
