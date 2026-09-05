#!/usr/bin/env bash
# 대시보드 배포 — **반드시 preview 배포 + 보호 별칭**으로 (V10 · TASKS M7 트러블슈팅 ①).
#
# Hobby 플랜은 프로덕션 도메인(krx-signal-verify.vercel.app)에 Vercel Authentication을 걸 수 없다
# (API: "not available on your plan for production deployments", 2026-09-06 실측). 보호되는 것은
# preview 배포와 그 별칭만이다. 그래서
#   · 프로덕션 자리에는 무해한 자리표시 페이지(scripts/vercel-placeholder)만 둔다
#   · 진짜 앱은 preview로 올리고 krx-signal-verify-dash.vercel.app 별칭에 붙인다 (302 → Vercel 인증)
#   · 프로덕션 배포가 하나도 없으면 다음 배포가 프로덕션이 된다 — 그래서 자리표시를 먼저 확인한다
#
# 사용: scripts/deploy_web.sh            (web/ 에서 npm run lint · test · build 를 먼저 통과시킨 뒤)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB="$ROOT/web"
ALIAS="krx-signal-verify-dash.vercel.app"
PROD_ALIAS="krx-signal-verify.vercel.app"

cd "$WEB"
[ -f .vercel/project.json ] || { echo "web/.vercel/project.json 이 없다 — 'vercel link --yes --project krx-signal-verify' 먼저"; exit 1; }

# 1. 프로덕션 자리에 자리표시가 있어야 한다. 없으면 먼저 올린다 (없으면 다음 배포가 프로덕션이 된다).
if ! vercel ls 2>&1 | grep -q "Production"; then
  echo "프로덕션 배포가 없다 — 자리표시를 먼저 올린다"
  TMP="$(mktemp -d)"; cp -R "$ROOT/scripts/vercel-placeholder/." "$TMP/"; mkdir -p "$TMP/.vercel"; cp .vercel/project.json "$TMP/.vercel/"
  (cd "$TMP" && vercel deploy --prod --yes >/dev/null)
  rm -rf "$TMP"
fi
TITLE="$(curl -s "https://$PROD_ALIAS" | grep -oE '<title>[^<]*</title>' || true)"
[ "$TITLE" = "<title>비공개</title>" ] || { echo "!! $PROD_ALIAS 가 자리표시가 아니다: $TITLE — 멈춘다"; exit 2; }

# 2. 진짜 앱을 preview로.
OUT="$(vercel deploy --yes 2>&1)" || { echo "$OUT"; exit 1; }
URL="$(echo "$OUT" | grep -oE 'https://krx-signal-verify-[a-z0-9]+-daehyub71s-projects\.vercel\.app' | head -1)"
TARGET="$(vercel inspect "$URL" 2>&1 | awk '/^ *target/{print $2}')"
if [ "$TARGET" != "preview" ]; then
  echo "!! target=$TARGET — 프로덕션이 됐다(공개). 즉시 제거한다"; vercel remove "$URL" --yes; exit 3
fi

# 3. 보호 별칭에 붙이고, 진짜로 막히는지 본다.
vercel alias set "$URL" "$ALIAS" >/dev/null
sleep 3
CODE="$(curl -s -o /dev/null -w '%{http_code}' "https://$ALIAS")"
[ "$CODE" = "302" ] || [ "$CODE" = "401" ] || { echo "!! https://$ALIAS 가 $CODE — 보호가 아니다. 별칭을 뗀다"; vercel alias rm "$ALIAS" --yes; exit 4; }
echo "ok: https://$ALIAS → $URL ($CODE → Vercel 인증) · 프로덕션은 자리표시"
