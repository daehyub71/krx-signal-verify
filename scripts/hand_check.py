"""손검증 — 코드가 낸 값을 **DART 원문과 눈으로 대조한다** (M2 완료 기준).

    python scripts/hand_check.py

테스트는 전부 mock이라(N14) 여기서만 실물이 맞는지 본다. 세 가지를 본다.

1. **재무 5종목** — `financial.py`가 낸 값이 DART 원문(`fnlttMultiAcnt.json` 응답)과 같은가.
   **금융사 1종목을 반드시 포함한다** — F31이 정직하게 비우는지 보려는 것이다.
2. **MCP 폴백** — 공시 MCP를 죽였을 때 REST가 **같은 목록**을 주는가 (F34·D15).
3. **갈래 격리** — 갈래 하나를 죽여도 나머지가 오고 판정이 나가는가 (F34).

공매도 5종목 KRX 대조는 M8 이후다 — `ksc_shorting`이 아직 없다.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import Any

from verify import (  # noqa: E402
    config,
    corp,
    dart,
    dart_fin,
    dart_mcp,
    financial,
    lanes,
    mcpc,
    shorting,
    store,
)

TODAY = dt.date.today()


def _pick(cur: Any, n: int = 4) -> list[tuple[str, str, str]]:
    """일반 종목 n개 + **금융사 1개**. 금융사가 없으면 F31을 못 본다."""
    cur.execute(
        "select ticker, name, sector from ksc_tickers where sector is not null "
        "and sector not in ('보험','증권','은행') order by ticker limit %s",
        (n,),
    )
    rows: list[tuple[str, str, str]] = list(cur.fetchall())
    cur.execute(
        "select ticker, name, sector from ksc_tickers "
        "where sector = '보험' order by ticker limit 1"
    )
    return rows + list(cur.fetchall())


def check_financials(cur: Any, codes: dict[str, str]) -> int:
    print("① 재무 5종목 — 코드가 낸 값 ↔ DART 원문")
    picks = _pick(cur)
    pairs = [(t, codes[t]) for t, _, _ in picks if t in codes]
    got = dart_fin.fetch_accounts([cc for _, cc in pairs], TODAY)
    bad = 0
    for (ticker, name, sector), (_, cc) in zip(picks, pairs, strict=False):
        acc = got.get(cc)
        if acc is None:
            print(f"   [{name}({ticker}) · {sector}] 보고서를 못 찾았다")
            continue
        f = financial.read(acc)
        raw = {
            financial.normalize(str(x["account_nm"])): x["thstrm_amount"]
            for x in acc.items if x["fs_div"] == ("CFS" if f.basis == "연결" else "OFS")
        }
        print(f"\n   [{name}({ticker}) · {sector}] {f.report} ({f.basis})")
        for label, c in (("매출액", f.revenue), ("영업이익", f.operating), ("당기순이익", f.net)):
            if c is None:
                mark = "원문에도 없음 ✓" if label not in raw else f"⚠ 원문엔 {raw[label]} 있음"
                print(f"     {label:<6s} 비움 — {mark}")
                bad += 0 if label not in raw else 1
                continue
            same = financial.amount(raw.get(label)) == c.now
            mark = "✓" if same else "⚠"
            print(f"     {label:<6s} {c.now:>22,} ↔ 원문 {raw.get(label):>24s} {mark}")
            bad += 0 if same else 1
        if f.debt_ratio is not None:
            liab, eq = financial.amount(raw.get("부채총계")), financial.amount(raw.get("자본총계"))
            calc = liab / eq * 100 if liab and eq else None
            ok = calc is not None and abs(calc - f.debt_ratio) < 0.01
            shown = f"{calc:.1f}%" if calc is not None else "—"
            print(f"     부채비율 {f.debt_ratio:>21.1f}% ↔ 원문 계산 {shown} {'✓' if ok else '⚠'}")
            bad += 0 if ok else 1
        if f.absent:
            print(f"     비운 항목: {' · '.join(f.absent)}")
    return bad


def check_fallback(codes: dict[str, str]) -> int:
    print("\n② MCP 폴백 — 공시 MCP를 죽였을 때")
    cc = codes.get("005930", "00126380")
    end, bgn = TODAY, TODAY - dt.timedelta(days=30)

    class Dead:
        def call_json(self, *a: object, **k: object) -> object:
            raise mcpc.McpProtocolError("[dart] 세션 파손 — 손검증용")

    live, src1 = dart_mcp.fetch_disclosures(cc, bgn, end)
    fell, src2 = dart_mcp.fetch_disclosures(cc, bgn, end, server=Dead())
    same = {d.rcept_no for d in live} == {d.rcept_no for d in fell}
    print(f"   MCP  {len(live):>3d}건 (출처={src1})")
    print(f"   폴백 {len(fell):>3d}건 (출처={src2})")
    print(f"   수번호 집합 일치: {'✓' if same else '⚠'}")
    return 0 if (same and src2 == dart_mcp.SOURCE_REST) else 1


def check_lanes(cur: Any) -> int:
    print("\n③ 갈래 격리 — 하나를 죽여도 나머지가 온다")

    def boom() -> object:
        raise RuntimeError("손검증용 강제 실패")

    got = lanes.collect(
        d=TODAY, ticker="005930",
        disclosures=lambda: ["공시 1건"], news=boom, flows=lambda: "수급",
        financial=lambda: "재무", shorting=lambda: None,
    )
    print(f"   생략: {' · '.join(got.skipped)}")
    print(f"   이유: {got.reasons.get('뉴스', '')}")
    print(f"   표기: {' / '.join(got.notes())}")
    print(f"   남은 갈래: 공시={got.evidence.disclosures} · 수급={got.evidence.flows}")

    f = lanes.freshness(cur, today=TODAY)
    print(f"\n   상위 신선도: 기준일={f.data_date} · {f.days_behind}일 뒤 · 낡음={f.stale}")
    print(f"   {f.note or '(정상 — 아무 말도 하지 않는다)'}")

    s = shorting.probe(cur)
    print(f"   공매도 갈래: {s.state} (ok={s.ok}) — {s.reason}")
    return 0 if (got.skipped == ("뉴스", "공매도") and got.evidence.disclosures) else 1


def main() -> int:
    config.load_env()
    codes = corp.parse_corp_codes(dart.fetch_corp_codes())
    with store.connect() as conn, conn.cursor() as cur:
        bad = check_financials(cur, codes) + check_fallback(codes) + check_lanes(cur)
    mcpc.close_all()
    print(f"\n{'손검증 통과' if bad == 0 else f'어긋남 {bad}건'}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
