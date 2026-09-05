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

from collections.abc import Mapping
from datetime import date
from typing import Any, Protocol

import psycopg

from verify import config
from verify.models import UpstreamRun, Verdict


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

# ── 판정 저장 (M3) ───────────────────────────────────────────────


def save_verdicts(run_date: date, verdicts: Mapping[str, Verdict], source: str) -> int:
    """그날 판정을 `ksv_verdicts`에 남긴다 (F20).

    **`judge` 노드가 `explain`(LLM)보다 먼저 부른다** — LLM이 죽어도 판정은 이미 여기 있다.

    Args:
        run_date: KST 기준일.
        verdicts: `{ticker: Verdict}`.
        source: `batch` / `ondemand` — 집계는 기본으로 `batch`만 본다 (F43).

    Returns:
        저장한 행 수.

    Raises:
        NotImplementedError: 아직 — 열 구성·청크·왕복 테스트는 다음 태스크다.
            **조용히 0을 돌려주지 않는다.** 그러면 판정이 안 남는 것을 아무도 모른다.
    """
    raise NotImplementedError(
        f"ksv_verdicts 저장은 다음 태스크다 ({len(verdicts)}건 · {run_date} · {source})"
    )
