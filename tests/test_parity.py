"""선행 대조 — **이식이 같은 판정을 내는가** (V11).

M1이 M2보다 먼저인 이유가 이 파일이다. 이식한 도메인이 선행과 **같은 판정**을 내는 것을
먼저 확인해야, 뒤에 판정이 달라졌을 때 원인이 **신규 갈래인지 이식 실수인지** 가려진다.

CI에는 선행 리포가 없으므로 선행의 답을 **골든 파일로 굳혀** 두고 대조한다
(`scripts/capture_parity.py`가 만든다 · 실표본 352종).
**이 파일이 실패하면 이식이 갈라졌다는 뜻이다** — 우리가 고친 것이 의도한 것인지 먼저 본다.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from verify.flags import classify, is_reit, match, normalize
from verify.models import Disclosure
from verify.routine import is_routine

GOLDEN = Path(__file__).parent / "fixtures" / "parity_briefing.json"


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(GOLDEN.read_text(encoding="utf-8"))
    return data


def test_the_golden_file_covers_the_real_sample(golden: dict[str, Any]) -> None:
    """표본이 얇으면 대조가 의미 없다."""
    assert len(golden["rows"]) > 300


def test_match_is_identical(golden: dict[str, Any]) -> None:
    """규칙표 판정 — `(rule, level, subsidiary)`까지 같아야 한다."""
    diff = []
    for row in golden["rows"]:
        m = match(row["title"])
        got = None if m is None else [m.rule, m.level, m.subsidiary]
        if got != row["match"]:
            diff.append((row["title"], got, row["match"]))
    assert not diff, f"규칙표 판정이 갈라졌다 ({len(diff)}건): {diff[:3]}"


def test_match_with_a_reit_name_is_identical(golden: dict[str, Any]) -> None:
    """**리츠 예외는 종목명이 있어야 발동한다** — 이름 없이 부르면 그 갈래가 대조에서 빠진다.

    2026-09-02 변이 검사에서 드러났다: 리츠 예외를 통째로 지워도 대조가 통과했다.
    """
    diff = []
    for row in golden["rows"]:
        m = match(row["title"], "신한알파리츠")
        got = None if m is None else [m.rule, m.level, m.subsidiary]
        if got != row["match_reit"]:
            diff.append((row["title"], got, row["match_reit"]))
    assert not diff, f"리츠 예외가 갈라졌다 ({len(diff)}건): {diff[:3]}"


def test_normalize_is_identical(golden: dict[str, Any]) -> None:
    """정규화 — 이름·정정여부·note 셋 다."""
    diff = []
    for row in golden["rows"]:
        n = normalize(row["title"])
        got = [n.name, n.corrected, n.note]
        if got != row["norm"]:
            diff.append((row["title"], got, row["norm"]))
    assert not diff, f"정규화가 갈라졌다 ({len(diff)}건): {diff[:3]}"


def test_routine_is_identical(golden: dict[str, Any]) -> None:
    """정형 공시 판별."""
    diff = [
        (row["title"], is_routine(row["title"]), row["routine"])
        for row in golden["rows"]
        if is_routine(row["title"]) != row["routine"]
    ]
    assert not diff, f"정형 판별이 갈라졌다 ({len(diff)}건): {diff[:3]}"


def test_classify_is_identical(golden: dict[str, Any]) -> None:
    """종목 등급과 플래그 목록 — 판정이 어디서 왔는지까지."""
    diff = []
    for row in golden["rows"]:
        d = Disclosure(rcept_dt=date(2026, 9, 1), report_nm=row["title"], rcept_no="x1")
        v = classify([d])
        got = [v.level, [[f.rule, f.level] for f in v.flags]]
        want = [row["level"], row["flags"]]
        if got != want:
            diff.append((row["title"], got, want))
    assert not diff, f"등급 판정이 갈라졌다 ({len(diff)}건): {diff[:3]}"


def test_reit_exception_is_identical(golden: dict[str, Any]) -> None:
    for name, want in golden["reit"]:
        assert is_reit(name) == want, name
