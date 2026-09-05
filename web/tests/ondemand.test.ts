import { describe, expect, it } from "vitest";
import { decide, dispatchBody, dispatchUrl } from "@/lib/ondemand";

describe("decide — 형식 → 하루 상한 → 동시 1건", () => {
  it("정상이면 대문자로 정리한 티커와 남은 수", () => {
    const d = decide(" 0126z0 ", { used: 1, active: 0 }, 5);
    expect(d).toMatchObject({ ok: true, ticker: "0126Z0" });
    if (d.ok) expect(d.quota.remaining).toBe(4);
  });
  it("티커가 아니면 400 — 문자열이 아니어도", () => {
    expect(decide("5930", { used: 0, active: 0 }, 5)).toMatchObject({ ok: false, status: 400 });
    expect(decide(123456, { used: 0, active: 0 }, 5)).toMatchObject({ ok: false, status: 400 });
    expect(decide(undefined, { used: 0, active: 0 }, 5)).toMatchObject({ ok: false, status: 400 });
  });
  it("한도를 다 쓰면 429 — 내일 자정을 말한다", () => {
    const d = decide("005930", { used: 5, active: 0 }, 5);
    expect(d).toMatchObject({ ok: false, status: 429 });
    if (!d.ok) expect(d.error).toContain("00:00");
  });
  it("처리 중이면 429 — 동시 1건", () => {
    const d = decide("005930", { used: 0, active: 1 }, 5);
    expect(d).toMatchObject({ ok: false, status: 429 });
    if (!d.ok) expect(d.error).toContain("동시 1건");
  });
  it("형식 오류가 상한보다 먼저다", () => {
    expect(decide("x", { used: 9, active: 1 }, 5)).toMatchObject({ status: 400 });
  });
});

describe("dispatch — 워크플로 계약", () => {
  it("event_type은 verify-ticker, payload에 ticker와 request_id", () => {
    expect(dispatchBody("005930", 7)).toEqual({
      event_type: "verify-ticker",
      client_payload: { ticker: "005930", request_id: 7 },
    });
  });
  it("URL은 owner/repo 하나만 받는다", () => {
    expect(dispatchUrl("daehyub71/krx-signal-verify")).toBe(
      "https://api.github.com/repos/daehyub71/krx-signal-verify/dispatches",
    );
    expect(() => dispatchUrl("evil.com/x/../y")).toThrow();
    expect(() => dispatchUrl("")).toThrow();
  });
});
