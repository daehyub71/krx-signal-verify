"""lanes — F34. **새 갈래는 없어도 되는 층이다.**

실패한 갈래는 그 줄만 비우고 「생략」으로 적는다. 판정도 메일도 막지 않는다.
그리고 **조용히 빠지지 않는다** — 왜 비었는지가 함께 남는다.

지키는 것:
  · 갈래 하나가 죽어도 **나머지 넷은 그대로 온다**
  · 다섯이 다 죽어도 **판정은 나간다** — 공시 없는 판정도 판정이다
  · **비어 있음과 0은 다르다** — 「수급 0원」이 아니라 「수급 생략」이다
  · **상위가 낡으면 표시한다** (R5) — 2026-08-18~08-31에 조용히 2주간 멈춘 전력이 있다
  · ⚠ **`ksc_meta.updated_at` 열은 거짓말한다** — 2026-08-15인데 페이로드는 2026-09-04다
    (2026-09-05 실DB 확인). 신선도는 **값 안의 `updated`**로 본다
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from verify import lanes
from verify.models import EVIDENCE_LANES

D = date(2026, 9, 5)
T = "005930"


class FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def execute(self, query: Any, params: Any = None) -> FakeConn:
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def meta(updated: str | None = "2026-09-04", column: str = "2026-08-15") -> FakeConn:
    """`ksc_meta` 대역. **열의 `updated_at`과 값 안의 `updated`를 일부러 어긋나게 둔다.**"""
    value = {"updated": updated} if updated else {}
    return FakeConn([("update", value, date.fromisoformat(column))])


# ── 갈래 하나가 죽어도 나머지는 온다 ──────────────────────────────


def test_one_dead_lane_does_not_take_the_others() -> None:
    got = lanes.collect(
        d=D, ticker=T,
        disclosures=lambda: ["공시"],
        news=lambda: (_ for _ in ()).throw(RuntimeError("네이버 죽음")),
        flows=lambda: "수급",
        financial=lambda: "재무",
        shorting=lambda: None,
    )
    assert got.evidence.disclosures == ["공시"]
    assert got.evidence.news is None
    assert got.evidence.flows == "수급"


def test_the_reason_is_kept_not_swallowed() -> None:
    """**조용히 빠지지 않는다** — 왜 비었는지가 남아야 다음 날 고칠 수 있다."""
    got = lanes.collect(d=D, ticker=T, news=lambda: (_ for _ in ()).throw(RuntimeError("HTTP 429")))
    assert "뉴스" in got.skipped
    assert any("429" in r for r in got.reasons.values())
    assert got.reasons["뉴스"].startswith("RuntimeError")


def test_a_lane_returning_none_is_skipped_without_a_reason() -> None:
    """실패가 아니라 **원래 없는 것**이다 — 공매도가 M8 전까지 그 상태다."""
    got = lanes.collect(d=D, ticker=T, shorting=lambda: None)
    assert "공매도" in got.skipped
    assert got.reasons.get("공매도", "") == ""
    assert got.evidence.shorting is None  # 0으로 바꿔 넣지 않는다
    assert got.evidence.shorting is not 0  # noqa: F632 — 0으로 새는 것을 막는 자리다


def test_every_lane_dead_still_produces_evidence() -> None:
    """**판정을 막지 않는다.** 다섯이 다 죽어도 그날 그 종목의 행은 남는다."""
    boom = lambda: (_ for _ in ()).throw(RuntimeError("죽음"))  # noqa: E731
    got = lanes.collect(d=D, ticker=T, disclosures=boom, news=boom, flows=boom,
                        financial=boom, shorting=boom)
    assert got.evidence.d == D and got.evidence.ticker == T
    assert set(got.skipped) == set(EVIDENCE_LANES)


def test_nothing_is_filled_in_with_a_zero() -> None:
    """「수급 0원」과 「수급 생략」은 다른 말이다."""
    got = lanes.collect(d=D, ticker=T, flows=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert got.evidence.flows is None
    assert got.evidence.flows != 0
    assert got.evidence.flows != ()


def test_a_lane_that_works_is_not_marked() -> None:
    got = lanes.collect(d=D, ticker=T, disclosures=lambda: ["공시"], news=lambda: ["뉴스"],
                        flows=lambda: "f", financial=lambda: "fin", shorting=lambda: "s")
    assert got.skipped == ()
    assert got.notes() == ()


def test_lane_names_match_the_model() -> None:
    """이름이 갈라지면 화면과 저장이 다른 말을 한다."""
    assert lanes.LANE_NAMES == EVIDENCE_LANES


# ── 「생략」 표기 ─────────────────────────────────────────────────


def test_skipped_lanes_are_written_out() -> None:
    got = lanes.collect(d=D, ticker=T, news=lambda: None, shorting=lambda: None)
    text = " ".join(got.notes())
    assert "뉴스" in text and "공매도" in text
    assert "생략" in text


def test_notes_carry_no_forbidden_words() -> None:
    from verify import wording

    got = lanes.collect(d=D, ticker=T, news=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    for line in got.notes():
        assert not wording.has_forbidden(line), line
        assert not wording.has_forbidden_outcome(line), line


# ── 상위 신선도 (R5) ──────────────────────────────────────────────


def test_freshness_reads_the_payload_not_the_column() -> None:
    """⚠ **`updated_at` 열은 거짓말한다** — 2026-08-15인데 자료는 2026-09-04까지 있다."""
    f = lanes.freshness(meta(updated="2026-09-04", column="2026-08-15"), today=D)
    assert f.data_date == date(2026, 9, 4)
    assert f.days_behind == 1
    assert f.stale is False


def test_a_two_week_stall_is_flagged() -> None:
    """상위 리포가 2026-08-18~08-31에 조용히 2주간 멈춘 전력이 있다 (R5)."""
    f = lanes.freshness(meta(updated="2026-08-22"), today=D)
    assert f.days_behind == 14
    assert f.stale is True
    assert "2026-08-22" in f.note


def test_a_long_weekend_is_not_stale() -> None:
    """금요일 자료를 화요일에 읽는 것은 정상이다 — 매번 울면 신호가 죽는다."""
    f = lanes.freshness(meta(updated="2026-09-04"), today=date(2026, 9, 8))
    assert f.days_behind == 4
    assert f.stale is False


def test_the_threshold_is_one_day_past_a_long_weekend() -> None:
    assert lanes.STALE_AFTER_DAYS == 4
    assert lanes.freshness(meta(updated="2026-09-04"), today=date(2026, 9, 9)).stale is True


def test_missing_meta_is_unknown_not_fresh() -> None:
    """행이 없으면 **모르는 것**이다 — 최신이라고 가정하면 낡은 자료를 조용히 쓴다."""
    f = lanes.freshness(FakeConn([]), today=D)
    assert f.data_date is None
    assert f.stale is True
    assert "모른" in f.note or "없" in f.note


def test_meta_without_an_updated_field_is_unknown() -> None:
    f = lanes.freshness(meta(updated=None), today=D)
    assert f.data_date is None
    assert f.stale is True


def test_an_unreadable_date_is_unknown_not_a_crash() -> None:
    conn = FakeConn([("update", {"updated": "어제"}, date(2026, 8, 15))])
    f = lanes.freshness(conn, today=D)
    assert f.data_date is None
    assert f.stale is True


def test_freshness_note_is_shown_never_hidden() -> None:
    """**조용히 빠지지 않는다** — 낡았으면 사람이 읽는 자리에 뜬다."""
    f = lanes.freshness(meta(updated="2026-08-22"), today=D)
    assert f.note
    assert "낡" in f.note or "뒤" in f.note


def test_fresh_data_says_nothing() -> None:
    """정상일 때 조용해야 낡았을 때의 한 줄이 보인다."""
    assert lanes.freshness(meta(updated="2026-09-04"), today=D).note == ""


# ── 판정을 막지 않는다 ────────────────────────────────────────────


def test_a_verdict_still_comes_out_with_every_lane_empty() -> None:
    """F34의 요점. 증거가 하나도 없어도 **판정은 나간다.**"""
    from verify import verdict
    from verify.models import VerdictInput

    v = verdict.judge(VerdictInput())
    assert v.stand in ("정합", "불일치", "무관")
    assert v.limit_note


def test_skipped_lanes_become_blind_spots() -> None:
    """빈 갈래는 **사각지대로 흐른다** — 점수에 0으로 들어가지 않는다."""
    from verify import verdict
    from verify.models import VerdictInput

    v = verdict.judge(VerdictInput())
    assert "재무" in v.blind_spots
    assert "공매도" in v.blind_spots


@pytest.mark.parametrize("lane", EVIDENCE_LANES)
def test_no_single_lane_is_required(lane: str) -> None:
    """어느 하나도 필수가 아니다 — 하나가 필수면 그것이 죽는 날 전부 멈춘다."""
    keys = ("disclosures", "news", "flows", "financial", "shorting")
    calls: dict[str, Any] = {name: (lambda: "값") for name in keys}
    idx = EVIDENCE_LANES.index(lane)
    key = keys[idx]
    calls[key] = lambda: (_ for _ in ()).throw(RuntimeError("죽음"))
    got = lanes.collect(d=D, ticker=T, **calls)
    assert got.skipped == (lane,)
    assert len(got.evidence.missing_lanes()) == 1
