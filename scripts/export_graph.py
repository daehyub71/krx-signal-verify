"""컴파일된 그래프 → `docs/GRAPH.md` (mermaid).

**그래프를 고쳤으면 이걸 다시 돌린다.** 안 그러면 문서가 거짓말을 한다 —
선행에서 설계도 3장이 전부 두 판 낡은 채 남아 있었다 (N16).

`scripts/check_diagram.py`가 손그림(`docs/diagrams/graph.dot`)과 이 산출물의 간선을 대조하고,
CI가 그걸 돌린다. 그래서 **낡으면 머지 전에 걸린다.**
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verify import graph  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "docs" / "GRAPH.md"

HEADER = """# GRAPH.md — 컴파일된 그래프

> **이 파일은 손으로 고치지 않는다.** `python scripts/export_graph.py`가 만든다.
> 그래프를 고쳤으면 다시 돌린다 — 안 그러면 문서가 거짓말을 한다 (SPEC N16).
> 손그림 `docs/diagrams/graph.dot`과의 대조는 `python scripts/check_diagram.py`가 한다.

## 읽는 법

- `fill_outcomes → aggregate`가 **게이트보다 앞**에 있다. 어제 판정 채점은 오늘 신호와 무관해서,
  게이트가 `stale`·`gate_timeout`으로 끝나는 날에도 돌아야 한다.
- `gate → wait → gate`는 **사이클**이다. 1분씩 10회 기다렸다 포기한다 (F1).
- `fetch_signals`에서 갈라지는 두 갈래가 fan-out이다. 신호 0건이면 `judge`로 직행한다.
- `judge`가 `explain`보다 **앞**이다. LLM이 죽어도 판정은 이미 저장돼 있다 (F20).

"""


def edges() -> list[tuple[str, str, str]]:
    """(source, target, label). 라벨 없는 간선은 빈 문자열."""
    g = graph.build_graph().get_graph()
    return sorted((e.source, e.target, str(e.data or "")) for e in g.edges)


def main() -> int:
    app = graph.build_graph()
    mermaid = app.get_graph().draw_mermaid()
    rows = "\n".join(
        f"| `{s}` | `{t}` | {lb or '—'} |" for s, t, lb in edges()
    )
    OUT.write_text(
        f"{HEADER}```mermaid\n{mermaid}```\n\n## 간선 목록 "
        f"({len(edges())}개)\n\n| from | to | 조건 |\n|---|---|---|\n{rows}\n",
        encoding="utf-8",
    )
    print(f"{OUT.relative_to(OUT.parent.parent)} — 간선 {len(edges())}개")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
