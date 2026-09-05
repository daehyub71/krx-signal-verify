/**
 * 온디맨드 요청의 결정 — 순수 함수 (F41·F42·V8). 라우트 핸들러는 이걸 부르고 I/O만 한다.
 *
 * 상한은 **서버가 센다.** 화면의 숫자는 표시일 뿐이다.
 */

import { isTicker } from "./format";
import { quota, type Quota } from "./view";

export type Decision =
  | { ok: true; ticker: string; quota: Quota }
  | { ok: false; status: 400 | 429; error: string; quota: Quota | null };

/** 티커 형식 → 하루 상한 → 동시 1건 순으로 본다. 먼저 걸린 이유 하나만 말한다. */
export function decide(rawTicker: unknown, load: { used: number; active: number }, limit: number): Decision {
  const ticker = typeof rawTicker === "string" ? rawTicker.trim().toUpperCase() : "";
  const qta = quota(load.used, load.active, limit);
  if (!isTicker(ticker)) {
    return { ok: false, status: 400, error: "6자리 영숫자 티커여야 한다 (예: 005930, 0126Z0)", quota: qta };
  }
  if (!qta.canRequest) {
    const error = qta.reason === "limit"
      ? `오늘 요청 ${qta.used}/${qta.limit}를 다 썼다 — 내일 00:00(KST) 이후`
      : "처리 중인 요청이 있다 — 동시 1건";
    return { ok: false, status: 429, error, quota: qta };
  }
  return { ok: true, ticker, quota: qta };
}

/** 깃허브 `repository_dispatch` 본문 — 워크플로는 `verify-ticker`만 듣고 `request_id`로 상태를 쓴다. */
export function dispatchBody(ticker: string, requestId: number): {
  event_type: "verify-ticker";
  client_payload: { ticker: string; request_id: number };
} {
  return { event_type: "verify-ticker", client_payload: { ticker, request_id: requestId } };
}

export function dispatchUrl(repo: string): string {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) throw new Error(`VERIFY_REPO 형식이 아니다: ${repo}`);
  return `https://api.github.com/repos/${repo}/dispatches`;
}
