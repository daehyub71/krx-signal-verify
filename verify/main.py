"""CLI — I/O 층. 초기 상태를 만들어 그래프에 넘기고 종료 코드를 정한다.

**전략도 노드도 「오늘」을 스스로 알지 않는다.** 기준일은 여기서 한 번 주입한다 —
그래야 드라이런과 특정일 재현이 성립한다.

## 종료 코드

- `ok` · `no_signals` → **0.** 신호가 0건인 날도 「없음」을 보낸다. 정상 동작이다.
- `stale_data` · `gate_timeout` → **1.** 침묵을 정상으로 두지 않는다 —
  상위가 조용히 2주간 멈춘 적이 있다 (2026-08-18~08-31).
- `failed` → **1.** 부분 성공을 성공으로 위장하지 않는다.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from verify import config, graph
from verify import nodes as graph_nodes
from verify import state as st

KST = ZoneInfo("Asia/Seoul")

# 티커는 숫자가 아니다 — `0126Z0`(삼성에피스홀딩스)처럼 문자가 섞인 6자리가 실재한다.
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")

# 이 상태로 끝나면 워크플로를 실패시킨다.
FAILING = (st.STATUS_STALE_DATA, st.STATUS_GATE_TIMEOUT, st.STATUS_FAILED)


def _as_date(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y%m%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"YYYYMMDD 형식이어야 한다: {raw!r}") from exc


def _as_ticker(raw: str) -> str:
    if not TICKER_RE.match(raw):
        raise argparse.ArgumentTypeError(f"6자리 영숫자여야 한다(예: 042700, 0126Z0): {raw!r}")
    return raw


def _as_request_id(raw: str) -> int:
    if not raw.isdigit() or int(raw) <= 0:
        raise argparse.ArgumentTypeError(f"요청 id는 양의 정수여야 한다: {raw!r}")
    return int(raw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 읽는다. 기준일 기본값은 **서울 기준 오늘**이다 (UTC면 아침에 하루 밀린다)."""
    p = argparse.ArgumentParser(prog="verify", description="차트 신호를 증거로 검증한다")
    p.add_argument("--date", dest="run_date", type=_as_date, default=datetime.now(KST).date(),
                   help="기준일 YYYYMMDD (기본: 서울 오늘)")
    # 기본값을 ""로 두면 안 된다 — argparse는 **문자열 기본값도 `type`에 통과시킨다.**
    p.add_argument("--ticker", type=_as_ticker, default=None,
                   help="온디맨드로 검증할 종목. 주면 상위 신호 없이 이 종목만 본다")
    p.add_argument("--dry-run", action="store_true", help="발송·저장 없이 결과만 출력")
    p.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
    p.add_argument("--if-not-verified", action="store_true",
                   help="예비 cron용 — 오늘 이미 돌았으면 아무것도 하지 않는다")
    p.add_argument("--request-id", type=_as_request_id, default=None,
                   help="온디맨드 요청 표(ksv_requests)의 id — running→done/failed로 갱신")
    args = p.parse_args(argv)
    if args.request_id is not None and not args.ticker:
        p.error("--request-id는 --ticker와 함께 써야 한다 (요청 표는 온디맨드 전용)")
    return args


def initial_state(args: argparse.Namespace) -> st.VerifyState:
    """그래프에 넣을 초기 상태.

    **노드가 채울 키를 미리 넣지 않는다** — 넣으면 스텁이 통과했는지 구분이 안 된다.
    """
    return {
        "mode": st.MODE_ONDEMAND if args.ticker else st.MODE_BATCH,
        "run_date": args.run_date,
        "ticker": args.ticker or "",
        "force": args.force,
        "dry_run": args.dry_run,
    }


