"""신호 날짜 ≠ 실행 날짜 (M7 트러블슈팅 ④).

상위 `krx-signal-alerts`는 **아침에 전 거래일 종가로** 신호를 낸다 — 월요일 10:05 KST 실행이
`d = 금요일`로 36건을 썼다 (2026-09-07 실측). 이 배치는 `run_date = 오늘`로 신호를 찾아
`no_signals`로 끝났다.
**자동 배치가 한 번도 신호를 잡지 못한 원인**이다 (09-03 판정은 `--date`를 준 수동 실행이었다).

지키는 것:
  · 게이트가 받아 오는 상위 `data_date`로 신호를 찾는다 — `run_date`가 아니다
  · 온디맨드(게이트 없음)는 상위 실행 기록에서 같은 날짜를 얻는다. 없으면 `run_date`
  · 「오늘 이미 돌았다」는 판정 표가 아니라 **실행 기록**으로 본다 — 판정 `d`는 신호 날짜라
    오늘이 아니다
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from verify import main as m
from verify import nodes, store
from verify import state as st
from verify.models import SignalRow

RUN = date(2026, 9, 7)      # 월요일 — 배치가 도는 날
SIGNAL = date(2026, 9, 4)   # 금요일 — 상위가 신호에 붙인 날짜


ONDEMAND: dict[str, Any] = {"run_date": RUN, "mode": st.MODE_ONDEMAND, "ticker": "017890"}


def rows_for(day: date) -> list[SignalRow]:
    return [SignalRow(d=day, strategy="vcp", ticker="017890", name="한국알콜", evidence={})]


def asking(asked: list[date], rows: bool = True) -> Any:
    """`_fetch_signals` 대역 — 어느 날짜로 물었는지 적는다."""
    def _f(d: date) -> list[SignalRow]:
        asked.append(d)
        return rows_for(d) if rows else []
    return _f


def seeing(seen: list[date]) -> Any:
    """`prefetch` 대역 — 수집 기준일을 적는다."""
    def _f(rows: Any, day: date) -> dict[str, Any]:
        seen.append(day)
        return {"errors": []}
    return _f


# ── fetch_signals ────────────────────────────────────────────────


def test_batch_reads_signals_of_the_upstream_data_date(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[date] = []
    monkeypatch.setattr(nodes, "_fetch_signals", asking(asked))
    monkeypatch.setattr(nodes, "prefetch", lambda rows, day: {"errors": []})
    out = nodes.fetch_signals(cast(st.VerifyState, {"run_date": RUN, "data_date": SIGNAL}))
    assert asked == [SIGNAL], "run_date로 찾으면 월요일엔 늘 0건이다"
    assert out["signals"][0].d == SIGNAL


def test_ondemand_asks_the_upstream_for_the_signal_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """온디맨드는 게이트를 건너뛰어 `data_date`가 없다 — 상위 실행 기록에 묻는다."""
    asked: list[date] = []
    monkeypatch.setattr(nodes, "_signal_day", lambda run_date: SIGNAL)
    monkeypatch.setattr(nodes, "_fetch_signals", asking(asked))
    monkeypatch.setattr(nodes, "prefetch", lambda rows, day: {"errors": []})
    nodes.fetch_signals(cast(st.VerifyState, ONDEMAND))
    assert asked == [SIGNAL]


def test_falls_back_to_run_date_without_an_upstream_record(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[date] = []
    monkeypatch.setattr(nodes, "_signal_day", lambda run_date: None)
    monkeypatch.setattr(nodes, "_fetch_signals", asking(asked, rows=False))
    nodes.fetch_signals(cast(st.VerifyState, ONDEMAND))
    assert asked == [RUN]


def test_a_dead_signal_day_lookup_is_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(run_date: date) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(nodes, "_signal_day", boom)
    out = nodes.fetch_signals(cast(st.VerifyState, ONDEMAND))
    assert out["signals"] == [] and out["errors"]


def test_collection_windows_still_use_the_run_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """근거 수집(공시 30일·재무 보고서 선택)은 **오늘** 기준이다 — 신호 뒤의 공시도 봐야 한다."""
    seen: list[date] = []
    monkeypatch.setattr(nodes, "_fetch_signals", lambda d: rows_for(d))
    monkeypatch.setattr(nodes, "prefetch", seeing(seen))
    nodes.fetch_signals(cast(st.VerifyState, {"run_date": RUN, "data_date": SIGNAL}))
    assert seen == [RUN]


# ── store ────────────────────────────────────────────────────────


class FakeConn:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row, self.sql, self.params = row, "", None

    def execute(self, sql: Any, params: Any = None) -> FakeConn:
        self.sql, self.params = " ".join(str(sql).split()), params
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


def test_signal_day_comes_from_the_upstream_run_record() -> None:
    conn = FakeConn((datetime(2026, 9, 7, 1, 6, tzinfo=UTC), SIGNAL, "ok", 36))
    assert store.fetch_signal_day(conn, RUN) == SIGNAL


def test_signal_day_is_none_without_an_upstream_run() -> None:
    assert store.fetch_signal_day(FakeConn(None), RUN) is None


def test_has_run_looks_at_the_run_log_not_the_verdicts() -> None:
    conn = FakeConn((1,))
    assert store.has_run(conn, RUN) is True
    assert "ksv_runs" in conn.sql and "ksv_verdicts" not in conn.sql
    assert "run_date = %s" in conn.sql
    # 게이트 실패는 「돌았다」가 아니다 — cron이 다시 돈다
    assert "'ok'" in conn.sql and "'no_signals'" in conn.sql
    assert conn.params == (RUN,)


def test_has_run_is_false_without_a_completed_run() -> None:
    assert store.has_run(FakeConn(None), RUN) is False


# ── main ─────────────────────────────────────────────────────────


def test_already_verified_uses_the_run_log() -> None:
    """판정 `d`는 신호 날짜(금요일)라 `run_date`(월요일)로 판정 표를 보면 늘 「안 돌았다」다."""
    import inspect

    src = inspect.getsource(m._already_verified)
    assert "store.has_run(" in src
    assert "fetch_verdicts" not in src
