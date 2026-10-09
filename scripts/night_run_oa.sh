#!/usr/bin/env bash
# D-081 새 구조 한 밤 — D-100부터 none → rule → turn 세 팔을 순차로 잰다.
#
#   nohup bash scripts/night_run_oa.sh dan 20261020 >> results/night_oa_dan_20261020_01.log 2>&1 &
#
#   none  검사기 없음
#   rule  injection_rule,pii_mask       — 이력까지 전부 보는 범위 (A)
#   turn  injection_rule_turn,pii_mask  — 이번 턴만으로 막고 이력의 걸린 턴은 가리는 범위 (C)
#
# 옛 런처와 다른 점:
#   - 모든 팔이 garak → AnythingLLM(target). 게이트웨이는 AnythingLLM 뒤 /v1에 있고, 팔 사이에는
#     gateway의 검사기만 바꾼다.
#   - B2 환경변수를 스크립트 안에서 고정한다. 빠지면 compose가 조용히 옛 경로로 되돌린다.
#   - E3는 "base 창 감사 0건"이 아니라 조각마다 감사 줄 수 = garak 출력 수다(validate_oa_arm.py).
#   - D-100: dan은 팔마다 garak을 세 조각(앞 8개 / DanInTheWild / 뒤 8개)으로 나눠 돌린다. DanInTheWild
#     표집이 seed 직후, HTTP 호출 전에 끝나므로 앞 프로브의 재시도가 표집을 바꿀 수 없다(D-090).
#     garak이 한 실행 안에서 돌던 정렬 순서 그대로라 요청 순서는 예전과 같다. 조각마다 E1·E3·E5를 보고,
#     끝나면 조각 리포트를 이어 팔 리포트 하나(results/<run>_<팔>.report.jsonl)로 만든다.
#
# 착수 전에 사람이 통과시킬 것: D-081 §7 P1·P2·P4, 노이즈 플로어, 그 밤의 FPR 관문(--link time).
set -Eeuo pipefail
cd /home/smhrd/project/llm-security-gateway

NIGHT=${1:?사용: night_run_oa.sh <pi|dan|enc> <YYYYMMDD>}
DAY=${2:?사용: night_run_oa.sh <pi|dan|enc> <YYYYMMDD>}
[[ "$DAY" =~ ^[0-9]{8}$ ]] || { echo "날짜 형식 오류: $DAY"; exit 1; }
# PARTS: 팔마다 순서대로 돌리는 garak 실행 단위. 조각이 하나면 예전과 같다.
case "$NIGHT" in
  pi)  PARTS=(promptinject) ;;
  dan) PARTS=(dan.Ablation_Dan_11_0,dan.AntiDAN,dan.AutoDANCached,dan.ChatGPT_Developer_Mode_RANTI,dan.ChatGPT_Developer_Mode_v2,dan.ChatGPT_Image_Markdown,dan.DAN_Jailbreak,dan.DUDE
              dan.DanInTheWild
              dan.Dan_10_0,dan.Dan_11_0,dan.Dan_6_0,dan.Dan_6_2,dan.Dan_7_0,dan.Dan_8_0,dan.Dan_9_0,dan.STAN) ;;
  enc) PARTS=(encoding.InjectNato,encoding.InjectZalgo) ;;
  *)   echo "알 수 없는 밤: $NIGHT (pi|dan|enc)"; exit 1 ;;
esac
PROBES=$(IFS=,; echo "${PARTS[*]}")

set -a
source .env
set +a
export ANYTHINGLLM_LLM_PROVIDER=generic-openai
export GATEWAY_TARGET_URL=http://host.docker.internal:11434
UPSTREAM=http://host.docker.internal:11434

RUN_ID=oa_${NIGHT}_${DAY}_01
NONE=${RUN_ID}_none
RULE=${RUN_ID}_rule
TURN=${RUN_ID}_turn
SEED=20260819
AUDIT=logs/gateway.jsonl
LOCK=results/${RUN_ID}_started.lock
MANIFEST=results/${RUN_ID}_manifest.txt
REPORT_DIR=garak/logs/garak_runs

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

