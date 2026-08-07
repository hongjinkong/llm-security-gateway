#!/usr/bin/env bash
# garak 실행 래퍼 — 베이스라인과 방어 적용을 '설정 파일 하나'만 다르게 돌린다.
#
#   bash scripts/run_garak.sh target  "$DAN_PROBES" 10 baseline_dan_recheck
#   bash scripts/run_garak.sh gateway promptinject   10 gw_none_promptinject
#
# 이 스크립트는 베이스라인 3종을 실제로 돌린 명령을 그대로 옮긴 것이다(2026-08-07 확정).
# 달라지는 것은 -G 로 넘기는 설정 파일 하나뿐이며, 그 두 파일은 uri 한 줄만 다르다.
# EVAL 5.1: 그 외 조건이 바뀌면 베이스라인과 비교할 수 없다.
#
# 의도적으로 넣지 않은 것:
#   --parallel_requests  최종 베이스라인 3종이 순차로 돌았다(리포트 parallel_requests=false).
#                        D-024에서 8GB VRAM 병렬이 오히려 느렸다고 확인됨.
#   sessionId            베이스라인 요청 템플릿에 없다. 넣으면 전체 재측정이다.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

WHERE=${1:?"첫 번째 인자: target 또는 gateway"}
PROBES=${2:?"두 번째 인자: 프로브 문자열 (dan은 D-022의 고정 문자열)"}
GENS=${3:-10}
NAME=${4:-run}

case "$WHERE" in
  target)  CFG=anythingllm_rest.json ;;
  gateway) CFG=gateway_rest.json ;;
  *) echo "첫 번째 인자는 target 또는 gateway"; exit 1 ;;
esac

# 타겟 컨테이너가 실제로 붙어 있는 네트워크를 그대로 쓴다(compose 프로젝트명에 의존 안 함)
NET=$(docker inspect target-anythingllm \
        --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}' | awk '{print $1}')
[ -n "$NET" ] || { echo "target-anythingllm 컨테이너가 떠 있지 않다"; exit 1; }

if [ "$WHERE" = "gateway" ]; then
  docker inspect llm-gateway >/dev/null 2>&1 || { echo "llm-gateway 컨테이너가 떠 있지 않다"; exit 1; }
  DET=$(docker exec llm-gateway printenv GATEWAY_DETECTORS 2>/dev/null || true)
  echo "게이트웨이 검사기 구성: '${DET:-(없음)}'   ← EVAL 5.2 표의 어느 행인지 반드시 기록할 것"
fi

docker rm -f "garak_${NAME}" >/dev/null 2>&1 || true

echo "실행: where=$WHERE  probes=$PROBES  generations=$GENS  name=$NAME  network=$NET"
echo "시작: $(date -Iseconds)"

# detached로 띄운다. 몇 시간짜리 실행이라 터미널이 닫혀도 살아남아야 한다.
# 화면잠금(Win+L)은 괜찮지만 절전은 컨테이너를 통째로 죽인다 → powercfg 확인할 것.
# REST_API_KEY: garak RestGenerator가 설정의 $KEY 자리에 넣는 환경변수 이름.
docker run -d --name "garak_${NAME}" \
  --network "$NET" \
  -e REST_API_KEY="$TARGET_API_KEY" \
  -v "$PWD/garak:/work" \
  -v "$PWD/garak/logs:/root/.local/share/garak" \
  garak-runner \
    --target_type rest \
    -G "/work/$CFG" \
    --probes "$PROBES" \
    --generations "$GENS" \
    --report_prefix "$NAME"

cat <<EOF

진행 확인:
  docker logs -f garak_${NAME}
  bash check.sh

완주 후:
  python3 scripts/asr_summary.py garak/logs/garak_runs/${NAME}.report.jsonl \\
    | tee results/${NAME}_summary.md
  cp garak/logs/garak_runs/${NAME}.report.jsonl results/${NAME}.report.jsonl

리포트가 위 이름으로 없으면 (report_prefix 미적용 시):
  ls -t garak/logs/garak_runs/*.report.jsonl | head -1
EOF
