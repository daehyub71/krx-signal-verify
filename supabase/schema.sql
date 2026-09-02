-- krx-signal-verify 스키마 (ksv_ 접두어 · 6개)
--
-- 같은 Supabase 프로젝트를 네 프로젝트가 나눠 쓴다. 남의 접두어를 건드리지 않는다:
--   ksc_*(krx-stock-charts) · ksa_*(krx-signal-alerts) · ksb_*(krx-signal-briefing)는 읽기만.
--
-- 재실행해도 안전하다(멱등). 적용은 `python scripts/apply_schema.py`.
--
-- ─────────────────────────────────────────────────────────────
-- RLS 방침 — 여기가 이 프로젝트의 보안 급소다 (SPEC §5 · V9)
--
--   `to anon` 정책은 **어떤 경우에도 만들지 않는다.**
--   선행 ksb_*에 열어 뒀다가 **공개된 anon 키로 브리핑 15행이 통째로 읽혔다** (2026-08-31).
--   그 anon 키는 상위 krx-stock-charts 웹 번들에 실려 있다.
--
--   그런데 **RLS를 켜고 정책을 하나도 안 만들면 「아무도 못 읽는다」**가 된다 —
--   PostgreSQL은 소유자·슈퍼유저·BYPASSRLS를 뺀 모든 롤에 0행을 준다.
--   배치는 service_role(BYPASSRLS)이라 상관없지만, **대시보드의 ksv_reader는 막힌다.**
--   그래서 `to ksv_reader` SELECT 정책은 **반드시 만든다.**
--
--   ksv_reader에 BYPASSRLS를 주는 길도 있으나 쓰지 않는다 — 폭발 반경이 다시 넓어진다.
-- ─────────────────────────────────────────────────────────────

-- 전용 읽기 롤. **비밀번호는 여기 적지 않는다** — 커밋되는 파일이다.
-- `apply_schema.py --set-reader-password`가 KSV_READER_PASSWORD 환경변수로 따로 건다.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'ksv_reader') then
    create role ksv_reader login noinherit;
  end if;
end $$;

-- ─────────────────────────────────────────────
-- 1. 판정 (F20) — 선행은 렌더 때 계산하고 버렸다. 그래서 이력이 없었다.
--
-- `rules_version`이 붙는다. 가중치를 고치면 버전이 올라가고
-- **과거 판정은 그때의 산식으로 남는다** — 서로 다른 자로 잰 값을 한 표에 섞지 않는다.
-- `source`는 처음부터 열어 둔다 (F21b): 지금은 batch/ondemand뿐이지만
-- 나중에 소급(backfill)이 늘어도 스키마를 고치지 않는다.
-- ─────────────────────────────────────────────
create table if not exists ksv_verdicts (
  d              date not null,
  ticker         text not null,
  source         text not null default 'batch',
  name           text not null default '',
  strategy       text not null default '',
  stand          text not null,
  score          smallint not null,
  parts          jsonb not null default '[]'::jsonb,
  blind_spots    text[] not null default '{}',
  rules_version  text not null,
  created_at     timestamptz not null default now(),

  primary key (d, ticker, source),

  -- 티커는 숫자가 아니다. `0126Z0`(삼성에피스홀딩스)처럼 문자가 섞인 6자리가 실재한다.
  constraint ksv_verdicts_ticker_format check (ticker ~ '^[0-9A-Z]{6}$'),
  -- 「호재」 같은 말이 새어 드는 것을 DB가 2차로 막는다 (N1).
  constraint ksv_verdicts_stand check (stand in ('정합', '불일치', '무관')),
  constraint ksv_verdicts_score check (score between 0 and 100),
  constraint ksv_verdicts_source check (source in ('batch', 'ondemand', 'backfill'))
);

create index if not exists ksv_verdicts_ticker_d on ksv_verdicts (ticker, d desc);

-- ─────────────────────────────────────────────
-- 2. 증거 다섯 갈래 — 없어도 되는 층이다 (F34). 실패한 갈래는 null로 남는다.
-- ─────────────────────────────────────────────
create table if not exists ksv_evidence (
  d            date not null,
  ticker       text not null,
  disclosures  jsonb,
  news         jsonb,
  flows        jsonb,
  financial    jsonb,
  shorting     jsonb,
  missing      text[] not null default '{}',
  created_at   timestamptz not null default now(),

  primary key (d, ticker),
  constraint ksv_evidence_ticker_format check (ticker ~ '^[0-9A-Z]{6}$')
);

-- ─────────────────────────────────────────────
-- 3. 사후 주가 (F22·F23) — **되돌아보는 표이지 예측하는 표가 아니다.**
--
-- 미도래 구간은 null이다. 0으로 두면 「초과수익 0%」로 읽힌다.
-- 지수 수익률을 함께 담아 초과수익을 재현 가능하게 둔다.
-- **`baseline` 열은 두지 않는다** — 기준선은 소속 시장 지수 하나뿐이다 (V12).
-- 지수가 없으면 그 구간을 채우지 않는다. 프록시로 대신 재지 않는다 (F23b).
-- ─────────────────────────────────────────────
create table if not exists ksv_outcomes (
  d          date not null,
  ticker     text not null,
  market     text not null default '',
  h5         real,
  h20        real,
  h60        real,
  h5_index   real,
  h20_index  real,
  h60_index  real,
  filled_at  timestamptz,

  primary key (d, ticker),
  constraint ksv_outcomes_ticker_format check (ticker ~ '^[0-9A-Z]{6}$')
);

