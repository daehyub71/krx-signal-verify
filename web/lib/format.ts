/**
 * 표시 형식 — 순수 함수. 숫자와 날짜를 사람 말로.
 *
 * 마이너스는 `−`(U+2212)로 쓴다 — 하이픈은 표에서 대시와 섞여 읽힌다.
 * 없는 값은 언제나 `—`다. **0으로 두지 않는다** — 「초과수익 0%」로 읽힌다 (F22).
 */

export const DASH = "—";
const MINUS = "−";

function signed(v: number, digits: number): string {
  const abs = Math.abs(v).toFixed(digits);
  if (Number(abs) === 0) return abs;
  return (v < 0 ? MINUS : "+") + abs;
}

/** 등락 · 변동률. `1.234 → "+1.2%"`, `null → "—"`. */
export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return signed(v, digits) + "%";
}

/** 초과수익은 퍼센트 포인트다 — 종목 % − 지수 %. */
export function pctPoint(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return signed(v, digits) + "%p";
}

/** 원 단위 금액을 억·조로. `-1_126_000_000 → "−11.26억"`. */
export function won(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const sign = v < 0 ? MINUS : v > 0 ? "+" : "";
  const a = Math.abs(v);
  if (a >= 1e12) return `${sign}${(a / 1e12).toFixed(2)}조`;
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(2)}억`;
  if (a >= 1e4) return `${sign}${Math.round(a / 1e4).toLocaleString("ko-KR")}만`;
  return `${sign}${a.toLocaleString("ko-KR")}원`;
}

/** 부호 없는 원 금액 (재무 표). */
export function wonPlain(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const a = Math.abs(v);
  const body = a >= 1e12 ? `${(a / 1e12).toFixed(2)}조` : a >= 1e8 ? `${(a / 1e8).toFixed(1)}억` : `${a.toLocaleString("ko-KR")}원`;
  return v < 0 ? MINUS + body : body;
}

const DOW = ["일", "월", "화", "수", "목", "금", "토"];

/** `YYYY-MM-DD`를 시간대에 흔들리지 않게 분해한다. 잘못된 값은 null. */
export function parts(d: string): { y: number; m: number; day: number } | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]), day: Number(m[3]) };
}

/** `2026-09-03 → "09-03"`. */
export function md(d: string): string {
  const p = parts(d);
  return p ? `${String(p.m).padStart(2, "0")}-${String(p.day).padStart(2, "0")}` : d;
}

/** `2026-09-03 → "09-03 수"`. 요일은 UTC 정오로 계산해 시간대에 안 흔들린다. */
export function dayLabel(d: string): string {
  const p = parts(d);
  if (!p) return d;
  const dow = DOW[new Date(Date.UTC(p.y, p.m - 1, p.day, 12)).getUTCDay()];
  return `${md(d)} ${dow}`;
}

/** `2026-09-03 → "2026년 9월 3일"`. */
export function fullDate(d: string): string {
  const p = parts(d);
  return p ? `${p.y}년 ${p.m}월 ${p.day}일` : d;
}

/** 티커는 숫자가 아니다 — `0126Z0`이 실재한다. */
export function isTicker(s: string): boolean {
  return /^[0-9A-Z]{6}$/.test(s);
}

/** 서울 기준 오늘 `YYYY-MM-DD`. 서버가 UTC라 `new Date().toISOString()`은 아침에 하루 밀린다. */
export function todaySeoul(now: Date = new Date()): string {
  const kst = new Date(now.getTime() + 9 * 3600 * 1000);
  return kst.toISOString().slice(0, 10);
}
