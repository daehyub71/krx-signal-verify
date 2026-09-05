import Link from "next/link";
import { StandChip } from "./components/StandChip";
import { fetchDates, fetchDay, fetchDayMissing, fetchLatestDate, fetchRunFor } from "@/lib/queries";
import { dayLabel, fullDate } from "@/lib/format";
import type { Stand, VerdictRow } from "@/lib/types";
import { countStands, filterRows, sortByScore, topParts } from "@/lib/view";

export const dynamic = "force-dynamic";

type Props = { searchParams: Promise<{ d?: string; stand?: string; strategy?: string; sort?: string }> };

const STANDS: Stand[] = ["정합", "불일치", "무관"];

/** 오늘 (F51) — 그날 판정을 표로. 기본 정렬은 점수 낮은 것부터(메일과 같다). */
export default async function Page({ searchParams }: Props) {
  const sp = await searchParams;
  const latest = await fetchLatestDate();
  if (!latest) {
    return (
      <main className="mx-auto max-w-[1376px] px-8 py-16 text-center text-muted">
        아직 판정이 없다. 배치가 한 번도 돌지 않았거나 저장에 실패했다.
      </main>
    );
  }
  const dates = await fetchDates(20);
  const d = sp.d && dates.some((x) => x.d === sp.d) ? sp.d : latest;
  const [rows, missing, run] = await Promise.all([fetchDay(d), fetchDayMissing(d), fetchRunFor(d)]);
  const missingOf = new Map(missing.map((m) => [m.ticker, m.missing]));

  const stand = STANDS.includes(sp.stand as Stand) ? (sp.stand as Stand) : "";
  const strategies = [...new Set(rows.map((r) => r.strategy))].sort();
  const strategy = strategies.includes(sp.strategy ?? "") ? sp.strategy! : "";
  const shown = sortRows(filterRows(rows, { stand, strategy }), sp.sort);
  const counts = countStands(rows);

  const href = (over: Partial<Record<"d" | "stand" | "strategy" | "sort", string>>) => {
    const p = new URLSearchParams();
    const merged = { d, stand, strategy, sort: sp.sort ?? "", ...over };
    for (const [k, v] of Object.entries(merged)) if (v) p.set(k, v);
    return `/?${p.toString()}`;
  };

  return (
    <main className="mx-auto flex max-w-[1376px] flex-col gap-4 px-8 py-6">
      <div className="flex flex-wrap items-end gap-4">
        <h1 className="text-[22px] font-bold">{fullDate(d)} 판정</h1>
        <div className="flex items-center gap-2 text-[13px]">
          {STANDS.map((s) => (
            <Link key={s} href={href({ stand: stand === s ? "" : s })} className="flex items-center gap-1.5 no-underline" style={{ opacity: stand && stand !== s ? 0.45 : 1 }}>
              <StandChip stand={s} small /> <span className="mono text-ink">{counts[s]}</span>
            </Link>
          ))}
        </div>
        <div className="grow" />
        <div className="flex items-center gap-1.5 text-xs text-muted">
          {dates.slice(0, 8).map((x) => (
            <Link key={x.d} href={href({ d: x.d })} className={`mono rounded-md px-2 py-1 no-underline ${x.d === d ? "bg-ink text-surface" : "text-ink-2"}`}>
              {dayLabel(x.d)} <span style={{ opacity: 0.7 }}>{x.n}</span>
            </Link>
          ))}
        </div>
      </div>

      {run && run.status !== "ok" && run.status !== "no_signals" && (
        <div className="rounded-md border border-line bg-raise px-3 py-2 text-[13px] text-ink-2">
          이날 실행은 <span className="mono">{run.status}</span>{run.gate ? ` (게이트 ${run.gate})` : ""}으로 끝났다 — 상위 자료가 낡았거나 오지 않았다.
        </div>
      )}

      {strategies.length > 1 && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted">전략</span>
          {strategies.map((s) => (
            <Link key={s} href={href({ strategy: strategy === s ? "" : s })} className={`mono rounded-md border px-2 py-0.5 no-underline ${strategy === s ? "border-ink text-ink" : "border-line-2 text-ink-2"}`}>{s}</Link>
          ))}
        </div>
      )}

      {rows.length === 0 ? (
        <div className="card text-[13px] text-ink-2">그날 검증할 신호가 없었다.</div>
      ) : (
        <div className="card overflow-x-auto p-0">
          <table className="tbl">
            <thead>
              <tr>
                <th><Link href={href({ sort: "ticker" })} className="text-muted no-underline">종목</Link></th>
                <th>전략</th>
                <th><Link href={href({ sort: "stand" })} className="text-muted no-underline">판정</Link></th>
                <th className="num"><Link href={href({ sort: "" })} className="text-muted no-underline">점수 ↑</Link></th>
                <th>근거 요약</th>
                <th>생략</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={`${r.ticker}-${r.source}`}>
                  <td>
                    <Link href={`/t/${r.ticker}?d=${r.d}&source=${r.source}`} className="font-semibold text-ink no-underline">{r.name || r.ticker}</Link>
                    <span className="mono ml-1.5 text-xs text-muted">{r.ticker}</span>
                    {r.source !== "batch" && <span className="ml-1.5 text-xs text-faint">{r.source}</span>}
                  </td>
                  <td className="mono text-ink-2">{r.strategy}</td>
                  <td><StandChip stand={r.stand} /></td>
                  <td className="mono num font-semibold">{r.score}</td>
                  <td className="text-[13px] text-ink-2" style={{ whiteSpace: "normal" }}>
                    {topParts(r.parts).map((p) => (
                      <span key={p.label} className="mr-3">{p.label} <span className="mono">{p.delta > 0 ? `+${p.delta}` : p.delta}</span></span>
                    ))}
                  </td>
                  <td className="text-xs text-faint">{missingOf.get(r.ticker)?.join(" · ") ?? ""}</td>
                  <td className="text-muted"><Link href={`/t/${r.ticker}?d=${r.d}&source=${r.source}`} className="no-underline">→</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="text-xs text-faint">
        점수는 신호의 근거가 받쳐지는지를 재며 공매도 · 실적·밸류에이션 · 업황 · 시장 전체 흐름을 보지 않는다. 앞으로의 주가를 말하지 않는다.
      </div>
    </main>
  );
}

function sortRows(rows: VerdictRow[], sort?: string): VerdictRow[] {
  if (sort === "ticker") return [...rows].sort((a, b) => a.ticker.localeCompare(b.ticker));
  if (sort === "stand") {
    const order: Record<Stand, number> = { 불일치: 0, 무관: 1, 정합: 2 };
    return [...rows].sort((a, b) => order[a.stand] - order[b.stand] || a.score - b.score);
  }
  return sortByScore(rows);
}
