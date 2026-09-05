import { fetchDiscrimination } from "@/lib/queries";
import type { DiscriminationRow, Quartiles } from "@/lib/types";
import { band, latestDiscrimination, overlapText, sampleState } from "@/lib/view";

export const dynamic = "force-dynamic";

/**
 * 분별력 (F54) — 두 군의 초과수익 분포를 겹쳐 본다. **이 화면에서 종목으로 가는 링크는 없다** (R2).
 * 표본 30 미만은 그리지 않고, 성과를 한 숫자로 요약하는 말은 어디에도 없다.
 */
export default async function Page() {
  const rows = latestDiscrimination(await fetchDiscrimination());
  const asOf = rows[0]?.as_of;
  const version = rows[0]?.rules_version;

  return (
    <main className="mx-auto flex max-w-[1376px] flex-col gap-4 px-8 py-6">
      <div>
        <h1 className="text-[24px] font-bold leading-tight">이것은 예측이 아니다 — 정합 군과 불일치 군이 갈리는지를 본다</h1>
        <p className="mt-1 max-w-[980px] text-[13px] text-ink-2">
          판정일 뒤 5·20·60거래일 초과수익(종목 − 시장 지수, %p)을 두 군으로 나눠 분포만 겹쳐 본다.
          종목 하나의 앞날을 말하지 않고, 몇 개가 어떻게 됐는지도 세지 않는다. 표본이 30건에 못 미치는 구간은 그리지 않는다.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4 text-xs text-ink-2">
        <span className="flex items-center gap-1.5"><i className="inline-block h-3 w-3 rounded-sm" style={{ background: "var(--agree)" }} />정합 군 — 사분위 띠(q1~q3)</span>
        <span className="flex items-center gap-1.5"><i className="hatch inline-block h-3 w-3 rounded-sm" />불일치 군 — 빗금</span>
        <span className="flex items-center gap-1.5"><i className="inline-block h-3.5 w-0.5 rounded-sm" style={{ background: "var(--ink)" }} />중앙값</span>
        <span className="text-faint">색 없이도 빗금과 라벨로 읽힌다</span>
        <span className="grow" />
        <span className="mono text-muted">{asOf ? `as_of ${asOf} · 산식 v${version}` : "집계 없음"}</span>
      </div>

      {rows.length === 0 ? (
        <div className="card text-[13px] text-ink-2">아직 집계가 없다 — 첫 배치 뒤 5거래일이 지나야 첫 값이 생긴다.</div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {rows.map((r) => <HorizonCard key={r.horizon} r={r} />)}
        </div>
      )}

      {rows.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <div className="flex items-center justify-between border-b border-line bg-raise px-4 py-2.5">
            <div className="h">숫자 표 — 차트와 같은 값 (차트를 못 보는 경우의 대안)</div>
            <div className="mono text-xs text-muted">단위 %p</div>
          </div>
          <table className="tbl">
            <thead><tr><th>군 · 구간</th><th className="num">n</th><th className="num">q1</th><th className="num">중앙값</th><th className="num">q3</th><th className="num">겹침</th><th>산식</th></tr></thead>
            <tbody>
              {rows.flatMap((r) => [
                <NumRow key={`a${r.horizon}`} label={`정합 · ${r.horizon}일`} n={r.n_aligned} q={r.aligned} overlap={r.overlap} version={r.rules_version} />,
                <NumRow key={`c${r.horizon}`} label={`불일치 · ${r.horizon}일`} n={r.n_conflict} q={r.conflict} overlap={r.overlap} version={r.rules_version} />,
              ])}
            </tbody>
          </table>
        </div>
      )}

      <div className="text-xs text-faint">
        무관 군은 집계에서 뺀다(근거가 없다는 판정이라 비교 대상이 아니다) · 온디맨드 결과는 넣지 않는다(F43) · 산식이 바뀌면 판마다 따로 집계한다 · 이 화면에서 종목으로 가는 링크는 없다
      </div>
    </main>
  );
}

