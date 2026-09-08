# krx-signal-verify

[English (README.md)](README.md)

국내 주식 차트 신호를 **근거로 검증**한다. 상위 스크리너가 매일 내는 신호마다 다섯 갈래 — DART 공시(본문 포함)·
네이버 뉴스·기관/외국인 수급·DART 재무·공매도 — 를 모으고, 근거가 신호와 **정합**하는지 **불일치**하는지 **무관**한지를
**코드가** 규칙으로 판정한다(0~100점 + 보지 않은 것의 목록). LLM은 설명만 쓰고 판정을 바꾸지 못한다.
판정은 저장되고, 뒤에 시장 지수 대비 초과수익을 재어 두 판정 군을 **분포**로 비교한다 — 적중률은 만들지 않는다.

> 투자 권고가 아닙니다. 수신자 한 사람의 참고용 테스트입니다. 점수는 근거가 신호를 얼마나 받치는지를 잴 뿐,
> 앞으로의 주가를 말하지 않습니다.

![아키텍처](docs/arch.png)

## 하는 일

| 단계 | 내용 |
|---|---|
| 게이트 | dispatch 이벤트를 믿지 않고 상위 실행 기록(`ksa_runs`)을 본다. `stale`·`gate_timeout`은 기록으로 남고 침묵하지 않는다 |
| 신호 | 상위가 붙인 날짜(전 거래일 종가 기준)로 신호를 읽는다 — 실행일이 아니다 |
| 증거 | DART 목록+본문(MCP, REST 폴백) · 종목명 필터 뉴스 · 30일 수급 · 분기 재무(`fnlttMultiAcnt` 15개사/회, 보고서 내려가기) · 20거래일 공매도 비중 |
| 판정 | 규칙표(`docs/RULES.md`, `rules_version`) → 정합/불일치/무관 + 점수 + 근거 조각 + 사각지대. **LLM보다 먼저 저장** |
| 서술 | Claude가 JSON 스키마로 짧은 설명을 쓰고, 코드가 검증한다(금지어·입력에 있는 티커·우리가 세어 준 건수) |
| 관측 | 5·20·60거래일 초과수익(소속 시장 지수 대비). 미도래는 `null` |
| 분별력 | 정합 군 vs 불일치 군의 사분위·중앙값·표본 수·겹침. n<30이면 그리지 않는다 |
| 표면 | 간략 메일 + 링크, Next.js 대시보드(오늘·종목·이력·분별력·온디맨드) — Vercel 인증 뒤 |
| 온디맨드 | 대시보드가 요청을 넣고 워크플로를 깨워 `done`까지 폴링(약 2.5분) |

## 스택

- **배치**: Python 3.11 · LangGraph(그래프/순수 도메인/I/O 3층) · psycopg 3 · Anthropic SDK · stdio MCP 클라이언트(`korean-dart-mcp`·`naver-search-mcp`, REST 폴백)
- **저장**: Supabase Postgres (`ksv_*`, RLS 켬, `anon` 정책 없음, 전용 읽기 롤 `ksv_reader`)
- **자동화**: 깃허브 Actions — 상위 `repository_dispatch` · 예비 cron · `workflow_dispatch` · 온디맨드 `verify-ticker`
- **웹**: Next.js 16 · TypeScript · Tailwind 4 · `pg`(서버 전용, 풀러) · Vitest
- **상위(읽기만)**: `krx-stock-charts`(봉·종목·수급·지수·공매도) · `krx-signal-alerts`(신호)

## 구조

```
verify/        배치 패키지 — graph.py · nodes.py · state.py (그래프 층)
               verdict.py · flags.py · routine.py · financial.py · shorting.py · wording.py · analysis.py (순수 도메인)
               store.py · dart.py · dart_mcp.py · dart_fin.py · news_mcp.py · mcpc.py · llm.py · notify.py · main.py (I/O)
tests/         pytest 752개 — 바깥으로 나가는 이음매는 전부 대역. 실DB·SMTP·LLM은 가드 테스트가 막는다
web/           Next.js 대시보드 (app/ · lib/ · tests/ — Vitest 59개)
supabase/      schema.sql (멱등 · RLS · 읽기 롤 정책)
scripts/       apply_schema.py · export_graph.py · check_diagram.py · deploy_web.sh · hand_check.py
docs/          SPEC.md · PLAN.md · DESIGN.md · TASKS.md · RULES.md · GRAPH.md · diagrams/*.dot
.github/       ci.yml (ruff · mypy · pytest) · verify.yml (배치)
```

## 설치

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # 값을 채운다. .env는 커밋되지 않는다
python scripts/apply_schema.py  # ksv_* 테이블·RLS·읽기 롤 정책 (멱등)
python scripts/apply_schema.py --set-reader-password   # KSV_READER_PASSWORD로 설정
```

환경변수 **이름**은 `.env.example`에 있다(DART · Anthropic · 네이버 · Supabase · 읽기 롤 · Gmail SMTP · 대시보드 URL). 값은 절대 커밋하지 않는다.

## 실행

```bash
python -m verify.main                     # 오늘 배치 (게이트 → 수집 → 판정 → 서술 → 메일)
python -m verify.main --date 20260904     # 특정 실행일
python -m verify.main --ticker 005930     # 온디맨드: 한 종목, 메일 없음
python -m verify.main --dry-run --force   # 다시 판정·저장, 발송 없음
python -m verify.main --if-not-verified   # 예비 cron: 오늘 이미 돌았으면 아무것도 안 함
```

## 검증

```bash
ruff check . && mypy && pytest -q                      # 배치 (mypy는 tests까지)
cd web && npm run lint && npm test && npm run build    # 대시보드
python scripts/check_diagram.py                        # 손그림 그래프 == 컴파일된 그래프
```

## 대시보드 배포

```bash
scripts/deploy_web.sh
```

Vercel Hobby 플랜은 프로덕션 도메인을 잠글 수 없다. 그래서 프로덕션에는 무해한 자리표시만 두고, 진짜 앱은
Vercel 인증 뒤의 **preview** 배포로 올려 고정 별칭에 붙인다. 별칭이 보호되지 않으면 스크립트가 멈춘다.

## 보안 메모

- 시크릿은 `.env` · 깃허브 Secrets · Vercel 환경변수에만. DART 키는 모든 오류 메시지에서 마스킹된다.
- `ksv_*`는 RLS가 켜져 있고 `anon` 정책이 없다(회귀 테스트로 고정). 대시보드는 `ksv_reader`로 읽는다 — SELECT와 온디맨드 요청 표의 `INSERT(queued)`·`UPDATE(failed)`만 할 수 있다.
- 워크플로 입력은 환경변수로 받고 셸에 보간하지 않는다.
- 문구 규칙(N1/N2)을 파이썬과 웹 소스에서 검사한다 — 매매 판단 없음, 적중 문구 없음.

## 문서

- `docs/SPEC.md` — 요구사항과 결정(V1~V14)
- `docs/RULES.md` — 판정 규칙표와 점수 산식 이력
- `docs/DESIGN.md` — 대시보드 IA·와이어프레임·합의된 시안
- `docs/TASKS.md` — 마일스톤 기록·측정·트러블슈팅
