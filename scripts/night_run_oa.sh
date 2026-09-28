#!/usr/bin/env bash
# D-081 새 구조 한 밤 — none → rule 두 팔을 순차로 잰다. night_run_encoding.sh의 새 구조 판.
#
#   nohup bash scripts/night_run_oa.sh pi 20261001 >> results/night_oa_pi_20261001_01.log 2>&1 &
#
# 옛 런처와 다른 점:
#   - 두 팔 모두 garak → AnythingLLM(target). 게이트웨이는 AnythingLLM 뒤 /v1에 있고, 팔 사이에는
#     gateway의 검사기만 바꾼다.
#   - B2 환경변수를 스크립트 안에서 고정한다. 빠지면 compose가 조용히 옛 경로로 되돌린다.
#   - E3는 "base 창 감사 0건"이 아니라 팔마다 감사 줄 수 = garak 출력 수다(validate_oa_arm.py).
#
# 착수 전에 사람이 통과시킬 것: D-081 §7 P1·P2·P4, 노이즈 플로어, 그 밤의 FPR 관문(--link time).
set -Eeuo pipefail
cd /home/smhrd/project/llm-security-gateway

NIGHT=${1:?사용: night_run_oa.sh <pi|dan|enc> <YYYYMMDD>}
DAY=${2:?사용: night_run_oa.sh <pi|dan|enc> <YYYYMMDD>}
[[ "$DAY" =~ ^[0-9]{8}$ ]] || { echo "날짜 형식 오류: $DAY"; exit 1; }
case "$NIGHT" in
  pi)  PROBES=promptinject ;;
  dan) PROBES=dan.DanInTheWild,dan.Ablation_Dan_11_0,dan.AutoDANCached,dan.AntiDAN,dan.ChatGPT_Developer_Mode_RANTI,dan.ChatGPT_Developer_Mode_v2,dan.ChatGPT_Image_Markdown,dan.DAN_Jailbreak,dan.DUDE,dan.Dan_10_0,dan.Dan_11_0,dan.Dan_6_0,dan.Dan_6_2,dan.Dan_7_0,dan.Dan_8_0,dan.Dan_9_0,dan.STAN ;;
  enc) PROBES=encoding.InjectNato,encoding.InjectZalgo ;;
  *)   echo "알 수 없는 밤: $NIGHT (pi|dan|enc)"; exit 1 ;;
esac

set -a
source .env
set +a
export ANYTHINGLLM_LLM_PROVIDER=generic-openai
export GATEWAY_TARGET_URL=http://host.docker.internal:11434
UPSTREAM=http://host.docker.internal:11434

RUN_ID=oa_${NIGHT}_${DAY}_01
NONE=${RUN_ID}_none
RULE=${RUN_ID}_rule
SEED=20260819
AUDIT=logs/gateway.jsonl
LOCK=results/${RUN_ID}_started.lock
MANIFEST=results/${RUN_ID}_manifest.txt
REPORT_DIR=garak/logs/garak_runs

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

trap 'code=$?; log "ERROR launcher exit=$code"; exit "$code"' ERR

collision_check() {
  if [[ -e "$LOCK" || -e "$MANIFEST" ]]; then
    log "고유 실행 잠금/manifest 충돌: $RUN_ID"
    return 1
  fi
  for name in "$NONE" "$RULE"; do
    if docker container inspect "garak_$name" >/dev/null 2>&1; then
      log "컨테이너 이름 충돌: garak_$name"
      return 1
    fi
    if [[ -e "$REPORT_DIR/$name.report.jsonl" || -e "results/$name.report.jsonl" ]]; then
      log "리포트 이름 충돌: $name"
      return 1
    fi
  done
  if [[ -n "$(docker ps -q --filter name=garak_)" ]]; then
    log "기존 garak 컨테이너 실행 중"
    return 1
  fi
}

