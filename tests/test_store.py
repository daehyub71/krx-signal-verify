"""상위 조회 — I/O 층. **DB 없이** 가짜 커넥션으로 계약을 잠근다.

조회 함수는 **순수한 「인자 → 행」 모양**이다 (PLAN §6-2) — 그래프 상태를 모른다.
그래야 나중에 MCP 도구로 그대로 감쌀 수 있다 (V14).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest

from verify import store
from verify.models import UpstreamRun


class FakeCursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row


class FakeConn:
    """`execute(sql, params)`를 받아 적고 미리 정한 행을 돌려준다."""

    def __init__(self, row: tuple[Any, ...] | None = None) -> None:
        self.row = row
        self.sql = ""
        self.params: Any = None

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.sql = " ".join(str(sql).split())
        self.params = params
        return FakeCursor(self.row)


OK_ROW = (datetime(2026, 9, 2, 1, 5, tzinfo=UTC), date(2026, 9, 1), "ok", 30)


def test_returns_none_when_upstream_has_not_run() -> None:
    """행이 없으면 `None`. 게이트가 `missing`으로 판정해 기다린다."""
    assert store.fetch_upstream_run(FakeConn(None), date(2026, 9, 2)) is None


def test_maps_the_row_into_a_typed_record() -> None:
    run = store.fetch_upstream_run(FakeConn(OK_ROW), date(2026, 9, 2))
    assert run == UpstreamRun(
        run_at=OK_ROW[0], data_date=date(2026, 9, 1), status="ok", signals=30
    )


def test_matches_today_in_seoul_not_utc() -> None:
    """상위는 08:20 KST에 돈다 = 전날 23:20 UTC. UTC로 세면 하루 어긋난다."""
    conn = FakeConn(OK_ROW)
    store.fetch_upstream_run(conn, date(2026, 9, 2))
    assert "asia/seoul" in conn.sql.lower()
    assert conn.params == (date(2026, 9, 2),)


def test_takes_the_latest_run_of_the_day() -> None:
    """하루에 여러 번 돈 날이 있다(재실행). **마지막 것**을 본다."""
    conn = FakeConn(OK_ROW)
    store.fetch_upstream_run(conn, date(2026, 9, 2))
    assert "order by run_at desc" in conn.sql.lower()
    assert "limit 1" in conn.sql.lower()


def test_reads_only_ksa_runs() -> None:
    """상위 테이블은 읽기만 한다. 쓰기 문장이 섞이면 안 된다."""
    conn = FakeConn(OK_ROW)
    store.fetch_upstream_run(conn, date(2026, 9, 2))
    low = conn.sql.lower()
    assert low.startswith("select")
    for banned in ("insert", "update", "delete", "drop", "alter"):
        assert banned not in low


def test_query_function_does_not_know_graph_state() -> None:
    """`VerifyState`를 받지 않는다 — 받으면 나중에 MCP 도구로 못 감싼다 (V14)."""
    import inspect

    params = list(inspect.signature(store.fetch_upstream_run).parameters)
    assert params == ["conn", "run_date"]


# ── 게이트 판정 — 순수 함수라 DB가 필요 없다 ────────────────────


def test_gate_missing_when_no_row() -> None:
    from verify import nodes
    from verify import state as st

    assert nodes.gate_from(None)["gate"] == st.GATE_MISSING


def test_gate_stale_when_upstream_said_so() -> None:
    """상위가 스스로 `stale_data`로 끝낸 날이 실재한다 (2026-08-30·08-31)."""
    from verify import nodes
    from verify import state as st

    run = UpstreamRun(OK_ROW[0], date(2026, 8, 27), "stale_data", 0)
    out = nodes.gate_from(run)
    assert out["gate"] == st.GATE_STALE
    assert out["data_date"] == date(2026, 8, 27)


def test_gate_ready_when_upstream_is_ok() -> None:
    from verify import nodes
    from verify import state as st

    out = nodes.gate_from(UpstreamRun(*OK_ROW))
    assert out["gate"] == st.GATE_READY
    assert out["data_date"] == date(2026, 9, 1)


@pytest.mark.parametrize("status", ["failed", "gate_timeout", ""])
def test_gate_treats_any_non_ok_status_as_stale(status: str) -> None:
    """모르는 상태가 오면 **더 안전한 쪽**으로 — 신호를 믿지 않는다."""
    from verify import nodes
    from verify import state as st

    assert nodes.gate_from(UpstreamRun(OK_ROW[0], None, status, 0))["gate"] == st.GATE_STALE
