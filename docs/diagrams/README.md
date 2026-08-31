# 다이어그램 원본

PNG는 Graphviz로 만든다. 고치면 **반드시 다시 렌더링한다** (`brew install graphviz`).

```bash
cd docs/diagrams
for d in arch graph modules outcome web; do
  dot -Tpng -Gdpi=160 $d.dot -o ../$d.png
done
```

`graph.dot`은 **설계도**다. 구현 후의 실제 그래프는 `scripts/export_graph.py`가 `docs/GRAPH.md`(mermaid)로 뽑는다.
둘이 다르면 코드가 설계에서 벗어난 것이다 — 선행 프로젝트에서 설계도 3장이 전부 두 판 낡은 채로 남아 있었다(2026-08-31).
`scripts/check_diagram.py`가 `graph.dot`과 `GRAPH.md`의 간선을 대조한다.
