"""judge 노드 — 판정과 **저장**을 한 단계로. `explain`(LLM)은 뒤에 붙는 선택 층이다 (M3).

선행은 한 노드가 판정 계산과 LLM 호출을 겸했다. 그래서 **LLM이 죽으면 판정도 같이 사라졌다** —
렌더 때 계산하고 버렸으니 이력 자체가 없었다 (F20, 2026-08-31 확인).

여기서 지키는 것:
  · **판정은 저장까지 끝낸 뒤에 `explain`으로 간다** — 순서가 보장의 전부다
  · **LLM이 죽어도 판정은 이미 DB에 있다** — 이것을 테스트가 증명한다
  · 판정은 **코드가** 낸다. LLM은 서술만 하고 `stand`·`score`를 바꾸지 못한다 (F10)
  · 저장이 실패해도 **판정은 상태에 남는다** — 메일은 나가야 한다 (F34)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from verify import graph, nodes
from verify import state as st
from verify.models import Disclosure, Evidence, SignalRow, VerdictInput

D = date(2026, 9, 5)


def signal(ticker: str = "005930", name: str = "삼성전자") -> SignalRow:
    return SignalRow(d=D, ticker=ticker, name=name, strategy="vcp", evidence={})


def evidence(ticker: str = "005930", **over: Any) -> Evidence:
    base: dict[str, Any] = {
        "disclosures": (Disclosure(D, "전환사채권발행결정", "20260905000001"),),
        "news": (), "flows": None, "financial": None, "shorting": None,
    }
    base.update(over)
    return Evidence(d=D, ticker=ticker, **base)


def base_state(**over: Any) -> st.VerifyState:
    s: dict[str, Any] = {
        "run_date": D,
        "mode": st.MODE_BATCH,
        "signals": [signal()],
        "evidence": [evidence()],
        "errors": [],
    }
    s.update(over)
    return s  # type: ignore[return-value]


class Recorder:
    """저장 대역. **무엇이 언제 저장됐는지** 적어 둔다."""

    def __init__(self, boom: Exception | None = None) -> None:
        self.saved: list[Any] = []
        self.boom = boom

    def __call__(self, run_date: date, verdicts: Any, source: str) -> int:
        if self.boom:
            raise self.boom
        self.saved.append((run_date, dict(verdicts), source))
        return len(verdicts)


@pytest.fixture
def saver(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(nodes, "_save_verdicts", rec)
    return rec


# ── 판정은 코드가 낸다 ────────────────────────────────────────────


def test_judge_produces_a_verdict_per_signal(saver: Recorder) -> None:
    out = nodes.judge(base_state())
    assert set(out["verdicts"]) == {"005930"}
    v = out["verdicts"]["005930"]
    assert v.stand in ("정합", "불일치", "무관")
    assert 0 <= v.score <= 100


def test_a_signal_without_evidence_still_gets_a_verdict(saver: Recorder) -> None:
    """증거가 하나도 없어도 판정은 나간다 (F34)."""
    out = nodes.judge(base_state(evidence=[]))
    assert set(out["verdicts"]) == {"005930"}
    assert out["verdicts"]["005930"].blind_spots


def test_no_signals_means_no_verdicts_and_no_save(saver: Recorder) -> None:
    out = nodes.judge(base_state(signals=[], evidence=[]))
    assert out["verdicts"] == {}
    assert saver.saved == []


def test_the_verdict_carries_its_limit_note(saver: Recorder) -> None:
    """점수와 **항상 함께** 나가는 한 줄 (N1)."""
    v = nodes.judge(base_state())["verdicts"]["005930"]
    assert "앞으로의 주가를 말하지 않는다" in v.limit_note


# ── ★ 저장이 explain보다 먼저다 ───────────────────────────────────


def test_judge_saves_before_it_returns(saver: Recorder) -> None:
    out = nodes.judge(base_state())
    assert len(saver.saved) == 1
    run_date, saved, source = saver.saved[0]
    assert run_date == D
    assert set(saved) == set(out["verdicts"])


def test_the_verdict_is_already_stored_when_explain_dies() -> None:
    """**이 파일의 요점.** LLM이 죽어도 판정은 이미 DB에 있다.

    그래프를 통째로 돌리면서 `explain`에 예외를 심는다 — 선행이 잃은 것이 정확히 이것이다.
    """
    saved: list[Any] = []

    def save(run_date: date, verdicts: Any, source: str) -> int:
        saved.append(dict(verdicts))
        return len(verdicts)

    def explode(s: st.VerifyState) -> dict[str, Any]:
        raise RuntimeError("anthropic 500")

    app = graph.build_graph(overrides={
        "gate": lambda s: {"gate": st.GATE_READY},  # 실DB를 부르지 않는다
        "judge": _judge_with(save),
        "explain": explode,
    })
    out = app.invoke(base_state(), {"recursion_limit": st.RECURSION_LIMIT})

    assert saved and set(saved[0]) == {"005930"}  # 저장은 이미 끝났다
    assert any("anthropic 500" in e for e in out["errors"])  # 실패가 삼켜지지 않았다
    # **LLM 실패는 실행을 실패로 만들지 않는다** — 있으면 좋은 층이다 (M5).
    # 다만 조용하지도 않다: 실행 기록에 남아 다음 날 볼 수 있다.
    assert out["status"] == st.STATUS_OK
    assert any("anthropic 500" in e for e in out["run"].detail["errors"])
    assert out["run"].verdicts == 1  # 판정은 세어져 남았다


def _judge_with(save: Any) -> Any:
    """저장 대역을 끼운 judge 노드."""

    def node(s: st.VerifyState) -> dict[str, Any]:
        import verify.nodes as n

        real, n._save_verdicts = n._save_verdicts, save
        try:
            return n.judge(s)
        finally:
            n._save_verdicts = real

    return node


def test_judge_comes_before_explain_in_the_graph() -> None:
    """순서가 보장의 전부다 — 뒤바뀌면 위 테스트가 의미를 잃는다."""
    from pathlib import Path

    dot = (Path(__file__).parent.parent / "docs" / "diagrams" / "graph.dot").read_text(
        encoding="utf-8"
    )
    assert "judge -> explain" in dot.replace('"', "")


def test_explain_never_changes_the_verdict(saver: Recorder) -> None:
    """LLM은 서술만 한다 — `stand`·`score`를 바꾸지 못한다 (F10)."""
    before = nodes.judge(base_state())["verdicts"]["005930"]
    after = nodes.explain({**base_state(), "verdicts": {"005930": before}})
    assert "verdicts" not in after  # explain은 판정 키를 돌려주지 않는다


# ── 저장이 실패해도 판정은 남는다 ─────────────────────────────────


def test_a_failed_save_does_not_lose_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """저장이 죽어도 **메일은 나가야 한다** — 판정을 상태에서 지우지 않는다 (F34)."""
    monkeypatch.setattr(nodes, "_save_verdicts", Recorder(RuntimeError("57014 statement timeout")))
    out = nodes.judge(base_state())
    assert set(out["verdicts"]) == {"005930"}
    assert any("57014" in e for e in out["errors"])


def test_a_failed_save_is_never_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """선행에서 44행이 한 문장으로 나갔다가 하루치가 통째로 사라졌다 — 조용하면 모른다."""
    monkeypatch.setattr(nodes, "_save_verdicts", Recorder(RuntimeError("죽음")))
    assert nodes.judge(base_state())["errors"]


# ── 저장 인자 ─────────────────────────────────────────────────────


def test_batch_and_ondemand_are_saved_apart(saver: Recorder) -> None:
    """온디맨드는 표본이 편향돼 있어 집계에서 뺀다 (F43) — 출처를 처음부터 적는다."""
    nodes.judge(base_state())
    assert saver.saved[0][2] == st.MODE_BATCH
    saver.saved.clear()
    nodes.judge(base_state(mode=st.MODE_ONDEMAND, ticker="005930"))
    assert saver.saved[0][2] == st.MODE_ONDEMAND


def test_judge_is_pure_apart_from_the_save(saver: Recorder) -> None:
    """산식은 도메인에 있다 — 노드는 모아서 넘기고 받아 적기만 한다 (N4)."""
    import inspect

    src = inspect.getsource(nodes.judge)
    for word in ("W_", "score +", "score -", "stand ="):
        assert word not in src, word


def test_judge_node_stays_under_the_line_limit() -> None:
    """노드 20줄 상한 (N6)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(nodes.judge).lstrip())
    fn = tree.body[0]
    assert isinstance(fn, ast.FunctionDef)
    assert (fn.end_lineno or 0) - (fn.lineno or 0) <= 20