function HorizonCard({ r }: { r: DiscriminationRow }) {
  const s = sampleState(r.n_aligned, r.n_conflict);
  const a = band(r.aligned);
  const c = band(r.conflict);
  return (
    <section className="card">
      <div className="flex items-baseline justify-between"><div className="h">{r.horizon}거래일 뒤</div></div>
      {!s.enough || !a || !c ? (
        <div className="my-3 flex h-28 items-center justify-center rounded-md border border-dashed border-line-2 text-center text-[13px] leading-relaxed text-muted">
          <span>표본 부족<br /><span className="mono text-xs">정합 n={r.n_aligned} · 불일치 n={r.n_conflict} · 필요 30</span></span>
        </div>
      ) : (
        <div className="relative my-3 h-28">
          {[0, 25, 50, 75, 100].map((x) => (
            <i key={x} className="absolute top-0 bottom-5 w-px" style={{ left: `${x}%`, background: x === 50 ? "var(--line-2)" : "var(--line)" }} />
          ))}
          {[["−10", 0], ["−5", 25], ["0 %p", 50], ["+5", 75], ["+10", 100]].map(([t, x]) => (
            <span key={t} className="absolute bottom-0 -translate-x-1/2 text-[11px] text-faint" style={{ left: `${x}%` }}>{t}</span>
          ))}
          <i className="absolute h-[22px] rounded-sm" style={{ top: 14, left: `${a.left}%`, width: `${a.width}%`, background: "var(--agree)", boxShadow: "0 0 0 2px var(--surface)" }} />
          {a.median !== null && <i className="absolute h-[30px] w-0.5 -translate-x-1/2 rounded-sm" style={{ top: 10, left: `${a.median}%`, background: "var(--ink)" }} />}
          <span className="absolute text-xs text-ink-2" style={{ top: 42, left: `${a.left}%` }}>정합 <b>n={r.n_aligned}</b> · 중앙 <b className="mono">{fmt(r.aligned.median)}</b></span>
          <i className="hatch absolute h-[22px] rounded-sm" style={{ top: 58, left: `${c.left}%`, width: `${c.width}%`, boxShadow: "0 0 0 2px var(--surface)" }} />
          {c.median !== null && <i className="absolute h-[30px] w-0.5 -translate-x-1/2 rounded-sm" style={{ top: 54, left: `${c.median}%`, background: "var(--ink)" }} />}
          <span className="absolute text-xs text-ink-2" style={{ top: 84, left: `${c.left}%` }}>불일치 <b>n={r.n_conflict}</b> · 중앙 <b className="mono">{fmt(r.conflict.median)}</b></span>
        </div>
      )}
      <div className="text-xs text-muted">
        겹침 <span className="mono text-ink">{overlapText(r.overlap)}</span> — 1이면 완전히 겹친다(구분 못 한다), 0이면 전혀 안 겹친다
      </div>
    </section>
  );
}

function fmt(v: number | null): string {
  if (v === null) return "—";
  return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1);
}

function NumRow({ label, n, q, overlap, version }: { label: string; n: number; q: Quartiles; overlap: number | null; version: string }) {
  const dim = { color: "var(--faint)" };
  return (
    <tr>
      <td className={n === 0 ? "text-muted" : ""}>{label}</td>
      <td className="mono num">{n}</td>
      <td className="mono num" style={q.q1 === null ? dim : undefined}>{fmt(q.q1)}</td>
      <td className="mono num font-semibold" style={q.median === null ? dim : undefined}>{fmt(q.median)}</td>
      <td className="mono num" style={q.q3 === null ? dim : undefined}>{fmt(q.q3)}</td>
      <td className="mono num" style={overlap === null ? dim : undefined}>{overlapText(overlap)}</td>
      <td className="mono text-muted">v{version}</td>
    </tr>
  );
}
