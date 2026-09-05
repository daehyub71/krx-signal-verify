import Link from "next/link";
import { notFound } from "next/navigation";
import { StandChip } from "../../components/StandChip";
import { DisclosureLane, FinancialLane, FlowsLane, NewsLane, Observation, ShortingLane } from "../../components/lanes";
import { dayLabel, isTicker } from "@/lib/format";
import { fetchEvidence, fetchOutcome, fetchTickerDates, fetchVerdict } from "@/lib/queries";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ ticker: string }>; searchParams: Promise<{ d?: string; source?: string }> };

/** 종목 (F52) — 증거 다섯 갈래를 한 화면에. 한계 문구는 점수 바로 아래, 접히지 않는다. */
export default async function Page({ params, searchParams }: Props) {
  const { ticker: raw } = await params;
  const ticker = raw.toUpperCase();
  if (!isTicker(ticker)) notFound();
  const sp = await searchParams;
  const dates = await fetchTickerDates(ticker);
  if (dates.length === 0) {
    return (
      <main className="mx-auto max-w-[1376px] px-8 py-16 text-center text-muted">
        <span className="mono">{ticker}</span>에 판정이 없다. 오늘 신호가 있으면 상단에서 온디맨드로 요청할 수 있다.
      </main>
    );
  }
  const d = sp.d && dates.includes(sp.d) ? sp.d : dates[0];
  const source = sp.source === "ondemand" || sp.source === "batch" || sp.source === "backfill" ? sp.source : undefined;
  const [v, e, o] = await Promise.all([fetchVerdict(ticker, d, source), fetchEvidence(ticker, d), fetchOutcome(ticker, d)]);
  if (!v) notFound();
  const stored = e !== null;

  return (
    <main className="mx-auto flex max-w-[1376px] flex-col gap-4 px-8 py-5">
      <div className="flex items-center gap-3 text-xs text-muted">
        <Link href={`/?d=${d}`} className="no-underline">← {dayLabel(d)} 판정</Link>
        <span className="grow" />
        {dates.slice(0, 10).map((x) => (
          <Link key={x} href={`/t/${ticker}?d=${x}`} className={`mono rounded-md px-2 py-0.5 no-underline ${x === d ? "bg-ink text-surface" : "text-ink-2"}`}>{x}</Link>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2 flex flex-col gap-3">
          <section className="card flex flex-col gap-2.5">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-[22px] font-bold">{v.name || ticker}</h1>
              <span className="mono text-muted">{ticker}{o?.market ? ` · ${o.market}` : ""} · {v.strategy}</span>
              <span className="grow" />
              <StandChip stand={v.stand} />
              <span className="mono text-[28px] font-bold leading-none">{v.score}</span>
              <span className="mono text-xs text-faint">{v.d} · 산식 v{v.rules_version} · {v.source}</span>
            </div>
            <div className="border-l-2 border-line-2 pl-2.5 text-[13px] text-ink-2">
              이 점수는 신호의 근거가 받쳐지는지를 재며, {v.blind_spots.length ? v.blind_spots.join(" · ") : "보지 않는 것들"}을 보지 않는다. 앞으로의 주가를 말하지 않는다.
            </div>
            <div className="flex flex-wrap gap-x-3.5 gap-y-1.5 text-[13px]">
              <span className="mono text-muted">50</span>
              {v.parts.map((p) => (
                <span key={p.label}>{p.label} <span className="mono">{p.delta > 0 ? `+${p.delta}` : p.delta}</span></span>
              ))}
            </div>
          </section>

          <DisclosureLane items={e?.disclosures ?? null} bodies={e?.bodies ?? null} anomaly={e?.anomaly ?? null} stored={stored} />
          <NewsLane items={e?.news ?? null} stored={stored} />
          <FlowsLane flows={e?.flows ?? null} stored={stored} />
        </div>

        <div className="flex flex-col gap-3">
          <Observation outcome={o} />
          <FinancialLane fin={e?.financial ?? null} stored={stored} />
          <ShortingLane shorting={e?.shorting ?? null} stored={stored} />
          <section className="card flex grow flex-col gap-1.5">
            <div className="h">서술 · LLM</div>
            {v.summary ? (
              <div className="text-[13px] text-ink-2">{v.summary}</div>
            ) : (
              <div className="text-[13px] text-faint">⚠ 서술 생략 — 판정·점수는 코드가 냈고 설명만 없다</div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
