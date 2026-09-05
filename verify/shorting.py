"""공매도 갈래 (F32·F33). **지금은 「없는 층」 경로만** — M8 승인 전이다 (2026-09-05).

`ksc_shorting`이 아직 없다(실DB 확인). SPEC F32도 「상위가 수집하면 SQL로 읽는다」라
**스키마가 안 정해졌다.** 지금 파싱을 쓰면 상상한 열 이름에 맞추게 되고, 상위가 다른 이름으로
만들면 조용히 어긋난다. 그래서 여기서는 **상태 판별 하나**만 정한다.

## 그 판별이 곧 R6다

pykrx `get_shorting_balance_by_ticker`는 **예외를 던지지 않고 0행·빈 열**을 준다
(2026-08-31 · 09-01 재현). `try/except`로는 안 걸린다. 그러면 그 갈래가
**「정상적으로 비어 있는」 상태**로 지나가고, 아무도 자료가 없다는 것을 모른다.

그래서 겉보기에 같은 두 상태를 가른다.

| 상태 | 무슨 일인가 | 실패인가 |
|------|-------------|----------|
| `MISSING` | 표 자체가 없다 — 상위가 아직 수집 전이다 | **아니다.** 없는 층 (F34가 「생략」) |
| `EMPTY` | 표는 있는데 **0행** | **그렇다** (R6). 수집이 조용히 실패한 것이다 |
| `UNPARSED` | 표에 행이 있다 | **그렇다** — 읽을 코드가 아직 없다. 조용히 빈 결과를 주지 않는다 |

`UNPARSED`가 이 모듈의 알람이다. 상위가 채우기 시작하면 **여기가 소리를 낸다** —
그때 M8에서 파싱을 쓰면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from verify.store import Queryable

WINDOW_DAYS = 20  # F32 — 거래량·비중 추이 구간

TABLE = "ksc_shorting"

MISSING = "missing"  # 표가 없다 — 없는 층 (정상)
EMPTY = "empty"  # 표는 있는데 0행 — 실패 (R6)
UNPARSED = "unparsed"  # 행은 있는데 읽을 코드가 없다 — 실패

# 표가 실재하는지만 묻는다. **열 이름을 여기 적지 않는다** — 아직 정해지지 않았다.
Q_TABLE_EXISTS = "select to_regclass(%s) is not null"
Q_ANY_ROWS = f"select 1 from {TABLE} limit %s"


@dataclass(frozen=True, slots=True)
class Shorting:
    """공매도 갈래의 상태. **자료가 아니라 상태다** — 아직 읽지 않는다."""

    state: str
    reason: str = ""
    rows: int = 0
    days: tuple[Any, ...] = ()  # 20거래일 추이 — M8에서 채운다

    @property
    def ok(self) -> bool:
        """이 상태가 정상인가. **`MISSING`만 정상이다** — 나머지는 알려야 한다 (R6)."""
        return self.state == MISSING


def probe(conn: Queryable, *, limit: int = 1) -> Shorting:
    """공매도 갈래가 어떤 상태인지 본다. **자료를 읽지는 않는다.**

    Args:
        conn: DB 커넥션.
        limit: 행 존재 확인에 쓸 상한.

    Returns:
        `MISSING`(없는 층 · 정상) · `EMPTY`(0행 · 실패, R6) · `UNPARSED`(행 있음 · 실패).
    """
    exists = conn.execute(Q_TABLE_EXISTS, (TABLE,)).fetchone()
    if not (exists and exists[0]):
        return Shorting(
            state=MISSING,
            reason=f"{TABLE}가 없다 — 상위가 아직 수집하지 않는다 (M8 승인 전). 없는 층으로 흐른다",
        )
    rows = len(conn.execute(Q_ANY_ROWS, (limit,)).fetchall())
    if rows == 0:
        return Shorting(
            state=EMPTY,
            reason=f"{TABLE}는 있는데 0행이다 — 수집이 조용히 실패했다 (R6). 「없음」이 아니다",
        )
    return Shorting(
        state=UNPARSED,
        rows=rows,
        reason=f"{TABLE}에 자료가 들어오기 시작했다 — 읽는 코드는 M8에서 쓴다",
    )


def read_days(conn: Queryable, ticker: str, days: int = WINDOW_DAYS) -> tuple[Any, ...]:
    """20거래일 공매도 거래량·비중 추이 (F32). **아직 없다.**

    Raises:
        NotImplementedError: 늘 — `ksc_shorting` 스키마가 정해지지 않았다 (2026-09-05).
            추측한 열 이름으로 짜면 상위가 다른 이름을 쓸 때 조용히 어긋난다.
    """
    raise NotImplementedError(
        f"{TABLE} 스키마가 아직 없다 — 파싱은 M8(상위 공매도 수집 승인) 뒤에 쓴다"
    )
