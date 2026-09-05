/**
 * 문구 규칙 N1·N2 — `verify/wording.py`와 **같은 목록**이다. 한쪽만 고치면 안 된다.
 *
 * 웹은 우리가 쓴 문장(라벨·안내·한계 문구)에만 적용한다. 공시 제목·뉴스 제목은 남이 쓴 원문이라
 * 그대로 싣는다. `tests/wording.test.ts`가 `app/`·`lib/` 소스 전체를 훑는다.
 */

/** N1 — 매매 판단. */
export const FORBIDDEN = ["추천", "매수", "매도", "보류", "목표가", "손절", "여력", "이탈", "진입", "비중"] as const;

/** 먼저 지우는 합성어 — 없으면 수급도 공매도도 말할 수 없다. 긴 것부터 지운다. */
export const ALLOWED_COMPOUNDS = [
  "공매도 비중", "공매도비중", "공매도", "순매수", "순매도", "매수세", "매도세", "매수관여율",
] as const;

/** N2 — 성과 주장. `예측`은 막지 않는다 — 한계 문구가 「예측이 아니다」라고 말해야 한다. */
export const FORBIDDEN_OUTCOME = ["적중", "승률", "수익률", "정확도", "맞혔", "맞았", "틀렸", "빗나"] as const;

export const ALLOWED_OUTCOME_COMPOUNDS = ["초과수익"] as const;

function strip(text: string, words: readonly string[]): string {
  let rest = text;
  for (const w of [...words].sort((a, b) => b.length - a.length)) rest = rest.split(w).join(" ");
  return rest;
}

/** 걸린 N1 금지어, 없으면 빈 문자열. */
export function hasForbidden(text: string): string {
  const rest = strip(text, ALLOWED_COMPOUNDS);
  return FORBIDDEN.find((w) => rest.includes(w)) ?? "";
}

/** 걸린 N2 문구, 없으면 빈 문자열. */
export function hasForbiddenOutcome(text: string): string {
  const rest = strip(text, ALLOWED_OUTCOME_COMPOUNDS);
  return FORBIDDEN_OUTCOME.find((w) => rest.includes(w)) ?? "";
}

/** 두 규칙을 한 번에. `["N1", 말]` · `["N2", 말]` · `["", ""]`. */
export function firstViolation(text: string): ["N1" | "N2" | "", string] {
  const a = hasForbidden(text);
  if (a) return ["N1", a];
  const b = hasForbiddenOutcome(text);
  if (b) return ["N2", b];
  return ["", ""];
}