save_manifest() {
  {
    printf 'run_id=%s\n' "$RUN_ID"
    printf 'decision=D-081\n'
    printf 'started_kst=%s\n' "$(TZ=Asia/Seoul date -Is)"
    printf 'git_head=%s\n' "$(git rev-parse HEAD)"
    printf 'gateway_code=%s\n' "$(python3 gateway/version.py)"
    printf 'garak_image_id=%s\n' "$(docker image inspect garak-runner --format '{{.Id}}')"
    printf 'gateway_image_id=%s\n' "$(docker image inspect llm-security-gateway-gateway:latest --format '{{.Id}}')"
    printf 'target_image_id=%s\n' "$(docker inspect target-anythingllm --format '{{.Image}}')"
    printf 'target_llm_provider=%s\n' "$(docker exec target-anythingllm printenv LLM_PROVIDER)"
    printf 'gateway_upstream=%s\n' "$UPSTREAM"
    printf 'target_model=gemma3:4b\nchat_mode=query\n'
    printf 'probes=%s\n' "$PROBES"
    printf 'generations=10\nseed=%s\n' "$SEED"
    printf 'garak=0.15.1\neval_threshold=0.5\n'
    printf 'blocked_message=%s\n' "$(docker exec llm-gateway printenv GATEWAY_BLOCKED_MESSAGE 2>/dev/null || true)"
  } > "$MANIFEST"
}

audit_lines() {
  if [[ -f "$AUDIT" ]]; then wc -l < "$AUDIT" | tr -d ' '; else echo 0; fi
}

configure() {
  local detectors=$1
  local out target provider
  GATEWAY_DETECTORS="$detectors" docker compose up -d --force-recreate gateway
  sleep 12
  if ! out=$(bash scripts/verify_gateway.sh "${detectors:-none}" 2>&1); then
    printf '%s\n' "$out"
    log "검증실패: 기대 검사기 ${detectors:-none}"
    return 1
  fi
  printf '%s\n' "$out"
  case "$out" in
    *"측정을 시작해도 좋다"*) ;;
    *) log "검증 문구 없음: 기대 검사기 ${detectors:-none}"; return 1 ;;
  esac
  target=$(curl -s --max-time 5 http://localhost:8080/__gateway/health \
           | python3 -c 'import json,sys; print(json.load(sys.stdin)["target"])')
  if [[ "$target" != "$UPSTREAM" ]]; then
    log "옛 경로: gateway target=$target (기대 $UPSTREAM)"
    return 1
  fi
  provider=$(docker exec target-anythingllm printenv LLM_PROVIDER)
  if [[ "$provider" != generic-openai ]]; then
    log "옛 경로: AnythingLLM LLM_PROVIDER=$provider (기대 generic-openai)"
    return 1
  fi
}

run_arm() {
  local arm=$1
  local detectors=$2
  local name=$3
  local code from
  configure "$detectors"
  from=$(audit_lines)
  log "START $name (probes=$PROBES gen=10 seed=$SEED detectors=${detectors:-none} audit_from=$from)"
  bash scripts/run_garak.sh target "$PROBES" 10 "$name" "$SEED"
  docker wait "garak_$name"
  code=$(docker inspect "garak_$name" --format '{{.State.ExitCode}}')
  log "END $name exit=$code"
  [[ "$code" == 0 ]] || return 1
  if [[ "$arm" == rule ]]; then
    python3 scripts/validate_oa_arm.py --report "$REPORT_DIR/$name.report.jsonl" --name "$name" \
      --arm "$arm" --audit "$AUDIT" --audit-from "$from" \
      --peer "results/$NONE.report.jsonl" --peer-name "$NONE"
  else
    python3 scripts/validate_oa_arm.py --report "$REPORT_DIR/$name.report.jsonl" --name "$name" \
      --arm "$arm" --audit "$AUDIT" --audit-from "$from"
  fi
  if [[ "$NIGHT" == enc ]]; then
    python3 scripts/validate_encoding.py --report "$REPORT_DIR/$name.report.jsonl" --name "$name"
  fi
  cp "$REPORT_DIR/$name.report.jsonl" "results/$name.report.jsonl"
}

collision_check
if ! ( set -C; : > "$LOCK" ) 2>/dev/null; then
  log "고유 실행 잠금 충돌"
  exit 1
fi
save_manifest
log "D-081 밤샘 시작: $RUN_ID"
run_arm none "" "$NONE"
run_arm rule injection_rule,pii_mask "$RULE"
cp "$AUDIT" "results/audit_${RUN_ID}.jsonl"
log "D-081 밤샘 종료: 두 팔 검증 완료"
