"""ksv_verdicts 저장·복원 (F20·M3). **왕복이 이 파일의 요점이다.**

선행에서 **되살리는 열이 저장하는 열보다 적어 재실행이 15종목을 지웠다.** 재실행은
「읽어서 → 합쳐서 → 다시 쓴다」인데, 읽을 때 빠진 열은 쓸 때 기본값으로 덮인다.

그리고 선행은 **44행을 한 문장으로 upsert했다가 `57014 statement timeout`으로 하루치를
통째로 잃었다** (2026-08-31). 나눠 보낸다.

지키는 것:
  · **쓰는 열과 읽는 열이 같다** — 한 곳(`VERDICT_COLUMNS`)에서 나오고 테스트가 대조한다
  · `to_row()` → `from_row()` 왕복에서 **아무것도 잃지 않는다**
  · 청크로 나눠 보내고, **한 청크가 실패해도 어디까지 갔는지 안다**
  · `rules_version`을 **반드시 적는다** — 가중치를 고치면 과거 판정과 자가 달라진다 (F26)
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from verify import store, verdict
from verify.models import SignalRow, Verdict, VerdictPart

D = date(2026, 9, 5)


def signal(ticker: str = "005930", name: str = "삼성전자", strategy: str = "vcp") -> SignalRow:
    return SignalRow(d=D, ticker=ticker, name=name, strategy=strategy, evidence={})


def a_verdict(**over: Any) -> Verdict:
    base: dict[str, Any] = {
        "stand": "불일치",
        "score": 20,
        "parts": (VerdictPart("🔴 1건", -8), VerdictPart("오버행 18.6%", -19)),
        "blind_spots": ("재무", "공매도", "업황"),
        "rules_version": verdict.RULES_VERSION,
    }
    base.update(over)
    return Verdict(**base)


class FakeConn:
    """`execute` 호출을 적어 둔다. 청크 경계와 문장을 본다."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None,
                 boom_on: int | None = None) -> None:
        self.rows = rows or []
        self.boom_on = boom_on
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: Any, params: Any = None) -> FakeConn:
        self.calls.append((str(query), params))
        if self.boom_on is not None and len(self.calls) == self.boom_on:
            raise RuntimeError("57014 statement timeout")
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


# ── ★ 쓰는 열 = 읽는 열 ───────────────────────────────────────────


def test_one_column_list_feeds_both_directions() -> None:
    """두 곳에 적으면 갈라진다 — 그리고 갈라진 쪽이 조용히 지운다."""
    row = store.to_row(signal(), a_verdict(), store.SOURCE_BATCH)
    assert tuple(row) == store.VERDICT_COLUMNS


def test_the_select_reads_every_column_it_writes() -> None:
    """**선행이 여기서 15종목을 잃었다.** 읽는 열이 적으면 재실행이 기본값으로 덮는다."""
    selected = store.Q_VERDICTS.split("select", 1)[1].split("from", 1)[0]
    read = {c.strip() for c in selected.split(",")}
    assert set(store.VERDICT_COLUMNS) <= read, set(store.VERDICT_COLUMNS) - read


def test_schema_has_no_column_we_forget_to_write() -> None:
    """스키마에 열을 늘리고 `to_row`를 안 고치면 그 열은 늘 기본값이 된다."""
    import pathlib
    import re

    sql = pathlib.Path("supabase/schema.sql").read_text(encoding="utf-8")
    body = sql.split("create table if not exists ksv_verdicts (", 1)[1].split(");", 1)[0]
    skip = ("constraint", "primary key", "--")
    cols = {
        m.group(1) for line in body.splitlines()
        if (m := re.match(r"\s{2}(\w+)\s+\w", line))
        and not line.strip().startswith(skip)
    }
    generated = {"created_at"}  # DB가 채운다
    assert cols - generated == set(store.VERDICT_COLUMNS)


# ── ★ 왕복 ────────────────────────────────────────────────────────


def test_round_trip_loses_nothing() -> None:
    v = a_verdict()
    sig = signal()
    row = store.to_row(sig, v, store.SOURCE_BATCH)
    back_t, back_v, back_meta = store.from_row(tuple(row[c] for c in store.VERDICT_COLUMNS))
    assert back_t == sig.ticker
    assert back_v == v
    assert back_meta == {"d": D, "ticker": sig.ticker, "source": store.SOURCE_BATCH,
                         "name": sig.name, "strategy": sig.strategy}


