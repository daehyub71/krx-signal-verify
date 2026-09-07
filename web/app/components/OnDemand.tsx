"use client";

/**
 * 온디맨드 입력 + 상태 패널 (F41·F42). 상단 바에 하나만 있다 — 어디서든 연다 (DESIGN §2-5).
 *
 * 흐름: 요청 접수 → 대기(Actions 깨움) → 처리 중(1~3분, 2026-09-07 실측 2.5분) → 완료(→ 종목) / 실패 / 신호 없음.
 * 한도 숫자는 서버가 준 것을 보일 뿐이다 — 판단은 `/api/verify`가 한다.
 */

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Quota } from "@/lib/view";
import { requestStep } from "@/lib/view";
import { StandChip } from "./StandChip";
import type { RequestRow, Stand } from "@/lib/types";

type Req = Pick<RequestRow, "id" | "ticker" | "status" | "result_d" | "detail">;

const STEPS = ["요청 접수", "대기", "처리 중", "완료"];
const POLL_MS = 5_000;
const GIVE_UP_MS = 4 * 60_000;

export function OnDemand() {
  const [ticker, setTicker] = useState("");
  const [quota, setQuota] = useState<Quota | null>(null);
  const [req, setReq] = useState<Req | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const startedAt = useRef(0);

  const loadQuota = useCallback(async () => {
    try {
      const r = await fetch("/api/verify", { cache: "no-store" });
      if (r.ok) setQuota((await r.json()).quota);
    } catch {
      // 한도 표시는 있으면 좋은 층이다 — 못 받아도 버튼은 서버가 막는다
    }
  }, []);

  // 첫 표시용 한도 — 서버에서 받아 온 뒤에 반영한다 (외부 상태 구독 꼴).
  useEffect(() => {
    let alive = true;
    fetch("/api/verify", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => { if (alive && j?.quota) setQuota(j.quota); })
      .catch(() => { /* 못 받아도 버튼은 서버가 막는다 */ });
    return () => { alive = false; };
  }, []);

  // 진행 중 요청은 5초마다 본다. 4분이 넘으면 화면만 멈춘다 — 워크플로는 제 갈 길을 간다.
  useEffect(() => {
    if (!req || (req.status !== "queued" && req.status !== "running")) return;
    const t = setInterval(async () => {
      if (Date.now() - startedAt.current > GIVE_UP_MS) {
        setError("4분이 지났다 — 이력에서 확인하라. 워크플로는 계속 돈다");
        clearInterval(t);
        return;
      }
      try {
        const r = await fetch(`/api/verify?id=${req.id}`, { cache: "no-store" });
        if (r.ok) {
          const next = (await r.json()) as Req;
          setReq(next);
          if (next.status === "done" || next.status === "failed") void loadQuota();
        }
      } catch {
        // 한 번 못 받은 것은 다음 틱에 다시
      }
    }, POLL_MS);
    return () => clearInterval(t);
  }, [req, loadQuota]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const r = await fetch("/api/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker }),
      });
      const j = await r.json();
      if (j.quota) setQuota(j.quota);
      if (!r.ok) {
        setError(j.error ?? `실패 (HTTP ${r.status})`);
        setOpen(true);
        return;
      }
      startedAt.current = Date.now();
      setReq({ id: j.id, ticker: j.ticker, status: "queued", result_d: null, detail: {} });
      setOpen(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setOpen(true);
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || (quota !== null && !quota.canRequest);

  return (
    <div className="relative flex items-center gap-3">
      <form onSubmit={submit} className="flex items-center gap-2">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="종목코드 6자리"
          maxLength={6}
          aria-label="온디맨드 검증 종목코드"
          className="mono h-9 w-[150px] rounded-md border border-line-2 bg-surface px-3 text-[13px] text-ink outline-none focus:border-ink"
        />
        <button
          type="submit"
          disabled={disabled || ticker.length !== 6}
          className="h-9 rounded-md bg-ink px-4 text-[13px] font-semibold text-surface disabled:border disabled:border-line disabled:bg-sunk disabled:text-faint"
        >
          검증 요청
        </button>
      </form>
      {quota && (
        <button type="button" onClick={() => setOpen((v) => !v)} className="mono whitespace-nowrap text-xs text-muted">
          오늘 남은 요청 <b className="text-ink">{quota.remaining}</b>/{quota.limit} · 동시 1건
        </button>
      )}

      {open && (
        <div className="card absolute right-0 top-12 z-30 w-[560px] shadow-lg" role="status">
          <div className="flex items-start justify-between">
            <div className="h">온디맨드 검증{req ? ` — ${req.ticker}` : ""}</div>
            <button type="button" onClick={() => setOpen(false)} className="text-xs text-muted">닫기</button>
          </div>
          {req && <Stepper status={req.status} />}
          {req && <Outcome req={req} />}
          {error && <div className="mt-2 rounded-md border border-conflict px-3 py-2 text-[13px] text-ink-2">{error}</div>}
          <div className="mt-3 text-xs text-faint">
            오늘 신호가 있는 종목만 검증한다 · 결과는 이력에 <span className="mono">ondemand</span>로 남고 메일은 보내지 않는다 ·
            온디맨드 결과는 분별력 집계에 넣지 않는다 (F43)
          </div>
        </div>
      )}
    </div>
  );
}

function Stepper({ status }: { status: Req["status"] }) {
  const at = requestStep(status);
  return (
    <ol className="mt-3 flex items-start">
      {STEPS.map((label, i) => {
        const done = i < at || status === "done";
        const now = i === at && status !== "done";
        const failed = status === "failed" && i === at;
        return (
          <li key={label} className="flex flex-1 flex-col items-center gap-1 text-xs" style={{ color: failed ? "var(--conflict)" : done || now ? "var(--ink)" : "var(--faint)" }}>
            <span
              className="block h-3 w-3 rounded-full border-2"
              style={{
                borderColor: failed ? "var(--conflict)" : done || now ? "var(--ink)" : "var(--line-2)",
                background: done ? "var(--ink)" : "var(--surface)",
                boxShadow: now ? "0 0 0 4px var(--sunk)" : undefined,
              }}
            />
            <span style={{ fontWeight: now ? 600 : 400 }}>{failed ? "실패" : label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function Outcome({ req }: { req: Req }) {
  if (req.status === "queued" || req.status === "running") {
    return <div className="mt-3 rounded-md border border-line bg-raise px-3 py-2 text-[13px] text-ink-2">공시 · 뉴스 · 수급 · 재무 갈래를 모으고 판정을 내는 중이다 (1~3분 · 실측 2.5분). 처리 중에는 새 요청을 받지 않는다.</div>;
  }
  if (req.status === "failed") {
    const why = req.detail?.errors?.[0] ?? "배치가 정상 종료하지 않았다";
    return <div className="mt-3 text-[13px] text-ink-2">{why} — 잠시 뒤 다시 요청할 수 있다.</div>;
  }
  const v = req.detail?.verdicts?.[req.ticker];
  if (!v) {
    return <div className="mt-3 text-[13px] text-ink-2">오늘 <b className="mono">{req.ticker}</b>에 신호가 없다. 신호가 없는 종목은 검증 대상이 아니라 근거를 모으지 않는다. (한도는 소모한다)</div>;
  }
  return (
    <div className="mt-3 flex items-center gap-3 text-[13px]">
      <StandChip stand={v.stand as Stand} />
      <span className="mono text-xl font-bold">{v.score}</span>
      <span className="grow" />
      <Link href={`/t/${req.ticker}?d=${req.result_d ?? ""}&source=ondemand`} className="font-medium">종목 화면 →</Link>
    </div>
  );
}
