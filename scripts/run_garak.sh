#!/usr/bin/env bash
# garak 실행 래퍼 — 베이스라인과 방어 적용을 '설정 파일 하나'만 다르게 돌린다.
#
#   bash scripts/run_garak.sh target  dan 10 baseline_dan
#   bash scripts/run_garak.sh gateway dan 10 piimask_dan
#
# EVAL 5.1 고정 조건: 두 실행은 REST 설정의 uri를 빼면 완전히 같아야 한다.
# 프롬프트 템플릿(message/mode)도 베이스라인과 동일하게 유지한다. sessionId를
# 여기서 새로 넣으면 조건이 바뀌어 베이스라인과 비교할 수 없게 된다(D-013 참고).
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; source .env; set +a

WHERE=${1:?"첫 번째 인자: target 또는 gateway"}
PROBES=${2:?"두 번째 인자: 프로브 문자열 (dan은 D-022의 고정 문자열을 쓸 것)"}
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

mkdir -p garak/logs/garak_runs
echo "실행: where=$WHERE  probes=$PROBES  generations=$GENS  name=$NAME  network=$NET"
echo "시작: $(date -Iseconds)"

docker run --rm --name "garak_${NAME}" \
  --network "$NET" \
  -e KEY="$TARGET_API_KEY" \
  -v "$PWD/garak:/work" \
  -v "$PWD/garak/logs/garak_runs:/root/.local/share/garak/garak_runs" \
  garak-runner \
    --target_type rest \
    --generator_option_file "/work/$CFG" \
    --probes "$PROBES" \
    --generations "$GENS" \
    --report_prefix "$NAME"

echo "종료: $(date -Iseconds)"
echo "다음: python3 scripts/asr_summary.py garak/logs/garak_runs/${NAME}.report.jsonl | tee results/${NAME}_summary.md"