def test_round_trip_keeps_parts_in_order() -> None:
    """`parts`는 「무엇 때문에 얼마가」다 — 순서가 바뀌면 설명이 달라진다."""
    v = a_verdict(parts=(VerdictPart("가", -1), VerdictPart("나", -2), VerdictPart("다", 3)))
    _, back, _ = store.from_row(tuple(store.to_row(signal(), v, "batch")[c]
                                      for c in store.VERDICT_COLUMNS))
    assert back.parts == v.parts


def test_round_trip_keeps_empty_collections_empty() -> None:
    """빈 튜플이 `None`으로 돌아오면 다음 저장이 not-null 제약에 걸린다."""
    v = a_verdict(parts=(), blind_spots=())
    _, back, _ = store.from_row(tuple(store.to_row(signal(), v, "batch")[c]
                                      for c in store.VERDICT_COLUMNS))
    assert back.parts == ()
    assert back.blind_spots == ()


def test_round_trip_keeps_a_letter_ticker() -> None:
    """`0126Z0`(삼성에피스홀딩스) — 티커는 숫자가 아니다."""
    _, _, meta = store.from_row(tuple(store.to_row(signal("0126Z0"), a_verdict(), "batch")[c]
                                      for c in store.VERDICT_COLUMNS))
    assert meta["d"] == D


def test_fetch_verdicts_rebuilds_from_the_database(  ) -> None:
    row = store.to_row(signal(), a_verdict(), store.SOURCE_BATCH)
    conn = FakeConn([tuple(row[c] for c in store.VERDICT_COLUMNS)])
    got = store.fetch_verdicts(conn, D)
    assert set(got) == {"005930"}
    assert got["005930"] == a_verdict()


def test_fetch_filters_by_date_and_source() -> None:
    conn = FakeConn([])
    store.fetch_verdicts(conn, D, source=store.SOURCE_ONDEMAND)
    assert conn.calls[0][1] == (D, store.SOURCE_ONDEMAND)


# ── rules_version (F26) ───────────────────────────────────────────


def test_rules_version_is_always_written() -> None:
    """가중치를 고치면 이 값이 올라가고 **과거 판정은 그때의 산식으로 남는다** (F26·V5)."""
    row = store.to_row(signal(), a_verdict(), "batch")
    assert row["rules_version"] == verdict.RULES_VERSION
    assert row["rules_version"]  # not null이다


def test_an_unstamped_verdict_is_refused() -> None:
    """빈 `rules_version`으로 저장하면 서로 다른 자로 잰 값이 한 표에 섞인다."""
    with pytest.raises(ValueError, match="rules_version"):
        store.to_row(signal(), a_verdict(rules_version=""), "batch")


def test_judge_stamps_the_version() -> None:
    from verify.models import VerdictInput

    assert verdict.judge(VerdictInput()).rules_version == verdict.RULES_VERSION


def test_the_version_looks_like_a_version() -> None:
    import re

    assert re.fullmatch(r"\d+\.\d+", verdict.RULES_VERSION), verdict.RULES_VERSION


# ── ★ 청크 ────────────────────────────────────────────────────────


def test_rows_are_sent_in_chunks() -> None:
    """선행은 44행을 한 문장으로 보냈다가 `57014`로 **하루치를 통째로** 잃었다."""
    sigs = [signal(f"{i:06d}") for i in range(44)]
    conn = FakeConn()
    n = store.save_verdicts(D, {s.ticker: a_verdict() for s in sigs},
                            store.SOURCE_BATCH, signals=sigs, conn=conn)
    assert n == 44
    assert len(conn.calls) == 3  # 20 · 20 · 4
    assert store.CHUNK_ROWS == 20


def test_a_single_chunk_is_one_statement() -> None:
    conn = FakeConn()
    store.save_verdicts(D, {"005930": a_verdict()}, "batch", signals=[signal()], conn=conn)
    assert len(conn.calls) == 1


def test_nothing_to_save_sends_nothing() -> None:
    conn = FakeConn()
    assert store.save_verdicts(D, {}, "batch", signals=[], conn=conn) == 0
    assert conn.calls == []


def test_a_failed_chunk_says_how_far_it_got() -> None:
    """하루치를 통째로 잃는 것과 절반을 잃는 것은 다르다 — 어디까지 갔는지 알아야 한다."""
    sigs = [signal(f"{i:06d}") for i in range(44)]
    conn = FakeConn(boom_on=2)
    with pytest.raises(RuntimeError, match="20행까지"):
        store.save_verdicts(D, {s.ticker: a_verdict() for s in sigs},
                            store.SOURCE_BATCH, signals=sigs, conn=conn)


