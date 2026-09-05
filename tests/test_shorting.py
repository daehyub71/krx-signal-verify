"""shorting — 공매도 갈래. **지금은 「없는 층」 경로만** (M8 승인 전, 2026-09-05).

`ksc_shorting`이 아직 없다(실DB 확인). SPEC F32도 「상위가 수집하면 SQL로 읽는다」라
스키마가 안 정해졌다 — 지금 파싱을 쓰면 **상상한 스키마에 맞추게 된다.**

그래서 여기서 정하는 것은 **상태 판별 하나**다. 그리고 그것이 R6가 말하는 바로 그 구별이다.

  · **표가 없다** → 없는 층. 정상이고, F34가 「생략」으로 표기한다
  · **표는 있는데 0행** → **실패다.** pykrx `get_shorting_balance_by_ticker`가
    예외 없이 0행·빈 열을 준다(2026-08-31·09-01 재현). `try/except`로는 안 걸린다.
    이걸 「없음」으로 흘려보내면 그 갈래가 **정상적으로 비어 있는 상태**로 지나간다

두 상태가 겉보기에 같아 보이는 것이 R6의 함정이고, 여기서 가른다.
"""

from __future__ import annotations

import pytest

from verify import shorting


class FakeConn:
    """`execute`만 흉내 낸다. 표 존재 여부와 행 수를 정한다."""

    def __init__(self, *, table: bool = True, rows: int = 0) -> None:
        self.table, self.rows = table, rows
        self.sql: list[str] = []

    def execute(self, query: str, params: object = None) -> FakeConn:
        self.sql.append(str(query))
        rows: list[tuple[object, ...]] = (
            [(self.table,)] if "to_regclass" in str(query)
            else [(f"0000{i:02d}",) for i in range(self.rows)]
        )
        self._out = rows
        return self

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._out

    def fetchone(self) -> tuple[object, ...] | None:
        return self._out[0] if self._out else None


# ── 표가 없다 = 없는 층 (정상) ────────────────────────────────────


def test_absent_table_is_a_missing_layer_not_a_failure() -> None:
    """M8 승인 전의 기본 상태다. 판정·메일을 막지 않는다 (F34)."""
    s = shorting.probe(FakeConn(table=False))
    assert s.state == shorting.MISSING
    assert s.ok is True  # 실패가 아니다
    assert "수집" in s.reason or "없" in s.reason


def test_a_missing_layer_yields_no_data_and_no_zero() -> None:
    """0으로 채우면 「공매도가 없었다」는 없는 사실이 생긴다."""
    s = shorting.probe(FakeConn(table=False))
    assert s.rows == 0
    assert s.days == ()


# ── 표는 있는데 0행 = 실패 (R6) ───────────────────────────────────


def test_an_empty_table_is_a_failure_not_an_absence() -> None:
    """**R6의 핵심.** pykrx가 예외 없이 0행을 준다 — 「없음」으로 흘리면 조용히 지나간다."""
    s = shorting.probe(FakeConn(table=True, rows=0))
    assert s.state == shorting.EMPTY
    assert s.ok is False
    assert "0행" in s.reason


def test_the_two_states_are_never_the_same() -> None:
    """겉보기 결과(자료 없음)가 같아서 가르지 않으면 R6가 그대로 재현된다."""
    gone = shorting.probe(FakeConn(table=False))
    empty = shorting.probe(FakeConn(table=True, rows=0))
    assert gone.state != empty.state
    assert gone.ok is not empty.ok
    assert (gone.rows, empty.rows) == (0, 0)  # 행 수만 보면 구별이 안 된다


# ── 표에 행이 있다 = 아직 못 읽는다 (M8) ──────────────────────────


def test_rows_present_says_parsing_is_not_written_yet() -> None:
    """**조용히 빈 결과를 주지 않는다.** 상위가 채우기 시작하면 여기가 알린다."""
    s = shorting.probe(FakeConn(table=True, rows=20))
    assert s.state == shorting.UNPARSED
    assert s.ok is False
    assert "M8" in s.reason
    assert s.rows == 20


def test_unparsed_still_returns_no_days() -> None:
    """파싱을 안 썼으므로 추이도 없다 — 지어내지 않는다."""
    assert shorting.probe(FakeConn(table=True, rows=20)).days == ()


# ── 파싱은 아직 없다 ──────────────────────────────────────────────


def test_parsing_is_not_implemented_and_says_so() -> None:
    """`ksc_shorting` 스키마가 안 정해졌다 — 추측으로 짜지 않는다 (2026-09-05)."""
    with pytest.raises(NotImplementedError, match="M8"):
        shorting.read_days(FakeConn(table=True, rows=20), "005930")


def test_module_does_not_guess_a_schema() -> None:
    """열 이름을 지금 적어 두면 상위가 다른 이름으로 만들었을 때 조용히 어긋난다."""
    import pathlib

    src = pathlib.Path(shorting.__file__).read_text(encoding="utf-8")
    for guess in ("select 공매도", "short_volume", "short_ratio", "shorting_volume"):
        assert guess not in src, guess


def test_window_is_twenty_trading_days() -> None:
    """F32 — 20거래일 추이. 숫자만 미리 못 박아 둔다."""
    assert shorting.WINDOW_DAYS == 20


# ── 판정에 어떻게 흘러가는가 ──────────────────────────────────────


def test_a_missing_layer_becomes_a_blind_spot_not_a_score() -> None:
    """`judge()`는 공매도를 **사각지대로만** 본다 — 점수에 안 들어간다 (F30·F32·V5)."""
    from verify import verdict
    from verify.models import VerdictInput

    without = verdict.judge(VerdictInput())
    assert "공매도" in without.blind_spots

    with_it = verdict.judge(VerdictInput(shorting=object()))
    assert "공매도" not in with_it.blind_spots
    assert with_it.score == without.score  # 점수는 그대로다
