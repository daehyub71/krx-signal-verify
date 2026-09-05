"""수집 배선 — `fetch_signals`·`fetch_one` (F2·F3~F9).

M2가 수집 **모듈**을 다 만들었는데 **그것을 부르는 노드 둘이 계획에서 빠져 있었다**
(2026-09-05 발견 — `ksv_verdicts`가 0행인 것을 보고). 여기서 붙인다.

지키는 것:
  · **그날 `suppressed = false`인 것만** — 억제된 신호는 상위가 메일에 안 실었다 (F2)
  · **`sent_email`을 쓰지 않는다** — 상위가 그 열을 채우지 않는다 (실측: 전부 false)
  · `fetch_one`은 **갈래 하나가 죽어도 나머지를 가져온다** (F34) — `lanes.collect`에 맡긴다
  · **한 종목이 fan-out을 죽이지 않는다** — 예외를 밖으로 내지 않는다
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from verify import nodes
from verify import state as st
from verify.models import Evidence, SignalRow

D = date(2026, 9, 3)


class FakeConn:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: Any, params: Any = None) -> FakeConn:
        self.calls.append((str(query), params))
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def raw(ticker: str = "000430", name: str = "대원강업", strategy: str = "mtf") -> tuple[Any, ...]:
    return (D, strategy, ticker, name, {"price": {"close": 4335, "change_pct": 2.85}})


# ── store.fetch_signals ───────────────────────────────────────────


def test_signals_are_rebuilt_as_domain_rows() -> None:
    from verify import store

    got = store.fetch_signals(FakeConn([raw(), raw("002900", "TYM")]), D)
    assert [s.ticker for s in got] == ["000430", "002900"]
    assert isinstance(got[0], SignalRow)
    assert got[0].name == "대원강업"
    assert got[0].close == 4335  # evidence 프로퍼티가 살아 있다


def test_only_unsuppressed_rows_are_selected() -> None:
    """억제된 신호는 상위가 메일에 안 실었다 — 우리도 검증하지 않는다 (F2).

    실측(2026-09-05): 572행 중 **309행이 `suppressed = true`**다. 안 거르면 절반 이상이 는다.
    """
    from verify import store

    where = store.Q_SIGNALS.lower().split("where", 1)[1].split("order by", 1)[0]
    assert "suppressed" in where
    assert "not suppressed" in where or "suppressed = false" in where
    assert " or " not in where  # 필터가 무력화되지 않는다


def test_sent_email_is_not_used() -> None:
    """상위가 그 열을 채우지 않는다 — 실측에서 전부 `false`다. 쓰면 0건이 된다 (F2)."""
    from verify import store

    assert "sent_email" not in store.Q_SIGNALS
    assert "sent_kakao" not in store.Q_SIGNALS


def test_signals_are_ordered_stably() -> None:
    """상위 메일과 같은 순서로 본다 — 순서가 흔들리면 어제와 대조가 안 된다."""
    from verify import store

    assert "order by" in store.Q_SIGNALS.lower()


def test_the_day_is_a_parameter() -> None:
    from verify import store

    conn = FakeConn([])
    store.fetch_signals(conn, D)
    assert conn.calls[0][1] == (D,)


def test_no_rows_is_an_empty_list_not_an_error() -> None:
    """신호 없는 날이 있다 — 휴장일·억제 전량."""
    from verify import store

    assert store.fetch_signals(FakeConn([]), D) == []


# ── fetch_signals 노드 ────────────────────────────────────────────


def test_the_node_puts_signals_into_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "_fetch_signals", lambda run_date: [
        SignalRow(d=run_date, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    ])
    out = nodes.fetch_signals(cast(st.VerifyState, {"run_date": D}))
    assert [s.ticker for s in out["signals"]] == ["000430"]


def test_ondemand_takes_only_that_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """궁금해서 넣은 종목 하나만 본다 — 그날 신호 전부를 돌리지 않는다 (V8)."""
    monkeypatch.setattr(nodes, "_fetch_signals", lambda run_date: [
        SignalRow(d=run_date, strategy="mtf", ticker="000430", name="대원강업", evidence={}),
        SignalRow(d=run_date, strategy="vcp", ticker="005930", name="삼성전자", evidence={}),
    ])
    out = nodes.fetch_signals(
        cast(st.VerifyState, {"run_date": D, "mode": st.MODE_ONDEMAND, "ticker": "005930"})
    )
    assert [s.ticker for s in out["signals"]] == ["005930"]


def test_an_ondemand_ticker_with_no_signal_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """그날 신호가 아니었던 종목 — 지어내지 않는다."""
    monkeypatch.setattr(nodes, "_fetch_signals", lambda run_date: [])
    out = nodes.fetch_signals(
        cast(st.VerifyState, {"run_date": D, "mode": st.MODE_ONDEMAND, "ticker": "005930"})
    )
    assert out["signals"] == []


def test_a_failed_fetch_does_not_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    """I/O 노드는 예외를 밖으로 내지 않는다 — raise하면 `record_run`에 못 간다."""
    def boom(run_date: date) -> Any:
        raise RuntimeError("DB 죽음")

    monkeypatch.setattr(nodes, "_fetch_signals", boom)
    out = nodes.fetch_signals(cast(st.VerifyState, {"run_date": D}))
    assert out["signals"] == []
    assert any("DB 죽음" in e for e in out["errors"])


# ── fetch_one 노드 ────────────────────────────────────────────────


def test_fetch_one_returns_one_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "_collect_lanes", lambda run_date, sig, ctx=None: (
        Evidence(d=run_date, ticker=sig.ticker, disclosures=("공시",)), (), {}
    ))
    sig = SignalRow(d=D, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    out = nodes.fetch_one(cast(st.VerifyState, {"run_date": D, "signal": sig}))
    assert len(out["evidence"]) == 1
    assert out["evidence"][0].ticker == "000430"


def test_fetch_one_reports_skipped_lanes(monkeypatch: pytest.MonkeyPatch) -> None:
    """빈 갈래가 **조용히 빠지지 않는다** (F34)."""
    monkeypatch.setattr(nodes, "_collect_lanes", lambda run_date, sig, ctx=None: (
        Evidence(d=run_date, ticker=sig.ticker), ("뉴스",), {"뉴스": "RuntimeError: 429"}
    ))
    sig = SignalRow(d=D, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    out = nodes.fetch_one(cast(st.VerifyState, {"run_date": D, "signal": sig}))
    assert any("뉴스" in e for e in out["errors"])
    assert any("429" in e for e in out["errors"])


def test_one_dead_ticker_does_not_kill_the_fan_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """**한 종목이 fan-out을 죽이지 않는다** — 44종목 중 하나가 터져도 나머지는 온다."""
    def boom(run_date: date, sig: SignalRow, ctx: Any = None) -> Any:
        raise RuntimeError("수집 전체 실패")

    monkeypatch.setattr(nodes, "_collect_lanes", boom)
    sig = SignalRow(d=D, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    out = nodes.fetch_one(cast(st.VerifyState, {"run_date": D, "signal": sig}))
    assert len(out["evidence"]) == 1  # 빈 증거라도 자리는 남긴다
    assert out["evidence"][0].ticker == "000430"
    assert out["evidence"][0].missing_lanes()  # 다섯 갈래가 전부 비었다
    assert any("수집 전체 실패" in e for e in out["errors"])


def test_evidence_is_a_list_so_the_reducer_can_join(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Annotated[list, operator.add]`가 합친다 — 목록이 아니면 합류가 깨진다."""
    monkeypatch.setattr(nodes, "_collect_lanes", lambda run_date, sig, ctx=None: (
        Evidence(d=run_date, ticker=sig.ticker), (), {}
    ))
    sig = SignalRow(d=D, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    out = nodes.fetch_one(cast(st.VerifyState, {"run_date": D, "signal": sig}))
    assert isinstance(out["evidence"], list)


def test_both_nodes_are_no_longer_stubs() -> None:
    assert "fetch_signals" not in nodes.STUB_NODES
    assert "fetch_one" not in nodes.STUB_NODES


@pytest.mark.parametrize("name", ["fetch_signals", "fetch_one"])
def test_nodes_stay_under_the_line_limit(name: str) -> None:
    """노드 20줄 상한 (N6)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(getattr(nodes, name)).lstrip())
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert (fn.end_lineno or 0) - (fn.lineno or 0) <= 20


# ── Send payload — 실행에서만 드러난 함정 ─────────────────────────


def test_the_send_payload_carries_the_day() -> None:
    """⚠ **`Send`의 payload가 그 노드의 상태를 통째로 대신한다** — 합쳐지지 않는다.

    `run_date`를 안 실으면 `fetch_one`이 `KeyError: 'run_date'`로 죽고 fan-out 전체가
    빈 증거로 지나간다 (2026-09-05 실행에서 잡혔다). 단위 테스트는 상태를 직접
    만들어 주므로 이 함정을 못 본다 — 그래서 payload 자체를 본다.
    """
    sig = SignalRow(d=D, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    sends = nodes.fan_out(cast(st.VerifyState, {"run_date": D, "signals": [sig]}))
    assert isinstance(sends, list)
    payload = sends[0].arg
    assert payload["run_date"] == D
    assert payload["signal"] is sig


def test_fetch_one_can_run_on_only_what_send_gives_it() -> None:
    """payload에 실린 것만으로 돌아야 한다 — 다른 상태 키를 기대하면 실행에서 죽는다."""
    sig = SignalRow(d=D, strategy="mtf", ticker="000430", name="대원강업", evidence={})
    sends = nodes.fan_out(cast(st.VerifyState, {"run_date": D, "signals": [sig]}))
    assert isinstance(sends, list)
    out = nodes.fetch_one(cast(st.VerifyState, sends[0].arg))
    assert out["evidence"][0].ticker == "000430"
