"""enrich — 수급·시세·시총을 **상위 DB에서 SQL로**. 새 API도 새 키도 없다.

지키는 것:
  · **`None`을 0으로 세지 않는다** — 그 투자자 표에 종목이 없던 날과 순매수 0원인 날은 다르다.
    `ksc_investor_flows.inst_net`은 실제로 `null`이 온다 (2026-09-05 실DB 확인)
  · **종목마다 마지막 N거래일을 따로 센다** — 날짜로 자르면 거래정지 종목의 창이 조용히 짧아진다
  · **행이 없는 종목은 빠진다** — 호출자가 「생략」으로 표기한다 (F34).
    빈 `InvestorFlows`를 만들어 넣으면 「수급이 0이었다」로 읽힌다
  · `ksc_bars`는 `timeframe='D'`로 거른다 — 주봉·월봉이 같은 표에 있다
  · **상위 테이블에 쓰지 않는다** — 이 모듈에 SELECT 아닌 문장이 없다
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from verify import enrich
from verify.models import InvestorFlows

T1, T2 = "005930", "000660"


class FakeConn:
    """`execute(sql, params)`만 흉내 낸다. 부른 SQL과 인자를 적어 둔다."""

    def __init__(self, *batches: list[tuple[Any, ...]]) -> None:
        self.batches = list(batches)
        self.sql: list[str] = []
        self.params: list[Any] = []

    def execute(self, query: Any, params: Any = None) -> FakeConn:
        self.sql.append(str(query))
        self.params.append(params)
        self._rows = self.batches.pop(0) if self.batches else []
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


D1, D2, D3 = date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3)


# ── 수급 30일 ─────────────────────────────────────────────────────


def test_flows_are_grouped_by_ticker_in_date_order() -> None:
    conn = FakeConn([
        (T1, D1, 100, 10, 5, -110),
        (T1, D2, 200, 20, 5, -220),
        (T2, D1, 300, 30, 0, -330),
    ])
    got = enrich.fetch_flows(conn, [T1, T2])
    assert set(got) == {T1, T2}
    assert [x.d for x in got[T1].days] == [D1, D2]
    assert got[T1].days[0].inst == 100
    assert got[T2].days[0].indiv == -330


def test_foreign_is_the_sum_of_both_foreign_columns() -> None:
    """상위는 `외국인`과 `기타외국인`을 따로 담는다 — 우리 모델은 합쳐서 하나로 본다."""
    conn = FakeConn([(T1, D1, 0, 30, 7, 0)])
    assert enrich.fetch_flows(conn, [T1])[T1].days[0].foreign == 37


def test_null_is_not_zero() -> None:
    """**이 파일에서 가장 중요한 줄.** 표에 없던 날과 0원인 날은 다르다."""
    conn = FakeConn([(T1, D1, None, None, None, None)])
    day = enrich.fetch_flows(conn, [T1])[T1].days[0]
    assert day.inst is None
    assert day.foreign is None
    assert day.indiv is None


def test_foreign_is_none_only_when_both_columns_are_null() -> None:
    """한쪽만 있으면 그 값이 답이다 — 없는 쪽을 0으로 세어 합치지 않는다."""
    assert enrich.fetch_flows(FakeConn([(T1, D1, 0, 30, None, 0)]), [T1])[T1].days[0].foreign == 30
    assert enrich.fetch_flows(FakeConn([(T1, D1, 0, None, 7, 0)]), [T1])[T1].days[0].foreign == 7
    both_null = enrich.fetch_flows(FakeConn([(T1, D1, 0, None, None, 0)]), [T1])
    assert both_null[T1].days[0].foreign is None


def test_a_ticker_with_no_rows_is_absent_not_empty() -> None:
    """빈 `InvestorFlows`를 채워 넣으면 「수급이 0이었다」로 읽힌다 (F34)."""
    got = enrich.fetch_flows(FakeConn([(T1, D1, 1, 1, 0, -2)]), [T1, T2])
    assert T2 not in got
    assert got[T1] != InvestorFlows()


def test_no_tickers_means_no_query() -> None:
    conn = FakeConn()
    assert enrich.fetch_flows(conn, []) == {}
    assert conn.sql == []


def test_window_counts_trading_days_per_ticker() -> None:
    """날짜로 자르면 거래정지 종목의 창이 조용히 짧아진다 — 종목별로 센다."""
    conn = FakeConn([])
    enrich.fetch_flows(conn, [T1], days=30)
    sql = conn.sql[0]
    assert "lateral" in sql.lower()
    assert conn.params[0][0] == 30


def test_flow_window_default_is_thirty() -> None:
    conn = FakeConn([])
    enrich.fetch_flows(conn, [T1])
    assert conn.params[0][0] == enrich.FLOW_WINDOW_DAYS == 30


# ── 시세·시총 ─────────────────────────────────────────────────────


def test_quote_reads_market_cap_and_recent_turnover() -> None:
    conn = FakeConn([(T1, "삼성전자", "KOSPI", 500_000_000, 5_000, D3, 70_000, 12_345, 5)])
    q = enrich.fetch_quotes(conn, [T1])[T1]
    assert q.name == "삼성전자"
    assert q.market == "KOSPI"
    assert q.mktcap == 500_000_000
    assert q.close == 70_000
    assert q.last_d == D3
    assert q.trdval == 12_345
    assert q.bar_days == 5


def test_quote_only_reads_daily_bars() -> None:
    """주봉·월봉이 같은 표에 있다 — 안 거르면 거래대금이 부풀고 종가가 엉킨다."""
    conn = FakeConn([])
    enrich.fetch_quotes(conn, [T1])
    assert "timeframe = 'D'" in conn.sql[0]


def test_quote_survives_a_ticker_with_no_bars() -> None:
    """신규 상장이나 오래 정지된 종목 — 시총만 있고 일봉이 없을 수 있다."""
    conn = FakeConn([(T1, "이름", "KOSDAQ", 1_000, 100, None, None, None, 0)])
    q = enrich.fetch_quotes(conn, [T1])[T1]
    assert q.close is None
    assert q.last_d is None
    assert q.trdval is None
    assert q.bar_days == 0


def test_quote_absent_ticker_is_absent() -> None:
    assert enrich.fetch_quotes(FakeConn([]), [T1]) == {}


def test_no_tickers_means_no_quote_query() -> None:
    conn = FakeConn()
    assert enrich.fetch_quotes(conn, []) == {}
    assert conn.sql == []


def test_company_names_come_from_the_same_read() -> None:
    """뉴스 검색어가 종목명이다 — 이름 때문에 조회를 한 번 더 하지 않는다."""
    conn = FakeConn([(T1, "삼성전자", "KOSPI", 1, 1, D3, 1, 1, 1)])
    assert enrich.fetch_quotes(conn, [T1])[T1].name == "삼성전자"


# ── SQL 문장 자체 — 가짜 커넥션은 문장을 무시한다 ─────────────────
#
# 위 테스트들은 **파이썬 매핑**을 본다. 문장이 틀려도 대역이 준비된 행을 돌려주므로
# 안 걸린다 (변이 검사로 확인, 2026-09-05). 그래서 문장 모양을 여기서 따로 잠근다.


def test_flows_are_ordered_oldest_first() -> None:
    """`InvestorFlows.recent(n)`이 뒤에서 자른다 — 내림차순이면 **가장 오래된 n일**을 준다."""
    assert "order by f.ticker, f.d\n" in enrich.Q_FLOWS
    assert "f.d desc" not in enrich.Q_FLOWS.split("join lateral")[0]


def test_quote_query_reads_the_company_name() -> None:
    """뉴스 검색어이자 제목 필터의 기준이다 — 없으면 그 종목의 뉴스 갈래가 통째로 빈다."""
    assert "t.name" in enrich.Q_QUOTES
    assert "t.market" in enrich.Q_QUOTES  # M4가 소속 시장 지수를 고를 때 쓴다


def test_quote_query_does_not_drop_tickers_without_a_market_cap() -> None:
    """선행은 `and t.mktcap is not null`로 걸렀다. 우리는 **이름 때문에** 안 거른다 —
    시총이 아직 없는 종목도 뉴스는 찾아야 한다."""
    assert "mktcap is not null" not in enrich.Q_QUOTES


def test_flow_window_is_per_ticker_not_by_calendar() -> None:
    assert "join lateral" in enrich.Q_FLOWS
    assert "current_date" not in enrich.Q_FLOWS


# ── 상위 테이블에 쓰지 않는다 ─────────────────────────────────────


def test_module_has_no_write_statements() -> None:
    """`ksa_*`·`ksc_*`·`ksb_*`는 남의 것이다 (CLAUDE.md)."""
    import pathlib

    src = pathlib.Path(enrich.__file__).read_text(encoding="utf-8").lower()
    for verb in ("insert into", "update ", "delete from", "drop ", "alter table", "truncate"):
        assert verb not in src, verb


def test_every_query_targets_only_upstream_reads() -> None:
    sql = " ".join(v for k, v in vars(enrich).items() if k.startswith("Q_") and isinstance(v, str))
    tables = set(re.findall(r"from\s+(\w+)|join\s+(\w+)", sql.lower()))
    names = {t for pair in tables for t in pair if t and t != "lateral"}
    assert names <= {"ksc_investor_flows", "ksc_tickers", "ksc_bars"}, names
