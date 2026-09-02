"""손그림(`graph.dot`)과 자동 생성본(`GRAPH.md`)의 **간선을 대조**한다.

선행에서 설계도 3장이 전부 두 판 낡은 채 남아 있었다 — `arch.dot`에는 이미 뺀 MCP 서버가,
`modules.dot`에는 새로 생긴 모듈 6개가 빠져 있었다.
**손그림은 조용히 낡고 아무도 알려 주지 않는다.** 그래서 CI가 대조한다 (SPEC N16).

```bash
python scripts/export_graph.py   # 먼저 자동 생성본을 새로 만들고
python scripts/check_diagram.py  # 대조한다
```
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOT = ROOT / "docs" / "diagrams" / "graph.dot"
MD = ROOT / "docs" / "GRAPH.md"

# 그림에만 있는 장식 노드. 간선 대조에서 뺀다.
DECORATIVE = {"START", "END"}
# 자동 생성본의 시작·끝 노드는 그림에서 START/END로 그린다.
ALIAS = {"__start__": "START", "__end__": "END"}


def dot_edges(text: str) -> set[tuple[str, str]]:
    """`a -> b [...]` 를 모은다. 주석과 `style=invis`(배치용 가짜 간선)는 뺀다."""
    out: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        line = raw.split("//")[0].strip()
        if "->" not in line or "invis" in line:
            continue
        # `a -> b -> c` 연쇄도 받는다
        names = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", line.split("[")[0])
        for a, b in zip(names, names[1:], strict=False):
            out.add((a, b))
    return out


def md_edges(text: str) -> set[tuple[str, str]]:
    """`GRAPH.md`의 간선 표에서 모은다 — 표는 export_graph.py가 만든다."""
    out: set[tuple[str, str]] = set()
    for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", text, re.M):
        a, b = ALIAS.get(m.group(1), m.group(1)), ALIAS.get(m.group(2), m.group(2))
        out.add((a, b))
    return out


def main() -> int:
    if not MD.is_file():
        print("docs/GRAPH.md가 없다 — `python scripts/export_graph.py`를 먼저 돌려라")
        return 1

    drawn = {e for e in dot_edges(DOT.read_text(encoding="utf-8")) if "cluster" not in e[0]}
    real = md_edges(MD.read_text(encoding="utf-8"))

    only_drawn = sorted(drawn - real)
    only_real = sorted(real - drawn)

    print(f"손그림 {len(drawn)}개 · 실제 {len(real)}개")
    for a, b in only_drawn:
        print(f"  ✗ 그림에만 있다 (낡았다): {a} -> {b}")
    for a, b in only_real:
        print(f"  ✗ 그림에 없다 (안 그렸다): {a} -> {b}")

    if only_drawn or only_real:
        print("\n설계도가 코드와 갈라졌다. `graph.dot`을 고치고 다시 렌더링하라:")
        print("  dot -Tpng docs/diagrams/graph.dot -o docs/graph.png")
        return 1
    print("일치 — 설계도가 코드와 같다")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
