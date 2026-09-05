"""노드 — M0에서는 배선만 실물이다.

수집·판정·발송은 **빈 통과 함수**로 두고, 라우팅과 마무리만 실구현한다.
PLAN이 정한 순서다: **그래프를 먼저 세우고 노드를 나중에 채운다** —
노드를 다 만든 뒤 조립하면 reducer·조건부 엣지·합류가 한꺼번에 터진다.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from typing import Any

import pytest

from verify import nodes, state
from verify.models import SendResult, SignalRow


def st(**kw: Any) -> state.VerifyState:
    base: dict[str, Any] = {"mode": state.MODE_BATCH, "run_date": date(2026, 9, 1)}
    base.update(kw)
    return base  # type: ignore[return-value]


def sig() -> SignalRow:
    return SignalRow(d=date(2026, 9, 1), strategy="vcp", ticker="042700", name="한미반도체")


# ── route_mode — 온디맨드는 게이트를 건너뛴다 (V8) ────────────────


def test_ondemand_skips_the_gate() -> None:
    assert nodes.route_mode(st(mode=state.MODE_ONDEMAND, ticker="042700")) == nodes.TO_COLLECT


def test_batch_goes_through_the_gate() -> None:
    assert nodes.route_mode(st()) == nodes.TO_GATE


def test_unknown_mode_is_treated_as_batch() -> None:
    """모드가 깨져 오면 **더 안전한 쪽**(게이트를 거치는 쪽)으로 흐른다."""
    assert nodes.route_mode(st(mode="엉뚱함")) == nodes.TO_GATE


# ── route_gate — 이벤트가 아니라 DB를 믿는다 (F1) ─────────────────


def test_ready_proceeds() -> None:
    assert nodes.route_gate(st(gate=state.GATE_READY)) == nodes.TO_COLLECT


def test_stale_does_not_collect_but_still_reports() -> None:
    """`stale_data`면 신호 없이 「검증 없음」을 보낸다 — 침묵하지 않는다."""
    assert nodes.route_gate(st(gate=state.GATE_STALE)) == nodes.TO_REPORT


def test_missing_waits_until_the_tenth_try() -> None:
    for attempts in (0, 1, 9):
        assert nodes.route_gate(st(gate=state.GATE_MISSING, attempts=attempts)) == nodes.TO_WAIT


def test_missing_gives_up_at_the_limit() -> None:
    """10회를 채우면 `gate_timeout`. 무한히 기다리지 않는다."""
    s = st(gate=state.GATE_MISSING, attempts=state.GATE_MAX_ATTEMPTS)
    assert nodes.route_gate(s) == nodes.TO_REPORT


def test_wait_increments_attempts() -> None:
    assert nodes.wait(st(attempts=3))["attempts"] == 4


# ── 상태 판정 — finalize 한 곳에서만 정한다 ──────────────────────


def test_status_precedence_gate_timeout_wins() -> None:
    s = st(gate=state.GATE_MISSING, attempts=state.GATE_MAX_ATTEMPTS, signals=[sig()])
    assert nodes._status_of(s) == state.STATUS_GATE_TIMEOUT


def test_status_stale_data() -> None:
    assert nodes._status_of(st(gate=state.GATE_STALE)) == state.STATUS_STALE_DATA


def test_status_no_signals_when_gate_ready_but_empty() -> None:
    assert nodes._status_of(st(gate=state.GATE_READY, signals=[])) == state.STATUS_NO_SIGNALS


def test_status_failed_when_send_failed() -> None:
    s = st(gate=state.GATE_READY, signals=[sig()], send=SendResult(ok=False, reason="smtp"))
    assert nodes._status_of(s) == state.STATUS_FAILED


def test_status_ok() -> None:
    s = st(gate=state.GATE_READY, signals=[sig()], send=SendResult(ok=True))
    assert nodes._status_of(s) == state.STATUS_OK


def test_dry_run_without_send_is_not_a_failure() -> None:
    """`--dry-run`은 발송을 안 한다. 발송 결과가 없다고 실패로 적으면 안 된다."""
    s = st(gate=state.GATE_READY, signals=[sig()], dry_run=True)
    assert nodes._status_of(s) == state.STATUS_OK


# ── record_run — 실패해도 먼저 기록한다 ──────────────────────────


def test_record_run_survives_a_failed_send() -> None:
    """발송이 실패해도 기록은 남아야 한다. 여기서 raise하면 실패 기록까지 사라진다."""
    s = st(gate=state.GATE_READY, signals=[sig()], send=SendResult(ok=False, reason="smtp"))
    rec = nodes.record_run(s)["run"]
    assert rec.status == state.STATUS_FAILED
    assert rec.signals == 1


def test_record_run_keeps_outcomes_even_when_gate_failed() -> None:
    """채점은 게이트와 무관하게 돈다 — 그 결과가 기록에서 빠지면 안 된다."""
    s = st(gate=state.GATE_MISSING, attempts=state.GATE_MAX_ATTEMPTS, outcomes_filled=42)
    assert nodes.record_run(s)["run"].outcomes_filled == 42


def test_finalize_sets_status_and_is_the_only_judge() -> None:
    s = st(gate=state.GATE_STALE)
    assert nodes.finalize(s)["status"] == state.STATUS_STALE_DATA


# ── 스텁 — 이제 하나도 없다 (M5에서 마지막이 실물이 됐다) ────────


def test_there_are_no_stubs_left() -> None:
    """**M5에서 마지막 스텁(`render`·`send_email`)이 실물이 됐다** (2026-09-05).

    아래 `parametrize` 테스트는 목록이 비면서 **건너뛰기로 사라졌다** —
    상수 목록을 `parametrize`에 쓰면 비웠을 때 실패가 아니라 소멸이다.
    그래서 「비어 있음」 자체를 여기서 못 박는다.
    """
    assert nodes.STUB_NODES == ()


@pytest.mark.parametrize("name", sorted(nodes.STUB_NODES) or ["__none__"])
def test_stub_nodes_pass_through_without_raising(name: str) -> None:
    """I/O 노드는 **예외를 밖으로 내지 않는다.** 스텁 단계에서도 그 계약을 지킨다.

    목록이 비면 `__none__`으로 한 번 돌아 **건너뛰지 않는다** — 건너뛴 테스트는
    깨진 테스트보다 눈에 안 띈다.
    """
    if name == "__none__":
        assert nodes.STUB_NODES == ()
        return
    fn = getattr(nodes, name)
    assert isinstance(fn(st()), dict)


def test_implemented_nodes_are_not_listed_as_stubs() -> None:
    """실물이 된 노드가 목록에 남으면 **스텁 테스트가 그 노드의 I/O를 부른다.**

    로컬엔 `.env`가 있어 통과하고 CI에서만 터진다 — 2026-09-02에 `gate`가 그랬다.
    """
    src = inspect.getsource(nodes)
    for name in nodes.STUB_NODES:
        body = src.split(f"def {name}(")[1].split("\n\n\ndef ")[0]
        assert body.rstrip().endswith("return {}"), f"{name}은 이미 실물이다 — STUB_NODES에서 빼라"


def test_fan_out_returns_one_send_per_signal() -> None:
    s = st(signals=[sig(), sig()])
    assert len(nodes.fan_out(s)) == 2


def test_fan_out_on_empty_signals_goes_straight_through() -> None:
    """빈 목록을 돌려주면 그래프가 갈 곳을 잃는다 — 다음 노드 이름을 준다."""
    assert nodes.fan_out(st(signals=[])) == "judge"


# ── 구조 ─────────────────────────────────────────────────────────


def test_every_node_is_at_most_twenty_lines() -> None:
    """노드가 20줄을 넘으면 도메인 로직이 샌 것이다 (N6). 세는 것은 실행되는 줄뿐."""
    tree = ast.parse(inspect.getsource(nodes))
    too_long: list[str] = []
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        body = [
            b
            for b in fn.body
            if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))
        ]
        if not body:
            continue
        span = max(b.end_lineno or b.lineno for b in body) - body[0].lineno + 1
        if span > 20:
            too_long.append(f"{fn.name} ({span}줄)")
    assert not too_long, f"20줄을 넘는 노드: {too_long}"


def test_nodes_module_does_not_touch_io() -> None:
    """M0의 노드는 배선만 안다. I/O는 뒤 마일스톤에서 `store`·`notify`를 거쳐 들어온다."""
    src = inspect.getsource(nodes)
    for banned in ("supabase", "psycopg", "smtplib", "anthropic", "httpx"):
        assert banned not in src, f"nodes.py가 {banned}를 직접 안다"
