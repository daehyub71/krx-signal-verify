# CLAUDE.md — krx-signal-verify

워크스페이스 규칙(`../CLAUDE.md`)을 따르며, 아래는 이 프로젝트 고유 규칙이다.

**작업 시작 전 `docs/SPEC.md` → `docs/PLAN.md` → `docs/DESIGN.md` → `docs/TASKS.md` 순으로 읽는다.**

## 개요

`krx-signal-alerts`가 아침에 보낸 차트 신호가 **근거를 갖는지** 증거 다섯 갈래로 맞춰 판정하고,
**그 판정을 저장해 나중에 되돌아본다.** 선행 `krx-signal-briefing`은 판정을 렌더 때 계산하고 버렸다 —
그래서 「그 판정에 분별력이 있었는가」를 한 번도 물을 수 없었다.

```
차트 신호 (상위)  또는  사용자가 넣은 임의 종목
      ├ 1 DART 공시 본문   ├ 2 네이버 뉴스   ├ 3 기관·외국인 수급
      ├ 4 재무 (신규)      └ 5 공매도 (신규)
      ▼
  정합 / 불일치 / 무관 + 점수 + 근거 서술     ← 판정·점수는 코드가, LLM은 설명만
      ├ 저장  ksv_verdicts (rules_version과 함께)
      ├ 채점  5·20·60거래일 뒤 지수 대비 초과수익
      └ 표면  간략 메일 + 웹 대시보드 4화면
```

- **상위 프로젝트의 읽기 전용 소비자다.** `ksa_*`·`ksc_*`는 SELECT만. 쓰는 곳은 `ksv_*`뿐.
- 배치 층: `verify/` (Python + **LangGraph**) → Supabase `ksv_*` (service_role로 쓰기)
- 표현 층: `web/` (Next.js) → **전용 읽기 롤로 서버 사이드에서만** 읽는다 (V9)
- 상위와의 접점은 **`ksa_signals.evidence` 키뿐**이다 (상위 PLAN §4 공유 계약 — 우리는 네 번째 소비자)

### LangGraph 3층 분리 — 선행 두 프로젝트와 같은 규칙

| 층 | 파일 | 규칙 |
|----|------|------|
| 그래프 | `state.py` · `nodes.py` · `graph.py` | LangGraph를 아는 **유일한** 층 |
| 도메인 | `corp.py` · `flags.py` · `routine.py` · `verdict.py` · `render.py` · `analysis.py` · `financial.py` · `shorting.py` · `outcome.py` · `discriminate.py` · `models.py` | **LangGraph·DB·HTTP·LLM을 import하지 않는다.** 순수 함수. 여기가 TDD 대상 |
| I/O | `store.py` · `enrich.py` · `mcpc.py` · `dart*.py` · `news_mcp.py` · `llm.py` · `notify.py` · `config.py` · `main.py` | 부수효과를 아는 유일한 곳. 테스트는 전부 mock |

- **노드는 20줄을 넘지 않는다.** 넘으면 도메인 로직이 새어 들어온 것이니 도메인 모듈로 옮긴다.
- **LangGraph를 걷어내도 도메인 코드가 그대로 살아 있어야 한다.**
- **`store.py`의 조회 함수를 그래프 상태에 묶지 않는다** — 순수한 「인자 → 행」 모양이면
  나중에 MCP 도구로 그대로 감쌀 수 있다 (SPEC V14 · PLAN §6-2).

## 문구 규칙 — 이 프로젝트의 가장 큰 리스크 둘

**N1 매매 판단 금지** (선행 계승). 사실과 근거 정합성은 되고 매매 판단은 안 된다.
금지어: `추천` `매수` `매도` `보류` `목표가` `손절` `여력` `이탈` `진입` `비중` · 단독 `없음`.
`순매수`·`순매도`·`매수세`·`매도세`는 **허용 복합어로 먼저 지우고** 검사한다 —
선행에서 `순매도`가 `매도`에 걸려 분석 15개가 통째로 버려졌다.

**N2 적중 문구 금지** (이 프로젝트 신설). **개별 종목에 「맞았다/틀렸다」를 쓰지 않는다.**
집계에도 `적중률` `승률` `수익률`을 쓰지 않고 **`초과수익 분포`·`분별력`·`표본 수`**로 적는다.

> **「불일치」는 "근거가 신호와 어긋난다"이지 "떨어진다"가 아니다.**
> 화면에 「불일치 적중률 68%」가 뜨는 순간 이 프로젝트는 하지 않기로 한 일(예측)을 하는 장치가 된다.
> 문구로만 막지 않는다 — **`discriminate.py`의 반환 타입에 적중률 필드를 두지 않아 구조로 막는다.**

