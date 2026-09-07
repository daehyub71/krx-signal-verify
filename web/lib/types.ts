/**
 * `ksv_*` 행의 모양 — 배치(`verify/store.py`)가 쓰는 열과 같다.
 *
 * 날짜 열은 **문자열 `YYYY-MM-DD`**로 받는다 (`lib/db.ts`가 pg의 date 파서를 끈다).
 * JS Date로 받으면 시간대 때문에 하루가 밀린다.
 */

export type Stand = "정합" | "불일치" | "무관";
export type Source = "batch" | "ondemand" | "backfill";

export interface VerdictPart {
  label: string;
  delta: number;
}

export interface VerdictRow {
  d: string;
  ticker: string;
  source: Source;
  name: string;
  strategy: string;
  stand: Stand;
  score: number;
  parts: VerdictPart[];
  blind_spots: string[];
  rules_version: string;
  summary: string | null;
}

// ── 증거 다섯 갈래 (verify/models.py의 dataclass를 JSON으로 내린 것) ──

export interface Disclosure {
  rcept_dt: string;
  report_nm: string;
  rcept_no: string;
  flr_nm: string;
  corrected: boolean;
}

export interface NewsItem {
  title: string;
  link: string;
  published: string | null;
  summary: string;
  source: string;
}

export interface FlowDay {
  d: string;
  inst: number | null;
  foreign: number | null;
  indiv: number | null;
}

export interface InvestorFlows {
  days: FlowDay[];
}

export interface Change {
  now: number;
  prev: number | null;
  period: string;
}

export interface Financial {
  report: string;
  basis: string;
  revenue: Change | null;
  operating: Change | null;
  net: Change | null;
  debt_ratio: number | null;
  retained: number | null;
  absent: string[];
  extra: [string, Change][];
  equity_wiped_out: boolean;
}

export interface EventBody {
  rcept_no: string;
  event_type: string;
  amount: number | null;
  use_of_funds: [string, number][];
  kind: string;
  method: string;
  coupon_rate: number | null;
  conv_price: number | null;
  overhang_pct: number | null;
  outstanding: number | null;
  refix_floor: number | null;
}

export interface Anomaly {
  score: number;
  verdict: string;
  summary: string;
  flags: string[];
}

export interface ShortDay {
  d: string;
  short_vol: number;
  buy_vol: number;
  ratio: number;
}

/** 공매도 갈래 — 상위 `ksc_shorting` 20거래일 (F32). `days`는 날짜 오름차순. */
export interface Shorting {
  state: string;
  reason: string;
  rows: number;
  days: ShortDay[];
}

export interface EvidenceRow {
  d: string;
  ticker: string;
  disclosures: Disclosure[] | null;
  news: NewsItem[] | null;
  flows: InvestorFlows | null;
  financial: Financial | null;
  shorting: Shorting | null;
  bodies: EventBody[] | null;
  anomaly: Anomaly | null;
  missing: string[];
}

export interface OutcomeRow {
  d: string;
  ticker: string;
  market: string;
  h5: number | null;
  h20: number | null;
  h60: number | null;
  h5_index: number | null;
  h20_index: number | null;
  h60_index: number | null;
}

export interface Quartiles {
  q1: number | null;
  median: number | null;
  q3: number | null;
}

export interface DiscriminationRow {
  as_of: string;
  horizon: 5 | 20 | 60;
  rules_version: string;
  n_aligned: number;
  n_conflict: number;
  aligned: Quartiles;
  conflict: Quartiles;
  overlap: number | null;
}

export interface RunRow {
  run_at: string;
  run_date: string;
  status: string;
  gate: string;
  signals: number;
  verdicts: number;
  outcomes_filled: number;
  detail: { errors?: string[] };
}

export type RequestStatus = "queued" | "running" | "done" | "failed";

export interface RequestRow {
  id: number;
  requested_at: string;
  ticker: string;
  status: RequestStatus;
  result_d: string | null;
  detail: {
    status?: string;
    verdicts?: Record<string, { stand: Stand; score: number }>;
    errors?: string[];
  };
}

/** 이력 표 한 줄 — 판정 + 도래한 초과수익. */
export interface HistoryRow extends VerdictRow {
  market: string;
  h5: number | null;
  h20: number | null;
  h60: number | null;
  h5_index: number | null;
  h20_index: number | null;
  h60_index: number | null;
}

export const HORIZONS = [5, 20, 60] as const;
export type Horizon = (typeof HORIZONS)[number];

/** 갈래 순서는 고정이다 (DESIGN §2-2). 빈 갈래도 이 순서로 자리를 남긴다. */
export const LANES = ["공시", "뉴스", "수급", "재무", "공매도"] as const;
export type Lane = (typeof LANES)[number];
