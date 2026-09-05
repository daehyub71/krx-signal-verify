/**
 * 종목 화면의 다섯 갈래 + 관측 (F52 · F22 · F23). 서버 컴포넌트 — 동기 렌더라 테스트가 문자열로 확인한다.
 *
 * 순서 고정: 공시 → 뉴스 → 수급 → 재무 → 공매도. **빈 갈래도 자리를 남긴다** — 「생략 — 이유」.
 * 공시·뉴스 제목은 남이 쓴 원문이라 그대로 싣는다. 공시에는 DART 원문 링크가 반드시 붙는다 (N3).
 */

import type { Anomaly, Disclosure, EventBody, EvidenceRow, Financial, InvestorFlows, NewsItem, OutcomeRow } from "@/lib/types";
import { DASH, md, pct, pctPoint, won, wonPlain } from "@/lib/format";
import { horizonCells } from "@/lib/view";

export function dartUrl(rceptNo: string): string {
  return `https://dart.fss.or.kr/dsaf001/main.do?rcptNo=${encodeURIComponent(rceptNo)}`;
}

function Ext() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
      <path d="M14 4h6v6M20 4l-9 9M19 14v6H4V5h6" />
    </svg>
  );
}

function Lane({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="card flex flex-col gap-1.5">
      <div className="h">{n} {title}</div>
      {children}
    </section>
  );
}

function Skip({ why }: { why: string }) {
  return <div className="text-[13px] text-faint">생략 — {why}</div>;
}

const NO_EVIDENCE = "이날의 증거가 저장되지 않았다 (증거 저장은 2026-09-06부터)";

// ── 1 공시 ────────────────────────────────────────────────────────

