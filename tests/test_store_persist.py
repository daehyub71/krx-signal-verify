"""증거·서술·실행기록·요청 상태 저장 (M7 선행). **웹이 읽을 표를 배치가 실제로 채운다.**

M3~M6 동안 `ksv_evidence`·`ksv_runs`는 스키마만 있고 **아무도 쓰지 않았다**
(2026-09-06 확인: 둘 다 0행).
LLM 서술도 메일에만 실리고 사라졌다. 종목 화면(F52)은 이 셋 없이는 빈 화면이다.

지키는 것:
  · 증거 행의 **쓰는 열이 한 곳(`EVIDENCE_COLUMNS`)에서 나온다**
  · dataclass·date·tuple이 **JSON으로 내려간다** — `json.dumps`가 터지면 한 종목의 증거가 통째로
    빠진다
  · upsert — 재실행이 행을 늘리지 않는다
  · 직접 연 커넥션은 `with`로 닫는다 — 커밋 없는 커넥션은 **예외도 없이 롤백된다** (2026-09-05)
  · 요청 상태는 `running`·`done`·`failed`만 — `queued`로 되돌리는 길을 코드가 열지 않는다
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import pytest

from verify import store
from verify.models import Disclosure, Evidence, FlowDay, InvestorFlows, NewsItem, RunRecord

D = date(2026, 9, 5)


class FakeConn:
    def __init__(self, boom_on: int | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.boom_on = boom_on
        self.exited = False

    def execute(self, query: Any, params: Any = None) -> FakeConn:
        self.calls.append((" ".join(str(query).split()), params))
        if self.boom_on is not None and len(self.calls) == self.boom_on:
            raise RuntimeError("57014 statement timeout")
        return self

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.exited = True


def evidence(ticker: str = "005930") -> Evidence:
    return Evidence(
        d=D, ticker=ticker,
        disclosures=(Disclosure(D, "전환사채권발행결정", "20260905000001", flr_nm="삼성전자"),),
        news=(NewsItem(title="제목", link="https://n.news.naver.com/x", published=D,
                       source="매체"),),
        flows=InvestorFlows(days=(FlowDay(d=D, inst=-100, foreign=200, indiv=-100),)),
        financial=None, shorting=None,
    )


# ── JSON으로 내려간다 ─────────────────────────────────────────────


def test_jsonable_turns_dataclasses_dates_and_tuples_into_plain_json() -> None:
    got = store.jsonable(evidence())
    text = json.dumps(got, ensure_ascii=False)  # 터지지 않는 것이 요점
    assert '"rcept_no": "20260905000001"' in text
    assert '"d": "2026-09-05"' in text
    assert isinstance(got["disclosures"], list)


def test_jsonable_keeps_scalars_and_none() -> None:
    assert store.jsonable(None) is None
    assert store.jsonable(3) == 3
    assert store.jsonable("x") == "x"
    assert store.jsonable(datetime(2026, 9, 5, 1, 2)) == "2026-09-05T01:02:00"


def test_jsonable_falls_back_to_str_for_unknown_objects() -> None:
    class Odd:
        def __str__(self) -> str:
            return "odd"

    assert store.jsonable(Odd()) == "odd"


# ── 증거 행 ───────────────────────────────────────────────────────


def test_evidence_row_keys_are_the_column_list() -> None:
    assert tuple(store.evidence_row(evidence())) == store.EVIDENCE_COLUMNS


def test_evidence_row_records_missing_lanes_and_null_for_absent() -> None:
    row = store.evidence_row(evidence())
    assert row["financial"] is None and row["shorting"] is None
    assert row["missing"] == ["재무", "공매도"]
    assert json.loads(row["disclosures"])[0]["report_nm"] == "전환사채권발행결정"


def test_save_evidence_upserts_on_d_ticker() -> None:
    conn = FakeConn()
    assert store.save_evidence([evidence(), evidence("000660")], conn=conn) == 2
    sql, params = conn.calls[0]
    assert sql.startswith("insert into ksv_evidence")
    assert "on conflict (d, ticker) do update set" in sql
    assert len(params) == 2 * len(store.EVIDENCE_COLUMNS)


def test_save_evidence_chunks_and_reports_progress() -> None:
    rows = [evidence(f"{i:06d}") for i in range(store.CHUNK_ROWS + 1)]
    conn = FakeConn(boom_on=2)
    with pytest.raises(RuntimeError, match=f"{store.CHUNK_ROWS}행까지"):
        store.save_evidence(rows, conn=conn)


def test_save_evidence_with_nothing_sends_nothing() -> None:
    conn = FakeConn()
    assert store.save_evidence([], conn=conn) == 0
    assert conn.calls == []


def test_save_evidence_opens_and_closes_its_own_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    own = FakeConn()
    monkeypatch.setattr(store, "connect", lambda: own)
    assert store.save_evidence([evidence()]) == 1
    assert own.exited, "with connect()로 열지 않았다 — 커밋 없이 롤백된다"


# ── 서술 ─────────────────────────────────────────────────────────


def test_save_summaries_updates_each_verdict_row() -> None:
    conn = FakeConn()
    n = store.save_summaries(D, {"005930": "설명 하나", "000660": "설명 둘"},
                             store.SOURCE_BATCH, conn=conn)
    assert n == 2
    sql, params = conn.calls[0]
    assert sql == ("update ksv_verdicts set summary = %s "
                   "where d = %s and ticker = %s and source = %s")
    assert params == ("설명 하나", D, "005930", "batch")


def test_save_summaries_with_nothing_sends_nothing() -> None:
    conn = FakeConn()
    assert store.save_summaries(D, {}, store.SOURCE_BATCH, conn=conn) == 0
    assert conn.calls == []


# ── 실행 기록 ─────────────────────────────────────────────────────


def test_save_run_inserts_the_record_without_run_at() -> None:
    """`run_at`은 DB 기본값(now())에 맡긴다 — 두 번 돈 날도 PK가 안 겹친다."""
    conn = FakeConn()
    run = RunRecord(run_at=D, status="ok", gate="ready", signals=15, verdicts=15,
                    outcomes_filled=3, detail={"errors": ["x"]})
    assert store.save_run(run, conn=conn) == 1
    sql, params = conn.calls[0]
    assert sql.startswith("insert into ksv_runs (run_date, status, gate, signals, verdicts, "
                          "outcomes_filled, detail)")
    assert "run_at" not in sql
    assert params[:6] == (D, "ok", "ready", 15, 15, 3)
    assert json.loads(params[6]) == {"errors": ["x"]}


# ── 요청 상태 ─────────────────────────────────────────────────────


def test_mark_request_updates_status_result_and_detail() -> None:
    conn = FakeConn()
    store.mark_request(7, "done", result_d=D, detail={"stand": "정합"}, conn=conn)
    sql, params = conn.calls[0]
    assert sql == "update ksv_requests set status = %s, result_d = %s, detail = %s where id = %s"
    assert params[0] == "done" and params[1] == D and params[3] == 7
    assert json.loads(params[2]) == {"stand": "정합"}


@pytest.mark.parametrize("bad", ["queued", "", "완료"])
def test_mark_request_refuses_states_the_worker_must_not_write(bad: str) -> None:
    """`queued`로 되돌리는 길을 두지 않는다 — 웹의 INSERT 정책과 짝이다."""
    with pytest.raises(ValueError):
        store.mark_request(7, bad, conn=FakeConn())


def test_mark_request_running_leaves_result_null() -> None:
    conn = FakeConn()
    store.mark_request(7, "running", conn=conn)
    _, params = conn.calls[0]
    assert params[1] is None and json.loads(params[2]) == {}
