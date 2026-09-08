# krx-signal-verify

[한국어 (README_KO.md)](README_KO.md)

Verifies daily Korean-equity chart signals against evidence. For every signal the upstream
screener emits, this project collects five lanes of evidence — DART filings (with bodies),
Naver news, institutional/foreign flows, DART financials and short-selling — and lets **code**
decide whether the evidence *aligns with*, *conflicts with* or is *unrelated to* the signal,
with a 0–100 score and an explicit list of blind spots. An LLM only writes the explanation; it
cannot change the verdict. Verdicts are stored, later outcomes are measured against the market
index, and the two verdict groups are compared as **distributions** — never as a hit rate.

> Not investment advice. A personal, single-recipient test. Grades and scores describe how well
> the evidence supports a signal, not where the price will go.

![architecture](docs/arch.png)

## What it does

| Stage | Detail |
|---|---|
| Gate | Waits for the upstream run record (`ksa_runs`) instead of trusting the dispatch event; `stale` / `gate_timeout` are recorded, never silent |
| Signals | Reads the signals dated by the upstream (the previous trading day's close), not by the run date |
| Evidence | DART list + event bodies (MCP with REST fallback), Naver news filtered by company name, 30-day flows, quarterly financials (`fnlttMultiAcnt`, 15 companies per call, report descent), 20-day short-selling ratio |
| Verdict | Rule table (`docs/RULES.md`, `rules_version`) → 정합 / 불일치 / 무관 + score + parts + blind spots. Saved **before** the LLM runs |
| Explanation | Claude writes a short rationale under a JSON schema; output is validated (forbidden wording, known tickers, counts we supplied) |
| Outcomes | 5/20/60 trading-day excess return vs the stock's own market index; pending horizons stay `null` |
| Discrimination | Quartiles, medians, sample sizes and overlap of the 정합 vs 불일치 groups; nothing is drawn below n=30 |
| Surfaces | A short mail with a link, and a Next.js dashboard (today · ticker · history · discrimination · on-demand) behind Vercel authentication |
| On-demand | The dashboard queues a ticker, dispatches the workflow, and polls the request row until `done` (≈2.5 min) |

## Stack

- **Batch**: Python 3.11, LangGraph (three layers: graph / pure domain / I/O), psycopg 3, Anthropic SDK, stdio MCP clients (`korean-dart-mcp`, `naver-search-mcp`) with REST fallback
- **Storage**: Supabase Postgres (`ksv_*` tables, RLS on, no `anon` policies, dedicated read-only role `ksv_reader`)
- **Automation**: GitHub Actions — `repository_dispatch` from the upstream screener, a backup cron, `workflow_dispatch`, and `verify-ticker` for on-demand requests
- **Web**: Next.js 16 · TypeScript · Tailwind 4 · `pg` (server-only, pooled), Vitest
- **Upstream (read-only)**: `krx-stock-charts` (bars, tickers, flows, index bars, short-selling), `krx-signal-alerts` (signals)

## Repository layout

```
verify/        batch package — graph.py · nodes.py · state.py (graph layer)
               verdict.py · flags.py · routine.py · financial.py · shorting.py · wording.py · analysis.py (pure domain)
               store.py · dart.py · dart_mcp.py · dart_fin.py · news_mcp.py · mcpc.py · llm.py · notify.py · main.py (I/O)
tests/         752 pytest cases — every outward seam is mocked; a guard test blocks the real DB/SMTP/LLM
web/           Next.js dashboard (app/, lib/, tests/ — 59 Vitest cases)
supabase/      schema.sql (idempotent; RLS + reader role policies)
scripts/       apply_schema.py · export_graph.py · check_diagram.py · deploy_web.sh · hand_check.py
docs/          SPEC.md · PLAN.md · DESIGN.md · TASKS.md · RULES.md · GRAPH.md · diagrams/*.dot
.github/       ci.yml (ruff · mypy · pytest) · verify.yml (the batch)
```

## Setup

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # fill in values; .env is git-ignored
python scripts/apply_schema.py  # creates ksv_* tables, RLS, reader policies (idempotent)
python scripts/apply_schema.py --set-reader-password   # from KSV_READER_PASSWORD
```

Environment variable **names** are listed in `.env.example` (DART, Anthropic, Naver, Supabase,
reader role, Gmail SMTP, dashboard URL). Never commit values.

## Run

```bash
python -m verify.main                     # today's batch (gate → collect → judge → explain → mail)
python -m verify.main --date 20260904     # a specific run date
python -m verify.main --ticker 005930     # on-demand: one ticker, no mail
python -m verify.main --dry-run --force   # re-judge and save without sending
python -m verify.main --if-not-verified   # backup cron: no-op if today already ran
```

## Verify

```bash
ruff check . && mypy && pytest -q                      # batch (mypy covers tests too)
cd web && npm run lint && npm test && npm run build    # dashboard
python scripts/check_diagram.py                        # hand-drawn graph == compiled graph
```

## Dashboard deployment

```bash
scripts/deploy_web.sh
```

Vercel's Hobby plan cannot protect the production domain, so the script keeps a harmless
placeholder on production and deploys the real app as a **preview** behind Vercel
authentication, aliased to a stable URL. It refuses to proceed if the alias is not protected.

## Security notes

- Secrets live only in `.env` / GitHub Secrets / Vercel env vars; the DART key is masked in every error message.
- `ksv_*` tables have RLS enabled and no `anon` policy (a regression test enforces it). The dashboard reads through `ksv_reader`, which can only `SELECT` — plus `INSERT (queued)` / `UPDATE (failed)` on the on-demand request table.
- Workflow inputs are passed through environment variables, never interpolated into shell.
- Wording rules (N1/N2) are enforced in Python and in the web source: no trading advice, no hit-rate language.

## Docs

- `docs/SPEC.md` — requirements and decisions (V1–V14)
- `docs/RULES.md` — the verdict rule table and score formula history
- `docs/DESIGN.md` — dashboard IA, wireframes, the agreed canvas
- `docs/TASKS.md` — milestone log, measurements, troubleshooting
