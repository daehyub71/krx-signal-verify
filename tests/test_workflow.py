"""verify.yml — 자동화 (M6). 워크플로 파일은 실행 없이 **모양**을 잠근다.

지키는 것:
  · 트리거 넷 — dispatch(`alert-completed`) · 온디맨드(`verify-ticker`) · 예비 cron · 수동
  · **입력을 셸에 직접 보간하지 않는다** — `${{ inputs.x }}`가 `run:` 안에 있으면 명령 주입 경로다
  · **`python -u`** — 버퍼링되면 시간 초과로 잘린 실행의 로그가 통째로 빈다 (상위 2026-08-31)
  · 예비 cron은 `--if-not-verified` — dispatch로 이미 돌았으면 메일을 두 번 보내지 않는다
  · 워크플로가 읽는 Secrets는 전부 `.env.example`에 있는 이름이다 — 오타는 빈 값으로 조용히 흐른다
  · **게이트는 이벤트가 아니라 DB를 믿는다** — `--if-not-verified`의 실물 판정도 DB를 본다
"""

from __future__ import annotations

import pathlib
import re
from datetime import date
from typing import Any

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
YML = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def run_block() -> str:
    """`검증` 단계의 `run: |` 본문만."""
    return YML.split("run: |", 1)[1]


# ── 트리거 넷 ─────────────────────────────────────────────────────


def test_it_wakes_on_the_upstream_dispatch() -> None:
    assert "repository_dispatch:" in YML
    assert "alert-completed" in YML


def event_types() -> list[str]:
    """`repository_dispatch:` 아래 `types:` 목록만. **주석에 있는 이름은 세지 않는다.**"""
    block = YML.split("repository_dispatch:", 1)[1].split("schedule:", 1)[0]
    m = re.search(r"types:\s*\[([^\]]*)\]", block)
    assert m, "types: 가 없다"
    return [t.strip() for t in m.group(1).split(",")]


def test_it_wakes_on_the_upstream_dispatch_type() -> None:
    assert "alert-completed" in event_types()


def test_it_accepts_an_ondemand_ticker_event() -> None:
    """웹의 `/api/verify`가 이 이벤트를 보낸다 (F41). 티커는 `client_payload`에 실린다.

    **`types:` 줄을 본다** — 이름이 주석에도 있어 문자열 검사로는 빠져도 통과했다
    (변이 검사로 드러남, 2026-09-05).
    """
    assert "verify-ticker" in event_types()
    assert "github.event.client_payload.ticker" in YML


def test_the_backup_cron_runs_after_the_upstream() -> None:
    """상위는 08:20 KST(23:20 UTC). 09:05 KST(00:05 UTC)면 45분 여유다. 평일만."""
    assert re.search(r'cron:\s*"5 0 \* \* 0-4"', YML)


def test_manual_runs_are_possible_with_a_date() -> None:
    assert "workflow_dispatch:" in YML
    assert "inputs.date" in YML


# ── 명령 주입을 막는다 ────────────────────────────────────────────


def test_no_input_is_interpolated_into_the_shell() -> None:
    """**`${{ … }}`가 `run:` 안에 있으면 임의 명령 주입 경로다.** 전부 `env:`로 받는다."""
    assert "${{" not in run_block()


def test_every_input_goes_through_env() -> None:
    for name in ("RUN_DATE", "TICKER", "DRY_RUN", "FORCE", "IF_NOT_VERIFIED"):
        assert f"{name}:" in YML, name
        assert f'"${name}"' in run_block() or f"${name}" in run_block(), name


def test_the_ticker_is_revalidated_by_argparse() -> None:
    """워크플로가 받아 넘긴 티커를 **코드가 다시 검사한다** — `^[0-9A-Z]{6}$`."""
    from verify import main

    with pytest.raises(Exception, match="6자리"):
        main._as_ticker("005930; rm -rf /")


# ── 잘린 로그를 막는다 ────────────────────────────────────────────


