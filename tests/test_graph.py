"""그래프 배선 — **연결·분기·합류만** 본다. 도메인 판정은 도메인 테스트가 본다.

여기서 지키는 것 둘:
- **fan-out 합류** — reducer가 없으면 마지막 하나만 남고 예외도 안 난다 (선행 두 곳에서 실증)
- **`record_run`까지 반드시 온다** — I/O 노드가 raise하면 그날 실패 기록까지 사라진다
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.conftest import BASE, boom, collects, gate_returns, one_evidence, sent_fail, sent_ok
from verify import graph
from verify import state as st


def run(overrides: dict[str, Any], **init: Any) -> dict[str, Any]:
    app = graph.build_graph(overrides)
    return dict(app.invoke({**BASE, **init}, {"recursion_limit": st.RECURSION_LIMIT}))


# ── 게이트 세 경로 (F1) ──────────────────────────────────────────


def test_ready_collects_and_finishes_ok() -> None:
    out = run({"gate": gate_returns(st.GATE_READY), "fetch_signals": collects(2),
               "fetch_one": one_evidence, "send_email": sent_ok})
    assert out["status"] == st.STATUS_OK


def test_stale_reports_without_collecting() -> None:
    """`stale_data`면 신호 없이 「검증 없음」을 보낸다 — 침묵하지 않는다."""
    out = run({"gate": gate_returns(st.GATE_STALE), "send_email": sent_ok})
    assert out["status"] == st.STATUS_STALE_DATA
    assert not out.get("signals")


def test_missing_retries_then_times_out_and_still_records() -> None:
    """1분×10회 뒤 포기. **그래도 `record_run`까지 온다.**"""
    out = run({"gate": gate_returns(st.GATE_MISSING), "send_email": sent_ok})
    assert out["status"] == st.STATUS_GATE_TIMEOUT
    assert out["attempts"] == st.GATE_MAX_ATTEMPTS
    assert out["run"].status == st.STATUS_GATE_TIMEOUT


def test_missing_then_ready_recovers() -> None:
    """상위가 늦게 쓴 날. 기다렸다가 정상으로 흐른다."""
    out = run({"gate": gate_returns(st.GATE_MISSING, st.GATE_MISSING, st.GATE_READY),
               "fetch_signals": collects(1), "fetch_one": one_evidence, "send_email": sent_ok})
    assert out["status"] == st.STATUS_OK
    assert out["attempts"] == 2


# ── fan-out 합류 — 이 파일의 존재 이유 ───────────────────────────


def test_fan_out_joins_every_branch() -> None:
    """Send 3개 → evidence 3개. **reducer가 없으면 1개만 남는다.** 지우지 말 것."""
    out = run({"gate": gate_returns(st.GATE_READY), "fetch_signals": collects(3),
               "fetch_one": one_evidence, "send_email": sent_ok})
    assert len(out["evidence"]) == 3
    assert {e.ticker for e in out["evidence"]} == {"000000", "000001", "000002"}


def test_zero_signals_goes_straight_through() -> None:
    """신호 0건인 날에도 끝까지 흐르고 「없음」을 보낸다 — 침묵이 정상이 아니다."""
    out = run({"gate": gate_returns(st.GATE_READY), "fetch_signals": collects(0),
               "send_email": sent_ok})
    assert out["status"] == st.STATUS_NO_SIGNALS
    assert out.get("evidence", []) == []


# ── 채점은 게이트와 무관하게 돈다 ────────────────────────────────


def test_outcomes_are_filled_even_when_the_gate_times_out() -> None:
    """어제 판정 채점은 오늘 신호와 무관하다. 게이트가 죽은 날에도 돌아야 한다."""
    out = run({"fill_outcomes": lambda _: {"outcomes_filled": 42},
               "gate": gate_returns(st.GATE_MISSING), "send_email": sent_ok})
    assert out["status"] == st.STATUS_GATE_TIMEOUT
    assert out["run"].outcomes_filled == 42


# ── 실패해도 기록은 남는다 ───────────────────────────────────────


def test_failed_send_is_recorded_not_raised() -> None:
    out = run({"gate": gate_returns(st.GATE_READY), "fetch_signals": collects(1),
               "fetch_one": one_evidence, "send_email": sent_fail})
    assert out["status"] == st.STATUS_FAILED
    assert out["run"].status == st.STATUS_FAILED


@pytest.mark.parametrize("node", ["fetch_one", "explain", "render"])
def test_io_node_that_raises_must_not_lose_the_record(node: str) -> None:
    """**여기서 예외가 새면 `record_run`에 못 가 실패 기록이 통째로 사라진다.**"""
    over: dict[str, Any] = {"gate": gate_returns(st.GATE_READY), "fetch_signals": collects(1),
                            "fetch_one": one_evidence, "send_email": sent_ok}
    over[node] = boom
    out = run(over)
    assert "run" in out, f"{node}가 raise하자 실행 기록이 사라졌다"


# ── 온디맨드 (V8) ────────────────────────────────────────────────


def test_batch_goes_through_the_gate() -> None:
    """온디맨드의 짝. **배치는 반드시 게이트를 거친다** — 안 거치면 낡은 데이터로 판정한다."""
    called: list[str] = []

    def tracking_gate(_: Any) -> dict[str, Any]:
        called.append("gate")
        return {"gate": st.GATE_READY}

    out = run({"gate": tracking_gate, "fetch_signals": collects(1),
               "fetch_one": one_evidence, "send_email": sent_ok}, mode=st.MODE_BATCH)
    assert called == ["gate"]
    assert out["status"] == st.STATUS_OK


def test_ondemand_skips_the_gate_entirely() -> None:
    called: list[str] = []
    out = run({"gate": lambda _: called.append("gate") or {},  # type: ignore[func-returns-value]
               "fetch_signals": collects(1), "fetch_one": one_evidence, "send_email": sent_ok},
              mode=st.MODE_ONDEMAND, ticker="042700")
    assert called == []
    assert out["status"] == st.STATUS_OK


# ── 구조 ─────────────────────────────────────────────────────────


def test_graph_compiles_without_overrides() -> None:
    assert graph.build_graph() is not None
