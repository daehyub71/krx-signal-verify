"""outcome — 판정 뒤 5·20·60거래일 수익률과 같은 구간 지수 수익률 (F22·F23·F23b). 순수 함수.

**되돌아보는 배치이지 예측하는 배치가 아니다.** 미도래 구간은 `null`로 두고 매일 채운다.

지키는 것:
  · **거래정지일을 관측에서 뺀다** — 이 DB에서 정지는 `v=0` · `O=H=L=C`(가격 동결)로 남는다.
    전 일봉의 **2.36%**(45,818행, 2026-09-05 실측). 상위 스키마가 0가격을 거부해
    TASKS가 적은 `O/H/L=0` 모양은 **아예 들어오지 않는다.**
    안 거르면 「수익률 0%」가 「거래가 없었다」를 덮어 분포가 0쪽으로 쏠린다
  · **구간의 양 끝이 거래일이어야 한다** — 끝이 정지면 종가가 어제 것 그대로라 가짜 수익률이 된다
  · **종목과 지수가 같은 날짜를 본다** — 한쪽만 날짜를 옮기면 초과수익이 실재하지 않는 값이 된다
  · **지수가 없으면 채우지 않는다** (F23b) — 프록시로 대신 재지 않는다
"""

from __future__ import annotations

from datetime import date

import pytest

from verify import outcome
from verify.models import Outcome

D = date(2026, 9, 1)


def day(n: int) -> date:
    return date(2026, 9, n)


def bar(d: date, close: float, volume: int = 1000) -> outcome.DayBar:
    return outcome.DayBar(d=d, close=close, volume=volume)


def halted(d: date, close: float) -> outcome.DayBar:
    """거래정지일 — 거래량 0, 가격 동결."""
    return outcome.DayBar(d=d, close=close, volume=0)


# ── 거래정지일 ────────────────────────────────────────────────────


def test_a_halted_bar_is_not_tradable() -> None:
    assert outcome.tradable(bar(D, 100)) is True
    assert outcome.tradable(halted(D, 100)) is False


def test_zero_volume_is_the_marker_in_this_database() -> None:
    """상위 스키마가 `o > 0`을 강제해 **0가격 행은 저장되지 않는다** (2026-09-05 실측).

    그래서 정지는 「거래량 0 + 가격 동결」로만 나타난다.
    """
    assert outcome.tradable(outcome.DayBar(d=D, close=486.0, volume=0)) is False


def test_halted_days_do_not_count_toward_the_horizon() -> None:
    """정지일을 세면 5거래일이 실제로는 3거래일이 된다."""
    cal = [day(1), day(2), day(3), day(4), day(7), day(8)]
    assert outcome.nth_trading_day(cal, day(1), 3) == day(4)
    assert outcome.nth_trading_day(cal, day(1), 5) == day(8)


def test_a_horizon_beyond_the_calendar_is_none() -> None:
    """**아직 오지 않은 날이다** — 0으로 채우면 「수익률 0%」가 된다 (F22)."""
    cal = [day(1), day(2), day(3)]
    assert outcome.nth_trading_day(cal, day(1), 5) is None


def test_the_base_day_must_be_in_the_calendar() -> None:
    assert outcome.nth_trading_day([day(2), day(3)], day(1), 1) is None


# ── 수익률 ────────────────────────────────────────────────────────


def test_return_is_a_percentage() -> None:
    assert outcome.pct(110.0, 100.0) == pytest.approx(10.0)
    assert outcome.pct(90.0, 100.0) == pytest.approx(-10.0)


def test_a_zero_base_gives_no_return() -> None:
    """0으로 나누지 않는다 — 없는 숫자를 만들지 않는다."""
    assert outcome.pct(100.0, 0.0) is None
    assert outcome.pct(100.0, None) is None
    assert outcome.pct(None, 100.0) is None


# ── 측정 ──────────────────────────────────────────────────────────


def series(*pairs: tuple[int, float]) -> list[outcome.DayBar]:
    return [bar(day(n), c) for n, c in pairs]


