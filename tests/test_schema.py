"""스키마 회귀 — **실DB 없이** `schema.sql`을 읽어 위험한 변경을 잡는다.

선행에서 `ksb_*`에 `to anon` 정책을 열어 뒀다가 **공개된 anon 키로 15행이 통째로 읽혔다**
(2026-08-31). 그 구멍이 되살아나는 것을 여기서 막는다.

반대 실수도 막는다: **정책을 하나도 안 만들면 `ksv_reader`도 0행을 받아 대시보드가 막힌다.**
검사 기준은 「정책 0개」가 아니라 **「anon 정책 0개 + reader 정책 존재」**다.
"""

from __future__ import annotations

import re

from verify import config

SQL = (config.PROJECT_ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")

TABLES = (
    "ksv_verdicts",
    "ksv_evidence",
    "ksv_outcomes",
    "ksv_discrimination",
    "ksv_runs",
    "ksv_requests",
)


def statements() -> list[str]:
    """주석을 걷어낸 문장들. 주석 안의 `to anon`을 오탐하지 않는다."""
    body = re.sub(r"--[^\n]*", "", SQL)
    return [s.strip().lower() for s in body.split(";") if s.strip()]


def test_all_six_tables_are_created() -> None:
    for t in TABLES:
        assert f"create table if not exists {t}" in SQL, f"{t}가 없다"


def test_every_table_has_rls_enabled() -> None:
    for t in TABLES:
        assert f"alter table {t}" in SQL and "enable row level security" in SQL


def test_no_policy_is_granted_to_anon_or_public() -> None:
    """이 테스트가 깨지면 공개된 anon 키로 판정이 통째로 읽힌다. 지우지 말 것."""
    for s in statements():
        if s.startswith("create policy"):
            assert " to anon" not in s, f"anon 정책이 살아났다: {s[:80]}"
            assert " to public" not in s, f"public 정책이 살아났다: {s[:80]}"
            assert " to authenticated" not in s, f"authenticated 정책이 살아났다: {s[:80]}"


def test_every_table_has_a_reader_select_policy() -> None:
    """RLS만 켜고 정책을 안 만들면 **모든 롤이 0행**을 받는다 — 대시보드도 막힌다."""
    for t in TABLES:
        got = [
            s for s in statements()
            if s.startswith("create policy") and f" on {t} " in s and "to ksv_reader" in s
        ]
        assert got, f"{t}에 ksv_reader SELECT 정책이 없다 — 대시보드가 0행을 받는다"


def test_reader_policies_are_select_only() -> None:
    for s in statements():
        if s.startswith("create policy") and "ksv_reader" in s:
            assert "for select" in s, f"읽기 롤에 SELECT 아닌 정책이 있다: {s[:80]}"


def test_role_statements_carry_no_password() -> None:
    """비밀번호는 커밋되는 파일에 적지 않는다 — 환경변수로만 건다 (N10)."""
    for s in statements():
        if "create role" in s or "alter role" in s:
            assert "password" not in s, f"스키마 파일에 비밀번호가 적혀 있다: {s[:60]}"


def test_reader_role_is_not_given_bypassrls() -> None:
    """BYPASSRLS를 주면 V9가 service_role을 버린 이유(폭발 반경)가 그대로 돌아온다.

    주석에는 「쓰지 않는다」는 설명이 있으므로 **문장만** 본다.
    """
    for s in statements():
        assert "bypassrls" not in s, f"BYPASSRLS가 붙었다: {s[:60]}"


def test_ticker_columns_accept_letters() -> None:
    """`0126Z0`이 실재한다. 숫자로만 제약하면 종목이 조용히 누락된다."""
    assert SQL.count("'^[0-9A-Z]{6}$'") >= 4


def test_verdict_stand_is_constrained_to_three_values() -> None:
    """DB가 2차 방어선이다 — 「호재」 같은 말이 새어 들면 저장이 거부된다 (N1)."""
    assert "stand in ('정합', '불일치', '무관')" in SQL


def test_outcomes_has_no_baseline_column() -> None:
    """기준선은 소속 시장 지수 하나뿐이다 — 방식을 기록할 열을 두지 않는다 (V12)."""
    block = SQL.split("create table if not exists ksv_outcomes")[1].split(");")[0]
    assert "baseline" not in block


def test_discrimination_has_no_hit_rate_column() -> None:
    """「불일치 적중률 68%」 한 줄이면 다음 판정을 예측으로 읽는다 (R2)."""
    block = SQL.split("create table if not exists ksv_discrimination")[1].split(");")[0].lower()
    for banned in ("hit_rate", "accuracy", "win_rate", "return"):
        assert banned not in block, f"적중률 성격의 열이 있다: {banned}"


def test_source_column_is_open_for_backfill() -> None:
    """지금은 batch/ondemand뿐이지만 나중에 소급이 늘어도 스키마를 안 고친다 (F21b)."""
    assert "source in ('batch', 'ondemand', 'backfill')" in SQL
