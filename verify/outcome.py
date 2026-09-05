"""판정 뒤 5·20·60거래일 수익률과 같은 구간 지수 수익률 (F22·F23·F23b). **순수 함수.**

**되돌아보는 배치이지 예측하는 배치가 아니다.** 미도래 구간은 `None`으로 두고 매일 채운다.
0으로 채우면 「수익률 0%」가 되어 분포가 오염된다.

## 거래정지일을 관측에서 뺀다

이 DB에서 정지는 **`v=0` · `O=H=L=C`(가격 동결)**로 남는다 — 전 일봉의 **2.36%**
(45,818행, 2026-09-05 실측). TASKS가 적은 `O/H/L=0` 모양은 **아예 들어오지 않는다**:
상위 스키마의 `check (o > 0 and h > 0 ...)`가 그런 행을 거부하기 때문이다.

안 거르면 「수익률 0%」가 「거래가 없었다」를 덮는다. 상위에서 이걸 놓쳐 VCP 판정이
545→176건으로 정상화된 전력이 있다.

**구간의 양 끝이 거래일이어야 한다.** 끝이 정지면 종가가 어제 것 그대로라 가짜 수익률이 된다.
가운데 정지는 문제가 아니다 — 가격은 실제로 A에서 B로 움직였다.

## 달력은 지수에서 온다

종목마다 정지가 달라 **종목 달력으로 세면 종목마다 「5거래일 뒤」가 다른 날이 된다.**
시장이 실제로 열린 날(`ksc_index_bars`)을 세야 모두에게 같은 뜻이 된다.
그러면 종목과 지수가 **같은 날짜**를 보게 되고, 초과수익이 실재하는 값이 된다.

## 지수가 없으면 채우지 않는다 (F23b)

프록시로 대신 재지 않는다. 종목 수익률만 남기고 지수·초과는 `None`으로 둔다.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from verify.models import HORIZONS as HORIZONS  # 도메인 것을 그대로 — 두 곳에 적으면 갈라진다
from verify.models import Outcome


@dataclass(frozen=True, slots=True)
class DayBar:
    """하루치 종가. `ksc_bars`·`ksc_index_bars` 한 행에서 필요한 것만."""

    d: date
    close: float | None
    volume: int = 0


def tradable(bar: DayBar) -> bool:
    """그날 실제로 거래됐는가. **거래량 0이면 정지다** (이 DB의 정지 모양)."""
    return bar.volume > 0 and bar.close is not None


def nth_trading_day(calendar: Sequence[date], base: date, n: int) -> date | None:
    """시장 달력에서 `base`로부터 `n`번째 거래일. 아직 안 왔으면 `None`.

    Args:
        calendar: 오름차순 거래일. 지수에서 온다 — 종목 달력을 쓰면 종목마다 달라진다.
        base: 판정일.
        n: 거래일 수.

    Returns:
        그날. `base`가 달력에 없거나 `n`번째가 아직 없으면 `None` —
        **0으로 채우지 않는다** (F22).
    """
    i = bisect_left(list(calendar), base)
    if i >= len(calendar) or calendar[i] != base or i + n >= len(calendar):
        return None
    return calendar[i + n]


def pct(now: float | None, then: float | None) -> float | None:
    """수익률(%). 기준이 없거나 0이면 `None` — 없는 숫자를 만들지 않는다."""
    if now is None or then is None or then == 0:
        return None
    return (now - then) / then * 100


def _closes(bars: Sequence[DayBar]) -> dict[date, DayBar]:
    return {b.d: b for b in bars}


def measure(
    d: date,
    ticker: str,
    market: str,
    stock: Sequence[DayBar],
    index: Sequence[DayBar],
    horizons: Sequence[int] = HORIZONS,
) -> Outcome:
    """판정일 기준 관측 구간을 잰다 (F22·F23·F23b).

    Args:
        d: 판정일.
        ticker: 종목.
        market: 소속 시장 — 어느 지수와 견줄지 부르는 쪽이 이미 골랐다 (F23).
        stock: 종목 일봉 (판정일 이후, 오름차순).
        index: 소속 시장 지수 일봉 — **달력의 출처이기도 하다.**
        horizons: 관측 구간. 기본은 5·20·60거래일.

    Returns:
        `Outcome`. **도래하지 않았거나 잴 수 없는 구간은 `None`이다.**
    """
    cal = [b.d for b in index]
    sb, ib = _closes(stock), _closes(index)
    base, base_index = sb.get(d), ib.get(d)
    values: dict[str, float | None] = {}
    for want, name in zip(horizons, HORIZONS, strict=True):
        target = nth_trading_day(cal, d, want)
        stock_r, index_r = None, None
        if target is not None and base is not None and tradable(base):
            end = sb.get(target)
            if end is not None and tradable(end):
                stock_r = pct(end.close, base.close)
            index_end = ib.get(target)
            if index_end is not None and base_index is not None:
                index_r = pct(index_end.close, base_index.close)
        values[f"h{name}"] = stock_r
        values[f"h{name}_index"] = index_r
    return Outcome(d=d, ticker=ticker, **values)
