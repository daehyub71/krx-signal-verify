"""그래프 상태 — reducer 하나가 빠지면 데이터가 조용히 사라진다.

`evidence`에 `Annotated[list, operator.add]`를 빼먹으면 fan-out 결과가
**마지막 하나만 남고 예외도 안 난다.** 선행 두 프로젝트에서 실증됐다.
`tests/test_graph.py`의 합류 테스트가 다른 한 겹이고, 여기는 **선언 자체**를 잠근다.
"""

from __future__ import annotations

import inspect
import operator
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from verify import models, state


def hints() -> dict[str, Any]:
    return get_type_hints(state.VerifyState, include_extras=True)


# ── reducer — 이 파일의 존재 이유 ────────────────────────────────


def test_evidence_carries_operator_add_reducer() -> None:
    """이 테스트가 깨지면 fan-out 결과가 마지막 하나만 남는다. 지우지 말 것."""
    ev = hints()["evidence"]
    assert get_origin(ev) is not None
    args = get_args(ev)
    assert operator.add in args[1:], "evidence에 operator.add reducer가 없다"


def test_evidence_reducer_actually_concatenates() -> None:
    """reducer가 붙어 있는지만이 아니라 **합쳐지는지**를 본다."""
    ev = hints()["evidence"]
    reducer = get_args(ev)[1]
    assert reducer([1, 2], [3]) == [1, 2, 3]


def test_fields_that_must_not_have_a_reducer() -> None:
    """덮어써야 하는 값에 reducer가 붙으면 상태가 눈덩이처럼 커진다."""
    h = hints()
    for key in ("gate", "attempts", "status", "verdicts"):
        assert get_origin(h[key]) is not Annotated, f"{key}에 reducer가 붙어 있다"


# ── 상수 ─────────────────────────────────────────────────────────


def test_gate_retries_ten_times_at_one_minute() -> None:
    """dispatch는 「워크플로가 끝났다」만 말한다. DB를 믿고 기다린다 (F1)."""
    assert state.GATE_MAX_ATTEMPTS == 10
    assert state.GATE_WAIT_SECONDS == 60


def test_horizons_are_five_twenty_sixty_and_shared_with_domain() -> None:
    """관측 구간이 두 곳에 따로 적히면 갈라진다 — 도메인 것을 그대로 쓴다."""
    assert state.HORIZONS == (5, 20, 60)
    assert state.HORIZONS is models.HORIZONS


def test_gate_values_are_the_four_documented_ones() -> None:
    assert set(state.GATE_VALUES) == {"ready", "stale", "missing", "timeout"}


def test_modes_are_batch_and_ondemand() -> None:
    """온디맨드는 게이트도 메일도 없고 종목이 하나다 (V8)."""
    assert set(state.MODES) == {"batch", "ondemand"}


def test_recursion_limit_covers_the_gate_loop() -> None:
    """`gate→wait→gate` 사이클이 10회 돈다. 여유가 없으면 중간에 끊긴다."""
    assert state.RECURSION_LIMIT > state.GATE_MAX_ATTEMPTS * 2


# ── 층 분리 ──────────────────────────────────────────────────────


def test_state_module_does_not_touch_io() -> None:
    """그래프 층은 DB·HTTP를 모른다 (N4). 여기서 새면 3층 분리가 무너진다."""
    src = inspect.getsource(state)
    for banned in ("supabase", "psycopg", "httpx", "urllib.request", "smtplib", "anthropic"):
        assert banned not in src, f"state.py가 {banned}를 안다"


def test_state_is_total_false() -> None:
    """노드는 자기가 채우는 키만 돌려준다. 전부 필수면 스텁이 못 돈다."""
    assert state.VerifyState.__total__ is False
