"""노드 — 그래프 층. **M0에서는 배선만 실물이다.**

수집·판정·발송은 빈 통과 함수로 두고 라우팅과 마무리만 실구현한다.
PLAN이 정한 순서다: **그래프를 먼저 세우고 노드를 나중에 채운다** —
노드를 다 만든 뒤 조립하면 reducer·조건부 엣지·합류가 한꺼번에 터진다.

## 이 파일의 두 규칙

1. **노드는 20줄을 넘지 않는다** (N6). 넘으면 도메인 로직이 샌 것이니 도메인 모듈로 옮긴다.
2. **I/O 노드는 예외를 밖으로 내지 않는다.** raise하면 `record_run`에 못 가
   **그날 실패 기록까지 사라진다.** 결과를 상태에 적고, 실패 판정은 `finalize` 한 곳에서만.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from langgraph.types import Send

from verify import (
    corp,
    dart,
    dart_fin,
    dart_mcp,
    enrich,
    financial,
    flags,
    lanes,
    mcpc,
    news_mcp,
    outcome,
    shorting,
    store,
    verdict,
)
from verify import state as st
from verify.models import (
    Evidence,
    RunRecord,
    SignalRow,
    UpstreamRun,
    Verdict,
    VerdictInput,
)

# 대기는 여기서 한다 — 테스트가 잠들지 않도록 갈아 끼울 수 있게 이름을 뺀다.
_sleep = time.sleep

# 조건부 엣지가 돌려주는 라벨. graph.py와 테스트가 같은 이름을 본다.
TO_GATE = "gate"
TO_COLLECT = "collect"
TO_WAIT = "wait"
TO_REPORT = "report"

# 아직 통과만 하는 노드들. 뒤 마일스톤에서 하나씩 실물이 된다.
# **실물이 되면 여기서 뺀다** — 안 빼면 스텁 테스트가 그 노드의 I/O를 부른다.
# `gate`가 그랬다: 로컬엔 `.env`가 있어 통과하고 **CI에서만 터졌다** (2026-09-02).
# I/O 이음매 — 테스트가 갈아 끼운다 (`_sleep`과 같은 꼴).
_save_verdicts = store.save_verdicts


def _fetch_signals(run_date: date) -> list[SignalRow]:
    """그날 신호를 상위에서 읽는다 (F2). 커넥션 수명이 여기서 끝난다."""
    with store.connect() as conn, conn.cursor() as cur:
        return store.fetch_signals(cur, run_date)


# 공시·본문·뉴스가 보는 창. **갈래마다 다르면 대조가 안 된다.**
WINDOW_DAYS = 30


def _corp_codes() -> dict[str, str]:
    """`{stock_code: corp_code}`. 실행에 **한 번만** 받는다 (약 4천 건)."""
    return corp.parse_corp_codes(dart.fetch_corp_codes())


def _upstream(tickers: Sequence[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """수급·시세를 상위 DB에서 **한 번에** 읽는다 (F12·F17). 종목마다 부르지 않는다."""
    with store.connect() as conn, conn.cursor() as cur:
        return (
            dict(enrich.fetch_flows(cur, list(tickers))),
            dict(enrich.fetch_quotes(cur, list(tickers))),
        )


def _financials(corp_codes: Sequence[str], day: date) -> dict[str, Any]:
    """재무를 **15개씩 묶어** 받는다 (F30). 종목마다 부르면 44회가 된다."""
    return financial.read_all(dart_fin.fetch_accounts(list(corp_codes), day))


def _shorting_state() -> Any:
    """공매도 갈래의 상태 (F32). M8 전까지 `MISSING`이라 값이 없다."""
    with store.connect() as conn, conn.cursor() as cur:
        got = shorting.probe(cur)
    return None if got.state == shorting.MISSING else got


def prefetch(signals: Sequence[SignalRow], day: date) -> dict[str, Any]:
    """묶어서 받을 것을 **실행에 한 번** 받는다 (F12·F17·F30·F32).

    묶음 하나가 죽어도 **나머지 갈래는 살아야 한다** (F34) — 각각 따로 감싼다.

    Returns:
        `corps`·`flows`·`quotes`·`financials`·`shorting`, 그리고 실패한 것의 `errors`.
    """
    tickers = [s.ticker for s in signals]
    errors: list[str] = []
    corps = _guarded("corps", _corp_codes, errors) or {}
    flows, quotes = _guarded("수급·시세", lambda: _upstream(tickers), errors) or ({}, {})
    codes = [c for t in tickers if (c := corps.get(t))]
    fins = _guarded("재무", lambda: _financials(codes, day), errors) if codes else {}
    return {
        "corps": corps, "flows": flows, "quotes": quotes,
        "financials": fins or {}, "shorting": _guarded("공매도", _shorting_state, errors),
        "errors": errors,
    }


def _guarded(what: str, fn: Callable[[], Any], errors: list[str]) -> Any:
    """묶음 하나를 감싼다. **하나가 죽어도 나머지 갈래는 살아야 한다** (F34)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — 묶음 단위 격리
        errors.append(f"{what} 조회 실패: {type(exc).__name__}: {exc}")
        return None


