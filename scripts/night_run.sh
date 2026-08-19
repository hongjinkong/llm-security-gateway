#!/usr/bin/env bash
cd /home/smhrd/project/llm-security-gateway || exit 1
set -a
source .env
set +a
DAN_PROBES=dan.DanInTheWild,dan.Ablation_Dan_11_0,dan.AutoDANCached,dan.AntiDAN,dan.ChatGPT_Developer_Mode_RANTI,dan.ChatGPT_Developer_Mode_v2,dan.ChatGPT_Image_Markdown,dan.DAN_Jailbreak,dan.DUDE,dan.Dan_10_0,dan.Dan_11_0,dan.Dan_6_0,dan.Dan_6_2,dan.Dan_7_0,dan.Dan_8_0,dan.Dan_9_0,dan.STAN
LOG=results/night_20260818.log
say() { echo "[$(date -Is)] $*" >> "$LOG"; }
run_arm() {
  WHERE=$1; DET=$2; NAME=$3
  if [ "$WHERE" = gateway ]; then
    GATEWAY_DETECTORS="$DET" docker compose up -d gateway >> "$LOG" 2>&1
    sleep 12
    OUT=$(bash scripts/verify_gateway.sh "${DET:-none}" 2>&1)
    echo "$OUT" >> "$LOG"
    case "$OUT" in
      *"측정을 시작해도 좋다"*) : ;;
      *) say "검증실패 $NAME 중단"; return 1 ;;
    esac
  fi
  say "START $NAME"
  bash scripts/run_garak.sh "$WHERE" "$DAN_PROBES" 10 "$NAME" >> "$LOG" 2>&1
  docker wait "garak_$NAME" >> "$LOG" 2>&1
  CODE=$(docker inspect "garak_$NAME" --format '{{.State.ExitCode}}')
  say "END $NAME exit=$CODE"
  [ "$CODE" = 0 ]
}
say "밤샘 시작"
run_arm target "" night_base_dan && run_arm gateway injection_rule,pii_mask night_rule_dan && run_arm gateway "" night_none_dan
say "밤샘 종료"
