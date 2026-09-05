"""수급·시세·시총을 **상위 DB에서 SQL로** 읽는다 (F12·F17). I/O 층.

**호출 0회, 키 0개, 새 API 없음.** 상위 `krx-stock-charts`가 pykrx로 매일 채운 것을
읽기만 한다 — 「수집은 charts가, 판단은 하위가」 (SPEC §2-3 V12의 원칙).

`ksa_*`·`ksc_*`·`ksb_*`는 **남의 것이다.** 이 모듈에 SELECT 아닌 문장을 두지 않는다
(테스트가 소스를 훑어 확인한다).

두 가지를 조심한다.

**① `None`을 0으로 세지 않는다.** `ksc_investor_flows.inst_net`은 실제로 `null`이 온다
(2026-09-05 실DB 확인). 그 투자자 표에 종목이 없던 날과 순매수가 0원이던 날은 **다른 사실**이고,
0으로 채우면 판정이 「기관이 안 샀다」로 기운다.

**② 창은 종목마다 따로 센다.** 「최근 30거래일」을 날짜로 자르면 거래정지가 낀 종목의 창이
조용히 짧아진다. `lateral`로 종목별 마지막 N행을 고른다.

행이 없는 종목은 **결과에서 빠진다** — 빈 값을 만들어 넣으면 「수급이 0이었다」로 읽힌다.
호출자가 「생략」으로 표기한다 (F34).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from verify.models import FlowDay, InvestorFlows, Quote
from verify.store import Queryable

FLOW_WINDOW_DAYS = 30  # 판정이 보는 수급 창 (judge의 30일 누적)
QUOTE_BAR_DAYS = 5  # 거래대금을 합칠 최근 거래일 수

# 종목별 마지막 N거래일. **날짜로 자르지 않는다** — 거래정지가 낀 종목의 창이 짧아진다.
Q_FLOWS = """
select f.ticker, f.d, f.inst_net, f.foreign_net, f.foreign_etc_net, f.indiv_net
  from ksc_investor_flows f
  join lateral (
      select d from ksc_investor_flows
       where ticker = f.ticker
       order by d desc limit %s
  ) w on w.d = f.d
 where f.ticker = any(%s)
 order by f.ticker, f.d
"""

# 시총·상장주식수는 `ksc_tickers`, 최근 거래대금·종가는 `ksc_bars`.
# **`timeframe = 'D'`를 빼면 주봉·월봉이 섞여** 거래대금이 부풀고 종가가 엉킨다.
Q_QUOTES = """
select t.ticker, t.name, t.market, t.mktcap, t.list_shrs,
       x.last_d, x.close, x.trdval, coalesce(x.days, 0)
  from ksc_tickers t
  left join lateral (
      select max(b.d) as last_d,
             (array_agg(b.c order by b.d desc))[1] as close,
             sum(b.a) as trdval,
             count(*) as days
        from (select d, a, c from ksc_bars
               where ticker = t.ticker and timeframe = 'D'
               order by d desc limit %s) b
  ) x on true
 where t.ticker = any(%s)
"""


def _int_or_none(raw: Any) -> int | None:
    """DB 값 → int. **`None`은 `None`으로 남긴다.**"""
    return None if raw is None else int(raw)


def _foreign(main: Any, etc: Any) -> int | None:
    """외국인 + 기타외국인. **둘 다 `None`일 때만 `None`** — 한쪽만 있으면 그것이 답이다.

    없는 쪽을 0으로 세어 합치면 「기타외국인이 0원이었다」는 없는 사실이 섞인다.
    """
    got = [int(v) for v in (main, etc) if v is not None]
    return sum(got) if got else None


def fetch_flows(
    conn: Queryable, tickers: Sequence[str], days: int = FLOW_WINDOW_DAYS
) -> dict[str, InvestorFlows]:
    """기관·외국인·개인 순매수 최근 N거래일 (F17).

    Args:
        conn: DB 커넥션.
        tickers: 대상 종목.
        days: **종목당** 거래일 수.

    Returns:
        `{ticker: InvestorFlows}` — 날짜 오름차순. **행이 없는 종목은 빠진다.**
    """
    if not tickers:
        return {}
    rows = conn.execute(Q_FLOWS, (days, list(tickers))).fetchall()
    out: dict[str, list[FlowDay]] = {}
    for ticker, d, inst, foreign, foreign_etc, indiv in rows:
        out.setdefault(str(ticker), []).append(
            FlowDay(
                d=d,
                inst=_int_or_none(inst),
                foreign=_foreign(foreign, foreign_etc),
                indiv=_int_or_none(indiv),
            )
        )
    return {t: InvestorFlows(days=tuple(v)) for t, v in out.items()}


def fetch_quotes(
    conn: Queryable, tickers: Sequence[str], days: int = QUOTE_BAR_DAYS
) -> dict[str, Quote]:
    """시세·시총 참고, 그리고 **종목명**(뉴스 검색어) (F12).

    이름을 여기서 함께 읽는다 — 검색어 때문에 조회를 한 번 더 하지 않는다.

    Args:
        conn: DB 커넥션.
        tickers: 대상 종목.
        days: 거래대금을 합칠 최근 거래일 수.

    Returns:
        `{ticker: Quote}`. **일봉이 없는 종목도 담는다** — 시총과 이름은 있기 때문이다.
        없는 값은 `None`으로 둔다.
    """
    if not tickers:
        return {}
    rows = conn.execute(Q_QUOTES, (days, list(tickers))).fetchall()
    return {
        str(ticker): Quote(
            ticker=str(ticker),
            name=str(name or ""),
            market=str(market or ""),
            mktcap=_int_or_none(mktcap),
            list_shrs=_int_or_none(list_shrs),
            last_d=last_d,
            close=_int_or_none(close),
            trdval=_int_or_none(trdval),
            bar_days=int(bar_days or 0),
        )
        for ticker, name, market, mktcap, list_shrs, last_d, close, trdval, bar_days in rows
    }