def _disclosures_of(corp_code: str, day: date) -> tuple[Any, Any]:
    """공시 목록과 **플래그된 것의 본문** (F4·F15). MCP 실패는 REST로 폴백한다."""
    bgn = day - timedelta(days=WINDOW_DAYS)
    items, _src = dart_mcp.fetch_disclosures(corp_code, bgn, day)
    flagged = flags.classify(tuple(items))
    bodies: list[Any] = []
    for rule in {f.rule for f in flagged.flags} & set(dart_mcp.EVENT_TYPE_OF):
        with suppress(mcpc.McpError):  # 본문은 있으면 좋은 층이다
            bodies.extend(dart_mcp.fetch_event(corp_code, rule, bgn, day))
    return tuple(items), tuple(bodies)


def _news_of(company_name: str) -> Any:
    """종목명으로 뉴스 (F11). 제목 필터까지 `news_mcp`가 건다."""
    return tuple(news_mcp.fetch_news(company_name))


def collect_lanes(
    run_date: date, sig: SignalRow, ctx: Mapping[str, Any]
) -> tuple[Evidence, tuple[str, ...], dict[str, str]]:
    """한 종목의 다섯 갈래 (F3~F9·F34). **M2 모듈을 부르는 자리는 여기 하나다.**

    묶음(수급·재무·공매도)은 이미 받아 둔 것을 `ctx`에서 꺼내고, 종목별(공시·뉴스)만 부른다.
    갈래별 실패 격리는 `lanes.collect`가 한다.
    """
    corp_code = str(ctx.get("corp") or "")
    holder: dict[str, Any] = {}

    def disclosures() -> Any:
        items, bodies = _disclosures_of(corp_code, run_date)
        holder["bodies"] = bodies
        return items or None

    got = lanes.collect(
        d=run_date, ticker=sig.ticker,
        disclosures=disclosures if corp_code else None,
        news=lambda: _news_of(sig.name) or None,
        flows=lambda: ctx.get("flows"),
        financial=lambda: ctx.get("financial"),
        shorting=lambda: ctx.get("shorting"),
    )
    ev = replace(got.evidence, bodies=holder.get("bodies"))
    return ev, got.skipped, got.reasons


# `fetch_one`이 부르는 이음매. 테스트가 갈아 끼운다.
_collect_lanes = collect_lanes

STUB_NODES = (
    "aggregate",
    "explain",
    "render",
    "send_email",
)


# ── 라우팅 ───────────────────────────────────────────────────────


def route_mode(s: st.VerifyState) -> str:
    """배치 / 온디맨드 분기 (V8).

    온디맨드는 게이트도 메일도 필요 없고 종목이 하나다. 같은 fan-out·판정 경로를 재사용한다.
    모드가 깨져 오면 **더 안전한 쪽**(게이트를 거치는 쪽)으로 흘린다.
    """
    return TO_COLLECT if s.get("mode") == st.MODE_ONDEMAND else TO_GATE


def route_gate(s: st.VerifyState) -> str:
    """게이트 판정 (F1). **이벤트가 아니라 DB를 믿는다.**

    dispatch는 「워크플로가 끝났다」만 말한다. 상위가 아직 안 썼을 수 있으므로
    `missing`이면 1분씩 10회 기다렸다가 포기한다.
    """
    gate = s.get("gate")
    if gate == st.GATE_READY:
        return TO_COLLECT
    if gate == st.GATE_MISSING and s.get("attempts", 0) < st.GATE_MAX_ATTEMPTS:
        return TO_WAIT
    return TO_REPORT


