"""정합 군과 불일치 군의 초과수익 **분포** 비교 (F24). **순수 함수.**

## 이 모듈이 막는 것 (R2)

「불일치 판정의 68%」처럼 비율 한 줄이면, 읽는 사람은 다음 판정을 **예측**으로 읽는다.
이 프로젝트가 하지 않기로 한 바로 그 일이다.

그래서 문구로 부탁하지 않고 **타입으로 막는다** — 반환 타입에 그런 필드가 아예 없다.
없는 값은 화면이 띄울 수도, 메일이 쓸 수도 없다 (V4).

## 무엇을 내놓는가

두 군의 **분포**다: 중앙값 · 사분위 · 겹침 · 표본 수.
「어느 판정이 옳았나」가 아니라 **「두 군이 갈리는가」**를 본다.

겹침이 작으면 판정이 무언가를 가르고 있다는 관측이고, 크면 못 가르고 있다는 관측이다.
어느 쪽이든 **개별 종목의 앞날에 대해서는 아무 말도 하지 않는다.**

## 표본이 얇을 때

소급하지 않기로 해서(V13) 표본은 오늘부터만 쌓인다 — 3개월간 얇다.
얇으면 **수치 대신 「표본 부족 (n=…)」**을 낸다. 없는 확신을 만들지 않는다 (R10).
다만 **표본 수는 보여 준다** — 얼마나 더 기다려야 하는지 알아야 한다.

## 「무관」은 군이 아니다

`무관`은 「볼 것이 없었다」다. 세 번째 군으로 세면 두 군의 비교가 흐려진다.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from verify.verdict import STAND_CONTRADICTS, STAND_CORROBORATES

# 이 아래면 수치를 내지 않는다. 하루 수십 건이라 한 달쯤이면 넘는다.
MIN_SAMPLE = 30


@dataclass(frozen=True, slots=True)
class Group:
    """한 군의 초과수익 분포. **비율을 담는 칸이 없다** — 분포만 낸다."""

    n: int = 0
    median: float | None = None
    q1: float | None = None
    q3: float | None = None

    @property
    def spread(self) -> float | None:
        """사분위 범위. 없으면 `None`."""
        return None if self.q1 is None or self.q3 is None else self.q3 - self.q1


@dataclass(frozen=True, slots=True)
class Discrimination:
    """두 군의 비교 (F24).

    **이 타입에 그런 비율을 담는 칸이 없다** — V4를 문구가 아니라 타입으로 강제한다.
    필드가 없으면 화면도 메일도 그 숫자를 만들 수 없다.
    """

    aligned: Group
    conflict: Group
    overlap: float | None = None  # 두 분포가 겹치는 정도 (0~1). 작을수록 갈린다
    thin: bool = True  # 표본이 얇은가 — **기본이 얇음이다**
    note: str = ""  # 얇을 때만 채운다. 정상이면 조용하다


def summarize(values: Sequence[float | None]) -> Group:
    """한 군의 분포. **`None`은 세지 않는다** — 미도래를 0으로 세면 분포가 0쪽으로 쏠린다."""
    got = sorted(v for v in values if v is not None)
    if not got:
        return Group()
    if len(got) == 1:
        return Group(n=1, median=got[0], q1=got[0], q3=got[0])
    q = statistics.quantiles(got, n=4, method="inclusive")
    return Group(n=len(got), median=statistics.median(got), q1=q[0], q3=q[2])


def _overlap(a: Group, b: Group) -> float | None:
    """두 사분위 구간이 겹치는 정도 (0~1). 겹칠 곳이 없으면 0, 같으면 1에 가깝다."""
    if a.q1 is None or a.q3 is None or b.q1 is None or b.q3 is None:
        return None
    lo, hi = max(a.q1, b.q1), min(a.q3, b.q3)
    shared = max(0.0, hi - lo)
    span = max(a.q3, b.q3) - min(a.q1, b.q1)
    return 1.0 if span == 0 else shared / span


def compare(
    aligned: Sequence[float | None],
    conflict: Sequence[float | None],
    min_n: int = MIN_SAMPLE,
) -> Discrimination:
    """두 군을 견준다 (F24).

    Args:
        aligned: 정합 판정의 초과수익.
        conflict: 불일치 판정의 초과수익.
        min_n: 이 아래면 수치를 내지 않는다.

    Returns:
        분포 요약. **표본이 얇으면 `overlap`이 `None`이고 `note`가 채워진다.**
    """
    a, c = summarize(aligned), summarize(conflict)
    if a.n < min_n or c.n < min_n:
        return Discrimination(
            aligned=a, conflict=c, overlap=None, thin=True,
            note=f"표본 부족 (정합 n={a.n} · 불일치 n={c.n} · 필요 {min_n})",
        )
    return Discrimination(aligned=a, conflict=c, overlap=_overlap(a, c), thin=False)


def split(
    rows: Sequence[tuple[str, float | None]],
) -> tuple[list[float | None], list[float | None]]:
    """`(stand, 초과수익)` 목록 → `(정합, 불일치)`. **`무관`은 어느 군도 아니다.**

    `None`을 여기서 지우지 않는다 — 표본 수를 셀 곳이 `summarize` 하나여야 한다.
    """
    return (
        [v for stand, v in rows if stand == STAND_CORROBORATES],
        [v for stand, v in rows if stand == STAND_CONTRADICTS],
    )


def to_row(as_of: date, horizon: int, rules_version: str, got: Discrimination) -> dict[str, Any]:
    """저장 행. **어느 산식으로 잰 것인지 함께 남긴다** (F26)."""
    return {
        "as_of": as_of,
        "horizon": horizon,
        "rules_version": rules_version,
        "n_aligned": got.aligned.n,
        "n_conflict": got.conflict.n,
        "aligned": {"median": got.aligned.median, "q1": got.aligned.q1, "q3": got.aligned.q3},
        "conflict": {"median": got.conflict.median, "q1": got.conflict.q1, "q3": got.conflict.q3},
        "overlap": got.overlap,
    }
