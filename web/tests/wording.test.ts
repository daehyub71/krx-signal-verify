/**
 * N1·N2 — 목록은 `verify/wording.py`와 같아야 하고, 웹 소스 어디에도 금지어가 없어야 한다.
 *
 * 화면 문구는 코드 안에 흩어져 있어 렌더 결과만 검사하면 빠지는 화면이 생긴다.
 * 그래서 **소스 파일을 통째로** 훑는다 — 주석까지. 우리가 쓴 글은 전부 우리 글이다.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  ALLOWED_COMPOUNDS,
  ALLOWED_OUTCOME_COMPOUNDS,
  FORBIDDEN,
  FORBIDDEN_OUTCOME,
  firstViolation,
  hasForbidden,
  hasForbiddenOutcome,
} from "@/lib/wording";

const ROOT = path.resolve(__dirname, "..");

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|css)$/.test(name)) out.push(p);
  }
  return out;
}

describe("규칙 — 파이썬과 같은 목록", () => {
  it("verify/wording.py의 목록과 글자 그대로 같다", () => {
    const py = readFileSync(path.resolve(ROOT, "..", "verify", "wording.py"), "utf8");
    const tuple = (name: string) => {
      const m = new RegExp(`${name}: tuple\\[str, \\.\\.\\.\\] = \\(([^)]*)\\)`, "s").exec(py)!;
      return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]);
    };
    expect([...FORBIDDEN]).toEqual(tuple("FORBIDDEN"));
    expect([...ALLOWED_COMPOUNDS]).toEqual(tuple("ALLOWED_COMPOUNDS"));
    expect([...FORBIDDEN_OUTCOME]).toEqual(tuple("FORBIDDEN_OUTCOME"));
    expect([...ALLOWED_OUTCOME_COMPOUNDS]).toEqual(tuple("ALLOWED_OUTCOME_COMPOUNDS"));
  });
  it("순매도·공매도 비중은 통과, 매도 판단은 걸린다", () => {
    expect(hasForbidden("30일 기관·외국인 순매도 · 공매도 비중 3%")).toBe("");
    expect(hasForbidden("지금이 매도 시점")).toBe("매도");
    expect(hasForbidden("비중 확대")).toBe("비중");
  });
  it("초과수익은 통과, 성과 주장은 걸린다", () => {
    expect(hasForbiddenOutcome("5거래일 초과수익 분포")).toBe("");
    expect(hasForbiddenOutcome("불일치 판정이 잘 맞았다")).toBe("맞았");
    expect(firstViolation("이것은 예측이 아니다")).toEqual(["", ""]);
    expect(firstViolation("승률 68%")).toEqual(["N2", "승률"]);
  });
});

describe("웹 소스 전체 — 우리가 쓴 글에 금지어가 없다", () => {
  const files = [...walk(path.join(ROOT, "app")), ...walk(path.join(ROOT, "lib"))]
    .filter((f) => !f.endsWith("lib/wording.ts"));

  it("훑을 파일이 있다", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it.each(files.map((f) => [path.relative(ROOT, f), f]))("%s", (_, f) => {
    const [rule, word] = firstViolation(readFileSync(f, "utf8"));
    expect(rule, `${word}(${rule})가 있다`).toBe("");
  });
});
