"""그래프 상태와 상수 — 그래프 층. LangGraph를 아는 세 파일 중 하나다.

**DB·HTTP·LLM을 모른다** (N4). 여기서 부수효과가 새면 3층 분리가 무너진다.

## reducer를 빼먹으면 조용히 사라진다

fan-out으로 노드 N개가 각자 `evidence`를 돌려줄 때, `Annotated[list, operator.add]`가
없으면 **마지막 하나만 남고 예외도 안 난다.** 선행 두 프로젝트에서 실증된 함정이다.
`tests/test_state.py`가 선언을 잠그고 `tests/test_graph.py`가 실제 합류를 본다 —
**둘 다 지우지 말 것.**

반대로 **덮어써야 하는 값에 reducer를 붙이면** 상태가 눈덩이처럼 커진다.
`gate`·`attempts`·`status`처럼 마지막 값만 의미 있는 키는 평범하게 둔다.
"""

from __future__ import annotations

import operator
from datetime import date
from typing import Annotated, Any, TypedDict

from verify.models import HORIZONS as HORIZONS  # 도메인 것을 그대로 쓴다 — 두 곳에 적으면 갈라진다
from verify.models import Evidence, RunRecord, SendResult, SignalRow, Verdict

# ── 게이트 (F1) ──────────────────────────────────────────────────
# dispatch는 「워크플로가 끝났다」만 말한다. 상위가 아직 DB에 안 썼을 수 있으므로
# **이벤트가 아니라 DB를 믿고** 기다린다. 10분을 넘기면 `gate_timeout`으로 끝낸다.
GATE_MAX_ATTEMPTS = 10
GATE_WAIT_SECONDS = 60

GATE_READY = "ready"
GATE_STALE = "stale"
GATE_MISSING = "missing"
GATE_TIMEOUT = "timeout"
GATE_VALUES = (GATE_READY, GATE_STALE, GATE_MISSING, GATE_TIMEOUT)

# ── 실행 모드 (V8) ───────────────────────────────────────────────
# 온디맨드는 게이트도 메일도 필요 없고 종목이 하나다. fan-out·판정 경로는 같이 쓴다.
MODE_BATCH = "batch"
MODE_ONDEMAND = "ondemand"
MODES = (MODE_BATCH, MODE_ONDEMAND)

# ── 종료 상태 ────────────────────────────────────────────────────
STATUS_OK = "ok"
STATUS_NO_SIGNALS = "no_signals"
STATUS_GATE_TIMEOUT = "gate_timeout"
STATUS_STALE_DATA = "stale_data"
STATUS_FAILED = "failed"

# `gate → wait → gate` 사이클이 10회 돈다. 왕복 2스텝 + 나머지 그래프에 여유를 둔다.
RECURSION_LIMIT = 60


class VerifyState(TypedDict, total=False):
    """그래프를 흐르는 상태.

    `total=False`다 — **노드는 자기가 채우는 키만 돌려준다.** 전부 필수로 두면
    스텁 노드가 못 돌고, M0의 「걷는 해골」이 성립하지 않는다.
    """

    # ── 입력 ──
    mode: str  # MODES
    run_date: date  # KST 기준일. **전략도 노드도 「오늘」을 스스로 알지 않는다**
    ticker: str  # 온디맨드일 때만
    force: bool
    dry_run: bool

    # ── 게이트 ──
    gate: str  # GATE_VALUES
    attempts: int
    data_date: date | None

    # ── 수집 ──
    signals: list[SignalRow]
    corps: dict[str, str]  # ticker → corp_code
    tickers: dict[str, dict[str, Any]]  # 종목 메타 (시장·업종·시총)
    investor: dict[str, list[dict[str, Any]]]  # 기관·외국인 30일
    shorting: dict[str, list[dict[str, Any]]]  # 공매도 20일 — 없을 수 있다 (F34)

    # ── fan-out 합류 ──
    # ⚠ reducer가 없으면 마지막 하나만 남고 **예외도 안 난다**. 지우지 말 것.
    evidence: Annotated[list[Evidence], operator.add]

    # ── 판정·서술 ──
    verdicts: dict[str, Verdict]  # 코드가 낸다. LLM이 바꾸지 못한다
    summaries: dict[str, str]  # 있으면 좋은 층 — 없어도 판정은 나간다
    summary_error: str

    # ── 적중 추적 ──
    # 게이트와 무관하게 돈다. 게이트가 stale/timeout으로 끝나는 날에도 채점은 돌아야 한다.
    outcomes_filled: int
    discrimination: dict[str, Any]

    # ── 오류 ──
    # I/O 노드가 예외를 밖으로 내지 않고 여기에 적는다. fan-out에서도 모여야 하므로 reducer.
    errors: Annotated[list[str], operator.add]

    # ── 출력 ──
    subject: str
    text: str
    html: str
    send: SendResult
    run: RunRecord
    status: str