def _already_verified(run_date: date) -> bool:
    """오늘 이미 정상 종료한 실행이 `ksv_runs`에 있는가.

    예비 cron이 dispatch와 겹친 날, 두 번째 실행이 **메일을 두 번 보내지 않게** 한다.
    판정 표로 보지 않는다 — 판정 `d`는 **신호 날짜**(전 거래일)라 실행 날짜와 다르다 (트러블슈팅 ④).
    """
    from verify import store  # main은 그래프 밖이라 여기서만 DB를 안다

    with store.connect() as conn:
        return store.has_run(conn, run_date)


def _mark_request(request_id: int, status: str, **kw: Any) -> None:
    """요청 표 갱신의 실물 (F41). main은 그래프 밖이라 여기서만 DB를 안다."""
    from verify import store

    store.mark_request(request_id, status, **kw)


def _request_detail(out: Mapping[str, Any], status: str) -> dict[str, Any]:
    """웹 상태 패널이 바로 보일 것 — 판정·점수·오류. 종목 화면까지 안 가도 「정합 68」이 보인다."""
    verdicts = out.get("verdicts") or {}
    return {
        "status": status,
        "verdicts": {t: {"stand": v.stand, "score": v.score} for t, v in verdicts.items()},
        "errors": list(out.get("errors") or []),
    }


def main(
    argv: list[str] | None = None,
    *,
    overrides: Mapping[str, Callable[..., dict[str, Any]]] | None = None,
    verified_check: Callable[[date], bool] | None = None,
    request_marker: Callable[..., None] | None = None,
) -> int:
    """한 번 돌리고 종료 코드를 돌려준다.

    Args:
        argv: CLI 인자. None이면 `sys.argv`.
        overrides: 노드 대체 (테스트용).
        verified_check: 그날 이미 돌았는지 묻는다. M0에서는 주입으로만 쓴다.
        request_marker: 온디맨드 요청 표 갱신. 없으면 실물(`_mark_request`).

    Returns:
        0(정상) 또는 1(실패). **부분 성공을 성공으로 위장하지 않는다.**
    """
    config.load_env()
    args = parse_args(argv)

    # 예비 cron(09:05 KST)은 dispatch로 이미 돌았는지 모른다 — **DB를 보고** 판단한다.
    # 주입이 없으면 실물(`_already_verified`)을 쓴다. M0에서는 주입으로만 썼다.
    check = verified_check or _already_verified
    if args.if_not_verified and not args.force and check(args.run_date):
        print(f"{args.run_date}는 이미 검증했다 — 아무것도 하지 않는다")
        return 0

    mark = request_marker or _mark_request

    def note(status: str, **kw: Any) -> None:
        # 요청 표 갱신은 부수 기록이다 — 죽어도 검증을 데려가지 않는다.
        if args.request_id is None:
            return
        try:
            mark(args.request_id, status, **kw)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠ 요청 {args.request_id} 상태 갱신 실패({status}): {exc}", file=sys.stderr)

    note("running")
    app = graph.build_graph(overrides)
    out = app.invoke(initial_state(args), {"recursion_limit": st.RECURSION_LIMIT})

    status = str(out.get("status", st.STATUS_FAILED))
    # 결과 날짜는 **신호의 날짜**다 — 판정 `d`와 같아야 종목 화면 링크가 맞는다 (트러블슈팅 ④).
    note("failed" if status in FAILING else "done",
         result_d=graph_nodes.signals_day(out), detail=_request_detail(out, status))
    for err in out.get("errors", []):
        print(f"⚠ {err}", file=sys.stderr)
    send = out.get("send")
    sent = "dry-run" if out.get("dry_run") else (
        f"보냄({send.reason})" if send and send.ok else f"실패({send.reason})" if send else "안 함"
    )
    said = out.get("summary_error") or f"{len(out.get('summaries') or {})}건"
    print(f"status={status} signals={len(out.get('signals', []))} "
          f"evidence={len(out.get('evidence', []))} outcomes={out.get('outcomes_filled', 0)} "
          f"verdicts={len(out.get('verdicts') or {})} mail={sent} summary={said}")
    return 1 if status in FAILING else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
