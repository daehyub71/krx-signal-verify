/**
 * 조회·요청 — 서버 컴포넌트와 라우트 핸들러만 부른다.
 *
 * 전부 「인자 → 행」이다. 화면 규칙(정렬·필터·표본 판정)은 `lib/view.ts`에 있다 —
 * 여기서는 SQL만.
 */

import "server-only";
import { one, q } from "./db";
import type {
  DiscriminationRow,
  EvidenceRow,
  HistoryRow,
  OutcomeRow,
  RequestRow,
  RunRow,
  VerdictRow,
} from "./types";

const VERDICT_COLS =
  "d, ticker, source, name, strategy, stand, score, parts, blind_spots, rules_version, summary";

/** 판정이 있는 날들 — 최신순, 그날 판정 수. 이력의 왼쪽 목록 (F53). */
export function fetchDates(limit = 60): Promise<{ d: string; n: number }[]> {
  return q(
    `select d, count(*)::int as n from ksv_verdicts group by d order by d desc limit $1`,
    [limit],
  );
}

export async function fetchLatestDate(): Promise<string | null> {
  const row = await one<{ d: string }>(`select max(d) as d from ksv_verdicts`);
  return row?.d ?? null;
}

/** 하루치 판정 전부 — 정렬은 화면이 한다. */
export function fetchDay(d: string): Promise<VerdictRow[]> {
  return q(`select ${VERDICT_COLS} from ksv_verdicts where d = $1 order by ticker`, [d]);
}

/** 그날 생략된 갈래 — 오늘 표의 「생략」 열. 증거가 없는 종목은 빠져 있다(= 저장 전). */
export function fetchDayMissing(d: string): Promise<{ ticker: string; missing: string[] }[]> {
  return q(`select ticker, missing from ksv_evidence where d = $1`, [d]);
}

/** 그날 마지막 실행 기록 — 게이트 상태를 빈 날 안내에 그대로 보인다 (DESIGN §2-1). */
export function fetchRunFor(d: string): Promise<RunRow | null> {
  return one(
    `select run_at, run_date, status, gate, signals, verdicts, outcomes_filled, detail
     from ksv_runs where run_date = $1 order by run_at desc limit 1`,
    [d],
  );
}

/** 종목 하나의 판정. 같은 날 배치·온디맨드가 둘 있으면 배치를 먼저 준다. */
export function fetchVerdict(ticker: string, d: string, source?: string): Promise<VerdictRow | null> {
  if (source) {
    return one(
      `select ${VERDICT_COLS} from ksv_verdicts where ticker = $1 and d = $2 and source = $3`,
      [ticker, d, source],
    );
  }
  return one(
    `select ${VERDICT_COLS} from ksv_verdicts where ticker = $1 and d = $2
     order by case source when 'batch' then 0 else 1 end limit 1`,
    [ticker, d],
  );
}

/** 종목이 판정된 날들 — 최신순. 종목 화면의 날짜 이동. */
export async function fetchTickerDates(ticker: string, limit = 30): Promise<string[]> {
  const rows = await q<{ d: string }>(
    `select distinct d from ksv_verdicts where ticker = $1 order by d desc limit $2`,
    [ticker, limit],
  );
  return rows.map((r) => r.d);
}

export function fetchEvidence(ticker: string, d: string): Promise<EvidenceRow | null> {
  return one(
    `select d, ticker, disclosures, news, flows, financial, shorting, bodies, anomaly, missing
     from ksv_evidence where ticker = $1 and d = $2`,
    [ticker, d],
  );
}

export function fetchOutcome(ticker: string, d: string): Promise<OutcomeRow | null> {
  return one(
    `select d, ticker, market, h5, h20, h60, h5_index, h20_index, h60_index
     from ksv_outcomes where ticker = $1 and d = $2`,
    [ticker, d],
  );
}

/** 이력 (F53) — 날짜 또는 종목으로. 도래한 초과수익을 함께. */
export function fetchHistory(f: { d?: string; ticker?: string; limit?: number }): Promise<HistoryRow[]> {
  const where: string[] = [];
  const vals: unknown[] = [];
  if (f.d) { vals.push(f.d); where.push(`v.d = $${vals.length}`); }
  if (f.ticker) { vals.push(f.ticker); where.push(`v.ticker = $${vals.length}`); }
  vals.push(f.limit ?? 200);
  return q(
    `select v.d, v.ticker, v.source, v.name, v.strategy, v.stand, v.score, v.parts, v.blind_spots,
            v.rules_version, v.summary,
            coalesce(o.market, '') as market,
            o.h5, o.h20, o.h60, o.h5_index, o.h20_index, o.h60_index
     from ksv_verdicts v
     left join ksv_outcomes o on o.d = v.d and o.ticker = v.ticker
     ${where.length ? "where " + where.join(" and ") : ""}
     order by v.d desc, v.rules_version desc, v.score asc, v.ticker
     limit $${vals.length}`,
    vals,
  );
}

/** 분별력 (F54) — 최근 as_of 몇 개 분. 최신 하나를 고르는 것은 화면(`latestDiscrimination`). */
export function fetchDiscrimination(): Promise<DiscriminationRow[]> {
  return q(
    `select as_of, horizon, rules_version, n_aligned, n_conflict, aligned, conflict, overlap
     from ksv_discrimination
     where as_of >= (select max(as_of) from ksv_discrimination) - 7
     order by as_of desc, horizon`,
  );
}

// ── 온디맨드 (F41·F42) ────────────────────────────────────────────

/** 오늘(서울) 쓴 요청 수와 진행 중 요청 수. 15분 넘게 `queued`/`running`이면 죽은 것으로 보고 세지 않는다. */
export async function fetchRequestLoad(todaySeoul: string): Promise<{ used: number; active: number }> {
  const row = await one<{ used: number; active: number }>(
    `select
       count(*) filter (where (requested_at at time zone 'Asia/Seoul')::date = $1::date)::int as used,
       count(*) filter (where status in ('queued', 'running')
                         and requested_at > now() - interval '15 minutes')::int as active
     from ksv_requests`,
    [todaySeoul],
  );
  return row ?? { used: 0, active: 0 };
}

export function fetchRequest(id: number): Promise<RequestRow | null> {
  return one(
    `select id, requested_at, ticker, status, result_d, detail from ksv_requests where id = $1`,
    [id],
  );
}

/** 요청을 넣는다 — 정책상 `queued`로만 들어간다. id를 돌려준다. */
export async function insertRequest(ticker: string): Promise<number> {
  const row = await one<{ id: number }>(
    `insert into ksv_requests (ticker, status) values ($1, 'queued') returning id`,
    [ticker],
  );
  if (!row) throw new Error("요청 INSERT가 id를 돌려주지 않았다");
  return row.id;
}

/** dispatch가 실패하면 자기 요청을 접는다 — 정책상 `failed`로만 바꿀 수 있다. */
export function failRequest(id: number, reason: string): Promise<unknown> {
  return q(
    `update ksv_requests set status = 'failed', detail = $2::jsonb where id = $1`,
    [id, JSON.stringify({ errors: [reason] })],
  );
}
