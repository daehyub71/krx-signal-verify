"""discriminate — 정합 군과 불일치 군의 초과수익 **분포** 비교 (F24). 순수 함수.

**이 파일이 R2를 막는다.** 「불일치 적중률 68%」 한 줄이면 다음 판정을 예측으로 읽는다.
그래서 문구가 아니라 **타입으로** 강제한다: 반환 타입에 적중률 필드가 없다.

무엇을 내놓는가 — 두 군의 **분포**다: 중앙값 · 사분위 · 겹침 · 표본 수.
「어느 쪽이 맞았나」가 아니라 **「두 군이 갈리는가」**를 본다.

지키는 것:
  · **반환 타입에 적중률·승률·정확도 필드가 없다** (V4)
  · **표본이 얇으면 수치 대신 「표본 부족 (n=…)」** — 없는 확신을 만들지 않는다
  · **`source='ondemand'`는 집계에서 뺀다** (F43) — 궁금해서 넣은 종목은 편향돼 있다
  · **미도래(`None`)를 0으로 세지 않는다** — 표본 수가 부풀고 분포가 0쪽으로 쏠린다
"""

from __future__ import annotations

import pathlib
from datetime import date
from typing import Any

import pytest

from verify import discriminate

D = date(2026, 9, 5)


def pairs(*items: tuple[str, float | None]) -> list[tuple[str, float | None]]:
    return list(items)


# ── ★ 적중률을 만들 수 없다 (V4·R2) ───────────────────────────────


def test_the_result_has_no_hit_rate_field() -> None:
    """**문구가 아니라 타입으로 막는다.** 필드가 없으면 화면이 띄울 수도 없다."""
    fields = set(discriminate.Discrimination.__dataclass_fields__)
    banned = {"hit_rate", "accuracy", "win_rate", "precision", "correct", "hits"}
    assert not (fields & banned), fields & banned


def test_no_field_name_suggests_a_score_card() -> None:
    for name in discriminate.Discrimination.__dataclass_fields__:
        for word in ("hit", "win", "accur", "correct"):
            assert word not in name.lower(), name


BANNED_WORDS = ("hit", "win", "accur", "correct", "rate", "적중", "승률")


@pytest.mark.parametrize("cls", [discriminate.Group, discriminate.Discrimination])
def test_no_type_can_carry_a_score_card(cls: Any) -> None:
    """**두 타입 모두 본다.** `Discrimination`만 막고 `Group`에 `win_rate`를 넣으면
    화면은 그것을 띄운다 (변이 검사로 드러남, 2026-09-05).
    """
    for name in cls.__dataclass_fields__:
        for word in BANNED_WORDS:
            assert word not in name.lower(), f"{cls.__name__}.{name}"


def test_the_group_summary_is_a_distribution() -> None:
    assert {"n", "median", "q1", "q3"} <= set(discriminate.Group.__dataclass_fields__)


def test_the_module_says_nothing_forbidden() -> None:
    """N2 — 이 모듈의 문장도 우리 문장이다."""
    from verify import wording

    src = pathlib.Path(discriminate.__file__).read_text(encoding="utf-8")
    for line in src.splitlines():
        if line.strip().startswith(("#", '"', "'")) or "`" in line:
            continue
        assert not wording.has_forbidden_outcome(line), line


# ── 분포 ──────────────────────────────────────────────────────────


def test_a_group_reports_its_quartiles() -> None:
    g = discriminate.summarize([1.0, 2.0, 3.0, 4.0, 5.0])
    assert g.n == 5
    assert g.median == pytest.approx(3.0)
    assert g.q1 == pytest.approx(2.0)
    assert g.q3 == pytest.approx(4.0)


def test_missing_values_are_not_counted_as_zero() -> None:
    """**미도래를 0으로 세면 표본이 부풀고 분포가 0쪽으로 쏠린다.**"""
    g = discriminate.summarize([1.0, None, 3.0, None])
    assert g.n == 2
    assert g.median == pytest.approx(2.0)