def test_python_runs_unbuffered() -> None:
    """버퍼링되면 시간 초과로 잘린 실행의 로그가 **통째로 빈다** (상위 2026-08-31)."""
    assert "python -u -m verify.main" in run_block()


def test_the_timeout_covers_the_gate_worst_case() -> None:
    """게이트가 끝까지 기다리면 10분이다. 그보다 넉넉해야 로그가 남는다."""
    m = re.search(r"timeout-minutes:\s*(\d+)", YML)
    assert m and int(m.group(1)) >= 20


# ── 두 번 보내지 않는다 ───────────────────────────────────────────


def test_the_cron_asks_before_running() -> None:
    """예비 cron은 dispatch로 이미 돌았는지 모른다 — `--if-not-verified`로 묻는다."""
    assert "github.event_name == 'schedule'" in YML
    assert "--if-not-verified" in run_block()


def test_overlapping_runs_wait_instead_of_killing() -> None:
    """앞엣것을 죽이면 판정이 반쯤 저장된 채 끝나고, 메일이 나간 뒤일 수도 있다."""
    assert "cancel-in-progress: false" in YML


def test_already_verified_looks_at_the_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """**게이트는 이벤트가 아니라 DB를 믿는다** — 이 판정도 같다."""
    from verify import main, store

    class Ctx:
        def __enter__(self) -> Ctx:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def cursor(self) -> Ctx:
            return self

    monkeypatch.setattr(store, "connect", Ctx)
    monkeypatch.setattr(store, "fetch_verdicts", lambda cur, d, source="batch": {"005930": 1})
    assert main._already_verified(date(2026, 9, 3)) is True
    monkeypatch.setattr(store, "fetch_verdicts", lambda cur, d, source="batch": {})
    assert main._already_verified(date(2026, 9, 3)) is False


def test_already_verified_counts_batch_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """온디맨드로 하나 넣은 것이 「오늘 배치를 돌렸다」가 되면 안 된다 (F43)."""
    from verify import main, store

    seen: list[Any] = []

    class Ctx:
        def __enter__(self) -> Ctx:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def cursor(self) -> Ctx:
            return self

    def fetch(cur: Any, d: Any, source: str = "batch") -> dict[str, Any]:
        seen.append(source)
        return {}

    monkeypatch.setattr(store, "connect", Ctx)
    monkeypatch.setattr(store, "fetch_verdicts", fetch)
    main._already_verified(date(2026, 9, 3))
    assert seen == ["batch"]


def test_the_default_check_is_the_real_one() -> None:
    """주입이 없으면 실물을 쓴다 — M0에서는 주입으로만 썼다."""
    import inspect

    from verify import main

    assert "verified_check or _already_verified" in inspect.getsource(main.main)


# ── Secrets 이름 ──────────────────────────────────────────────────


def test_every_secret_the_workflow_reads_is_declared() -> None:
    """Secrets 이름 오타는 **빈 값으로 조용히 흐른다** — `.env.example`이 정본이다."""
    used = set(re.findall(r"secrets\.([A-Z0-9_]+)", YML))
    declared = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", EXAMPLE, re.M))
    assert used <= declared, f".env.example에 없는 Secrets: {used - declared}"


def test_the_workflow_carries_every_key_the_code_needs() -> None:
    """코드가 읽는 키가 워크플로 `env:`에 없으면 CI에서만 「환경변수 없음」이 난다."""
    used_by_code: set[str] = set()
    for f in (ROOT / "verify").glob("*.py"):
        used_by_code |= set(
            re.findall(r'config\.(?:require|optional)\("([A-Z0-9_]+)"', f.read_text("utf-8"))
        )
    in_workflow = set(re.findall(r"^\s+([A-Z][A-Z0-9_]*):\s*\$\{\{", YML, re.M))
    assert used_by_code <= in_workflow, f"워크플로에 없다: {used_by_code - in_workflow}"


def test_permissions_are_read_only() -> None:
    """이 워크플로는 리포에 쓰지 않는다 — 결과는 Supabase·메일로 간다 (N15)."""
    assert re.search(r"permissions:\s*\n\s*contents: read", YML)