export function DisclosureLane({ items, bodies, anomaly, stored }: {
  items: Disclosure[] | null; bodies: EventBody[] | null; anomaly: Anomaly | null; stored: boolean;
}) {
  return (
    <Lane n={1} title="공시 · 30일">
      {!stored ? <Skip why={NO_EVIDENCE} /> : items === null ? <Skip why="공시 조회 실패 (DART)" /> : items.length === 0 ? (
        <div className="text-[13px] text-ink-2">30일 안에 공시가 없다</div>
      ) : (
        items.map((it) => {
          const body = bodies?.find((b) => b.rcept_no === it.rcept_no);
          return (
            <div key={it.rcept_no} className="flex flex-col gap-0.5">
              <div className="flex flex-wrap items-baseline gap-2.5 text-[13px]">
                <span className="mono w-[84px] text-muted">{it.rcept_dt}</span>
                <span className="font-semibold">{it.corrected ? "[정정] " : ""}{it.report_nm}</span>
                {it.flr_nm && <span className="text-xs text-faint">{it.flr_nm}</span>}
                <a href={dartUrl(it.rcept_no)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs">
                  DART 원문 <Ext />
                </a>
              </div>
              {body && <div className="pl-[94px] text-[13px] text-ink-2">{bodyLine(body)}</div>}
            </div>
          );
        })
      )}
      {stored && anomaly && (
        <div className="mt-1 text-xs text-muted">
          공시 이상 점수 <span className="mono">{anomaly.score}</span> · {anomaly.verdict}{anomaly.summary ? ` — ${anomaly.summary}` : ""}
        </div>
      )}
    </Lane>
  );
}

export function bodyLine(b: EventBody): string {
  const bits: string[] = [];
  if (b.amount !== null) bits.push(wonPlain(b.amount));
  for (const [use, amt] of b.use_of_funds ?? []) bits.push(`${use} ${wonPlain(amt)}`);
  if (b.method) bits.push(b.method);
  if (b.conv_price !== null) bits.push(`전환가 ${b.conv_price.toLocaleString("ko-KR")}원`);
  if (b.overhang_pct !== null) bits.push(`전환 시 발행주식의 ${b.overhang_pct.toFixed(2)}%`);
  if (b.refix_floor !== null) bits.push(`하향조정 하한 ${b.refix_floor.toLocaleString("ko-KR")}원`);
  if (b.coupon_rate !== null) bits.push(`표면금리 ${b.coupon_rate}%`);
  return bits.join(" · ");
}

// ── 2 뉴스 ────────────────────────────────────────────────────────

export function NewsLane({ items, stored }: { items: NewsItem[] | null; stored: boolean }) {
  return (
    <Lane n={2} title="뉴스 · 관련도순 · 제목에 종목명">
      {!stored ? <Skip why={NO_EVIDENCE} /> : items === null ? <Skip why="뉴스 조회 실패 (네이버)" /> : items.length === 0 ? (
        <div className="text-[13px] text-ink-2">제목에 종목명이 든 뉴스가 없다</div>
      ) : (
        items.slice(0, 8).map((it) => (
          <div key={it.link} className="flex flex-col gap-0.5">
            <div className="flex flex-wrap items-baseline gap-2.5 text-[13px]">
              <span className="mono w-[84px] text-muted">{it.published ?? DASH}</span>
              <a href={it.link} target="_blank" rel="noreferrer" className="font-medium">{it.title}</a>
              {it.source && <span className="text-xs text-faint">[{it.source}]</span>}
            </div>
            {it.summary && <div className="pl-[94px] text-[13px] text-ink-2">{it.summary}</div>}
          </div>
        ))
      )}
    </Lane>
  );
}

// ── 3 수급 ────────────────────────────────────────────────────────

export function FlowsLane({ flows, stored }: { flows: InvestorFlows | null; stored: boolean }) {
  const days = flows?.days ?? [];
  const recent = [...days].sort((a, b) => (a.d < b.d ? 1 : -1)).slice(0, 10);
  const max = Math.max(1, ...recent.flatMap((d) => [Math.abs(d.inst ?? 0), Math.abs(d.foreign ?? 0)]));
  const sum = (k: "inst" | "foreign") => days.reduce<number | null>((acc, d) => (d[k] === null ? acc : (acc ?? 0) + (d[k] as number)), null);
  return (
    <Lane n={3} title="수급 · 기관·외국인 순매수 30일 (원)">
      {!stored ? <Skip why={NO_EVIDENCE} /> : flows === null ? <Skip why="상위 수급 자료 없음" /> : days.length === 0 ? (
        <div className="text-[13px] text-ink-2">30일 안에 수급 행이 없다</div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[13px]">
            {recent.map((d) => (
              <FlowRow key={d.d} d={d.d} inst={d.inst} foreign={d.foreign} max={max} />
            ))}
          </div>
          <div className="mt-1 text-[13px] text-ink-2">
            {days.length}일 누적 외국인 <span className="mono">{won(sum("foreign"))}</span> · 기관 <span className="mono">{won(sum("inst"))}</span>
          </div>
        </>
      )}
    </Lane>
  );
}

function FlowRow({ d, inst, foreign, max }: { d: string; inst: number | null; foreign: number | null; max: number }) {
  return (
    <>
      <Bar label={`${md(d)} 외국인`} v={foreign} max={max} />
      <Bar label={`${md(d)} 기관`} v={inst} max={max} />
    </>
  );
}

function Bar({ label, v, max }: { label: string; v: number | null; max: number }) {
  const w = v === null ? 0 : Math.max(2, Math.round((Math.abs(v) / max) * 100));
  return (
    <div className="flex items-center gap-2.5">
      <span className="mono w-[96px] text-muted">{label}</span>
      <span className="h-2.5 rounded-sm" style={{ width: `${w}%`, maxWidth: 120, background: v === null ? "transparent" : v >= 0 ? "var(--up)" : "var(--down)" }} />
      <span className="mono w-[92px] text-right">{won(v)}</span>
    </div>
  );
}

// ── 4 재무 ────────────────────────────────────────────────────────

export function FinancialLane({ fin, stored }: { fin: Financial | null; stored: boolean }) {
  const line = (name: string, c: Financial["revenue"]) => {
    if (!c) return null;
    const chg = c.prev === null || c.prev === 0 ? "" : ` (${c.period || "전기"} 대비 ${pct(((c.now - c.prev) / Math.abs(c.prev)) * 100)})`;
    return (
      <div key={name} className="flex justify-between text-[13px]">
        <span>{name}</span>
        <span className="mono">{wonPlain(c.now)}{chg}</span>
      </div>
    );
  };
  return (
    <Lane n={4} title={fin ? `재무 · ${fin.report} 기준${fin.basis ? ` (${fin.basis})` : ""}` : "재무"}>
      {!stored ? <Skip why={NO_EVIDENCE} /> : fin === null ? <Skip why="재무 조회 실패 또는 보고서 없음 (DART)" /> : (
        <>
          {line("매출액", fin.revenue)}
          {line("영업이익", fin.operating)}
          {line("당기순이익", fin.net)}
          {fin.debt_ratio !== null && (
            <div className="flex justify-between text-[13px]"><span>부채비율</span><span className="mono">{fin.debt_ratio.toFixed(1)}%</span></div>
          )}
          {fin.equity_wiped_out && <div className="text-[13px] text-ink-2">자본총계가 0 이하라 부채비율을 내지 않았다</div>}
          {fin.retained !== null && (
            <div className="flex justify-between text-[13px]"><span>이익잉여금</span><span className="mono">{wonPlain(fin.retained)}</span></div>
          )}
          {(fin.extra ?? []).map(([name, c]) => line(name, c))}
          {(fin.absent ?? []).map((a) => (
            <div key={a} className="text-xs text-faint">이 보고서에 {a}이 없다</div>
          ))}
        </>
      )}
    </Lane>
  );
}

// ── 5 공매도 ──────────────────────────────────────────────────────

export function ShortingLane({ shorting, stored }: { shorting: unknown | null; stored: boolean }) {
  return (
    <Lane n={5} title="공매도 · 20거래일">
      {!stored ? <Skip why={NO_EVIDENCE} /> : shorting === null ? <Skip why="상위가 아직 수집하지 않는다 (M8 전). 자리는 남긴다" /> : (
        <div className="text-[13px] text-ink-2">{JSON.stringify(shorting).slice(0, 400)}</div>
      )}
    </Lane>
  );
}

// ── 관측 ──────────────────────────────────────────────────────────

export function Observation({ outcome }: { outcome: OutcomeRow | null }) {
  const cells = horizonCells(outcome);
  const market = outcome?.market || "지수";
  return (
    <section className="card flex flex-col gap-1.5">
      <div className="h">관측 · 판정일 기준 거래일 뒤 ({market} 대비)</div>
      <div className="grid grid-cols-[56px_repeat(3,minmax(0,1fr))] gap-x-2 gap-y-1.5 text-[13px]">
        <span /><span className="text-xs text-muted">종목</span><span className="text-xs text-muted">{market}</span><span className="text-xs text-muted">초과</span>
        {cells.map((c) => (
          <Cells key={c.h} h={c.h} stock={c.stock} index={c.index} ex={c.excess} state={c.state} />
        ))}
      </div>
      <div className="text-xs text-faint">
        — 는 아직 오지 않은 구간{cells.some((c) => c.state === "no_index") ? " · 지수가 없어 초과를 내지 않은 구간은 「기준선 미도달」" : ""}. 되돌아보는 값이며 예측이 아니다.
      </div>
    </section>
  );
}

function Cells({ h, stock, index, ex, state }: { h: number; stock: number | null; index: number | null; ex: number | null; state: string }) {
  const faint = { color: "var(--faint)" };
  return (
    <>
      <span className="mono text-muted">{h}일</span>
      <span className="mono" style={stock === null ? faint : undefined}>{pct(stock)}</span>
      <span className="mono" style={index === null ? faint : undefined}>{state === "no_index" ? "기준선 미도달" : pct(index)}</span>
      <span className="mono font-semibold" style={ex === null ? faint : undefined}>{pctPoint(ex)}</span>
    </>
  );
}

/** 증거 행이 있는지 — 없으면 다섯 갈래 전부 「저장되지 않았다」. */
export function stored(e: EvidenceRow | null): boolean {
  return e !== null;
}