def test_an_empty_group_is_empty_not_zero() -> None:
    g = discriminate.summarize([])
    assert g.n == 0
    assert g.median is None and g.q1 is None and g.q3 is None


# ── 겹침 ──────────────────────────────────────────────────────────


def test_two_separated_groups_barely_overlap() -> None:
    """갈리는 것이 이 프로젝트가 보려는 것이다."""
    got = discriminate.compare(
        aligned=[5.0, 6.0, 7.0, 8.0], conflict=[-8.0, -7.0, -6.0, -5.0], min_n=1
    )
    assert got.overlap is not None
    assert got.overlap < 0.2


def test_two_identical_groups_overlap_completely() -> None:
    same = [1.0, 2.0, 3.0, 4.0]
    got = discriminate.compare(aligned=same, conflict=list(same), min_n=1)
    assert got.overlap is not None
    assert got.overlap > 0.9


def test_overlap_needs_both_groups() -> None:
    got = discriminate.compare(aligned=[1.0, 2.0], conflict=[], min_n=1)
    assert got.overlap is None


@pytest.mark.parametrize("side", ["aligned", "conflict"])
def test_overlap_is_none_when_either_side_has_no_quartiles(side: str) -> None:
    """**양쪽을 다 봐야 한다** — 한쪽만 검사하면 반대쪽이 비었을 때 터진다."""
    full = discriminate.summarize([1.0, 2.0, 3.0, 4.0])
    empty = discriminate.Group()
    a, c = (empty, full) if side == "aligned" else (full, empty)
    assert discriminate._overlap(a, c) is None


# ── 표본 부족 (R10) ───────────────────────────────────────────────


def test_a_thin_sample_reports_no_numbers() -> None:
    """**없는 확신을 만들지 않는다.** 소급하지 않기로 해서(V13) 3개월간 얇다."""
    got = discriminate.compare(aligned=[1.0, 2.0], conflict=[-1.0], min_n=30)
    assert got.thin is True
    assert got.overlap is None
    assert "표본 부족" in got.note
    assert "n=" in got.note


def test_the_note_carries_the_actual_counts() -> None:
    got = discriminate.compare(aligned=[1.0, 2.0], conflict=[-1.0], min_n=30)
    assert "2" in got.note and "1" in got.note


def test_a_thick_sample_says_nothing_extra() -> None:
    """정상일 때 조용해야 얇을 때의 한 줄이 보인다."""
    got = discriminate.compare(aligned=[float(i) for i in range(40)],
                               conflict=[float(-i) for i in range(40)], min_n=30)
    assert got.thin is False
    assert got.note == ""


def test_counts_are_reported_even_when_thin() -> None:
    """수치는 감춰도 **표본 수는 보여 준다** — 얼마나 기다려야 하는지 알아야 한다."""
    got = discriminate.compare(aligned=[1.0], conflict=[], min_n=30)
    assert got.aligned.n == 1
    assert got.conflict.n == 0


def test_the_default_threshold_is_written_down() -> None:
    assert discriminate.MIN_SAMPLE >= 30


# ── 「무관」은 군이 아니다 ─────────────────────────────────────────


def test_only_two_groups_are_compared() -> None:
    """`무관`은 「볼 것이 없었다」다 — 세 번째 군으로 세면 비교가 흐려진다."""
    fields = set(discriminate.Discrimination.__dataclass_fields__)
    assert "aligned" in fields and "conflict" in fields
    assert "silent" not in fields and "neutral" not in fields


def test_split_puts_each_verdict_in_its_group() -> None:
    rows = [("정합", 1.0), ("불일치", -1.0), ("무관", 5.0), ("정합", 2.0)]
    a, c = discriminate.split(rows)
    assert a == [1.0, 2.0]
    assert c == [-1.0]


@pytest.mark.parametrize("stand", ["정합", "불일치"])
def test_split_keeps_none_so_the_group_can_drop_it(stand: str) -> None:
    """`None`을 여기서 지우면 **표본 수를 셀 곳이 사라진다** — 군에서 센다.

    **양쪽 다 본다** — 한쪽만 검사하면 다른 쪽에서 조용히 지워진다 (변이 검사로 드러남).
    """
    a, c = discriminate.split([(stand, None), (stand, 1.0)])
    got = a if stand == "정합" else c
    assert got == [None, 1.0]


