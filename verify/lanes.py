"""증거 갈래 수집 — **없어도 되는 층** (F34). 도메인 층.

새 갈래(재무·공매도)만이 아니라 **다섯 갈래 전부**가 이 규칙을 따른다: 실패하면 그 줄만 비우고
「생략」으로 적는다. **판정도 메일도 막지 않는다** — 공시 없는 판정도 판정이다.

다만 **조용히 빠지지는 않는다.** 왜 비었는지가 함께 남아야 다음 날 고칠 수 있다.
빈 갈래는 `judge()`에서 **사각지대로 흐르지 점수 0으로 들어가지 않는다** — 「수급 0원」과
「수급 생략」은 다른 말이다.

## 상위 신선도 (R5)

상위 `krx-stock-charts`가 조용히 멈추면 이 갈래들이 낡는다 — **2026-08-18~08-31에 실제로
2주간 멈춘 전력**이 있다. `ksc_meta`를 보고 낡았으면 표시한다.

⚠ **`ksc_meta.updated_at` 열을 믿지 마라.** 상위가 `upsert`로 값만 갈아 끼우는데
`default now()`는 INSERT에만 걸려, 그 열은 **행이 처음 만들어진 시각에 멈춰 있다**
(2026-09-05 확인: 열은 2026-08-15인데 자료는 2026-09-04까지 있다).
신선도는 **값 안의 `updated`**로 본다 — 상위가 열을 고치더라도 우리가 통제하지 못하는
열에 판단을 매달지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from verify.models import EVIDENCE_LANES, Evidence
from verify.store import Queryable

LANE_NAMES = EVIDENCE_LANES  # 이름이 갈라지면 화면과 저장이 다른 말을 한다

# 긴 연휴를 정상으로 본다. 금요일 자료를 화요일에 읽는 것은 4일이다 —
# 매번 울면 진짜 멈춤(2주)이 묻힌다.
STALE_AFTER_DAYS = 4

META_KEY = "update"
Q_META = "select key, value, updated_at from ksc_meta where key = %s"


@dataclass(frozen=True, slots=True)
class Collected:
    """한 종목의 갈래 수집 결과. **빈 갈래와 그 이유가 함께 있다.**"""

    evidence: Evidence
    skipped: tuple[str, ...] = ()
    reasons: dict[str, str] = field(default_factory=dict)

    def notes(self) -> tuple[str, ...]:
        """사람이 읽는 자리에 붙일 줄. 정상이면 **아무 말도 하지 않는다.**"""
        if not self.skipped:
            return ()
        return (f"{' · '.join(self.skipped)} 생략",)


def _run(name: str, fn: Callable[[], Any] | None, skipped: list[str],
         reasons: dict[str, str]) -> Any:
    """갈래 하나. **예외를 밖으로 내지 않는다** — 하나가 나머지 넷을 데려가면 안 된다."""
    if fn is None:
        skipped.append(name)
        reasons[name] = ""
        return None
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 — 갈래 단위 격리가 이 함수의 일이다
        skipped.append(name)
        reasons[name] = f"{type(exc).__name__}: {exc}"
        return None
    if value is None:
        skipped.append(name)
        reasons[name] = ""  # 실패가 아니라 **원래 없는 것**이다 (공매도가 M8 전까지 그렇다)
    return value


def collect(
    *,
    d: date,
    ticker: str,
    disclosures: Callable[[], Any] | None = None,
    news: Callable[[], Any] | None = None,
    flows: Callable[[], Any] | None = None,
    financial: Callable[[], Any] | None = None,
    shorting: Callable[[], Any] | None = None,
) -> Collected:
    """다섯 갈래를 모은다. **어느 하나도 필수가 아니다** (F34).

    Args:
        d: 기준일.
        ticker: 종목.
        disclosures: 공시 갈래. 나머지도 같은 꼴 — 인자 없는 호출로 값을 내거나 던진다.

    Returns:
        얻은 것, 못 얻은 갈래 이름, 그리고 **못 얻은 이유**. 실패한 갈래는 `None`이고
        `0`이나 빈 값으로 채우지 않는다.
    """
    skipped: list[str] = []
    reasons: dict[str, str] = {}
    got = [
        _run(name, fn, skipped, reasons)
        for name, fn in zip(
            LANE_NAMES, (disclosures, news, flows, financial, shorting), strict=True
        )
    ]
    return Collected(
        evidence=Evidence(d=d, ticker=ticker, disclosures=got[0], news=got[1],
                          flows=got[2], financial=got[3], shorting=got[4]),
        skipped=tuple(skipped),
        reasons=reasons,
    )


@dataclass(frozen=True, slots=True)
class Freshness:
    """상위 자료가 얼마나 뒤처져 있는가 (R5)."""

    data_date: date | None = None
    days_behind: int | None = None
    stale: bool = True  # **모르면 낡은 것으로 본다** — 최신이라 가정하면 조용히 쓴다
    note: str = ""


def _as_date(raw: Any) -> date | None:
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None


def freshness(conn: Queryable, *, today: date, key: str = META_KEY) -> Freshness:
    """상위 `ksc_meta`로 자료 신선도를 본다 (R5).

    **값 안의 `updated`를 읽는다.** `updated_at` 열은 상위 upsert가 갱신하지 않아
    행이 처음 만들어진 시각에 멈춰 있다 (2026-09-05 확인).

    Args:
        conn: DB 커넥션.
        today: 기준일 (KST).
        key: `ksc_meta`의 키.

    Returns:
        모르면 `stale=True`다 — **최신이라고 가정하지 않는다.**
        정상이면 `note`가 비어 있다: 매번 울면 진짜 멈춤이 묻힌다.
    """
    rows = conn.execute(Q_META, (key,)).fetchall()
    payload = rows[0][1] if rows and len(rows[0]) > 1 else None
    when = _as_date((payload or {}).get("updated")) if isinstance(payload, dict) else None
    if when is None:
        return Freshness(note=f"상위 자료 기준일을 모른다 (ksc_meta.{key} 없음) — 낡았을 수 있다")
    behind = (today - when).days
    if behind <= STALE_AFTER_DAYS:
        return Freshness(data_date=when, days_behind=behind, stale=False)
    return Freshness(
        data_date=when,
        days_behind=behind,
        stale=True,
        note=f"상위 자료가 {when.isoformat()}에 멈춰 있다 — {behind}일 뒤처졌다",
    )