trap 'code=$?; log "ERROR launcher exit=$code"; exit "$code"' ERR

# 조각이 하나면 팔 이름 그대로(옛 이름 규칙), 여럿이면 <팔>_p1 … <팔>_pN.
part_name() {
  if (( ${#PARTS[@]} > 1 )); then echo "${1}_p${2}"; else echo "$1"; fi
}

collision_check() {
  local arm k name
  if [[ -e "$LOCK" || -e "$MANIFEST" ]]; then
    log "고유 실행 잠금/manifest 충돌: $RUN_ID"
    return 1
  fi
  for arm in "$NONE" "$RULE" "$TURN"; do
    if [[ -e "results/$arm.report.jsonl" ]]; then
      log "리포트 이름 충돌: $arm"
      return 1
    fi
    for k in $(seq 1 ${#PARTS[@]}); do
      name=$(part_name "$arm" "$k")
      if docker container inspect "garak_$name" >/dev/null 2>&1; then
        log "컨테이너 이름 충돌: garak_$name"
        return 1
      fi
      if [[ -e "$REPORT_DIR/$name.report.jsonl" || -e "results/$name.report.jsonl" ]]; then
        log "리포트 이름 충돌: $name"
        return 1
      fi
    done
  done
  if [[ -n "$(docker ps -q --filter name=garak_)" ]]; then
    log "기존 garak 컨테이너 실행 중"
    return 1
  fi
}

save_manifest() {
  {
    printf 'run_id=%s\n' "$RUN_ID"
    printf 'decision=D-100 (D-081 설계)\n'
    printf 'arms=none,rule(injection_rule,pii_mask),turn(injection_rule_turn,pii_mask)\n'
    printf 'parts=%s\n' "${#PARTS[@]}"
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
  local code from k part pname
  local peer=()
  configure "$detectors"
  for k in $(seq 1 ${#PARTS[@]}); do
    part=${PARTS[$((k - 1))]}
    pname=$(part_name "$name" "$k")
    from=$(audit_lines)
    log "START $pname (probes=$part gen=10 seed=$SEED detectors=${detectors:-none} audit_from=$from)"
    bash scripts/run_garak.sh target "$part" 10 "$pname" "$SEED"
    docker wait "garak_$pname"
    code=$(docker inspect "garak_$pname" --format '{{.State.ExitCode}}')
    log "END $pname exit=$code"
    [[ "$code" == 0 ]] || return 1
    peer=()
    if [[ "$arm" != none ]]; then
      peer=(--peer "results/$(part_name "$NONE" "$k").report.jsonl" --peer-name "$(part_name "$NONE" "$k")")
    fi
    python3 scripts/validate_oa_arm.py --report "$REPORT_DIR/$pname.report.jsonl" --name "$pname" \
      --arm "$arm" --audit "$AUDIT" --audit-from "$from" ${peer[@]+"${peer[@]}"}
    if [[ "$NIGHT" == enc ]]; then
      python3 scripts/validate_encoding.py --report "$REPORT_DIR/$pname.report.jsonl" --name "$pname"
    fi
    cp "$REPORT_DIR/$pname.report.jsonl" "results/$pname.report.jsonl"
  done
  if (( ${#PARTS[@]} > 1 )); then
    # 회수 도구(rescore_blocking·asr_summary)는 팔당 리포트 하나를 읽는다. 조각을 실행 순서대로 잇는다.
    # 조각마다 setup·completion이 하나씩 있으므로 이은 파일에는 validate_oa_arm.py를 쓰지 않는다(조각이 이미 통과했다).
    for k in $(seq 1 ${#PARTS[@]}); do
      cat "results/$(part_name "$name" "$k").report.jsonl"
    done > "results/$name.report.jsonl"
    log "JOIN $name ← ${#PARTS[@]}조각"
  fi
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
run_arm turn injection_rule_turn,pii_mask "$TURN"
cp "$AUDIT" "results/audit_${RUN_ID}.jsonl"
log "D-081 밤샘 종료: 세 팔 검증 완료"