def wait(s: st.VerifyState) -> dict[str, Any]:
    """다음 시도까지 센다. 실제 대기는 `gate` 노드가 한다 (테스트가 잠들지 않도록)."""
    return {"attempts": s.get("attempts", 0) + 1}


# ── 마무리 — 실패 판정은 여기 한 곳에서만 ────────────────────────


def _status_of(s: st.VerifyState) -> str:
    """종료 상태를 정한다. **순서가 곧 우선순위다.**

    게이트가 못 선 날은 신호가 있든 없든 게이트 사유가 먼저다 — 그래야 원인이 안 묻힌다.
    `--dry-run`은 발송을 하지 않으므로 발송 결과가 없다고 실패로 적지 않는다.
    """
    gate = s.get("gate")
    if gate == st.GATE_MISSING and s.get("attempts", 0) >= st.GATE_MAX_ATTEMPTS:
        return st.STATUS_GATE_TIMEOUT
    if gate == st.GATE_STALE:
        return st.STATUS_STALE_DATA
    if not s.get("signals"):
        return st.STATUS_NO_SIGNALS
    send = s.get("send")
    if send is not None and not send.ok:
        return st.STATUS_FAILED
    return st.STATUS_OK


def record_run(s: st.VerifyState) -> dict[str, Any]:
    """실행을 기록한다. **여기까지는 무슨 일이 있어도 온다.**

    채점(`outcomes_filled`)은 게이트와 무관하게 돌므로, 게이트가 실패한 날에도 함께 남긴다.
    """
    return {
        "run": RunRecord(
            run_at=s["run_date"],
            status=_status_of(s),
            gate=str(s.get("gate", "")),
            signals=len(s.get("signals", [])),
            verdicts=len(s.get("verdicts", {})),
            outcomes_filled=s.get("outcomes_filled", 0),
            detail={"errors": list(s.get("errors", []))},
        )
    }


def finalize(s: st.VerifyState) -> dict[str, Any]:
    """마지막 한 곳. **성공/실패를 정하는 유일한 자리다.**"""
    return {"status": _status_of(s)}


# ── fan-out ──────────────────────────────────────────────────────


def fan_out(s: st.VerifyState) -> list[Send] | str:
    """신호마다 `fetch_one`을 하나씩 띄운다.

    합류는 `state.evidence`의 reducer가 한다 — **없으면 마지막 하나만 남고 예외도 안 난다.**
    신호가 0건이면 **`judge`로 직행**한다. 빈 목록을 돌려주면 그래프가 갈 곳을 잃는다.

    ⚠ **`Send`의 payload가 그 노드의 상태를 통째로 대신한다** — 합쳐지지 않는다.
    `run_date`를 함께 실어야 한다. 안 실으면 `fetch_one`이 `KeyError`로 죽고,
    fan-out 전체가 빈 증거로 지나간다 (2026-09-05 실행에서 잡혔다 — 단위 테스트는
    상태를 직접 만들어 주므로 이 함정을 못 본다).
    """
    signals = s.get("signals", [])
    if not signals:
        return "judge"
    day = s["run_date"]
    ctx = s.get("context") or {}
    return [
        Send("fetch_one", {"signal": sig, "run_date": day, "lane_ctx": _slice(ctx, sig)})
        for sig in signals
    ]


def _slice(ctx: Mapping[str, Any], sig: SignalRow) -> dict[str, Any]:
    """그 종목 몫만 떼어 payload에 싣는다. **맵 전체를 44번 복사하지 않는다.**"""
    corp_code = str((ctx.get("corps") or {}).get(sig.ticker) or "")
    return {
        "corp": corp_code,
        "flows": (ctx.get("flows") or {}).get(sig.ticker),
        "financial": (ctx.get("financials") or {}).get(corp_code),
        "shorting": ctx.get("shorting"),
    }


# ── 스텁 — M0에서는 통과만 한다 ──────────────────────────────────




def aggregate(s: st.VerifyState) -> dict[str, Any]:
    """군별 초과수익 분포를 집계한다 (M4)."""
    return {}


