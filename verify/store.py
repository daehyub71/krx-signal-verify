"""DB 조회 — I/O 층. **부수효과를 아는 유일한 곳 중 하나다.**

## 조회 함수는 그래프 상태를 모른다

`fetch_*`는 전부 **순수한 「인자 → 행」 모양**이다 (PLAN §6-2). `VerifyState`를 받지 않는다 —
받는 순간 나중에 MCP 도구로 감쌀 수 없고, 같은 것을 두 번 짓게 된다 (V14).

## 상위 테이블은 읽기만 한다

`ksa_*`·`ksc_*`·`ksb_*`는 남의 것이다. 이 모듈에 그 테이블을 향한 쓰기 문장을 두지 않는다.

## 대량 조회는 REST가 아니라 여기로

Supabase REST는 **1000행에서 조용히 잘린다** — `limit(2000)`을 줘도 1000행만 오고 오류가 없다.
선행에서 그걸 모르고 완결성 검사를 REST로 짜 「424개 누락」 오탐이 났다 (실제 14개).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Protocol

import psycopg

from verify import config
from verify.models import SignalRow, UpstreamRun, Verdict, VerdictPart


def connect() -> psycopg.Connection[Any]:
    """배치용 커넥션 (service_role). **RLS를 우회하므로 웹에 절대 내리지 않는다.**

    풀러(transaction 모드)를 거치므로 prepared statement를 쓰지 않는다 —
    같은 문장을 반복하면 psycopg가 자동으로 준비하려다 풀러와 부딪힌다.
    """
    return psycopg.connect(config.require("SUPABASE_DATABASE_URL"), prepare_threshold=None)


class Queryable(Protocol):
    """`execute(sql, params)`만 쓴다 — psycopg 커넥션과 테스트 대역이 함께 만족한다."""

    def execute(self, query: Any, params: Any = ...) -> Any: ...


# 상위는 08:20 KST에 돈다 = 전날 23:20 UTC. **UTC로 세면 하루 어긋난다.**
# 하루에 여러 번 돈 날이 있으므로(재실행) 마지막 것을 본다.
Q_UPSTREAM_RUN = """
select run_at, data_date, status, signal_n
from ksa_runs
where (run_at at time zone 'Asia/Seoul')::date = %s
order by run_at desc
limit 1
"""


def fetch_upstream_run(conn: Queryable, run_date: date) -> UpstreamRun | None:
    """그날 상위가 돌았는지 본다 (F1).

    Args:
        conn: DB 커넥션.
        run_date: KST 기준일.

    Returns:
        그날의 마지막 실행. 없으면 `None` — 게이트가 `missing`으로 보고 기다린다.
        **이벤트가 아니라 이 행을 믿는다**: dispatch는 「워크플로가 끝났다」만 말한다.
    """
    row = conn.execute(Q_UPSTREAM_RUN, (run_date,)).fetchone()
    if row is None:
        return None
    return UpstreamRun(run_at=row[0], data_date=row[1], status=str(row[2]), signals=int(row[3]))

# ── 판정 저장·복원 (F20·M3) ──────────────────────────────────────
#
# **쓰는 열과 읽는 열은 한 곳에서 나온다.** 선행은 두 곳에 적었다가 되살리는 열이 하나 모자라
# **재실행이 15종목을 지웠다** — 재실행은 「읽어서 → 합쳐서 → 다시 쓴다」라, 읽을 때 빠진 열은
# 쓸 때 기본값으로 덮인다. 열을 늘리려면 이 튜플 하나만 고치면 양쪽이 함께 는다.
VERDICT_COLUMNS: tuple[str, ...] = (
    "d",
    "ticker",
    "source",
    "name",
    "strategy",
    "stand",
    "score",
    "parts",
    "blind_spots",
    "rules_version",
)

SOURCE_BATCH = "batch"
SOURCE_ONDEMAND = "ondemand"

# 한 문장에 넣을 행 수.
#
# 선행은 44행을 한 문장으로 보냈다가 `57014 statement timeout`으로 하루치를 통째로 잃었다
# (2026-08-31). 그런데 **실DB로 재 보니 44행 한 문장이 17ms다** (2026-09-05):
# 청크 1행 442ms · 5행 93ms · 20행 39ms · **44행 17ms** · 300행 한 문장 68ms.
#
# 즉 **행 수가 느려서 난 timeout이 아니었다.** 원인은 다른 데 있었고(풀러·락·콜드 커넥션),
# 청크는 **timeout을 막는 약이 아니라 피해 범위를 줄이는 장치**다 —
# 한 문장이 죽어도 하루치가 아니라 20행만 잃고, `save_verdicts`가 어디까지 갔는지 말해 준다.
# 그 값이 22ms짜리 보험이라 그대로 둔다.
CHUNK_ROWS = 20

_COLS = ", ".join(VERDICT_COLUMNS)
_KEYS = ("d", "ticker", "source")
_UPDATES = ", ".join(f"{c} = excluded.{c}" for c in VERDICT_COLUMNS if c not in _KEYS)

Q_VERDICTS = f"""
select {_COLS}
from ksv_verdicts
where d = %s and source = %s
order by ticker
"""


def to_row(signal: SignalRow, v: Verdict, source: str) -> dict[str, Any]:
    """판정 하나 → 저장 행. 키 순서가 `VERDICT_COLUMNS`와 같다.

    Raises:
        ValueError: `rules_version`이 비었을 때. 판 번호 없이 저장하면 **서로 다른 자로 잰
            값이 한 표에 섞인다** (F26).
    """
    if not v.rules_version:
        raise ValueError(f"rules_version이 비었다: {signal.ticker}")
    return {
        "d": signal.d,
        "ticker": signal.ticker,
        "source": source,
        "name": signal.name,
        "strategy": signal.strategy,
        "stand": v.stand,
        "score": v.score,
        "parts": json.dumps([{"label": p.label, "delta": p.delta} for p in v.parts],
                            ensure_ascii=False),
        "blind_spots": list(v.blind_spots),
        "rules_version": v.rules_version,
    }


def from_row(row: Sequence[Any]) -> tuple[str, Verdict, dict[str, Any]]:
    """저장 행 → `(ticker, Verdict, 메타)`. `VERDICT_COLUMNS` 순서를 그대로 받는다."""
    got = dict(zip(VERDICT_COLUMNS, row, strict=True))
    raw = got["parts"]
    parts = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return (
        str(got["ticker"]),
        Verdict(
            stand=str(got["stand"]),
            score=int(got["score"]),
            parts=tuple(VerdictPart(str(p["label"]), int(p["delta"])) for p in parts),
            blind_spots=tuple(got["blind_spots"] or ()),
            rules_version=str(got["rules_version"]),
        ),
        {"d": got["d"], "ticker": str(got["ticker"]), "source": str(got["source"]),
         "name": str(got["name"]), "strategy": str(got["strategy"])},
    )


def save_verdicts(
    run_date: date,
    verdicts: Mapping[str, Verdict],
    source: str,
    *,
    signals: Sequence[SignalRow] = (),
    conn: Queryable | None = None,
) -> int:
    """그날 판정을 `ksv_verdicts`에 남긴다 (F20).

    **`judge` 노드가 `explain`(LLM)보다 먼저 부른다** — LLM이 죽어도 판정은 이미 여기 있다.

    Args:
        run_date: KST 기준일.
        verdicts: `{ticker: Verdict}`.
        source: `batch` / `ondemand` — PK에 들어간다. 궁금해서 넣은 종목이 그날 배치 판정을
            덮으면 안 된다 (F43).
        signals: 이름·전략을 얻을 곳. 없으면 빈 문자열로 둔다 — **판정을 버리지는 않는다.**
        conn: 커넥션 (테스트가 대역을 넣는다).

    Returns:
        저장한 행 수.

    Raises:
        RuntimeError: 청크가 실패했을 때. **어디까지 갔는지를 메시지에 적는다** —
            하루치를 통째로 잃는 것과 절반을 잃는 것은 다르다.
    """
    meta = {s.ticker: s for s in signals}
    rows = [
        to_row(meta.get(t) or SignalRow(d=run_date, ticker=t, name="", strategy="", evidence={}),
               v, source)
        for t, v in verdicts.items()
    ]
    if not rows:
        return 0
    if conn is not None:
        return _write(conn, rows)  # 커밋은 커넥션 주인이 한다
    # **직접 열면 직접 커밋한다.** psycopg는 기본이 비-autocommit이라, 커밋 없이 커넥션이
    # 사라지면 **예외도 없이 롤백된다** — 저장한 줄 알았는데 0행이다 (2026-09-05 실행에서 잡혔다).
    with connect() as own:
        return _write(own, rows)


def _write(c: Queryable, rows: Sequence[dict[str, Any]]) -> int:
    """청크로 나눠 보낸다. **어디까지 갔는지**를 실패 메시지에 적는다."""
    done = 0
    for i in range(0, len(rows), CHUNK_ROWS):
        chunk = rows[i : i + CHUNK_ROWS]
        try:
            c.execute(_insert_sql(len(chunk)), [x[col] for x in chunk for col in VERDICT_COLUMNS])
        except Exception as exc:
            raise RuntimeError(
                f"판정 저장이 {done}행까지 가고 멈췄다 ({len(rows)}행 중): {exc}"
            ) from exc
        done += len(chunk)
    return done


def _insert_sql(n: int) -> str:
    """행 `n`개짜리 upsert.

    **PK `(d, ticker, source)`로 덮어쓴다** — 재실행이 행을 늘리지 않는다.
    """
    values = ", ".join(["(" + ", ".join(["%s"] * len(VERDICT_COLUMNS)) + ")"] * n)
    return (
        f"insert into ksv_verdicts ({_COLS}) values {values} "
        f"on conflict (d, ticker, source) do update set {_UPDATES}"
    )


def fetch_verdicts(
    conn: Queryable, run_date: date, source: str = SOURCE_BATCH
) -> dict[str, Verdict]:
    """그날 저장된 판정을 되살린다.

    **읽는 열이 쓰는 열보다 적으면 재실행이 지운다** — 둘 다 `VERDICT_COLUMNS`에서 나온다.
    """
    rows = conn.execute(Q_VERDICTS, (run_date, source)).fetchall()
    return {t: v for t, v, _ in (from_row(r) for r in rows)}

# ── 그날의 신호 (F2) ─────────────────────────────────────────────
#
# **`suppressed = false`인 것만.** 억제된 신호는 상위가 메일에 안 실었으니 검증 대상이 아니다.
# 실측(2026-09-05): 572행 중 **309행이 억제**다 — 안 거르면 절반 이상이 는다.
#
# **`sent_email`을 쓰지 않는다.** 상위가 그 열을 채우지 않아 전부 `false`다 —
# 조건에 넣으면 매일 0건이 된다 (선행 2026-08-26 실측).
Q_SIGNALS = """
select d, strategy, ticker, name, evidence
from ksa_signals
where d = %s and not suppressed
order by strategy, ticker
"""


def fetch_signals(conn: Queryable, run_date: date) -> list[SignalRow]:
    """그날 검증할 신호 (F2). 순서는 상위 메일과 같게 전략·티커 순.

    Args:
        conn: DB 커넥션.
        run_date: KST 기준일.

    Returns:
        `SignalRow` 목록. 신호 없는 날이면 빈 목록 — 휴장일이나 전량 억제된 날이다.
    """
    rows = conn.execute(Q_SIGNALS, (run_date,)).fetchall()
    return [
        SignalRow(d=d, strategy=str(strategy or ""), ticker=str(ticker),
                  name=str(name or ""), evidence=ev)
        for d, strategy, ticker, name, ev in rows
    ]

