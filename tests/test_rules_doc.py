"""F26 — 점수 산식 이력 문서 `docs/RULES.md`.

**문서와 코드가 갈라지면 문서는 거짓말이 된다.** 그래서 대조를 테스트로 둔다:
현재 판 번호가 문서에 있고, 코드의 가중치 이름이 표에 다 적혀 있어야 한다.
"""

from __future__ import annotations

import pathlib
import re

from verify import verdict

DOC = (pathlib.Path(__file__).resolve().parent.parent / "docs" / "RULES.md").read_text(
    encoding="utf-8"
)


def test_the_document_exists_and_names_the_current_version() -> None:
    assert f"v{verdict.RULES_VERSION}" in DOC or f"`{verdict.RULES_VERSION}`" in DOC


def test_every_weight_in_the_code_is_in_the_table() -> None:
    """**가중치를 더하고 문서를 안 고치면 여기가 깨진다** — 그게 이 테스트의 전부다."""
    names = {
        n for n in dir(verdict)
        if n.startswith("W_") or n == "NEUTRAL"
    }
    missing = {n for n in names if f"`{n}`" not in DOC}
    assert not missing, missing


def test_the_procedure_for_changing_weights_is_written() -> None:
    """V5 — 사람이 SPEC을 고쳐서만 바꾼다. 절차가 없으면 다음 사람이 코드만 고친다.

    **순서까지 본다** — 「어딘가에 그 말이 있다」로는 절차가 지워져도 통과한다
    (변이 검사로 드러남, 2026-09-05). SPEC이 코드보다 먼저여야 한다.
    """
    block = DOC.split("가중치를 바꾸는 절차", 1)[1].split("---", 1)[0]
    first: dict[str, str] = {}
    for ln in block.splitlines():
        mark = ln.strip()[:1]
        if mark in "①②③④⑤":
            first.setdefault(mark, ln)
    steps = [first[m] for m in "①②③④⑤" if m in first]
    assert len(steps) == 5, first
    assert "SPEC" in steps[0], steps[0]  # SPEC이 먼저다 (V5)
    assert "verdict.py" in steps[1]
    assert "RULES_VERSION" in steps[2]
    assert "테스트" in steps[4]


def test_it_says_what_is_not_scored() -> None:
    """재무·공매도가 점수에 없다는 사실이 **한 문장 안에** 있어야 한다.

    말이 흩어져 있으면 다음 사람이 그 사실을 못 읽고 가중치를 더한다.
    """
    said = [
        ln for ln in DOC.splitlines()
        if "재무" in ln and "공매도" in ln and "점수" in ln
    ]
    assert said, "재무·공매도가 점수에 안 들어간다는 문장이 없다"
    assert any("않는다" in ln for ln in said), said


def test_the_history_table_has_a_row_per_version() -> None:
    rows = re.findall(r"^\|\s*`(\d+\.\d+)`\s*\|", DOC, re.M)
    assert verdict.RULES_VERSION in rows, rows


def test_it_does_not_promise_prediction(  ) -> None:
    """이 문서도 우리 문장이다 — N1·N2가 그대로 적용된다."""
    from verify import wording

    for line in DOC.splitlines():
        if line.strip().startswith(("|", ">")) or "`" in line:
            continue
        assert not wording.has_forbidden_outcome(line), line