-- ─────────────────────────────────────────────
-- 4. 분별력 (F24) — 군 간 분포 비교.
--
-- **적중률 열을 두지 않는다.** 「불일치 적중률 68%」 한 줄이면 다음 판정을 예측으로 읽는다 (R2).
-- 중앙값·사분위·겹침·표본 수만 담는다.
-- ─────────────────────────────────────────────
create table if not exists ksv_discrimination (
  as_of          date not null,
  horizon        smallint not null,
  rules_version  text not null,
  n_aligned      integer not null default 0,
  n_conflict     integer not null default 0,
  aligned        jsonb not null default '{}'::jsonb,
  conflict       jsonb not null default '{}'::jsonb,
  overlap        real,
  created_at     timestamptz not null default now(),

  primary key (as_of, horizon, rules_version),
  constraint ksv_discrimination_horizon check (horizon in (5, 20, 60))
);

-- ─────────────────────────────────────────────
-- 5. 실행 기록 — **실패해도 먼저 남긴다.**
-- ─────────────────────────────────────────────
create table if not exists ksv_runs (
  run_at          timestamptz primary key default now(),
  run_date        date not null,
  status          text not null,
  gate            text not null default '',
  signals         integer not null default 0,
  verdicts        integer not null default 0,
  outcomes_filled integer not null default 0,
  detail          jsonb not null default '{}'::jsonb
);

-- ─────────────────────────────────────────────
-- 6. 온디맨드 요청 큐 (V8) — 웹이 넣고 워크플로가 가져간다.
-- ─────────────────────────────────────────────
create table if not exists ksv_requests (
  id            bigserial primary key,
  requested_at  timestamptz not null default now(),
  ticker        text not null,
  status        text not null default 'queued',
  result_d      date,
  detail        jsonb not null default '{}'::jsonb,

  constraint ksv_requests_ticker_format check (ticker ~ '^[0-9A-Z]{6}$'),
  constraint ksv_requests_status check (status in ('queued', 'running', 'done', 'failed'))
);

create index if not exists ksv_requests_status on ksv_requests (status, requested_at);

-- ── 마이그레이션 ──────────────────────────────
-- `create table if not exists`는 **마이그레이션이 아니다** — 이미 있는 테이블에 열을 추가하지 않는다.
-- 정의만 고치면 새 DB에서만 반영되고 운영 DB는 조용히 그대로 남는다.
-- 열을 늘릴 때는 여기에 `alter table ... add column if not exists`를 반드시 한 줄 더한다.
--
-- (아직 없음 — 첫 판이다)

-- ─────────────────────────────────────────────
-- RLS — 켜고, anon은 막고, ksv_reader만 읽는다
-- ─────────────────────────────────────────────
alter table ksv_verdicts       enable row level security;
alter table ksv_evidence       enable row level security;
alter table ksv_outcomes       enable row level security;
alter table ksv_discrimination enable row level security;
alter table ksv_runs           enable row level security;
alter table ksv_requests       enable row level security;

-- 혹시 과거에 열어 둔 것이 있으면 지운다.
drop policy if exists ksv_verdicts_anon       on ksv_verdicts;
drop policy if exists ksv_evidence_anon       on ksv_evidence;
drop policy if exists ksv_outcomes_anon       on ksv_outcomes;
drop policy if exists ksv_discrimination_anon on ksv_discrimination;
drop policy if exists ksv_runs_anon           on ksv_runs;
drop policy if exists ksv_requests_anon       on ksv_requests;

-- 읽기 롤에게만 SELECT. **이것이 없으면 대시보드도 0행을 받는다.**
grant usage on schema public to ksv_reader;
grant select on ksv_verdicts, ksv_evidence, ksv_outcomes,
                ksv_discrimination, ksv_runs, ksv_requests to ksv_reader;

drop policy if exists ksv_verdicts_reader       on ksv_verdicts;
drop policy if exists ksv_evidence_reader       on ksv_evidence;
drop policy if exists ksv_outcomes_reader       on ksv_outcomes;
drop policy if exists ksv_discrimination_reader on ksv_discrimination;
drop policy if exists ksv_runs_reader           on ksv_runs;
drop policy if exists ksv_requests_reader       on ksv_requests;

create policy ksv_verdicts_reader       on ksv_verdicts       for select to ksv_reader using (true);
create policy ksv_evidence_reader       on ksv_evidence       for select to ksv_reader using (true);
create policy ksv_outcomes_reader       on ksv_outcomes       for select to ksv_reader using (true);
create policy ksv_discrimination_reader on ksv_discrimination for select to ksv_reader using (true);
create policy ksv_runs_reader           on ksv_runs           for select to ksv_reader using (true);
create policy ksv_requests_reader       on ksv_requests       for select to ksv_reader using (true);