def test_measure_fills_the_horizons_that_arrived() -> None:
    """도래한 구간만 채우고 **나머지는 `None`으로 남긴다.**

    `horizons=(1, 3, 5)`는 세 칸(`h5`·`h20`·`h60`)에 1·3·5거래일을 담는다는 뜻이다 —
    시험을 짧은 표본으로 하기 위한 것이고, 실제 기본값은 5·20·60이다.
    나흘치 자료면 1일·3일은 도래하고 5일은 아직이다.
    """
    stock = series((1, 100.0), (2, 102.0), (3, 105.0), (4, 108.0))
    index = series((1, 1000.0), (2, 1010.0), (3, 1020.0), (4, 1030.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(1, 3, 5))
    assert isinstance(got, Outcome)
    assert got.h5 == pytest.approx(2.0)  # 1거래일 뒤
    assert got.h20 == pytest.approx(8.0)  # 3거래일 뒤
    assert got.h60 is None  # 아직 안 왔다 — **0이 아니다**
    assert got.h60_index is None


def test_the_stock_and_the_index_use_the_same_days() -> None:
    """한쪽만 날짜를 옮기면 초과수익이 실재하지 않는 값이 된다."""
    stock = series((1, 100.0), (2, 100.0), (3, 110.0))
    index = series((1, 1000.0), (2, 1000.0), (3, 1050.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(2, 20, 60))
    assert got.h5 == pytest.approx(10.0)
    assert got.h5_index == pytest.approx(5.0)
    assert got.excess(5) == pytest.approx(5.0)


def test_a_halted_endpoint_is_not_measured() -> None:
    """끝이 정지면 종가가 어제 것 그대로다 — **가짜 수익률**이다."""
    stock = [bar(day(1), 100.0), bar(day(2), 102.0), halted(day(3), 102.0)]
    index = series((1, 1000.0), (2, 1010.0), (3, 1020.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(2, 20, 60))
    assert got.h5 is None


def test_a_halted_base_is_not_measured() -> None:
    stock = [halted(day(1), 100.0), bar(day(2), 110.0)]
    index = series((1, 1000.0), (2, 1010.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(1, 20, 60))
    assert got.h5 is None


def test_a_halt_inside_the_window_is_fine() -> None:
    """양 끝이 거래일이면 가운데 정지는 문제가 아니다 — 가격은 실제로 A→B로 움직였다."""
    stock = [bar(day(1), 100.0), halted(day(2), 100.0), bar(day(3), 110.0)]
    index = series((1, 1000.0), (2, 1000.0), (3, 1010.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(2, 20, 60))
    assert got.h5 == pytest.approx(10.0)


def test_the_calendar_comes_from_the_index_not_the_stock() -> None:
    """종목마다 정지가 달라 **종목 달력으로 세면 종목마다 구간이 달라진다.**

    시장이 실제로 열린 날을 세야 「5거래일 뒤」가 모두에게 같은 뜻이 된다.
    """
    stock = [bar(day(1), 100.0), bar(day(4), 110.0)]  # 2·3일 자료가 아예 없다
    index = series((1, 1000.0), (2, 1000.0), (3, 1000.0), (4, 1010.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(3, 20, 60))
    assert got.h5 == pytest.approx(10.0)  # 시장 달력으로 3거래일 뒤 = 09-04


# ── F23b — 지수가 없으면 채우지 않는다 ────────────────────────────


def test_no_index_means_no_excess(  ) -> None:
    """**프록시로 대신 재지 않는다** (F23b). 종목 수익률은 있어도 초과수익은 `None`."""
    stock = series((1, 100.0), (2, 110.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, [], horizons=(1, 20, 60))
    assert got.h5 is None  # 달력이 없으면 구간도 못 센다
    assert got.excess(5) is None


def test_a_missing_index_day_leaves_the_index_return_empty() -> None:
    """달력은 있는데 그날 지수 값이 없는 경우 — 종목만 채우고 초과는 비운다."""
    stock = series((1, 100.0), (2, 110.0))
    index = [bar(day(1), 1000.0), outcome.DayBar(d=day(2), close=None, volume=1)]
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(1, 20, 60))
    assert got.h5 == pytest.approx(10.0)
    assert got.h5_index is None
    assert got.excess(5) is None


def test_the_outcome_has_no_baseline_column() -> None:
    """기준선이 **하나뿐이라** 기록할 것이 없다 (V12). 열을 두면 다른 기준선을 부른다."""
    assert "baseline" not in Outcome.__dataclass_fields__


# ── 되돌아보는 배치다 ─────────────────────────────────────────────


def test_nothing_is_ever_extrapolated() -> None:
    """미도래는 `None`이고, 그 자리를 마지막 값으로 채우지 않는다."""
    stock = series((1, 100.0), (2, 102.0))
    index = series((1, 1000.0), (2, 1010.0))
    got = outcome.measure(D, "005930", "KOSPI", stock, index, horizons=(1, 20, 60))
    assert got.h20 is None and got.h60 is None
    assert got.h20_index is None and got.h60_index is None


def test_the_ticker_and_market_travel_with_it() -> None:
    got = outcome.measure(D, "0126Z0", "KOSDAQ", [], [], horizons=(5, 20, 60))
    assert got.ticker == "0126Z0"
    assert got.d == D


def test_horizons_default_to_five_twenty_sixty() -> None:
    from verify.models import HORIZONS

    assert outcome.HORIZONS == HORIZONS == (5, 20, 60)