def test_judge_is_no_longer_a_stub() -> None:
    assert "judge" not in nodes.STUB_NODES
    assert "explain" in nodes.STUB_NODES  # M5에서 실물이 된다


# ── 입력 조립은 도메인이 읽을 수 있는 꼴로 ────────────────────────


def test_verdict_input_is_built_from_evidence(saver: Recorder) -> None:
    ev = evidence(disclosures=(Disclosure(D, "유상증자결정", "20260905000002"),))
    out = nodes.judge(base_state(evidence=[ev]))
    v = out["verdicts"]["005930"]
    assert v.parts  # 공시를 봤다는 흔적이 있다


def test_evidence_for_another_ticker_is_not_mixed_in(saver: Recorder) -> None:
    """fan-out이 합류한 뒤라 여러 종목의 증거가 한 목록에 있다 — 섞이면 남의 공시로 판정한다."""
    out = nodes.judge(base_state(
        signals=[signal("005930"), signal("000660", "SK하이닉스")],
        evidence=[evidence("005930"), evidence("000660", disclosures=())],
    ))
    assert set(out["verdicts"]) == {"005930", "000660"}
    assert out["verdicts"]["005930"] != out["verdicts"]["000660"]


def test_news_reaches_the_formula(saver: Recorder) -> None:
    """위험 공시를 **설명하는 뉴스**가 있으면 점수가 달라진다 — 안 넘기면 그 지렛대가 죽는다."""
    cb = Disclosure(D, "전환사채권발행결정", "20260905000001")
    without = nodes.judge(base_state(evidence=[evidence(disclosures=(cb,), news=())]))
    withnews = nodes.judge(base_state(
        evidence=[evidence(disclosures=(cb,), news=("씨피시스템, CB 100억 제2공장 투입",))]
    ))
    assert without["verdicts"]["005930"].score != withnews["verdicts"]["005930"].score


