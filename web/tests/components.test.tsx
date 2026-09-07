/**
 * 컴포넌트 — 서버 렌더 문자열로 핵심 동작을 잠근다. 브라우저 없이 `renderToStaticMarkup`.
 *
 *   · 판정 칩은 글자를 단다 — 색만으로 구별하지 않는다
 *   · 공시에는 DART 원문 링크가 반드시 붙는다 (N3)
 *   · 빈 갈래는 사라지지 않고 「생략 — 이유」로 자리를 남긴다
 *   · 미도래 관측은 `—` — 0으로 보이지 않는다
 *   · 하단 띠 문구 (F55)
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Footer } from "@/app/components/Footer";
import { StandChip } from "@/app/components/StandChip";
import { DisclosureLane, FinancialLane, FlowsLane, NewsLane, Observation, ShortingLane, bodyLine, dartUrl } from "@/app/components/lanes";

const html = (el: React.ReactElement) => renderToStaticMarkup(el);

describe("StandChip", () => {
  it("세 판정이 글자와 각자의 클래스를 가진다", () => {
    expect(html(<StandChip stand="정합" />)).toContain("chip-agree");
    expect(html(<StandChip stand="불일치" />)).toContain("불일치");
    expect(html(<StandChip stand="무관" />)).toContain("chip-none");
  });
});

describe("Footer (F55)", () => {
  it("문구가 있고 고정이다", () => {
    const h = html(<Footer />);
    expect(h).toContain("투자 권고가 아닙니다 · 참고용 테스트");
    expect(h).toContain("fixed");
  });
});

describe("공시 갈래 — DART 링크 필수 (N3)", () => {
  const item = { rcept_dt: "2026-08-26", report_nm: "주요사항보고서(전환사채권발행결정)", rcept_no: "20260826000123", flr_nm: "씨피시스템", corrected: false };
  it("항목마다 원문 링크", () => {
    const h = html(<DisclosureLane items={[item]} bodies={null} anomaly={null} stored />);
    expect(h).toContain(dartUrl("20260826000123"));
    expect(h).toContain("dart.fss.or.kr/dsaf001/main.do?rcptNo=20260826000123");
    expect(h).toContain("DART 원문");
  });
  it("본문이 있으면 rcept_no로 짝지어 한 줄", () => {
    const body = { rcept_no: "20260826000123", event_type: "cb", amount: 10_000_000_000, use_of_funds: [["시설자금", 10_000_000_000]] as [string, number][], kind: "", method: "사모", coupon_rate: null, conv_price: 5106, overhang_pct: 5.1, outstanding: null, refix_floor: null };
    expect(bodyLine(body)).toBe("100.0억 · 시설자금 100.0억 · 사모 · 전환가 5,106원 · 전환 시 발행주식의 5.10%");
    expect(html(<DisclosureLane items={[item]} bodies={[body]} anomaly={null} stored />)).toContain("5.10%");
  });
  it("증거가 저장되지 않은 날은 그 이유로 생략", () => {
    expect(html(<DisclosureLane items={null} bodies={null} anomaly={null} stored={false} />)).toContain("생략 — 이날의 증거가 저장되지 않았다");
  });
  it("조회 실패(null)와 0건은 다른 말", () => {
    expect(html(<DisclosureLane items={null} bodies={null} anomaly={null} stored />)).toContain("생략 — 공시 조회 실패");
    expect(html(<DisclosureLane items={[]} bodies={null} anomaly={null} stored />)).toContain("30일 안에 공시가 없다");
  });
});

describe("나머지 갈래 — 빈 갈래도 자리를 남긴다", () => {
  it("뉴스는 원문 링크", () => {
    const h = html(<NewsLane items={[{ title: "씨피시스템, 100억 CB", link: "https://n.news.naver.com/a/1", published: "2026-08-26", summary: "요약", source: "매체" }]} stored />);
    expect(h).toContain('href="https://n.news.naver.com/a/1"');
    expect(h).toContain("[매체]");
  });
  it("수급은 누적과 막대", () => {
    const h = html(<FlowsLane flows={{ days: [{ d: "2026-08-26", inst: -100_000_000, foreign: -1_126_000_000, indiv: 1_226_000_000 }] }} stored />);
    expect(h).toContain("−11.26억");
    expect(h).toContain("1일 누적 외국인");
  });
  it("재무 — 매출액이 없는 보고서는 그 사실을 한 줄로", () => {
    const fin = { report: "2026년 반기보고서", basis: "연결", revenue: null, operating: { now: 5e9, prev: 4e9, period: "제 77 기 반기" }, net: null, debt_ratio: 120.4, retained: 3e10, absent: ["매출액"], extra: [] as [string, { now: number; prev: number | null; period: string }][], equity_wiped_out: false };
    const h = html(<FinancialLane fin={fin} stored />);
    expect(h).toContain("이 보고서에 매출액이 없다");
    expect(h).toContain("+25.0%");
    expect(h).toContain("120.4%");
  });
  it("공매도 — 없는 종목은 생략, 자리는 남는다", () => {
    const h = html(<ShortingLane shorting={null} stored />);
    expect(h).toContain("5 공매도");
    expect(h).toContain("생략 — 그날 공매도 통계에 이 종목이 없다");
  });
  it("공매도 — 20거래일 비중 막대와 평균", () => {
    const days = [
      { d: "2026-09-03", short_vol: 300000, buy_vol: 18000000, ratio: 1.6 },
      { d: "2026-09-04", short_vol: 368918, buy_vol: 18649816, ratio: 1.98 },
    ];
    const h = html(<ShortingLane shorting={{ state: "ready", reason: "", rows: 2, days }} stored />);
    expect(h).toContain("1.98%");
    expect(h).toContain("368,918주");
    expect(h).toContain("2거래일 공매도 비중 평균");
    expect(h).toContain("1.79%");
  });
});

describe("관측 — 미도래는 —, 지수 없으면 기준선 미도달", () => {
  it("행이 없으면 아홉 칸 전부 —", () => {
    const h = html(<Observation outcome={null} />);
    expect(h.match(/—/g)!.length).toBeGreaterThanOrEqual(9);
    expect(h).not.toContain("0.0%");
    expect(h).toContain("예측이 아니다");
  });
  it("5일만 도래", () => {
    const h = html(<Observation outcome={{ d: "2026-09-03", ticker: "413630", market: "KOSDAQ", h5: -3.4, h20: null, h60: null, h5_index: 1.2, h20_index: null, h60_index: null }} />);
    expect(h).toContain("−3.4%");
    expect(h).toContain("−4.6%p");
    expect(h).toContain("KOSDAQ 대비");
  });
  it("지수만 없으면 기준선 미도달", () => {
    const h = html(<Observation outcome={{ d: "2026-09-03", ticker: "413630", market: "KOSDAQ", h5: 2, h20: null, h60: null, h5_index: null, h20_index: null, h60_index: null }} />);
    expect(h).toContain("기준선 미도달");
  });
});
