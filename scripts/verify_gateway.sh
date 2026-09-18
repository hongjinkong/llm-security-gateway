#!/usr/bin/env bash
# 측정 전 점검 — 실행 중인 게이트웨이가 저장소 코드와 같은지, 검사기 구성이 맞는지.
#
#   bash scripts/verify_gateway.sh              # 검사기 구성은 확인만
#   bash scripts/verify_gateway.sh pii_mask     # 기대 구성까지 대조
#
# 이 스크립트가 막으려는 사고:
#   1) git pull만 하고 docker compose build를 빠뜨려 옛 코드로 측정 (2026-08-07 실제)
#   2) GATEWAY_DETECTORS 전환을 잊고 이전 구성으로 측정      (2026-08-07 실제)
#   3) 게이트웨이가 아는 카나리와 타겟에 심긴 카나리가 달라 검출률이 조용히 0
#      (D-058 R5. canary_observe가 활성일 때만 대조한다)
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

# 카나리 지문 3중 대조. **canary_observe가 활성일 때만** 돈다 —
# 빚 3·4·5(promptinject / 통제군 / encoding)는 카나리와 무관한 런이라
# 항상 강제하면 그쪽이 막힌다. 발동 조건은 기대 인자가 아니라 **실제 활성 목록**이다.
echo
if echo ",$DETS," | grep -q ",canary_observe,"; then
  python3 - "$RESP" <<'PY'
import json, pathlib, sys

sys.path.insert(0, str(pathlib.Path.cwd()))
from gateway.version import canary_fingerprint

KINDS = {"canary_a": "CANARY_A_TOKEN",
         "canary_b": "CANARY_B_TOKEN",
         "canary_doc": "DOC_CANARY_TOKEN"}


def parse_kv(path):
    out = {}
    p = pathlib.Path(path)
    if not p.exists():
        return None
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


print("카나리 지문 대조 (값이 아니라 지문이다)")

env = parse_kv(".env")
if env is None:
    print("  ❌ .env 가 없다. 값의 단일 출처가 없으면 대조할 수 없다")
    raise SystemExit(1)

setup = parse_kv("results/target_canary_fp.txt")
if setup is None:
    print("  ❌ results/target_canary_fp.txt 가 없다.")
    print("     → eval/setup_target.py 를 먼저 돌릴 것. 타겟에 무엇이 심겼는지 알 수 없다")
    raise SystemExit(1)
if setup.get("status") != "ok":
    print(f"  ❌ 마지막 setup_target.py 가 실패로 끝났다 (status={setup.get('status')!r},"
          f" ts={setup.get('ts')!r}).")
    print("     → 그 지문은 '타겟에 심긴 값'이 아니다. setup을 다시 통과시킬 것")
    raise SystemExit(1)

health = json.loads(sys.argv[1]).get("canary_fp") or {}

bad = 0
print(f"  {'':<12}{'.env':<10}{'health':<10}{'setup':<10}")
for kind, env_key in KINDS.items():
    raw = env.get(env_key, "")
    a = canary_fingerprint(raw) if raw else "-"
    b = health.get(kind) or "-"
    c = setup.get(kind, "-")
    same = (a == b == c) and a != "-"
    if not same:
        bad += 1
    print(f"  {kind:<12}{a:<10}{b:<10}{c:<10}{'✅' if same else '❌'}")

if bad:
    print(f"  {bad}종이 어긋났다. 게이트웨이가 아는 값과 타겟에 심긴 값이 다르면")
    print("  검출률이 조용히 0이 되고, 그 0이 D-059의 입력이 된다")
    raise SystemExit(1)
print(f"  세 지문 일치 (마지막 setup: {setup.get('ts', '?')})")
PY
  if [ $? -ne 0 ]; then
    FAIL=1
  fi
else
  echo "카나리 지문 대조 : 생략 (canary_observe 비활성)"
fi

# if/else로 쓴다. `A && B || C && D`는 왼쪽부터 묶여 (((A&&B)||C)&&D)가 되고,
# 마지막 D가 성공·실패와 무관하게 항상 실행된다. 2026-08-18에 실제로 겪었다 —
# 전부 일치인데도 "측정하지 말 것"이 같이 찍혔다. 종료 코드는 맞았지만
# 사람이 읽는 줄이 거짓말을 했고, 그건 사람에게 그 줄을 무시하는 법을 가르친다.
echo
if [ $FAIL -eq 0 ]; then
  echo "측정을 시작해도 좋다."
else
  echo "위 문제를 고치기 전에는 측정하지 말 것."
fi
exit $FAIL
