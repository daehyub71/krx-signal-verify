"""그래프 테스트용 배선 도구."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest

from verify import state as st
from verify.models import Evidence, SendResult, SignalRow


def signal(ticker: str = "042700", name: str = "한미반도체") -> SignalRow:
    return SignalRow(d=date(2026, 9, 1), strategy="vcp", ticker=ticker, name=name)


@pytest.fixture
def wiring() -> Callable[..., dict[str, Callable[..., dict[str, Any]]]]:
    """노드를 원하는 것만 갈아 끼운다. 나머지는 스텁 그대로 통과한다."""

    def make(
        **overrides: Callable[..., dict[str, Any]],
    ) -> dict[str, Callable[..., dict[str, Any]]]:
        return overrides

    return make


def gate_returns(*values: str) -> Callable[[Any], dict[str, Any]]:
    """게이트가 호출될 때마다 순서대로 값을 돌려준다. 마지막 값은 계속 반복."""
    seen = {"i": 0}

    def node(_: Any) -> dict[str, Any]:
        i = min(seen["i"], len(values) - 1)
        seen["i"] += 1
        return {"gate": values[i]}

    return node


def collects(n: int) -> Callable[[Any], dict[str, Any]]:
    def node(_: Any) -> dict[str, Any]:
        return {"signals": [signal(f"00000{i}", f"종목{i}") for i in range(n)]}

    return node


def one_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    """fan-out 한 갈래. **목록으로 돌려줘야 reducer가 합칠 수 있다.**"""
    sig = payload["signal"]
    return {"evidence": [Evidence(d=sig.d, ticker=sig.ticker)]}


def sent_ok(_: Any) -> dict[str, Any]:
    return {"send": SendResult(ok=True)}


def sent_fail(_: Any) -> dict[str, Any]:
    return {"send": SendResult(ok=False, reason="smtp timeout")}


def boom(_: Any) -> dict[str, Any]:
    raise RuntimeError("I/O가 터졌다")


BASE: dict[str, Any] = {"mode": st.MODE_BATCH, "run_date": date(2026, 9, 1)}

# ── 실DB 차단 (N14) ───────────────────────────────────────────────
#
# ⚠ **테스트가 프로덕션 DB에 쓴 적이 있다** (2026-09-05): 그래프 테스트가 신호를 만들고,
# `judge`가 실물이 되면서 진짜 `store.save_verdicts`를 불러 `ksv_verdicts`에 두 행이 남았다.
# `judge`는 저장 실패를 `errors`로 삼키므로 **조용히** 일어난다 — 아무 테스트도 안 깨졌다.
#
# 규율로는 못 막는다. 노드가 실물이 될 때마다 사람이 기억해야 하기 때문이다.
# **기본을 막아 두고, 필요한 테스트가 직접 갈아 끼운다.**


@pytest.fixture(autouse=True)
def no_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """실DB 접속과 판정 저장을 막는다. 모든 테스트에 적용된다.

    관찰이 필요한 테스트는 `monkeypatch.setattr(nodes, "_save_verdicts", ...)`로
    자기 대역을 끼운다 — 이 fixture보다 나중에 걸리므로 그쪽이 이긴다.
    """
    from verify import nodes, store

    def blocked(*args: Any, **kw: Any) -> Any:
        raise AssertionError(
            "테스트가 실DB를 부르려 한다 (N14) — 대역을 끼우거나 conn을 넘겨라"
        )

    monkeypatch.setattr(store, "connect", blocked)
    monkeypatch.setattr(nodes, "_save_verdicts", lambda *a, **k: 0)
    monkeypatch.setattr(nodes, "_fetch_signals", blocked)