**`RECIPIENTS`는 본인 한 사람.** 대시보드는 Vercel SSO 뒤에 둔다 (SPEC R1·V10).

## Supabase 테이블

| 테이블 | 소유 | 이 프로젝트의 권한 |
|--------|------|-------------------|
| `ksa_signals` · `ksa_runs` | `krx-signal-alerts` | **SELECT만** |
| `ksc_bars` · `ksc_tickers` · `ksc_investor_flows` · `ksc_index_bars` · `ksc_shorting` | `krx-stock-charts` | **SELECT만** |
| `ksb_*` | `krx-signal-briefing` (선행) | **읽지 않는다** — 병행 기간에도 간섭하지 않는다 |
| `ksv_verdicts` · `ksv_evidence` · `ksv_outcomes` · `ksv_discrimination` · `ksv_runs` · `ksv_requests` | **이 프로젝트** | 읽기·쓰기 |

**RLS는 켜되 `to anon` 정책은 만들지 않는다. 대신 `to ksv_reader` SELECT 정책은 반드시 만든다** —
정책이 하나도 없으면 PostgreSQL이 **모든 롤에 0행**을 주므로 대시보드도 막힌다 (SPEC §5).

## 실행

```bash
source venv/bin/activate

python -m verify.main                      # 오늘 기준 검증 + 메일
python -m verify.main --dry-run            # 발송·저장 없이 결과만
python -m verify.main --date 20260901      # 특정 기준일 재현
python -m verify.main --ticker 042700      # 온디맨드 (상위 신호 없이 임의 종목)
python -m verify.main --force              # 이미 있어도 다시 만든다
python -m verify.main --if-not-verified    # 예비 cron용 — 오늘 이미 돌았으면 no-op

python scripts/apply_schema.py             # ksv_* 스키마 적용 (멱등)
python scripts/export_graph.py             # 그래프 → docs/GRAPH.md (구조 변경 시 반드시)
python scripts/check_diagram.py            # graph.dot ↔ GRAPH.md 간선 대조
```

## 검증 (태스크·마일스톤 완료 시 전부 통과 필수)

```bash
ruff check .        # 1. 린트
mypy                # 2. 타입 체크 (strict — files는 pyproject.toml)
pytest tests/ -v    # 3. 테스트

cd web && npm run lint && npm test && npm run build   # 웹 (M7 이후)
```

## 자격증명

`.env`는 `.gitignore` 대상 — **절대 커밋 금지**. `.env.example`은 키 이름만 담는다.

| 키 | 용도 |
|----|------|
| `DART_API_KEY` | OpenDART 공시·재무. **URL 쿼리에 실린다** — 예외 메시지·로그에 URL을 통째로 찍지 않는다 |
| `ANTHROPIC_API_KEY` | 근거 서술 (F11). 없으면 판정만 나가고 `⚠ 서술 생략`이 붙는다 |
| `NCP_APIGW_API_KEY_ID`+`NCP_APIGW_API_KEY` **또는** `NAVER_CLIENT_ID`+`NAVER_CLIENT_SECRET` | 네이버 뉴스. **한 쌍만** 온전하면 된다 — 반쪽이면 서버가 기동을 거부한다 |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `SUPABASE_DATABASE_URL` | 배치. service key는 RLS를 우회한다 |
| `KSV_READER_DATABASE_URL` | 웹 전용 읽기 롤 (V9). **`NEXT_PUBLIC_` 접두어를 붙이지 않는다** |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `RECIPIENTS` | Gmail SMTP. 앱 비밀번호이지 계정 비밀번호가 아니다 |
| `VERCEL_TOKEN` / `VERCEL_PROJECT` | 대시보드 배포. **배포 보호(SSO)를 끄지 않는다** |
| (상위 리포) fine-grained PAT | 이 리포 1개 · Contents write — `alert.yml`의 dispatch용 |
| ~~`KIS_*`~~ | **임시.** V12 확인용이었고 결론은 pykrx다. 정리 대상 (TASKS M-1 ②e) |

## 이 프로젝트에서 조심할 것

- **fan-out 결과는 reducer로 받는다** — `evidence: Annotated[list, operator.add]`를 빼먹으면
  **마지막 하나만 남고 예외도 안 난다.** 선행 두 곳에서 실증됐다. `tests/test_graph.py`의 합류 테스트가
  유일한 방어선이니 지우지 말 것.
- **I/O 노드는 예외를 밖으로 내지 않는다** — raise하면 `record_run`에 못 가 **실패 기록까지 사라진다.**
  결과를 상태에 적고, 실패 판정은 `finalize` 한 곳에서만.
