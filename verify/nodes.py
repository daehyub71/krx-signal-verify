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
from typing import Any

from langgraph.types import Send

from verify import state as st
from verify import store
from verify.models import RunRecord, UpstreamRun

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
STUB_NODES = (
    "fill_outcomes",
    "aggregate",
    "fetch_signals",
    "fetch_one",
    "judge",
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
    """
    signals = s.get("signals", [])
    if not signals:
        return "judge"
    return [Send("fetch_one", {"signal": sig}) for sig in signals]


# ── 스텁 — M0에서는 통과만 한다 ──────────────────────────────────


def fill_outcomes(s: st.VerifyState) -> dict[str, Any]:
    """도래한 구간의 사후 주가를 채운다 (M4). **게이트보다 앞에서 돈다.**"""
    return {}


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


def fetch_signals(s: st.VerifyState) -> dict[str, Any]:
    """그날 `suppressed = false`인 신호를 읽는다 (M2)."""
    return {}


def fetch_one(s: st.VerifyState) -> dict[str, Any]:
    """한 종목의 증거 다섯 갈래를 모은다 (M2). 실패한 갈래는 비우고 계속한다."""
    return {}


def judge(s: st.VerifyState) -> dict[str, Any]:
    """판정과 점수를 내고 저장한다 (M3). **LLM보다 먼저, 저장까지 여기서.**"""
    return {}


def explain(s: st.VerifyState) -> dict[str, Any]:
    """근거 서술 (M5). **있으면 좋은 층** — 죽어도 판정은 이미 저장돼 있다."""
    return {}


def render(s: st.VerifyState) -> dict[str, Any]:
    """메일 본문을 만든다 (M5)."""
    return {}


def send_email(s: st.VerifyState) -> dict[str, Any]:
    """메일을 보낸다 (M5). **예외를 밖으로 내지 않고 결과를 상태에 적는다.**"""
    return {}
