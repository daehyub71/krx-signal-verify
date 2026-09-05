"""V13 — **소급 스크립트를 만들지 않는다.** 이 파일은 *만들지 않았음*을 지키는 테스트다.

결정은 2026-09-01에 확정됐다: 표본은 **오늘부터 실시간으로만** 쌓는다.

이유는 「하기 귀찮아서」가 아니다. 재현으로 만든 신호는 상위 억제(F10)를 거치지 않아
**실제로 발송된 신호와 집합이 다르다.** 그런 표본을 실제 판정과 한 표에 섞으면
분포 비교(F24)가 서로 다른 모집단을 견주게 된다.

지키는 것:
  · `scripts/backfill_verdicts.py`가 **없다**
  · 코드가 `backfill` 출처를 **쓰지 않는다** (스키마에는 열려 있다 — F21b)
  · 그런데 **재료는 그대로 있다** — 마음이 바뀌면 다시 검토할 수 있게 어디 있는지 적어 둔다
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_there_is_no_backfill_script() -> None:
    """이름을 못 박는다 — 다른 이름으로 슬쩍 들어오는 것까지는 못 막지만, 이것이 기준선이다."""
    assert not (ROOT / "scripts" / "backfill_verdicts.py").exists()


def test_no_script_replays_past_signals() -> None:
    """스크립트 폴더 어디에도 소급 재현이 없다."""
    for path in (ROOT / "scripts").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        assert "backfill" not in src.lower(), path.name


def test_the_code_never_writes_the_backfill_source() -> None:
    """스키마는 `backfill`을 허용한다 (F21b — 나중에 스키마를 안 고치려고). **코드는 안 쓴다.**"""
    for path in (ROOT / "verify").glob("*.py"):
        assert "backfill" not in path.read_text(encoding="utf-8"), path.name


def test_aggregates_exclude_anything_that_is_not_batch() -> None:
    """소급분이 들어오더라도 집계 기본값이 `batch`라 자동으로 빠진다 (F43)."""
    import inspect

    from verify import store

    assert inspect.signature(store.fetch_verdicts).parameters["source"].default == "batch"


def test_the_decision_and_its_materials_are_written_down() -> None:
    """**마음이 바뀔 때 이 검토를 되풀이하지 않도록** SPEC에 남아 있어야 한다.

    재료는 그대로다 — `ksc_bars` 3년치와 상위 `krx-signal-alerts/scripts/dryrun.py`.
    """
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    assert "소급하지 않는다" in spec
    assert "고려사항" in spec
    assert "V13" in spec


def test_the_upstream_replay_tool_still_exists() -> None:
    """재료가 사라졌다면 「나중에 다시 꺼낸다」가 빈말이 된다 — 있는지 확인한다.

    ⚠ **옆 리포는 로컬 워크스페이스에만 있다.** CI는 이 리포 하나만 받는다 —
    2026-09-05 CI가 여기서 깨졐다(로컬은 통과). 검사할 대상이 없는 곳에서는 건너뛴다.
    건너뜀은 사유가 남는다; 대상이 있는 곳(개발 맥)에서는 그대로 검사한다.
    """
    sibling = ROOT.parent / "krx-signal-alerts"
    if not sibling.exists():
        pytest.skip("옆 리포 krx-signal-alerts 가 체크아웃되지 않았다 (CI) — 로컬에서만 검사한다")
    dryrun = sibling / "scripts" / "dryrun.py"
    assert dryrun.exists(), "상위 dryrun.py가 없다 — SPEC §2-3의 전제가 깨졌다"