- **`fill_outcomes`는 게이트보다 앞에 둔다** — 어제 판정 채점은 오늘 신호와 무관하다.
  게이트가 `stale`·`gate_timeout`으로 끝나는 날에도 **채점은 돌아야 한다.**
- **저장은 청크로 나눠 보낸다** — 선행에서 44행을 한 문장으로 upsert했다가 `57014 statement timeout`으로
  **하루치가 통째로 사라졌다.** 상한을 올리기 전에 실DB로 재 본다.
- **되살리는 열이 저장하는 열보다 적으면 재실행이 지운다** — 선행에서 15종목이 실제로 사라졌다.
  `to_row()`에 열을 늘리면 `fetch_*`도 함께 늘린다. 왕복 테스트로 잠근다.
- **`evidence`는 우리가 통제하지 않는 계약이다** — `null`로 오거나, 종가가 `"8,420"`처럼 쉼표 낀 문자열로
  오거나, `conditions`가 목록이 아닐 수 있다. **`SignalRow` 프로퍼티를 쓰고 직접 `.get()`으로 파헤치지 않는다.**
- **게이트는 이벤트가 아니라 DB를 믿는다** — dispatch는 「워크플로가 끝났다」만 말한다.
  `ksa_runs` 오늘 행이 없으면 1분×10회 기다렸다 `gate_timeout`.
- **거래정지일은 관측 구간에서 배제한다** — 거래량 0 · 시고저=종가로 오고 **전 일봉의 4.5%**다.
  상위에서 이걸 놓쳐 VCP 판정이 545→176건으로 정상화된 전력이 있다.
- **지수 코드가 두 체계에서 다르다** — pykrx 코스피 `1001`·코스닥 `2001` / KIS 코스피 `0001`·코스닥 `1001`.
  **`1001`이 서로 다른 시장이다.** 섞으면 조용히 틀린 기준선으로 채점한다.
- **지수가 없으면 채우지 않는다** — `null`로 두고 「기준선 미도달」로 표시한다. **프록시로 대신 재지 않는다** (F23b).
- **`get_shorting_balance_by_ticker`는 예외가 아니라 0행으로 실패한다** — `try/except`로는 안 걸린다.
  **행 수 0을 실패로 판정**해야 그 갈래가 「정상적으로 비어 있는」 상태로 지나가지 않는다.
- **DART `013`은 오류가 아니다** — "조회된 데이터가 없습니다" = 공시 0건. `020`은 한도 초과.
- **DART 제목은 흔들린다** — `유상증자결정` / `유상증자 결정` / `[정정]유상증자결정` / `ㆍ`.
  `flags.normalize()`를 거치지 않은 매칭은 미탐.
- **뉴스는 앞 글자가 한글이면 다른 회사다** — `아이텍`이 `위세아이텍` 안에서 잡혔다. 닮은꼴 반례 테스트 필수.
- **모델에게 세라고 시키지 않는다 — 세어서 준다.** 입력에 없는 사실은 지어낸다
  (선행 실측: 플래그 1건인데 「위험 유형 2건」).
- **`stop_reason == "refusal"`을 먼저 본다** — Opus 5는 거부를 HTTP 200으로 준다.
- **Supabase REST는 1000행에서 조용히 잘린다** — 대량 조회는 psycopg 직결 또는 `range()` 페이지네이션.
  완결성 검사를 REST로 하면 오탐이 난다(선행에서 "424개 누락" 오탐, 실제 14개).
- **티커는 숫자가 아니다** — `0126Z0`이 실재한다. 검증식 `^[0-9A-Z]{6}$`.
- **체크포인터를 쓰지 않는다** — 단발 배치라 재개가 무의미하고, 상태에 키가 섞이면 디스크에 남는다.
- **그래프를 고쳤으면 `scripts/export_graph.py`를 다시 돌린다** — 설계도는 손그림이라 **조용히 낡는다.**
  선행에서 3장이 전부 두 판 낡아 있었다. `check_diagram.py`가 CI에서 대조한다.
- **`create table if not exists`는 마이그레이션이 아니다** — 열을 늘릴 때는
  `alter table … add column if not exists`를 반드시 더한다.
- **워크플로에서 파이썬은 `-u`로 돌린다** — 버퍼링 때문에 잘린 실행의 로그가 통째로 비었던 전력.
- **이 맥에는 TLS 인터셉션이 있다** — `certifi` 번들 없이 외부 HTTPS를 부르면
  `CERTIFICATE_VERIFY_FAILED`가 난다 (2026-09-01 실측). `certifi`는 런타임 의존성이다.
