"""MCP 서버 실물 확인 — 테스트는 전부 mock이므로(N14) 여기서 한 번 진짜로 붙여 본다.

    python scripts/mcp_probe.py

세션을 배치당 1회만 여는지, 도구가 실제로 답하는지, 죽은 서버가 즉시 실패하는지를 눈으로 본다.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from verify import mcpc  # noqa: E402
from verify.config import load_env  # noqa: E402


def main() -> int:
    load_env()
    ok = True
    for name in mcpc.SERVERS:
        spec = mcpc.SERVERS[name]
        gaps = spec.missing_credentials()
        if gaps:
            print(f"[{name}] 자격증명 없음: {', '.join(gaps)} — 건너뛴다")
            continue
        t0 = time.monotonic()
        try:
            s = mcpc.get(name)
        except mcpc.McpStartError as exc:
            print(f"[{name}] 기동 실패: {exc}")
            ok = False
            continue
        boot = time.monotonic() - t0
        print(f"[{name}] 기동 {boot:.1f}초 (실측 상한 {spec.cold_start_seconds}초) · "
              f"도구 {len(s.tools)}개")

        tool, args = (
            ("resolve_corp_code", {"query": "삼성전자"})
            if name == "dart"
            else ("search_news", {"query": "삼성전자", "display": 1, "sort": "sim"})
        )
        t1 = time.monotonic()
        try:
            body = s.call(tool, args)
            print(f"  {tool} {time.monotonic() - t1:.1f}초 · {len(body)}자 · {body[:110]!r}")
        except mcpc.McpError as exc:
            print(f"  {tool} 실패: {type(exc).__name__}: {exc}")
            ok = False

        # 두 번째 호출 — 세션을 다시 열지 않는다 (배치당 1회)
        t2 = time.monotonic()
        try:
            s.call(tool, args)
            print(f"  재호출 {time.monotonic() - t2:.1f}초 (기동 없이)")
        except mcpc.McpError as exc:
            print(f"  재호출 실패: {exc}")
            ok = False

        try:
            s.call("존재하지_않는_도구")
        except mcpc.McpCallError as exc:
            print(f"  없는 도구 → {type(exc).__name__} (세션 살아 있음: {s.available})")

    mcpc.close_all()
    print("닫음" if ok else "일부 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
