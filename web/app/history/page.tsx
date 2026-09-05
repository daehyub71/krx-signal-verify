import Link from "next/link";
import { StandChip } from "../components/StandChip";
import { dayLabel, fullDate, isTicker, pctPoint } from "@/lib/format";
import { fetchDates, fetchHistory, fetchLatestDate } from "@/lib/queries";
import { excess, versionBreaks } from "@/lib/view";

export const dynamic = "force-dynamic";

type Props = { searchParams: Promise<{ d?: string; ticker?: string }> };

/** 이력 (F53) — 날짜·종목으로 과거 판정. 판정 시점의 산식 판을 함께 보이고, 판이 바뀐 경계에 구분선. */
export default async function Page({ searchParams }: Props) {
  const sp = await searchParams;
  const ticker = sp.ticker && isTicker(sp.ticker.toUpperCase()) ? sp.ticker.toUpperCase() : "";
  const [dates, latest] = await Promise.all([fetchDates(60), fetchLatestDate()]);
  const d = ticker ? undefined : sp.d && dates.some((x) => x.d === sp.d) ? sp.d : latest ?? undefined;
  const rows = d || ticker ? await fetchHistory({ d, ticker }) : [];
  const breaks = new Set(versionBreaks(rows));

  return (
    <main className="mx-auto grid max-w-[1376px] grid-cols-[220px_minmax(0,1fr)] gap-5 px-8 py-6">
      <aside className="flex flex-col gap-1">
        <form action="/history" method="get" className="mb-2 flex gap-1.5">
          <input name="ticker" defaultValue={ticker} placeholder="종목코드" maxLength={6} aria-label="종목 검색" className="mono h-9 w-full rounded-md border border-line-2 bg-surface px-3 text-[13px] text-ink outline-none focus:border-ink" />
          <button type="submit" className="h-9 rounded-md border border-line-2 px-3 text-[13px] text-ink-2">검색</button>
        </form>
        <div className="h px-3 pb-1.5">최근 거래일 · 판정 수</div>
        {dates.map((x) => (
          <Link key={x.d} href={`/history?d=${x.d}`} className={`flex h-9 items-center justify-between rounded-md px-3 text-[13px] no-underline ${x.d === d ? "bg-ink text-surface" : "text-ink-2"}`}>
            <span className="mono">{dayLabel(x.d)}</span><span className="mono">{x.n}</span>
          </Link>
        ))}
        <div className="px-3 pt-2 text-xs text-faint">소급하지 않는다(V13). 표본은 첫 배치가 돈 날부터 실시간으로만 쌓인다.</div>
      </aside>

      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex items-end gap-4">
          <h1 className="text-[22px] font-bold">{ticker ? <><span className="mono">{ticker}</span> 판정 이력</> : d ? `${fullDate(d)} 판정` : "판정 이력"}</h1>
          <span className="mono text-[13px] text-muted">{rows.length}건{rows[0] ? ` · 산식 v${rows[0].rules_version}` : ""}</span>
          <span className="grow" />
          <span className="text-xs text-muted">판정 시점의 산식 판을 함께 본다 — 판이 다르면 다른 자로 잰 값이다</span>
        </div>

        <div className="card overflow-x-auto p-0">
          <table className="tbl">
            <thead>
              <tr>
                <th>판정일</th><th>종목</th><th>판정</th><th className="num">점수</th><th>산식</th><th>출처</th>
                <th className="num">5일 초과</th><th className="num">20일</th><th className="num">60일</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={10} className="text-[13px] text-muted">{ticker ? "이 종목에 판정이 없다" : "판정 없음"}</td></tr>
              )}
              {rows.map((r, i) => (
                <RowWithBreak key={`${r.d}-${r.ticker}-${r.source}`} r={r} brk={breaks.has(i)} />
              ))}
            </tbody>
          </table>
        </div>
        <div className="text-xs text-faint">초과 — 는 미도래(판정일에서 그만큼의 거래일이 아직 지나지 않았다) 또는 지수 기준선 미도달.</div>
      </div>
    </main>
  );
}

type Row = Awaited<ReturnType<typeof fetchHistory>>[number];

function RowWithBreak({ r, brk }: { r: Row; brk: boolean }) {
  const cell = (v: number | null) => (
    <td className="mono num" style={v === null ? { color: "var(--faint)" } : undefined}>{pctPoint(v)}</td>
  );
  return (
    <>
      {brk && (
        <tr><td colSpan={10} className="bg-raise text-xs text-faint" style={{ height: 28 }}>산식 v{r.rules_version}부터 — 위아래는 서로 다른 자로 잰 값이라 한 줄로 이어 읽지 않는다</td></tr>
      )}
      <tr>
        <td className="mono text-muted">{r.d}</td>
        <td>
          <Link href={`/t/${r.ticker}?d=${r.d}&source=${r.source}`} className="font-semibold text-ink no-underline">{r.name || r.ticker}</Link>
          <span className="mono ml-1.5 text-xs text-muted">{r.ticker}</span>
        </td>
        <td><StandChip stand={r.stand} /></td>
        <td className="mono num font-semibold">{r.score}</td>
        <td className="mono text-ink-2">v{r.rules_version}</td>
        <td className="text-xs text-ink-2">{r.source}</td>
        {cell(excess(r.h5, r.h5_index))}
        {cell(excess(r.h20, r.h20_index))}
        {cell(excess(r.h60, r.h60_index))}
        <td className="text-muted"><Link href={`/t/${r.ticker}?d=${r.d}&source=${r.source}`} className="no-underline">→</Link></td>
      </tr>
    </>
  );
}