# ── 저장 (F43) ────────────────────────────────────────────────────


def test_the_row_carries_the_ruleset_version() -> None:
    """서로 다른 자로 잰 값을 한 표에 섞지 않는다 (F26)."""
    got = discriminate.compare(aligned=[1.0] * 40, conflict=[-1.0] * 40, min_n=30)
    row = discriminate.to_row(D, 5, "1.0", got)
    assert row["rules_version"] == "1.0"
    assert row["as_of"] == D and row["horizon"] == 5


def test_the_row_has_no_hit_rate_either() -> None:
    got = discriminate.compare(aligned=[1.0] * 40, conflict=[-1.0] * 40, min_n=30)
    row = discriminate.to_row(D, 5, "1.0", got)
    for key in row:
        assert "hit" not in key and "accur" not in key, key


def test_the_query_excludes_ondemand() -> None:
    """궁금해서 넣은 종목은 표본이 편향돼 있다 (F43)."""
    from verify import store

    where = store.Q_DISCRIMINATION.lower().split("where", 1)[1]
    assert "source = 'batch'" in where or "source = %s" in where


# ── aggregate 노드 ────────────────────────────────────────────────


def test_the_node_stores_one_row_per_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    """5·20·60을 따로 잰다 — 한 줄로 합치면 구간별 차이가 사라진다."""
    from typing import cast

    from verify import nodes
    from verify import state as st

    saved: list[date] = []

    def spy(day: date) -> int:
        saved.append(day)
        return 3

    monkeypatch.setattr(nodes, "_discriminate", spy)
    out = nodes.aggregate(cast(st.VerifyState, {"run_date": D}))
    assert out["discrimination"]["rows"] == 3


def test_a_failure_does_not_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    from typing import cast

    from verify import nodes
    from verify import state as st

    def boom(day: date) -> int:
        raise RuntimeError("DB 죽음")

    monkeypatch.setattr(nodes, "_discriminate", boom)
    out = nodes.aggregate(cast(st.VerifyState, {"run_date": D}))
    assert any("DB 죽음" in e for e in out["errors"])


def test_aggregate_is_no_longer_a_stub() -> None:
    from verify import nodes

    assert "aggregate" not in nodes.STUB_NODES


def test_each_horizon_reads_its_own_column() -> None:
    """`h5`·`h20`·`h60`을 각각 지수와 견준다 — 한 열만 보면 나머지가 영원히 빈다."""
    from verify import store

    for h in (5, 20, 60):
        assert f"h{h} - o.h{h}_index" in store.excess_sql(h)


def test_the_excess_needs_both_sides() -> None:
    """지수가 없으면 초과도 없다 (F23b) — SQL이 `null`을 주고 군이 안 센다."""
    from verify import store

    assert "o.h5 - o.h5_index" in store.excess_sql(5)


def test_every_horizon_gets_its_own_row(monkeypatch: pytest.MonkeyPatch) -> None:
    """5·20·60을 **셋 다** 저장한다 — 하나만 쓰면 나머지 두 구간이 영원히 빈다.

    노드 테스트가 `_discriminate`를 통째로 갈아 끼우므로 여기서 그 안을 본다
    (변이 검사로 드러남, 2026-09-05).
    """
    from verify import nodes, store
    from verify import state as st

    saved: list[Any] = []
    monkeypatch.setattr(store, "connect", lambda: _FakeCtx())
    monkeypatch.setattr(store, "fetch_excess", lambda cur, h, rv: [])
    def keep(rows: Any, conn: Any = None) -> int:
        saved.extend(rows)
        return len(rows)

    monkeypatch.setattr(store, "save_discrimination", keep)
    nodes._discriminate(D)
    assert [r["horizon"] for r in saved] == list(st.HORIZONS)


class _FakeCtx:
    def __enter__(self) -> _FakeCtx:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def cursor(self) -> _FakeCtx:
        return self
