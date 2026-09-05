"""F21b·F43 — `source` 열을 처음부터 열어 둔다, 그리고 집계는 `batch`만 본다.

`batch` / `ondemand`가 지금 쓰는 값이고, 나중에 `backfill`이 늘어도 **스키마를 고치지 않는다.**
열거형이 아니라 **문자열 + CHECK**라 값을 더하는 것이 마이그레이션이 아니다.

**집계는 기본으로 `batch`만 본다** (F43) — 궁금해서 넣은 온디맨드 종목은 표본이 편향돼 있다.
「불일치가 잘 맞더라」를 보려고 불일치 종목만 골라 넣으면 분포가 그쪽으로 기운다.

이 규칙을 **문구가 아니라 기본값으로** 강제한다: `fetch_verdicts`의 `source` 기본값이 `batch`다.
"""

from __future__ import annotations

import pathlib
import re
from datetime import date
from typing import Any

import pytest

from verify import store

D = date(2026, 9, 5)
SQL = pathlib.Path("supabase/schema.sql").read_text(encoding="utf-8")


def table(name: str) -> str:
    return SQL.split(f"create table if not exists {name} (", 1)[1].split("\n);", 1)[0]


# ── 열이 열려 있다 ────────────────────────────────────────────────


def test_source_is_text_not_an_enum() -> None:
    """열거형이면 값을 더하는 것이 마이그레이션이 된다 — 문자열 + CHECK로 둔다."""
    body = table("ksv_verdicts")
    assert re.search(r"source\s+text\s+not null", body), body
    assert "enum" not in body.lower()


def test_backfill_is_already_allowed() -> None:
    """지금 안 쓰지만 **미리 열어 둔다** — 나중에 스키마를 고치지 않기 위해서다 (F21b)."""
    check = next(ln for ln in table("ksv_verdicts").splitlines() if "source check" in ln)
    for value in ("batch", "ondemand", "backfill"):
        assert f"'{value}'" in check, value


def test_the_check_still_refuses_anything_else() -> None:
    """열어 두는 것과 아무 말이나 받는 것은 다르다 — 오타가 조용히 들어오면 집계가 갈린다."""
    check = next(ln for ln in table("ksv_verdicts").splitlines() if "source check" in ln)
    assert "in (" in check
    assert len(re.findall(r"'\w+'", check)) == 3


def test_source_is_part_of_the_primary_key() -> None:
    """같은 날 같은 종목을 배치와 온디맨드가 각각 가질 수 있다 — 서로 덮으면 안 된다."""
    assert "primary key (d, ticker, source)" in table("ksv_verdicts")


def test_the_code_only_uses_the_two_it_needs() -> None:
    """`backfill`은 열어만 뒀지 **쓰지 않는다** (V13 — 소급하지 않는다)."""
    assert store.SOURCE_BATCH == "batch"
    assert store.SOURCE_ONDEMAND == "ondemand"
    src = pathlib.Path(store.__file__).read_text(encoding="utf-8")
    assert "backfill" not in src


# ── 집계는 batch만 (F43) ─────────────────────────────────────────


def test_reading_defaults_to_batch() -> None:
    """**문구가 아니라 기본값으로 강제한다.** 부르는 쪽이 잊어도 온디맨드가 안 섞인다."""
    import inspect

    sig = inspect.signature(store.fetch_verdicts)
    assert sig.parameters["source"].default == store.SOURCE_BATCH


def test_ondemand_must_be_asked_for_explicitly() -> None:
    class Conn:
        def __init__(self) -> None:
            self.params: Any = None

        def execute(self, query: Any, params: Any = None) -> Conn:
            self.params = params
            return self

        def fetchall(self) -> list[Any]:
            return []

    c = Conn()
    store.fetch_verdicts(c, D)
    assert c.params == (D, "batch")
    store.fetch_verdicts(c, D, source=store.SOURCE_ONDEMAND)
    assert c.params == (D, "ondemand")


def test_the_discrimination_table_records_which_ruleset(  ) -> None:
    """분포를 저장할 때도 **어느 산식으로 잰 것인지** 함께 남는다 (F26)."""
    assert "primary key (as_of, horizon, rules_version)" in table("ksv_discrimination")


@pytest.mark.parametrize("mode", ["batch", "ondemand"])
def test_the_node_passes_its_mode_through(mode: str) -> None:
    """온디맨드 실행이 배치로 기록되면 F43의 제외가 무의미해진다."""
    import inspect

    from verify import nodes

    src = inspect.getsource(nodes.judge)
    assert 'mode = s.get("mode") or st.MODE_BATCH' in src
    assert "signals=signals" in src