def gate_from(run: UpstreamRun | None) -> dict[str, Any]:
    """상위 실행 기록 → 게이트 판정. **순수 함수라 DB가 필요 없다.**

    상위가 스스로 `stale_data`로 끝내는 날이 있다 (실측). 그 판단을 다시 하지 않고 받는다.
    모르는 상태가 오면 **더 안전한 쪽**으로 — 신호를 믿지 않는다.
    """
    if run is None:
        return {"gate": st.GATE_MISSING}
    gate_value = st.GATE_READY if run.status == "ok" else st.GATE_STALE
    return {"gate": gate_value, "data_date": run.data_date}


def gate(s: st.VerifyState) -> dict[str, Any]:
    """상위 `ksa_runs` 오늘 행을 보고 판정한다 (F1).

    재시도일 때만 기다린다 — 첫 조회는 곧바로 한다. dispatch가 20초 만에 깨우므로
    상위가 아직 안 썼을 수 있다.
    """
    if s.get("attempts", 0) > 0:
        _sleep(st.GATE_WAIT_SECONDS)
    with store.connect() as conn:
        return gate_from(store.fetch_upstream_run(conn, s["run_date"]))






def verdict_input_for(signal: SignalRow, evidence: Evidence | None) -> VerdictInput:
    """신호 하나 + 그 종목의 증거 → 산식 입력. **순수 함수 — 상태를 모른다.**

    나중에 온디맨드·재판정이 같은 함수를 쓴다. `Evidence`를 그대로 넘기지 않는 이유는
    `models.VerdictInput` 주석에 있다 — 산식을 저장 형태와 떼어 놓는다.
    """
    ev = evidence or Evidence(d=signal.d, ticker=signal.ticker)
    flagged = flags.classify(tuple(ev.disclosures or ()))
    return VerdictInput(
        level=flagged.level,
        flags=flagged.flags,
        disclosures=flagged.disclosures,
        bodies=tuple(ev.bodies or ()),
        news=tuple(ev.news or ()),
        flows=ev.flows,
        anomaly=ev.anomaly,
        financial=ev.financial,
        shorting=ev.shorting,
    )


def _fill_outcomes(day: date) -> int:
    """아직 안 찬 판정에 관측 구간을 채운다 (F22·F23). 커넥션 수명이 여기서 끝난다."""
    since = day - timedelta(days=store.OUTCOME_LOOKBACK_DAYS)
    with store.connect() as conn, conn.cursor() as cur:
        pending = store.fetch_pending(cur, since)
        if not pending:
            return 0
        rows = [
            (outcome.measure(d, ticker, market, *_bars_for(cur, ticker, market, d)), market)
            for d, ticker, market in pending
        ]
        return store.save_outcomes(rows, conn=cur)


def _bars_for(
    cur: Any, ticker: str, market: str, since: date
) -> tuple[list[outcome.DayBar], list[outcome.DayBar]]:
    """그 종목과 소속 시장 지수의 일봉 (판정일 이후). **지수가 달력의 출처다.**"""
    stock = cur.execute(store.Q_STOCK_BARS, (ticker, since)).fetchall()
    index = cur.execute(store.Q_INDEX_BARS, (market, since)).fetchall()
    return (
        [outcome.DayBar(d=d, close=float(c), volume=int(v)) for d, c, v in stock],
        [outcome.DayBar(d=d, close=float(c), volume=1) for d, c in index],
    )


def fill_outcomes(s: st.VerifyState) -> dict[str, Any]:
    """어제까지의 판정에 관측 구간을 채운다 (F22). **게이트보다 앞에서 돈다.**

    어제 판정 채점은 오늘 신호와 무관하다 — 게이트가 `stale`·`gate_timeout`으로 끝나는
    날에도 채점은 돌아야 한다.

    **예외를 밖으로 내지 않는다** (N11).
    """
    try:
        return {"outcomes_filled": _fill_outcomes(s["run_date"])}
    except Exception as exc:  # noqa: BLE001 — I/O 노드의 규칙
        return {"outcomes_filled": 0, "errors": [f"관측 채우기 실패: {type(exc).__name__}: {exc}"]}


