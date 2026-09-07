"""shorting — 공매도 갈래 (F32 · V6b · M8, 2026-09-07). 상위 `ksc_shorting`을 SQL로 읽는다.

지키는 것:
  · 상태 셋 — **표가 없다**(없는 층·정상) · **표는 있는데 0행**(실패, R6) · **행이 있다**(읽는다).
    앞의 둘은 겉보기가 같아 가르지 않으면 「정상적으로 비어 있는」 상태로 지나간다
  · 열 이름은 상위와 같다 — `short_vol · buy_vol · ratio`. 상위 `tests/test_shorting.py`가 잠근다
  · 행이 없는 종목은 **빠진다** — 0으로 만들지 않는다. 0주는 KRX가 준 실제 값이다
  · 사람이 읽는 줄은 사실만 — `공매도 비중`은 허용 합성어라 N1을 통과한다
  · 판정 점수에는 안 들어간다 — 사각지대에서 빠질 뿐이다 (F32·V5)
"""

from __future__ import annotations

from datetime import date
from typing import Any

from verify import shorting, wording

D = date(2026, 9, 4)


class FakeConn:
    """`execute`만 흉내 낸다. 표 존재 여부·행 존재·읽기 행을 정한다."""

    def __init__(self, *, table: bool = True, any_rows: int = 0,
                 rows: list[tuple[Any, ...]] | None = None) -> None:
        self.table, self.any_rows, self.rows = table, any_rows, rows or []
        self.sql: list[str] = []
        self.params: list[Any] = []

    def execute(self, query: str, params: object = None) -> FakeConn:
        q = " ".join(str(query).split())
        self.sql.append(q)
        self.params.append(params)
        if "to_regclass" in q:
            self._out: list[tuple[Any, ...]] = [(self.table,)]
        elif q.startswith("select 1 from"):
            self._out = [(1,) for _ in range(self.any_rows)]
        else:
            self._out = self.rows
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._out

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._out[0] if self._out else None


ROWS = [
    ("005930", date(2026, 9, 3), 300_000, 18_000_000, 1.60),
    ("005930", D, 368_918, 18_649_816, 1.98),
    ("00104K", D, 0, 4_053, 0.0),
]


# ── 상태 ─────────────────────────────────────────────────────────


def test_absent_table_is_a_missing_layer_not_a_failure() -> None:
    s = shorting.probe(FakeConn(table=False))
    assert s.state == shorting.MISSING and s.ok is True and s.days == ()


def test_an_empty_table_is_a_failure_not_an_absence() -> None:
    """**R6의 핵심.** pykrx가 예외 없이 0행을 준다 — 「없음」으로 흘리면 조용히 지나간다."""
    s = shorting.probe(FakeConn(table=True, any_rows=0))
    assert s.state == shorting.EMPTY and s.ok is False and "0행" in s.reason


def test_the_two_states_are_never_the_same() -> None:
    gone = shorting.probe(FakeConn(table=False))
    empty = shorting.probe(FakeConn(table=True, any_rows=0))
    assert gone.state != empty.state and gone.ok is not empty.ok


def test_rows_present_is_ready() -> None:
    s = shorting.probe(FakeConn(table=True, any_rows=1))
    assert s.state == shorting.READY and s.ok is True


# ── 읽기 ─────────────────────────────────────────────────────────


def test_read_all_groups_by_ticker_in_date_order() -> None:
    got = shorting.read_all(FakeConn(rows=ROWS), ["005930", "00104K", "000660"])
    assert set(got) == {"005930", "00104K"}, "행이 없는 종목은 빠진다 — 0으로 만들지 않는다"
    days = got["005930"].days
    assert [x.d for x in days] == [date(2026, 9, 3), D]
    assert days[-1] == shorting.ShortDay(d=D, short_vol=368_918, buy_vol=18_649_816, ratio=1.98)
    assert got["005930"].state == shorting.READY


