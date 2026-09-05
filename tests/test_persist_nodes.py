"""노드가 증거·서술·실행기록을 **실제로 저장하러 간다** (M7 선행).

`ksv_evidence`·`ksv_runs`가 0행이었던 이유는 노드가 저장 함수를 부르지 않았기 때문이다 —
스키마도 모델(`RunRecord`)도 있었지만 이음매가 없었다. 여기서 세 이음매를 잠근다.

지키는 것:
  · `judge`는 판정 다음에 **증거도** 저장한다. 증거 저장이 실패해도 판정·증거는 상태에 남는다
  · `explain`은 걸러진 서술을 저장한다 — 버린 것은 저장하지 않는다
  · `record_run`은 기록을 **DB에 남기고** 상태에도 둔다. 저장이 죽어도 상태는 돌아온다
  · 온디맨드 증거는 `source`가 없는 표라 그날 배치 증거를 덮는다 — 같은 원천이니 문제없다
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from verify import nodes
from verify import state as st
from verify.llm import Summary
from verify.models import Disclosure, Evidence, SendResult, SignalRow

D = date(2026, 9, 5)


def signal(ticker: str = "005930") -> SignalRow:
    return SignalRow(d=D, ticker=ticker, name="삼성전자", strategy="vcp", evidence={})


def evidence(ticker: str = "005930") -> Evidence:
    return Evidence(d=D, ticker=ticker,
                    disclosures=(Disclosure(D, "전환사채권발행결정", "20260905000001"),))


def state(**over: Any) -> st.VerifyState:
    s: dict[str, Any] = {"run_date": D, "mode": st.MODE_BATCH,
                         "signals": [signal()], "evidence": [evidence()], "errors": []}
    s.update(over)
    return s  # type: ignore[return-value]


class Recorder:
    def __init__(self, boom: Exception | None = None) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.boom = boom

    def __call__(self, *a: Any, **kw: Any) -> int:
        self.calls.append((a, kw))
        if self.boom:
            raise self.boom
        return 1


# ── judge → 증거 ─────────────────────────────────────────────────


def test_judge_saves_the_evidence_it_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    monkeypatch.setattr(nodes, "_save_evidence", rec)
    out = nodes.judge(state())
    assert out["verdicts"]
    assert len(rec.calls) == 1
    (saved,), _ = rec.calls[0]
    assert [e.ticker for e in saved] == ["005930"]


def test_judge_saves_verdicts_before_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """판정이 먼저다 — 증거 저장이 느려도 판정은 이미 있다."""
    order: list[str] = []
    monkeypatch.setattr(nodes, "_save_verdicts", lambda *a, **k: order.append("verdicts") or 1)
    monkeypatch.setattr(nodes, "_save_evidence", lambda *a, **k: order.append("evidence") or 1)
    nodes.judge(state())
    assert order == ["verdicts", "evidence"]


def test_failed_evidence_save_is_an_error_not_a_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "_save_evidence", Recorder(RuntimeError("57014")))
    out = nodes.judge(state())
    assert out["verdicts"]
    assert any("증거 저장 실패" in e for e in out["errors"])


def test_judge_with_no_verdicts_saves_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    monkeypatch.setattr(nodes, "_save_evidence", rec)
    nodes.judge(state(signals=[], evidence=[]))
    assert rec.calls == []


# ── explain → 서술 ────────────────────────────────────────────────


def judged() -> st.VerifyState:
    s = state()
    s.update(nodes.judge(s))
    return s


def test_explain_saves_the_kept_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    monkeypatch.setattr(nodes, "_save_summaries", rec)
    text = ('{"items": [{"ticker": "005930", '
            '"reason": "전환사채 100억 발행 공시가 신호와 어긋난다."}]}')
    monkeypatch.setattr(nodes, "_summarize", lambda items: Summary(text=text))
    out = nodes.explain(judged())
    assert out["summaries"] == {"005930": "전환사채 100억 발행 공시가 신호와 어긋난다."}
    (run_date, summaries, source), _ = rec.calls[0]
    assert (run_date, source) == (D, st.MODE_BATCH)
    assert summaries == out["summaries"]


def test_explain_saves_nothing_when_llm_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    monkeypatch.setattr(nodes, "_save_summaries", rec)
    monkeypatch.setattr(nodes, "_summarize", lambda items: Summary(text="", error="timeout"))
    nodes.explain(judged())
    assert rec.calls == []


def test_failed_summary_save_keeps_the_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "_save_summaries", Recorder(RuntimeError("죽음")))
    text = '{"items": [{"ticker": "005930", "reason": "전환사채 발행 공시가 신호와 어긋난다."}]}'
    monkeypatch.setattr(nodes, "_summarize", lambda items: Summary(text=text))
    out = nodes.explain(judged())
    assert out["summaries"]
    assert any("서술 저장 실패" in e for e in out["errors"])


# ── record_run → 실행 기록 ────────────────────────────────────────


def test_record_run_writes_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = Recorder()
    monkeypatch.setattr(nodes, "_save_run", rec)
    out = nodes.record_run(state(send=SendResult(ok=True), gate=st.GATE_READY))
    (run,), _ = rec.calls[0]
    assert run == out["run"]
    assert run.run_at == D


def test_record_run_survives_a_dead_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """기록 저장이 죽어도 상태의 기록은 남는다 — `finalize`가 상태를 정한다."""
    monkeypatch.setattr(nodes, "_save_run", Recorder(RuntimeError("connection refused")))
    out = nodes.record_run(state(send=SendResult(ok=True), gate=st.GATE_READY))
    assert out["run"].status
    assert any("실행 기록 저장 실패" in e for e in out["errors"])


def test_record_run_carries_the_save_error_in_the_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """저장이 죽은 사실은 **상태의 errors**에 남는다 — 다음 노드가 본다."""
    monkeypatch.setattr(nodes, "_save_run", Recorder(RuntimeError("죽음")))
    out = nodes.record_run(state(send=SendResult(ok=True), gate=st.GATE_READY))
    assert "죽음" in " ".join(out["errors"])


# ── 이음매가 실물이다 ────────────────────────────────────────────


def test_the_default_seams_are_the_real_store_functions() -> None:
    import inspect

    src = inspect.getsource(nodes)
    for line in ("_save_evidence = store.save_evidence",
                 "_save_summaries = store.save_summaries",
                 "_save_run = store.save_run"):
        assert line in src, line
