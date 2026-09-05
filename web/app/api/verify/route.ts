/**
 * 온디맨드 — `POST` 요청 · `GET ?id=` 상태 · `GET` 한도 (F41·F42·V8).
 *
 * 경로: 브라우저 → (SSO) → 여기 → `ksv_requests` INSERT(queued) → 깃허브 `repository_dispatch`
 *   → `verify.yml`이 `--ticker --request-id`로 돌며 `running`→`done`/`failed`를 쓴다 → 화면이 GET으로 본다.
 *
 * 토큰(`VERIFY_DISPATCH_TOKEN`)은 서버에서만 산다 (R8). 응답에 절대 싣지 않는다.
 */

import { NextResponse } from "next/server";
import { todaySeoul } from "@/lib/format";
import { decide, dispatchBody, dispatchUrl } from "@/lib/ondemand";
import { failRequest, fetchRequest, fetchRequestLoad, insertRequest } from "@/lib/queries";
import { dailyLimit, quota } from "@/lib/view";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const id = Number(new URL(req.url).searchParams.get("id"));
  if (Number.isInteger(id) && id > 0) {
    const row = await fetchRequest(id);
    if (!row) return NextResponse.json({ error: "그런 요청이 없다" }, { status: 404 });
    return NextResponse.json({
      id: row.id, ticker: row.ticker, status: row.status, result_d: row.result_d, detail: row.detail,
    });
  }
  const load = await fetchRequestLoad(todaySeoul());
  return NextResponse.json({ quota: quota(load.used, load.active, dailyLimit(process.env.ONDEMAND_DAILY_LIMIT)) });
}

export async function POST(req: Request) {
  let body: { ticker?: unknown } = {};
  try {
    body = await req.json();
  } catch {
    // 본문이 없거나 JSON이 아니면 티커 없음으로 본다 — 아래 400
  }
  const load = await fetchRequestLoad(todaySeoul());
  const d = decide(body.ticker, load, dailyLimit(process.env.ONDEMAND_DAILY_LIMIT));
  if (!d.ok) return NextResponse.json({ error: d.error, quota: d.quota }, { status: d.status });

  const token = process.env.VERIFY_DISPATCH_TOKEN;
  const repo = process.env.VERIFY_REPO;
  if (!token || !repo) {
    return NextResponse.json({ error: "서버에 dispatch 설정이 없다 (VERIFY_DISPATCH_TOKEN · VERIFY_REPO)" }, { status: 503 });
  }

  const id = await insertRequest(d.ticker);
  let reason = "";
  try {
    const res = await fetch(dispatchUrl(repo), {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${token}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(dispatchBody(d.ticker, id)),
      cache: "no-store",
    });
    if (res.status !== 204) reason = `깃허브 dispatch 실패 (HTTP ${res.status})`;
  } catch (err) {
    reason = `깃허브 dispatch 실패 (${err instanceof Error ? err.message : String(err)})`;
  }
  if (reason) {
    await failRequest(id, reason);
    return NextResponse.json({ error: reason, id }, { status: 502 });
  }
  const after = quota(d.quota.used + 1, 1, d.quota.limit);
  return NextResponse.json({ id, ticker: d.ticker, status: "queued", quota: after }, { status: 202 });
}
