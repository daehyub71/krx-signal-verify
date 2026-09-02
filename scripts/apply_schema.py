"""`ksv_*` 스키마를 실DB에 적용한다 (멱등).

supabase-py는 DDL을 못 돌린다 — `SUPABASE_DATABASE_URL` + psycopg로 직접 실행한다.

```bash
python scripts/apply_schema.py                        # 적용
python scripts/apply_schema.py --verify               # 적용하지 않고 현재 상태만 본다
python scripts/apply_schema.py --set-reader-password  # ksv_reader 비밀번호 설정
```

**비밀번호는 스키마 파일에 적지 않는다** — 커밋되는 파일이다.
`KSV_READER_PASSWORD` 환경변수로만 건다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# `python scripts/apply_schema.py`로 직접 돌릴 수 있게 프로젝트 루트를 올린다 (선행과 같은 방식).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg import sql as pgsql  # noqa: E402

from verify import config  # noqa: E402

SCHEMA = config.PROJECT_ROOT / "supabase" / "schema.sql"

TABLES = (
    "ksv_verdicts",
    "ksv_evidence",
    "ksv_outcomes",
    "ksv_discrimination",
    "ksv_runs",
    "ksv_requests",
)

# 확인 질의 — 「무엇이 있고 무엇이 열려 있나」를 사람이 읽을 수 있게 뽑는다.
Q_TABLES = """
select tablename, rowsecurity
from pg_tables where schemaname = 'public' and tablename like 'ksv\\_%'
order by tablename
"""
Q_POLICIES = """
select tablename, policyname, cmd, roles::text
from pg_policies where schemaname = 'public' and tablename like 'ksv\\_%'
order by tablename, policyname
"""


def apply_schema(conn: psycopg.Connection[Any], path: Path) -> None:
    """스키마를 통째로 실행한다. 재실행해도 안전하다."""
    conn.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def set_reader_password(conn: psycopg.Connection[Any], password: str) -> None:
    """읽기 롤의 비밀번호를 건다. **값을 로그에 찍지 않는다** (N10)."""
    conn.execute(
        pgsql.SQL("alter role ksv_reader with password {}").format(pgsql.Literal(password))
    )
    conn.commit()


def report(conn: psycopg.Connection[Any]) -> int:
    """현재 상태를 사람이 읽게 출력하고, 위험이 있으면 0이 아닌 값을 돌려준다."""
    problems = 0

    rows: list[Any] = list(conn.execute(Q_TABLES).fetchall())
    found = {str(r[0]) for r in rows}
    print(f"테이블 {len(found)}/{len(TABLES)}")
    for name in TABLES:
        row = next((r for r in rows if r[0] == name), None)
        if row is None:
            print(f"  ✗ {name} 없음")
            problems += 1
        elif not row[1]:
            print(f"  ⚠ {name} — RLS가 꺼져 있다")
            problems += 1
        else:
            print(f"  ✓ {name} (RLS on)")

    print("\n정책")
    pols: list[Any] = list(conn.execute(Q_POLICIES).fetchall())
    if not pols:
        print("  ✗ 정책이 하나도 없다 — ksv_reader도 0행을 받는다")
        problems += 1
    for tbl, pol, cmd, roles in ((p[0], p[1], p[2], p[3]) for p in pols):
        risky = "anon" in str(roles) or "public" in str(roles)
        mark = "✗" if risky else "✓"
        print(f"  {mark} {tbl}.{pol} {cmd} → {roles}")
        if risky:
            problems += 1

    covered = {str(p[0]) for p in pols if "ksv_reader" in str(p[3])}
    missing = [t for t in TABLES if t not in covered]
    if missing:
        print(f"  ✗ ksv_reader 정책이 없는 테이블: {missing} — 대시보드가 막힌다")
        problems += 1

    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="apply_schema", description="ksv_* 스키마 적용 (멱등)")
    p.add_argument("--verify", action="store_true", help="적용하지 않고 현재 상태만 본다")
    p.add_argument("--set-reader-password", action="store_true",
                   help="KSV_READER_PASSWORD로 ksv_reader 비밀번호를 건다")
    args = p.parse_args(argv)

    config.load_env()
    dsn = config.require("SUPABASE_DATABASE_URL")

    with psycopg.connect(dsn) as conn:
        if not args.verify:
            apply_schema(conn, SCHEMA)
            print(f"적용: {SCHEMA.name}\n")
        if args.set_reader_password:
            set_reader_password(conn, config.require("KSV_READER_PASSWORD"))
            print("ksv_reader 비밀번호를 걸었다 (값은 출력하지 않는다)\n")
        problems = report(conn)

    print(f"\n{'문제 없음' if problems == 0 else f'확인할 것 {problems}건'}")
    return 1 if problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
