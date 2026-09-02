"""그래프 조립 — 그래프 층. **여기가 배선의 전부다.**

## 선행 그래프에서 달라진 셋 (PLAN §1-2)

1. **`route_mode` 진입 분기** — 온디맨드는 게이트도 메일도 필요 없고 종목이 하나다 (V8).
2. **`fill_outcomes` → `aggregate`가 게이트보다 먼저** — 어제 판정 채점은 오늘 신호와
   무관하다. 게이트가 `stale`·`timeout`으로 끝나는 날에도 **채점은 돌아야 한다.**
3. **`summarize`가 `judge` + `explain` 둘로 갈라졌다** — 판정은 저장까지 하는 별도
   단계이고(F20) LLM은 뒤에 붙는 선택 층이다. **LLM이 죽어도 판정은 이미 저장돼 있다.**

## 예외를 밖으로 내지 않는 것을 여기서 강제한다

「I/O 노드는 예외를 밖으로 내지 않는다」는 규칙이었지, 장치가 아니었다.
`_guard`가 모든 노드를 감싸 예외를 `state.errors`로 떨어뜨린다 —
**그래야 `record_run`까지 도달해 그날 실패 기록이 남는다.** 삼키지는 않는다: 기록에 남는다.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from verify import nodes
from verify import state as st

NodeFn = Callable[..., dict[str, Any]]

# 그래프에 얹는 노드 이름 순서 (배선 순서와 같게 둔다 — 읽는 사람이 흐름을 따라간다)
NODE_NAMES = (
    "fill_outcomes",
    "aggregate",
    "gate",
    "wait",
    "fetch_signals",
    "fetch_one",
    "judge",
    "explain",
    "render",
    "send_email",
    "record_run",
    "finalize",
)


def _guard(name: str, fn: NodeFn) -> NodeFn:
    """노드가 예외를 밖으로 내지 못하게 막는다.

    여기서 예외가 새면 `record_run`에 도달하지 못해 **그날 실패 기록 자체가 사라진다.**
    조용히 삼키지는 않는다 — `state.errors`에 남고 `record_run`이 기록으로 옮긴다.
    """

    def wrapped(payload: Any) -> dict[str, Any]:
        try:
            return fn(payload)
        except Exception as exc:  # noqa: BLE001 — 여기서 막지 않으면 기록이 사라진다
            return {"errors": [f"{name}: {type(exc).__name__}: {exc}"]}

    return wrapped


def build_graph(overrides: Mapping[str, NodeFn] | None = None) -> Any:
    """그래프를 조립해 컴파일한다.

    Args:
        overrides: 노드 이름 → 대체 함수. 테스트가 원하는 것만 갈아 끼운다.

    Returns:
        컴파일된 그래프. `invoke`에 `recursion_limit`을 함께 준다 —
        `gate → wait → gate` 사이클이 최대 10회 돈다.
    """
    over = dict(overrides or {})
    g = StateGraph(st.VerifyState)

    for name in NODE_NAMES:
        fn: NodeFn = over.get(name, getattr(nodes, name))
        g.add_node(name, _guard(name, fn))

    # 채점 먼저 — 게이트와 무관하게 돈다
    g.add_edge(START, "fill_outcomes")
    g.add_edge("fill_outcomes", "aggregate")

    # 배치는 게이트를 거치고, 온디맨드는 건너뛴다
    g.add_conditional_edges(
        "aggregate",
        nodes.route_mode,
        {nodes.TO_GATE: "gate", nodes.TO_COLLECT: "fetch_signals"},
    )

    # 게이트: 준비됐으면 수집, 없으면 기다렸다 다시, 상하면 신호 없이 보고
    g.add_conditional_edges(
        "gate",
        nodes.route_gate,
        {nodes.TO_COLLECT: "fetch_signals", nodes.TO_WAIT: "wait", nodes.TO_REPORT: "render"},
    )
    g.add_edge("wait", "gate")

    # fan-out — 합류는 state.evidence의 reducer가 한다. 0건이면 judge로 직행
    g.add_conditional_edges("fetch_signals", nodes.fan_out, ["fetch_one", "judge"])
    g.add_edge("fetch_one", "judge")

    # 판정이 먼저 저장되고, LLM은 그 뒤에 붙는 선택 층이다
    g.add_edge("judge", "explain")
    g.add_edge("explain", "render")
    g.add_edge("render", "send_email")
    g.add_edge("send_email", "record_run")
    g.add_edge("record_run", "finalize")
    g.add_edge("finalize", END)

    return g.compile()
