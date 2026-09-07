"""공매도 갈래 (F32·F33). 상위 `ksc_shorting`을 SQL로 읽는다 (V6b — M8, 2026-09-07).

상위 `krx-stock-charts` F15가 매일 시장당 1회로 전 종목의 `공매도·매수·비중`을 저장한다.
열은 `d · ticker · short_vol · buy_vol · ratio` — 상위 `tests/test_shorting.py`가 이 이름을 잠근다.

## 상태 판별이 먼저다 (R6)

pykrx의 공매도 함수는 **예외를 던지지 않고 0행**을 줄 수 있다. 그래서 읽기 전에 세 상태를 가른다.

| 상태 | 무슨 일인가 | 실패인가 |
|------|-------------|----------|
| `MISSING` | 표 자체가 없다 — 상위가 수집 전 | **아니다.** 없는 층 (F34가 「생략」) |
| `EMPTY` | 표는 있는데 **0행** | **그렇다** — 수집이 조용히 실패했다 |
| `READY` | 행이 있다 | 정상 — `read_all`로 읽는다 |

읽은 결과에서 **종목이 빠져 있는 것**은 정상이다(그날 공매도 통계에 없는 종목). 0주는 실제 값이다.
공매도는 판정 점수에 들어가지 않는다 — 사각지대에서 빠질 뿐이다 (F32·V5).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from verify.store import Queryable

WINDOW_DAYS = 20  # F32 — 거래량·비중 추이 구간

TABLE = "ksc_shorting"

MISSING = "missing"  # 표가 없다 — 없는 층 (정상)
EMPTY = "empty"  # 표는 있는데 0행 — 실패 (R6)
READY = "ready"  # 행이 있다 — 읽는다

Q_TABLE_EXISTS = "select to_regclass(%s) is not null"
Q_ANY_ROWS = f"select 1 from {TABLE} limit %s"

# 종목 N개 × 최근 `days`행. 수급(`enrich.Q_FLOWS`)과 같은 lateral 꼴 —
# 상위 인덱스 `(ticker, d desc)`를 탄다.
Q_DAYS = f"""
select s.ticker, s.d, s.short_vol, s.buy_vol, s.ratio
  from {TABLE} s
  join lateral (
      select d from {TABLE}
       where ticker = s.ticker
       order by d desc limit %s
  ) w on w.d = s.d
 where s.ticker = any(%s)
 order by s.ticker, s.d
"""


@dataclass(frozen=True, slots=True)
class ShortDay:
    """하루치 공매도. `ratio`는 KRX가 준 비중(%) 그대로."""

    d: date
    short_vol: int
    buy_vol: int
    ratio: float


@dataclass(frozen=True, slots=True)
class Shorting:
    """공매도 갈래 — 상태와 자료. `days`는 날짜 오름차순."""

    state: str
    reason: str = ""
    rows: int = 0
    days: tuple[ShortDay, ...] = ()

    @property
    def ok(self) -> bool:
        """알려야 할 상태가 아닌가. `MISSING`(없는 층)과 `READY`만 정상이다."""
        return self.state in (MISSING, READY)

    @property
    def latest(self) -> ShortDay | None:
        return self.days[-1] if self.days else None

    @property
    def avg_ratio(self) -> float | None:
        """창 안 비중 평균(%). 자료가 없으면 None — 0으로 두지 않는다."""
        if not self.days:
            return None
        return round(sum(x.ratio for x in self.days) / len(self.days), 2)

    def lines(self) -> tuple[str, ...]:
        """사람이 읽는 줄. **사실만** — 방향을 해석하지 않는다 (N1)."""
        if not self.days:
            return ()
        last = self.days[-1]
        return (
            f"{last.d:%m/%d} 공매도 {last.short_vol:,}주 · 공매도 비중 {last.ratio:.2f}%",
            f"{len(self.days)}거래일 공매도 비중 평균 {self.avg_ratio:.2f}%",
        )


def probe(conn: Queryable, *, limit: int = 1) -> Shorting:
    """공매도 갈래가 어떤 상태인지 본다. **자료를 읽지는 않는다.**

    Returns:
        `MISSING`(없는 층 · 정상) · `EMPTY`(0행 · 실패, R6) · `READY`(행 있음).
    """
    exists = conn.execute(Q_TABLE_EXISTS, (TABLE,)).fetchone()
    if not (exists and exists[0]):
        return Shorting(state=MISSING,
                        reason=f"{TABLE}가 없다 — 상위가 수집하지 않는다. 없는 층으로 흐른다")
    rows = len(conn.execute(Q_ANY_ROWS, (limit,)).fetchall())
    if rows == 0:
        return Shorting(state=EMPTY,
                        reason=f"{TABLE}는 있는데 0행이다 — 수집이 조용히 실패했다 (R6)")
    return Shorting(state=READY, rows=rows)


def read_all(
    conn: Queryable, tickers: Sequence[str], days: int = WINDOW_DAYS
) -> dict[str, Shorting]:
    """종목들의 최근 N거래일 공매도 (F32). **행이 없는 종목은 빠진다** — 0으로 만들지 않는다.

    Args:
        conn: DB 커넥션.
        tickers: 대상 종목.
        days: 종목당 거래일 수.

    Returns:
        `{ticker: Shorting(READY, days=…)}` — 날짜 오름차순.
    """
    if not tickers:
        return {}
    rows = conn.execute(Q_DAYS, (days, list(tickers))).fetchall()
    out: dict[str, list[ShortDay]] = {}
    for ticker, d, short_vol, buy_vol, ratio in rows:
        out.setdefault(str(ticker), []).append(
            ShortDay(d=d, short_vol=int(short_vol), buy_vol=int(buy_vol), ratio=float(ratio))
        )
    return {t: Shorting(state=READY, rows=len(v), days=tuple(v)) for t, v in out.items()}


def read_days(conn: Queryable, ticker: str, days: int = WINDOW_DAYS) -> tuple[ShortDay, ...]:
    """한 종목의 추이. `read_all`의 편의 꼴."""
    got: Any = read_all(conn, [ticker], days).get(ticker)
    return got.days if got else ()