def test_financial_and_shorting_reach_the_blind_spots(saver: Recorder) -> None:
    """점수에는 안 들어가지만 **사각지대 목록**을 줄인다 — 안 넘기면 늘 「안 봤다」로 나간다."""
    bare = nodes.judge(base_state())["verdicts"]["005930"]
    assert "재무" in bare.blind_spots and "공매도" in bare.blind_spots

    filled = nodes.judge(base_state(
        evidence=[evidence(financial=object(), shorting=object())]
    ))["verdicts"]["005930"]
    assert "재무" not in filled.blind_spots
    assert "공매도" not in filled.blind_spots


def test_the_default_save_is_the_real_one() -> None:
    """이음매가 기본값으로 아무것도 안 하면 **판정이 조용히 안 남는다.**

    테스트는 늘 갈아 끼우므로 기본값이 무엇인지는 여기서만 확인된다.
    """
    from verify import store

    assert nodes._save_verdicts is store.save_verdicts


def test_the_real_save_is_loud_until_it_exists() -> None:
    """아직 안 만든 저장이 0을 돌려주면, 판정이 안 남는 것을 아무도 모른다."""
    from verify import store

    with pytest.raises(NotImplementedError):
        store.save_verdicts(D, {}, st.MODE_BATCH)


def test_build_input_is_a_pure_function() -> None:
    """상태를 모른다 — 나중에 온디맨드·재판정이 같은 함수를 쓴다."""
    import inspect

    assert list(inspect.signature(nodes.verdict_input_for).parameters) == ["signal", "evidence"]
    got = nodes.verdict_input_for(signal(), evidence())
    assert isinstance(got, VerdictInput)
    assert got.disclosures
