#!/usr/bin/env bash
# 측정 전 점검 — 실행 중인 게이트웨이가 저장소 코드와 같은지, 검사기 구성이 맞는지.
#
#   bash scripts/verify_gateway.sh              # 검사기 구성은 확인만
#   bash scripts/verify_gateway.sh pii_mask     # 기대 구성까지 대조
#
# 이 스크립트가 막으려는 두 가지 사고(둘 다 2026-08-07에 실제 발생):
#   1) git pull만 하고 docker compose build를 빠뜨려 옛 코드로 측정
#   2) GATEWAY_DETECTORS 전환을 잊고 이전 구성으로 측정
set -uo pipefail
cd "$(dirname "$0")/.."

URL=${GATEWAY_URL:-http://localhost:8080}
EXPECT_DET=${1:-}

LOCAL=$(python3 gateway/version.py)

# 컨테이너를 막 띄운 직후에는 uvicorn 기동에 1~2초가 걸린다. 잠시 기다려 준다.
RESP=""
for i in $(seq 1 15); do
  RESP=$(curl -s --max-time 3 "$URL/__gateway/health" 2>/dev/null) && [ -n "$RESP" ] && break
  sleep 1
done
if [ -z "$RESP" ]; then
  echo "게이트웨이 응답 없음: $URL (15초 대기 후 포기)"
  echo "  → docker compose ps / docker logs llm-gateway 로 상태 확인"
  exit 1
fi

read -r RUNNING TARGET DETS <<<"$(python3 - "$RESP" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
print(d.get("code", "?"), d.get("target", "?"), ",".join(d.get("detectors", [])) or "-")
PY
)"

echo "저장소 코드 지문 : $LOCAL"
echo "실행 중 코드 지문 : $RUNNING"
echo "타겟             : $TARGET"
echo "활성 검사기       : $DETS"
echo

FAIL=0
if [ "$LOCAL" != "$RUNNING" ]; then
  echo "❌ 코드 불일치. 컨테이너가 옛 소스로 돌고 있다."
  echo "   → docker compose build gateway && docker compose up -d gateway"
  FAIL=1
else
  echo "✅ 코드 일치"
fi

if [ -n "$EXPECT_DET" ]; then
  WANT=$(echo "$EXPECT_DET" | tr -d ' ')
  [ "$WANT" = "none" ] && WANT="-"
  if [ "$DETS" != "$WANT" ]; then
    echo "❌ 검사기 구성 불일치. 기대 '$WANT' / 실제 '$DETS'"
    echo "   → GATEWAY_DETECTORS=$EXPECT_DET docker compose up -d gateway"
    FAIL=1
  else
    echo "✅ 검사기 구성 일치 ($DETS)"
  fi
fi

[ $FAIL -eq 0 ] && echo && echo "측정을 시작해도 좋다." || echo && echo "위 문제를 고치기 전에는 측정하지 말 것."
exit $FAIL
