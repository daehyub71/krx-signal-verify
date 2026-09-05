import { describe, expect, it } from "vitest";
import {
  band,
  countStands,
  dailyLimit,
  excess,
  filterRows,
  horizonCells,
  latestDiscrimination,
  overlapText,
  quota,
  requestStep,
  sampleState,
  sortByScore,
  topParts,
  versionBreaks,
} from "@/lib/view";
import type { DiscriminationRow, VerdictRow } from "@/lib/types";

function row(over: Partial<VerdictRow>): VerdictRow {
  return {
    d: "2026-09-03", ticker: "005930", source: "batch", name: "삼성전자", strategy: "vcp",
    stand: "무관", score: 50, parts: [], blind_spots: [], rules_version: "1.0", summary: null,
    ...over,
  };
}

describe("오늘 — 정렬·집계·필터", () => {
  it("점수 낮은 것부터, 같으면 티커", () => {
    const rows = [row({ ticker: "B", score: 68 }), row({ ticker: "C", score: 37 }), row({ ticker: "A", score: 68 })];
    expect(sortByScore(rows).map((r) => r.ticker)).toEqual(["C", "A", "B"]);
  });
  it("정렬은 입력을 바꾸지 않는다", () => {
    const rows = [row({ score: 2 }), row({ score: 1 })];
    sortByScore(rows);
    expect(rows[0].score).toBe(2);
  });
  it("판정 수를 센다 — 셋 다 항상 있다", () => {
    expect(countStands([row({ stand: "정합" }), row({ stand: "정합" }), row({ stand: "불일치" })]))
      .toEqual({ 정합: 2, 불일치: 1, 무관: 0 });
  });
  it("근거 요약은 영향 큰 것부터 2개", () => {
    const parts = [{ label: "a", delta: 3 }, { label: "b", delta: -8 }, { label: "c", delta: 6 }];
    expect(topParts(parts).map((p) => p.label)).toEqual(["b", "c"]);
  });
  it("필터 — 빈 값은 전부", () => {
    const rows = [row({ stand: "정합", strategy: "vcp" }), row({ stand: "불일치", strategy: "mtf" })];
    expect(filterRows(rows, { stand: "" }).length).toBe(2);
    expect(filterRows(rows, { stand: "불일치" }).length).toBe(1);
    expect(filterRows(rows, { strategy: "vcp" })[0].stand).toBe("정합");
  });
});

describe("관측 — 미도래는 null, 지수 없으면 초과도 null", () => {
  it("excess는 종목 − 지수", () => {
    expect(excess(-3.4, 1.2)).toBeCloseTo(-4.6);
    expect(excess(null, 1.2)).toBeNull();
    expect(excess(2, null)).toBeNull();
  });
  it("horizonCells — 세 상태", () => {
    const cells = horizonCells({ h5: -3.4, h20: 1, h60: null, h5_index: 1.2, h20_index: null, h60_index: null });
    expect(cells.map((c) => c.state)).toEqual(["ok", "no_index", "pending"]);
    expect(cells[0].excess).toBeCloseTo(-4.6);
    expect(cells[1].excess).toBeNull();
  });
  it("outcome 행이 없으면 전부 미도래", () => {
    expect(horizonCells(null).every((c) => c.state === "pending")).toBe(true);
  });
});

describe("이력 — 산식 판 경계", () => {
  it("판이 바뀌는 행의 인덱스", () => {
    const rows = [{ rules_version: "1.1" }, { rules_version: "1.1" }, { rules_version: "1.0" }, { rules_version: "1.0" }];
    expect(versionBreaks(rows)).toEqual([2]);
    expect(versionBreaks([])).toEqual([]);
  });
});

describe("분별력 — 표본 30 미만은 그리지 않는다 (R2)", () => {
  it("둘 다 30 이상이어야 충분", () => {
    expect(sampleState(41, 33).enough).toBe(true);
    expect(sampleState(41, 29).enough).toBe(false);
    expect(sampleState(0, 0).text).toBe("표본 부족 (정합 n=0 · 불일치 n=0 · 필요 30)");
  });
  it("문구에 적중률·승률이 없다", () => {
    for (const s of [sampleState(41, 33), sampleState(0, 0)]) {
      expect(s.text).not.toMatch(/적중|승률|정확도/);
    }
  });
  it("band — −10…+10 축에서의 위치(%)", () => {
    const b = band({ q1: -1.8, median: 1.2, q3: 3.9 })!;
    expect(b.left).toBeCloseTo(41);
    expect(b.width).toBeCloseTo(28.5);
    expect(b.median).toBeCloseTo(56);
  });
  it("band — 축 밖은 잘라 붙이고, 사분위가 없으면 null", () => {
    expect(band({ q1: -30, median: 0, q3: 30 })).toEqual({ left: 0, width: 100, median: 50 });
    expect(band({ q1: null, median: null, q3: null })).toBeNull();
  });
  it("overlapText", () => {
    expect(overlapText(0.6234)).toBe("0.62");
    expect(overlapText(null)).toBe("—");
  });
  it("latestDiscrimination — 최신 as_of · 최신 판 · 5/20/60 순", () => {
    const base = { rules_version: "1.0", n_aligned: 0, n_conflict: 0, overlap: null,
      aligned: { q1: null, median: null, q3: null }, conflict: { q1: null, median: null, q3: null } };
    const rows: DiscriminationRow[] = [
      { ...base, as_of: "2026-09-04", horizon: 60 },
      { ...base, as_of: "2026-09-05", horizon: 20 },
      { ...base, as_of: "2026-09-05", horizon: 5 },
      { ...base, as_of: "2026-09-05", horizon: 60 },
    ];
    expect(latestDiscrimination(rows).map((r) => [r.as_of, r.horizon])).toEqual([
      ["2026-09-05", 5], ["2026-09-05", 20], ["2026-09-05", 60],
    ]);
    expect(latestDiscrimination([])).toEqual([]);
  });
});

describe("온디맨드 — 하루 상한 + 동시 1건 (F42)", () => {
  it("남은 수와 가능 여부", () => {
    expect(quota(1, 0, 5)).toMatchObject({ remaining: 4, canRequest: true, reason: "" });
    expect(quota(5, 0, 5)).toMatchObject({ remaining: 0, canRequest: false, reason: "limit" });
    expect(quota(1, 1, 5)).toMatchObject({ remaining: 4, canRequest: false, reason: "busy", busy: true });
  });
  it("한도 초과가 처리 중보다 먼저 말해진다", () => {
    expect(quota(5, 1, 5).reason).toBe("limit");
  });
  it("초과 사용도 음수가 되지 않는다", () => {
    expect(quota(7, 0, 5).remaining).toBe(0);
  });
  it("requestStep — 실패는 처리 중 자리에서 멈춘다", () => {
    expect([requestStep("queued"), requestStep("running"), requestStep("done"), requestStep("failed")]).toEqual([1, 2, 3, 2]);
  });
  it("dailyLimit — 비었거나 이상하면 5", () => {
    expect(dailyLimit(undefined)).toBe(5);
    expect(dailyLimit("0")).toBe(5);
    expect(dailyLimit("3")).toBe(3);
    expect(dailyLimit("x")).toBe(5);
  });
});
