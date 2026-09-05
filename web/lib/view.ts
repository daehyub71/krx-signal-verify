/**
 * 화면 논리 — 순수 함수. DB도 React도 모른다.
 *
 * 여기 있는 것은 전부 DESIGN §2의 규칙을 코드로 옮긴 것이다:
 * 점수 오름차순(불일치가 위) · 미도래는 `—` · 표본 30 미만은 그리지 않음 · 하루 한도와 동시 1건.
 */

import type {
  DiscriminationRow,
  Horizon,
  OutcomeRow,
  RequestStatus,
  Stand,
  VerdictPart,
  VerdictRow,
} from "./types";
import { HORIZONS } from "./types";

// ── 오늘 (F51) ────────────────────────────────────────────────────

/** 점수 낮은 것부터 — 메일과 같다. 같으면 티커. */
export function sortByScore<T extends { score: number; ticker: string }>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => a.score - b.score || a.ticker.localeCompare(b.ticker));
}

export function countStands(rows: readonly { stand: Stand }[]): Record<Stand, number> {
  const out: Record<Stand, number> = { 정합: 0, 불일치: 0, 무관: 0 };
  for (const r of rows) out[r.stand] += 1;
  return out;
}

/** 근거 요약 — 영향이 큰 것부터 n개. */
export function topParts(parts: readonly VerdictPart[], n = 2): VerdictPart[] {
  return [...parts].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)).slice(0, n);
}

export function filterRows(
  rows: readonly VerdictRow[],
  f: { stand?: Stand | ""; strategy?: string },
): VerdictRow[] {
  return rows.filter((r) => (!f.stand || r.stand === f.stand) && (!f.strategy || r.strategy === f.strategy));
}

// ── 관측 (F22·F23) ────────────────────────────────────────────────

export type CellState = "ok" | "pending" | "no_index";

export interface HorizonCell {
  h: Horizon;
  stock: number | null;
  index: number | null;
  excess: number | null;
  state: CellState;
}

/** 종목 % − 지수 %. 어느 하나가 없으면 null — 프록시로 대신 재지 않는다 (F23b). */
export function excess(stock: number | null, index: number | null): number | null {
  return stock === null || index === null ? null : stock - index;
}

/** 5·20·60 셀. 종목 값이 없으면 미도래, 종목은 있는데 지수가 없으면 「기준선 미도달」. */
export function horizonCells(o: Pick<OutcomeRow, "h5" | "h20" | "h60" | "h5_index" | "h20_index" | "h60_index"> | null): HorizonCell[] {
  return HORIZONS.map((h) => {
    const stock = o ? o[`h${h}` as const] : null;
    const index = o ? o[`h${h}_index` as const] : null;
    const state: CellState = stock === null ? "pending" : index === null ? "no_index" : "ok";
    return { h, stock, index, excess: excess(stock, index), state };
  });
}

// ── 이력 (F53) ────────────────────────────────────────────────────

/** 산식 판이 바뀐 경계 — 그 행 **앞에** 「v1.1부터」 구분선을 그린다. 정렬된 입력을 받는다. */
export function versionBreaks(rows: readonly { rules_version: string }[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < rows.length; i++) {
    if (rows[i].rules_version !== rows[i - 1].rules_version) out.push(i);
  }
  return out;
}

// ── 분별력 (F54) ──────────────────────────────────────────────────

export const MIN_SAMPLE = 30;

export interface SampleState {
  enough: boolean;
  text: string;
}

/** 두 군이 모두 30건 이상일 때만 그린다. 아니면 문장으로. **성과를 요약하는 숫자는 어디에도 없다** (R2). */
export function sampleState(nAligned: number, nConflict: number, min = MIN_SAMPLE): SampleState {
  const enough = nAligned >= min && nConflict >= min;
  return {
    enough,
    text: enough
      ? `정합 n=${nAligned} · 불일치 n=${nConflict}`
      : `표본 부족 (정합 n=${nAligned} · 불일치 n=${nConflict} · 필요 ${min})`,
  };
}

export interface Band {
  left: number;
  width: number;
  median: number | null;
}

/** 사분위 띠의 위치(%) — 축은 `−domain … +domain` %p. 밖으로 나가면 잘라 붙인다. */
export function band(q: { q1: number | null; median: number | null; q3: number | null }, domain = 10): Band | null {
  if (q.q1 === null || q.q3 === null) return null;
  const pos = (v: number) => Math.min(100, Math.max(0, ((v + domain) / (2 * domain)) * 100));
  const left = pos(q.q1);
  const right = pos(q.q3);
  return { left, width: Math.max(0, right - left), median: q.median === null ? null : pos(q.median) };
}

/** 겹침 0~1을 사람 말로. */
export function overlapText(v: number | null): string {
  if (v === null) return "—";
  return v.toFixed(2);
}

/** 최신 `as_of`의 행만, 구간 순서로. 판이 여럿이면 최신 판. */
export function latestDiscrimination(rows: readonly DiscriminationRow[]): DiscriminationRow[] {
  if (rows.length === 0) return [];
  const asOf = rows.map((r) => r.as_of).sort().at(-1)!;
  const latest = rows.filter((r) => r.as_of === asOf);
  const version = latest.map((r) => r.rules_version).sort().at(-1)!;
  return HORIZONS.flatMap((h) => latest.filter((r) => r.horizon === h && r.rules_version === version));
}

// ── 온디맨드 (F41·F42) ────────────────────────────────────────────

export interface Quota {
  used: number;
  limit: number;
  remaining: number;
  busy: boolean;
  canRequest: boolean;
  reason: "" | "limit" | "busy";
}

/** 하루 상한과 동시 1건. 화면 숫자는 표시일 뿐이고 **서버가 같은 함수로 센다.** */
export function quota(usedToday: number, activeCount: number, limit: number): Quota {
  const remaining = Math.max(0, limit - usedToday);
  const busy = activeCount > 0;
  const reason: Quota["reason"] = remaining === 0 ? "limit" : busy ? "busy" : "";
  return { used: usedToday, limit, remaining, busy, canRequest: reason === "", reason };
}

/** 상태 스텝퍼의 위치 — 요청 접수 → 대기 → 처리 중 → 완료. 실패는 처리 중 자리에서 멈춘다. */
export function requestStep(status: RequestStatus): number {
  return { queued: 1, running: 2, done: 3, failed: 2 }[status];
}

/** `ONDEMAND_DAILY_LIMIT` 해석 — 비었거나 이상하면 5. */
export function dailyLimit(raw: string | undefined): number {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : 5;
}
