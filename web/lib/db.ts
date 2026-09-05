/**
 * DB 접속 — **서버 전용.** `ksv_reader` 롤 · 풀러(6543 · transaction 모드).
 *
 * 세 겹 방어(PLAN §4-1)의 ②③이 여기다:
 *   · 자격증명은 `KSV_READER_DATABASE_URL` 하나. **`NEXT_PUBLIC_` 접두어가 없으므로 번들에 안 실린다.**
 *   · 이 롤은 `ksv_*` SELECT와 `ksv_requests` INSERT(queued)/UPDATE(failed)만 할 수 있다 (V9).
 *   · Pool은 모듈 스코프에 하나 — 서버리스 인스턴스마다 하나라 `max`를 작게 (PLAN §4-1b).
 *
 * transaction 모드 풀러는 **이름 있는 prepared statement**를 못 쓴다. `pool.query(text, values)`는
 * 이름 없는 문장을 쓰므로 괜찮다 — `name:`을 주지 않는다.
 */

import "server-only";
import { Pool, types } from "pg";

// date(OID 1082)를 JS Date로 바꾸지 않는다 — 시간대 때문에 하루가 밀린다. 문자열 그대로.
types.setTypeParser(1082, (v) => v);
// int8(OID 20)은 문자열로 오므로 숫자로. 요청 id·count가 여기 해당한다.
types.setTypeParser(20, (v) => Number(v));

let pool: Pool | undefined;

export function db(): Pool {
  if (pool) return pool;
  const url = process.env.KSV_READER_DATABASE_URL;
  if (!url) {
    throw new Error("KSV_READER_DATABASE_URL이 없다 — Vercel 환경변수(서버 사이드)를 확인하라");
  }
  pool = new Pool({
    connectionString: url,
    max: 2,
    idleTimeoutMillis: 10_000,
    connectionTimeoutMillis: 8_000,
    ssl: { rejectUnauthorized: false },
  });
  return pool;
}

/** 한 문장 실행. 행 배열을 돌려준다. */
export async function q<T>(text: string, values: unknown[] = []): Promise<T[]> {
  const res = await db().query(text, values);
  return res.rows as T[];
}

/** 첫 행 또는 null. */
export async function one<T>(text: string, values: unknown[] = []): Promise<T | null> {
  const rows = await q<T>(text, values);
  return rows[0] ?? null;
}
