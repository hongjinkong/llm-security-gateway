#!/usr/bin/env bash
set -Eeuo pipefail
cd /home/smhrd/project/llm-security-gateway

RUN_ID=encoding_20260923_01
BASE=enc_20260923_01_base
RULE=enc_20260923_01_rule
PROBES=encoding.InjectNato,encoding.InjectZalgo
SEED=20260819
LOG=results/night_encoding_20260923_01.log
LOCK=results/encoding_20260923_01_started.lock
MANIFEST=results/encoding_20260923_01_manifest.txt
REPORT_DIR=garak/logs/garak_runs

log() {
  printf '[%s] %s\n' "$(date -Is)" "$*"
}

trap 'code=$?; log "ERROR launcher exit=$code"; exit "$code"' ERR

clock_ok() {
  python3 - <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("Asia/Seoul"))
if now.date().isoformat() != "2026-09-23" or not (1050 <= now.hour * 60 + now.minute < 1070):
    raise SystemExit(f"17:30~17:50 KST 외 착수 금지: {now.isoformat()}")
print(f"착수 시각: {now.isoformat()}")
PY
}

collision_check() {
  if [[ -e "$LOCK" || -e "$MANIFEST" ]]; then
    log "고유 실행 잠금/manifest 충돌"
    return 1
  fi
  for name in "$BASE" "$RULE"; do
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
    printf 'started_kst=%s\n' "$(TZ=Asia/Seoul date -Is)"
    printf 'git_head=%s\n' "$(git rev-parse HEAD)"
    printf 'gateway_code=%s\n' "$(python3 gateway/version.py)"
    printf 'garak_image_id=%s\n' "$(docker image inspect garak-runner --format '{{.Id}}')"
    printf 'gateway_image_id=%s\n' "$(docker image inspect llm-security-gateway-gateway:latest --format '{{.Id}}')"
    printf 'target_image_id=%s\n' "$(docker inspect target-anythingllm --format '{{.Image}}')"
    printf 'target_model=gemma3:4b\n'
    printf 'probes=%s\n' "$PROBES"
    printf 'generations=10\nseed=%s\n' "$SEED"
    printf 'garak=0.15.1\nprompt_cap=256\neval_threshold=0.5\n'
    printf 'blocked_message=%s\n' "$(docker exec llm-gateway printenv GATEWAY_BLOCKED_MESSAGE 2>/dev/null || true)"
    printf 'blocked_message_default=요청이 보안 정책에 의해 차단되었습니다.\n'
  } > "$MANIFEST"
}

configure() {
  local detectors=$1
  local expected=$2
  local out
  GATEWAY_DETECTORS="$detectors" docker compose up -d gateway
  sleep 12
  if ! out=$(bash scripts/verify_gateway.sh "$expected" 2>&1); then
    printf '%s\n' "$out"
    log "검증실패: 기대 검사기 $expected"
    return 1
  fi
  printf '%s\n' "$out"
  case "$out" in
    *"측정을 시작해도 좋다"*) ;;
    *) log "검증 문구 없음: 기대 검사기 $expected"; return 1 ;;
  esac
}

run_arm() {
  local where=$1
  local detectors=$2
  local expected=$3
  local name=$4
  local code
  configure "$detectors" "$expected"
  log "START $name (probes=$PROBES gen=10 seed=$SEED detectors=$expected)"
  bash scripts/run_garak.sh "$where" "$PROBES" 10 "$name" "$SEED"
  docker wait "garak_$name"
  code=$(docker inspect "garak_$name" --format '{{.State.ExitCode}}')
  log "END $name exit=$code"
  [[ "$code" == 0 ]] || return 1
  if [[ "$name" == "$RULE" ]]; then
    python3 scripts/validate_encoding.py --report "$REPORT_DIR/$name.report.jsonl" --name "$name" --peer "results/$BASE.report.jsonl" --peer-name "$BASE"
  else
    python3 scripts/validate_encoding.py --report "$REPORT_DIR/$name.report.jsonl" --name "$name"
  fi
  cp "$REPORT_DIR/$name.report.jsonl" "results/$name.report.jsonl"
}

clock_ok
python3 scripts/encoding_gate.py verify
collision_check
if ! ( set -C; : > "$LOCK" ) 2>/dev/null; then
  log "고유 실행 잠금 충돌"
  exit 1
fi
save_manifest
log "D-068 밤샘 시작: $RUN_ID"
run_arm target "" none "$BASE"
if [[ -s logs/gateway.jsonl ]]; then
  log "E3 실패: base 실행 창에 게이트웨이 감사 요청이 있음. rule 팔을 시작하지 않음"
  exit 2
fi
log "E3 base 통과: 게이트웨이 감사 요청 0"
run_arm gateway injection_rule,pii_mask injection_rule,pii_mask "$RULE"
python3 - <<'PY'
import json
from pathlib import Path
path = Path("logs/gateway.jsonl")
if not path.is_file():
    raise SystemExit("E3 실패: rule 감사 로그 없음")
rows = []
for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
    if line.strip():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"E3 실패: 감사 JSON {number}행 파손: {exc}")
if len(rows) != 5120:
    raise SystemExit(f"E3 실패: rule 감사 요청 {len(rows)}건 != 5,120건")
if any(row.get("status") != 200 for row in rows):
    raise SystemExit("E3 실패: rule 감사 로그에 200 아닌 응답이 있음")
ids = [row.get("request_id") for row in rows]
if None in ids or len(set(ids)) != len(ids):
    raise SystemExit("E3 실패: rule request_id 누락/중복")
print("E3 rule 통과: 감사 요청 5,120건, 응답 200, request_id 유일")
PY
cp logs/gateway.jsonl results/audit_encoding_20260923_01_night.jsonl
log "D-068 밤샘 종료: 두 팔 검증 완료"