- **pip은 이 디렉토리에서** (웹은 `web/`에서 npm) — 워크스페이스 루트 오설치 사례 있음.
- **`ksa_*`·`ksc_*`·`ksb_*`에 쓰지 않는다** — 남의 것이다.
- **MCP 서버 배너를 버전 확인에 쓰지 마라** — `korean-dart-mcp@0.10.1`을 받아도 stderr에
  「v0.9.2 stdio 서버 시작」이라고 찍는다. 상류가 `build/version.js`를 안 올린 것이고,
  package.json·npx 캐시·레지스트리 tarball은 전부 0.10.1이다 (2026-09-02 확인).
  배너를 보고 고정이 풀렸다고 판단해 핀을 내리면 **정말로 옛 서버를 쓰게 된다.**
- **MCP 자격증명은 쌍으로 본다** — 네이버는 HUB 쌍·개발자센터 쌍 중 **하나만** 온전하면 되지만
  **반쪽이면 서버가 기동을 거부한다.** 띄우기 전에 거르지 않으면 그 실패를 콜드스타트만큼
  기다린 뒤에야 받는다. 값이 **빈 문자열인 것도 없는 것으로 센다** — `.env`에 이름만 남은 줄이 흔하다.
- **콜드스타트 상한은 잰 값에서 나온다** — 빈 npm 캐시 실측(2026-09-02) dart 12.3초 · naver 3.0초.
  `Spec.cold_start_seconds`에 적어 두고 `START_TIMEOUT`이 그 다섯 배를 넘는지 테스트가 본다.
  서버를 더하면서 상한을 안 올리면 **그 테스트가 먼저 깨진다.**

- **뉴스 제목 필터: 찾기와 경계 검사를 같은 문자열에서 하지 마라** — 찾기는 공백을 뺀 것에서
  (`한올 바이오파마` = `한올바이오파마`), **앞 글자는 원문에서** 본다. 한 문자열로 통일하면
  `코스닥 아이텍 강세`의 앞이 `닥`으로 보여 멀쩡한 기사가 버려진다. 선행이 그랬고,
  25종목 250건 실측에서 **5건(2.6%)을 놓치고 있었다** — 그것도 「부채비율 430%까지 치솟은
  일성건설」처럼 **설명을 앞에 붙인 기사**만 골라서. 자동 시세 기사는 이름이 앞이라 살아남는다.
  **잰 것이 정밀도면 누락은 안 보인다** (2026-09-05).

- **계정 이름으로 업종을 판정하지 마라** — 「고유 계정이 있으면 금융사」로 봤다가 44종목 실측에서
  **아세아제지(종이·목재)가 금융사로 잡혔다**(`차입부채`는 제조업도 쓴다). 반대로 **삼성화재·코리안리는
  고유 계정이 아예 없다.** 계정 목록으로는 업종을 못 가른다 (2026-09-05).
  남길 것은 **「매출액을 못 찾았다」는 사실 하나**다 — 왜 없는지는 진단하지 않는다 (R7).
- **0행과 「표가 없다」는 다르다** (R6) — pykrx는 예외 없이 0행을 준다. 표가 없으면 **없는 층**(정상)이고,
  표가 있는데 0행이면 **수집 실패**다. 둘을 같이 다루면 그 갈래가 「정상적으로 비어 있는」 상태로 지나간다.

## 선행 프로젝트

| 프로젝트 | 관계 |
|----------|------|
| `../krx-signal-alerts/` | **신호 공급자.** 읽기만 한다. 예외는 `alert.yml`의 dispatch 단계 |
| `../krx-stock-charts/` | **시세·수급·지수·공매도 공급자.** 읽기만 한다. 상위 수집 추가 2건(①a 지수 · ①b 공매도)이 예정돼 있다 |
| `../krx-signal-briefing/` | **직계 선행.** 검증 로직·실측 기록·트러블슈팅이 전부 여기 있다. **새 것이 5거래일 정상 도착하면 끈다** (V1) |

## 진행 상태

**M-1 13/16 · M0 2/15** (2026-09-02) — SPEC **v0.7** · PLAN **v0.3**.
결정은 V1~V13 확정, **V14(MCP 서버를 어디서 만드나)만 의도적으로 M3 뒤로 미뤘다.**
진도는 `docs/TASKS.md` 대시보드 참조.

**M3.5 완료** (2026-09-05) — `ksc_index_bars`에 KOSPI·KOSDAQ 3년치(1,468행)가 서 있다. **M4 착수 가능.**