def test_the_statement_upserts_on_the_primary_key() -> None:
    """재실행이 두 번째 행을 만들면 안 된다 — PK는 `(d, ticker, source)`다."""
    conn = FakeConn()
    store.save_verdicts(D, {"005930": a_verdict()}, "batch", signals=[signal()], conn=conn)
    sql = conn.calls[0][0].lower()
    assert "on conflict (d, ticker, source)" in sql
    assert "do update" in sql


def test_the_update_list_covers_every_non_key_column() -> None:
    """**왕복 사고와 같은 계열이다.** 갱신 목록에서 열이 빠지면 **재실행이 그 열을 안 고친다** —
    산식을 바꾸고 다시 돌렸는데 점수가 어제 것 그대로인 식이다. 조용하다.
    """
    conn = FakeConn()
    store.save_verdicts(D, {"005930": a_verdict()}, "batch", signals=[signal()], conn=conn)
    sql = conn.calls[0][0]
    keys = ("d", "ticker", "source")
    for col in store.VERDICT_COLUMNS:
        if col in keys:
            continue
        assert f"{col} = excluded.{col}" in sql, col


def test_the_select_is_filtered_by_day_and_source() -> None:
    """가짜 커넥션은 문장을 무시한다 — `where`가 사라져도 준비된 행이 온다.

    필터가 빠지면 **3년치를 통째로 읽어** 어제 판정으로 오늘을 덮는다.
    """
    where = store.Q_VERDICTS.lower().split("where", 1)[1].split("order by", 1)[0]
    assert "d = %s" in where
    assert "source = %s" in where
    assert " or " not in where  # `1=1 or …` 로 무력화되지 않는다


def test_a_rerun_overwrites_rather_than_appends() -> None:
    """같은 (d, ticker, source)를 두 번 저장해도 행이 늘면 안 된다."""
    sql = store._insert_sql(1).lower()
    assert sql.count("on conflict") == 1
    assert "do nothing" not in sql  # 덮지 않으면 재판정이 반영되지 않는다


def test_a_verdict_without_its_signal_still_saves() -> None:
    """이름을 못 얻었다고 판정을 버리지 않는다 — 이름은 빈 문자열이 된다."""
    conn = FakeConn()
    n = store.save_verdicts(D, {"005930": a_verdict()}, "batch", signals=[], conn=conn)
    assert n == 1


def test_batch_and_ondemand_do_not_overwrite_each_other() -> None:
    """PK에 `source`가 있다 — 궁금해서 넣은 종목이 그날 배치 판정을 덮으면 안 된다 (F43)."""
    assert "source" in store.VERDICT_COLUMNS
    a = store.to_row(signal(), a_verdict(), store.SOURCE_BATCH)
    b = store.to_row(signal(), a_verdict(), store.SOURCE_ONDEMAND)
    assert (a["d"], a["ticker"]) == (b["d"], b["ticker"])
    assert a["source"] != b["source"]


# ── 커밋 — 실행에서만 드러난 함정 ─────────────────────────────────


def test_an_owned_connection_is_committed(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ psycopg는 **기본이 비-autocommit**이다. 커밋 없이 커넥션이 사라지면
    **예외도 없이 롤백**된다 — 저장한 줄 알았는데 0행이다 (2026-09-05 실행에서 잡혔다).

    `with connect() as c:` 의 `__exit__`가 커밋한다. 그 `with`를 빼면 여기가 깨진다.
    """
    events: list[str] = []

    class Owned:
        def __enter__(self) -> Owned:
            events.append("enter")
            return self

        def __exit__(self, *exc: object) -> None:
            events.append("exit")  # 여기서 커밋된다

        def execute(self, query: Any, params: Any = None) -> Owned:
            events.append("execute")
            return self

    monkeypatch.setattr(store, "connect", Owned)
    n = store.save_verdicts(D, {"005930": a_verdict()}, "batch", signals=[signal()])
    assert n == 1
    assert events == ["enter", "execute", "exit"]


def test_a_borrowed_connection_is_not_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """대역·호출자 커넥션은 **주인이 따로 있다** — 여기서 닫거나 커밋하지 않는다."""
    conn = FakeConn()
    store.save_verdicts(D, {"005930": a_verdict()}, "batch", signals=[signal()], conn=conn)
    assert not hasattr(conn, "committed")
