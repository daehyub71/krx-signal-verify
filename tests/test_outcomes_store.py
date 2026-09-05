"""ksv_outcomes 저장 + `fill_outcomes` 노드 (F22·F23).

지키는 것:
  · **쓰는 열 = 읽는 열** — `ksv_verdicts`에서 배운 것을 그대로. `market`이 스키마에만 있다
  · **게이트보다 앞에서 돈다** — 어제 판정 채점은 오늘 신호와 무관하다.
    게이트가 `stale`·`gate_timeout`으로 끝나는 날에도 채점은 돌아야 한다
  · **미도래를 0으로 덮지 않는다** — 이미 채워진 값을 `None`으로 되돌리지도 않는다
  · 실패해도 예외를 밖으로 내지 않는다 (I/O 노드 규칙)
"""

from __future__ import annotations

import pathlib
import re
from datetime import date
from typing import Any, cast

import pytest

from verify import nodes, store
from verify import state as st
from verify.models import Outcome

D = date(2026, 9, 3)
SQL = pathlib.Path("supabase/schema.sql").read_text(encoding="utf-8")


class FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: Any, params: Any = None) -> FakeConn:
        self.calls.append((str(query), params))
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def an_outcome(**over: Any) -> Outcome:
    base: dict[str, Any] = {
        "d": D, "ticker": "005930", "h5": 1.5, "h20": None, "h60": None,
        "h5_index": 0.5, "h20_index": None, "h60_index": None,
    }
    base.update(over)
    return Outcome(**base)


# ── 쓰는 열 = 읽는 열 ─────────────────────────────────────────────


def test_one_column_list_feeds_both_directions() -> None:
    row = store.outcome_row(an_outcome(), "KOSPI")
    assert tuple(row) == store.OUTCOME_COLUMNS


def test_the_select_reads_every_column_it_writes() -> None:
    """`ksv_verdicts`에서 배운 것 — 읽는 열이 적으면 재실행이 기본값으로 덮는다."""
    selected = store.Q_OUTCOMES.split("select", 1)[1].split("from", 1)[0]
    read = {c.strip() for c in selected.split(",")}
    assert set(store.OUTCOME_COLUMNS) <= read, set(store.OUTCOME_COLUMNS) - read


def test_the_schema_has_no_column_we_forget() -> None:
    body = SQL.split("create table if not exists ksv_outcomes (", 1)[1].split("\n);", 1)[0]
    skip = ("constraint", "primary key", "--")
    cols = {
        m.group(1) for line in body.splitlines()
        if (m := re.match(r"\s{2}(\w+)\s+\w", line)) and not line.strip().startswith(skip)
    }
    assert cols - {"filled_at"} == set(store.OUTCOME_COLUMNS)


def test_market_travels_with_the_outcome() -> None:
    """`Outcome`에는 없고 스키마에만 있다 — 안 실으면 그 열이 늘 빈다 (왕복 함정)."""
    assert store.outcome_row(an_outcome(), "KOSDAQ")["market"] == "KOSDAQ"


def test_round_trip_keeps_the_nulls() -> None:
    """미도래는 `None`이다. `0.0`으로 돌아오면 「수익률 0%」가 된다."""
    row = store.outcome_row(an_outcome(), "KOSPI")
    back, market = store.outcome_from_row(tuple(row[c] for c in store.OUTCOME_COLUMNS))
    assert back == an_outcome()
    assert back.h20 is None and back.h60_index is None
    assert market == "KOSPI"


# ── 저장 ──────────────────────────────────────────────────────────


def test_rows_are_chunked() -> None:
    conn = FakeConn()
    outs = [(an_outcome(ticker=f"{i:06d}"), "KOSPI") for i in range(45)]
    n = store.save_outcomes(outs, conn=conn)
    assert n == 45
    assert len(conn.calls) == 3


def test_saving_nothing_sends_nothing() -> None:
    conn = FakeConn()
    assert store.save_outcomes([], conn=conn) == 0
    assert conn.calls == []


def test_the_statement_upserts_on_day_and_ticker() -> None:
    conn = FakeConn()
    store.save_outcomes([(an_outcome(), "KOSPI")], conn=conn)
    sql = conn.calls[0][0].lower()
    assert "on conflict (d, ticker)" in sql
    assert "do update" in sql


def test_a_filled_value_is_never_overwritten_with_null() -> None:
    """**이미 도래해 채운 값을 다음 실행이 지우면 안 된다.**

    구간이 하나씩 도래하므로 매일 같은 행을 다시 쓴다 — `coalesce`로 지킨다.
    """
    conn = FakeConn()
    store.save_outcomes([(an_outcome(), "KOSPI")], conn=conn)
    sql = conn.calls[0][0].lower()
    for col in ("h5", "h20", "h60", "h5_index", "h20_index", "h60_index"):
        assert f"{col} = coalesce(excluded.{col}, ksv_outcomes.{col})" in sql, col


def test_the_fill_time_is_recorded() -> None:
    conn = FakeConn()
    store.save_outcomes([(an_outcome(), "KOSPI")], conn=conn)
    assert "filled_at = now()" in conn.calls[0][0].lower()


# ── fill_outcomes 노드 ────────────────────────────────────────────


def test_the_node_counts_what_it_filled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "_fill_outcomes", lambda day: 7)
    out = nodes.fill_outcomes(cast(st.VerifyState, {"run_date": D}))
    assert out["outcomes_filled"] == 7


def test_a_failure_does_not_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    """raise하면 `record_run`에 못 가 실패 기록까지 사라진다 (N11)."""
    def boom(day: date) -> int:
        raise RuntimeError("DB 죽음")

    monkeypatch.setattr(nodes, "_fill_outcomes", boom)
    out = nodes.fill_outcomes(cast(st.VerifyState, {"run_date": D}))
    assert out["outcomes_filled"] == 0
    assert any("DB 죽음" in e for e in out["errors"])


def test_scoring_runs_before_the_gate() -> None:
    """**어제 판정 채점은 오늘 신호와 무관하다** — 게이트가 실패한 날도 돌아야 한다."""
    dot = (pathlib.Path("docs") / "diagrams" / "graph.dot").read_text(encoding="utf-8")
    edges = dot.replace('"', "")
    assert "START -> fill_outcomes" in edges or "start -> fill_outcomes" in edges.lower()


def test_it_is_no_longer_a_stub() -> None:
    assert "fill_outcomes" not in nodes.STUB_NODES


def test_the_node_stays_under_the_line_limit() -> None:
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(nodes.fill_outcomes).lstrip())
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert (fn.end_lineno or 0) - (fn.lineno or 0) <= 20


# ── 어느 판정을 채울지 고른다 ─────────────────────────────────────


def test_only_unfinished_verdicts_are_looked_up() -> None:
    """60거래일이 다 찬 행을 매일 다시 재지 않는다."""
    where = store.Q_PENDING.lower().split("where", 1)[1]
    assert "h60 is null" in where


def test_it_does_not_look_further_back_than_the_longest_horizon() -> None:
    """60거래일이 지나면 더 채울 것이 없다 — 3년치를 매일 훑지 않는다."""
    assert "%s" in store.Q_PENDING
    assert store.OUTCOME_LOOKBACK_DAYS >= 60 * 2  # 달력일 여유 (주말·휴장)


def test_pending_rows_carry_the_market() -> None:
    """어느 지수와 견줄지는 `ksc_tickers.market`이 정한다 (F23)."""
    assert "market" in store.Q_PENDING