def fetch_signals(s: st.VerifyState) -> dict[str, Any]:
    """그날 검증할 신호를 읽는다 (F2). 온디맨드면 그 종목 하나만 남긴다 (V8).

    **예외를 밖으로 내지 않는다** — raise하면 `record_run`에 못 가 실패 기록까지 사라진다.
    """
    try:
        rows = _fetch_signals(s["run_date"])
    except Exception as exc:  # noqa: BLE001 — I/O 노드의 규칙 (N11)
        return {"signals": [], "errors": [f"신호 조회 실패: {type(exc).__name__}: {exc}"]}
    want = s.get("ticker") or ""
    if s.get("mode") == st.MODE_ONDEMAND and want:
        rows = [r for r in rows if r.ticker == want]
    if not rows:
        return {"signals": rows}
    # 묶어서 받을 것은 **여기서 한 번** 받는다 — 종목 목록을 아는 첫 자리다.
    ctx = prefetch(rows, s["run_date"])
    return {"signals": rows, "context": ctx, "errors": ctx["errors"]}


def fetch_one(s: st.VerifyState) -> dict[str, Any]:
    """종목 하나의 증거를 모은다 (F3~F9·F34). fan-out이 종목마다 부른다.

    **한 종목이 fan-out을 죽이지 않는다** — 통째로 실패해도 빈 증거로 자리를 남긴다.
    빈 갈래는 `errors`에 이유와 함께 남는다 (조용히 빠지지 않는다).
    """
    sig: SignalRow = s["signal"]
    try:
        ev, skipped, reasons = _collect_lanes(s["run_date"], sig, s.get("lane_ctx") or {})
    except Exception as exc:  # noqa: BLE001 — 종목 단위 격리
        ev = Evidence(d=s["run_date"], ticker=sig.ticker)
        skipped, reasons = ev.missing_lanes(), {"수집": f"{type(exc).__name__}: {exc}"}
    errors = [f"{sig.ticker} {k} 생략: {v}" for k, v in reasons.items() if v]
    if skipped and not errors:
        errors = [f"{sig.ticker} {' · '.join(skipped)} 생략"]
    return {"evidence": [ev], "errors": errors}


def judge_all(signals: Sequence[SignalRow], evidence: Sequence[Evidence]) -> dict[str, Verdict]:
    """신호들 → `{ticker: Verdict}`. **순수 함수 — 상태를 모른다.**

    fan-out이 합류한 뒤라 `evidence`에 여러 종목이 섞여 있다. **티커로 가른다** —
    안 가르면 남의 공시로 판정한다.
    """
    by_ticker = {e.ticker: e for e in evidence}
    return {
        sig.ticker: verdict.judge(verdict_input_for(sig, by_ticker.get(sig.ticker)))
        for sig in signals
    }


def judge(s: st.VerifyState) -> dict[str, Any]:
    """판정·점수를 내고 **저장까지 끝낸 뒤** 넘긴다 (F20·M3).

    선행은 한 노드가 판정과 LLM 호출을 겸해 **LLM이 죽으면 판정도 같이 사라졌다.**
    여기서는 저장이 `explain`보다 먼저다 — 그 순서가 보장의 전부다.
    저장이 실패해도 **판정을 상태에서 지우지 않는다** — 메일은 나가야 한다 (F34).
    """
    signals = s.get("signals") or []
    verdicts = judge_all(signals, s.get("evidence") or [])
    out: dict[str, Any] = {"verdicts": verdicts}
    if not verdicts:
        return out
    try:
        mode = s.get("mode") or st.MODE_BATCH
        _save_verdicts(s["run_date"], verdicts, mode, signals=signals)
    except Exception as exc:  # noqa: BLE001 — 저장 실패가 판정을 데려가면 안 된다
        out["errors"] = [f"판정 저장 실패: {type(exc).__name__}: {exc}"]
    return out


def explain(s: st.VerifyState) -> dict[str, Any]:
    """근거 서술 (M5). **있으면 좋은 층** — 죽어도 판정은 이미 저장돼 있다."""
    return {}


def render(s: st.VerifyState) -> dict[str, Any]:
    """메일 본문을 만든다 (M5)."""
    return {}


def send_email(s: st.VerifyState) -> dict[str, Any]:
    """메일을 보낸다 (M5). **예외를 밖으로 내지 않고 결과를 상태에 적는다.**"""
    return {}
