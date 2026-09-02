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
    return p.parse_args(argv)


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


def main(
    argv: list[str] | None = None,
    *,
    overrides: Mapping[str, Callable[..., dict[str, Any]]] | None = None,
    verified_check: Callable[[date], bool] | None = None,
) -> int:
    """한 번 돌리고 종료 코드를 돌려준다.

    Args:
        argv: CLI 인자. None이면 `sys.argv`.
        overrides: 노드 대체 (테스트용).
        verified_check: 그날 이미 돌았는지 묻는다. M0에서는 주입으로만 쓴다.

    Returns:
        0(정상) 또는 1(실패). **부분 성공을 성공으로 위장하지 않는다.**
    """
    config.load_env()
    args = parse_args(argv)

    if args.if_not_verified and not args.force and verified_check and verified_check(args.run_date):
        print(f"{args.run_date}는 이미 검증했다 — 아무것도 하지 않는다")
        return 0

    app = graph.build_graph(overrides)
    out = app.invoke(initial_state(args), {"recursion_limit": st.RECURSION_LIMIT})

    status = str(out.get("status", st.STATUS_FAILED))
    for err in out.get("errors", []):
        print(f"⚠ {err}", file=sys.stderr)
    print(f"status={status} signals={len(out.get('signals', []))} "
          f"evidence={len(out.get('evidence', []))} outcomes={out.get('outcomes_filled', 0)}")
    return 1 if status in FAILING else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
