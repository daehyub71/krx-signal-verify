import { describe, expect, it } from "vitest";
import { dayLabel, fullDate, isTicker, md, pct, pctPoint, todaySeoul, won, wonPlain } from "@/lib/format";

describe("pct / pctPoint — 없는 값은 언제나 —", () => {
  it("부호를 붙이고 마이너스는 U+2212", () => {
    expect(pct(1.234)).toBe("+1.2%");
    expect(pct(-3.4)).toBe("−3.4%");
    expect(pctPoint(-4.56)).toBe("−4.6%p");
  });
  it("0은 부호 없이", () => {
    expect(pct(0)).toBe("0.0%");
    expect(pct(-0.01)).toBe("0.0%");
  });
  it("null·undefined·NaN은 대시 — 0으로 두면 「초과수익 0%」로 읽힌다 (F22)", () => {
    expect(pct(null)).toBe("—");
    expect(pct(undefined)).toBe("—");
    expect(pctPoint(NaN)).toBe("—");
  });
});

describe("won — 억·조", () => {
  it("11.26억 순매도", () => {
    expect(won(-1_126_000_000)).toBe("−11.26억");
    expect(won(1_131_000_000)).toBe("+11.31억");
  });
  it("조 단위와 작은 값", () => {
    expect(won(2.5e12)).toBe("+2.50조");
    expect(won(35_000)).toBe("+4만");
    expect(won(900)).toBe("+900원");
    expect(won(0)).toBe("0원");
  });
  it("wonPlain은 부호 없이, 음수만 마이너스", () => {
    expect(wonPlain(12_345_000_000)).toBe("123.5억");
    expect(wonPlain(-500_000_000)).toBe("−5.0억");
    expect(wonPlain(null)).toBe("—");
  });
});

describe("날짜 — 시간대에 흔들리지 않는다", () => {
  it("dayLabel은 요일을 단다 (2026-09-03은 목요일)", () => {
    expect(dayLabel("2026-09-03")).toBe("09-03 목");
    expect(dayLabel("2026-09-06")).toBe("09-06 일");
  });
  it("md·fullDate", () => {
    expect(md("2026-09-03")).toBe("09-03");
    expect(fullDate("2026-09-03")).toBe("2026년 9월 3일");
  });
  it("잘못된 값은 그대로 돌려준다 — 조용히 오늘로 바꾸지 않는다", () => {
    expect(dayLabel("2026/09/03")).toBe("2026/09/03");
    expect(md("")).toBe("");
  });
  it("todaySeoul은 UTC 15:30을 다음 날로 본다", () => {
    expect(todaySeoul(new Date("2026-09-01T15:30:00Z"))).toBe("2026-09-02");
    expect(todaySeoul(new Date("2026-09-01T14:59:00Z"))).toBe("2026-09-01");
  });
});

describe("isTicker — 티커는 숫자가 아니다", () => {
  it.each(["005930", "0126Z0"])("%s 통과", (t) => expect(isTicker(t)).toBe(true));
  it.each(["5930", "0059300", "00593a", "005-30", ""])("%s 거절", (t) => expect(isTicker(t)).toBe(false));
});