def test_zero_short_volume_is_a_real_value() -> None:
    got = shorting.read_all(FakeConn(rows=ROWS), ["00104K"])
    assert got["00104K"].latest is not None and got["00104K"].latest.short_vol == 0


def test_read_all_asks_the_agreed_columns_with_the_window() -> None:
    conn = FakeConn(rows=[])
    shorting.read_all(conn, ["005930"], days=20)
    assert "select s.ticker, s.d, s.short_vol, s.buy_vol, s.ratio" in conn.sql[-1]
    assert "order by d desc limit %s" in conn.sql[-1]
    assert conn.params[-1] == (20, ["005930"])


def test_read_all_with_no_tickers_sends_nothing() -> None:
    conn = FakeConn(rows=ROWS)
    assert shorting.read_all(conn, []) == {}
    assert conn.sql == []


def test_read_days_is_the_single_ticker_form() -> None:
    assert len(shorting.read_days(FakeConn(rows=ROWS), "005930")) == 2
    assert shorting.read_days(FakeConn(rows=ROWS), "000660") == ()


def test_window_is_twenty_trading_days() -> None:
    assert shorting.WINDOW_DAYS == 20


# ── 요약 · 문구 ───────────────────────────────────────────────────


def test_average_ratio_is_none_without_data() -> None:
    assert shorting.Shorting(state=shorting.READY).avg_ratio is None
    assert shorting.Shorting(state=shorting.READY).lines() == ()


def test_lines_state_facts_and_pass_the_wording_rules() -> None:
    got = shorting.read_all(FakeConn(rows=ROWS), ["005930"])["005930"]
    lines = got.lines()
    assert lines[0] == "09/04 공매도 368,918주 · 공매도 비중 1.98%"
    assert lines[1] == "2거래일 공매도 비중 평균 1.79%"
    for line in lines:
        assert wording.first_violation(line) == ("", ""), line


# ── 판정에 어떻게 흘러가는가 ──────────────────────────────────────


def test_a_missing_layer_becomes_a_blind_spot_not_a_score() -> None:
    """`judge()`는 공매도를 **사각지대로만** 본다 — 점수에 안 들어간다 (F30·F32·V5)."""
    from verify import verdict
    from verify.models import VerdictInput

    without = verdict.judge(VerdictInput())
    assert "공매도" in without.blind_spots

    with_it = verdict.judge(VerdictInput(shorting=shorting.Shorting(state=shorting.READY)))
    assert "공매도" not in with_it.blind_spots
    assert with_it.score == without.score


def test_llm_input_carries_the_shorting_summary() -> None:
    """서술이 공매도를 말할 수 있어야 한다 (F32) — 평균과 최근 값만, 방향 해석은 없다."""
    from verify import analysis
    from verify.models import Disclosure, SignalRow, VerdictInput

    got = shorting.read_all(FakeConn(rows=ROWS), ["005930"])["005930"]
    sig = SignalRow(d=D, ticker="005930", name="삼성전자", strategy="vcp", evidence={})
    inp = VerdictInput(disclosures=(Disclosure(D, "주요사항보고서", "1"),), shorting=got)
    item = analysis.build_input([(sig, inp, None)])[0]
    assert item["shorting"]["avg_ratio_20d"] == 1.79
    assert item["shorting"]["latest"] == {"date": "09/04", "ratio": 1.98, "short_vol": 368_918}
    assert "shorting" in analysis.SYSTEM_PROMPT


def test_llm_input_skips_shorting_without_data() -> None:
    from verify import analysis
    from verify.models import Disclosure, SignalRow, VerdictInput

    sig = SignalRow(d=D, ticker="005930", name="삼성전자", strategy="vcp", evidence={})
    inp = VerdictInput(disclosures=(Disclosure(D, "주요사항보고서", "1"),), shorting=None)
    assert "shorting" not in analysis.build_input([(sig, inp, None)])[0]
