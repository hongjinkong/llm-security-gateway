#!/usr/bin/env bash
# D-060 — 빚 4(통제군) + 빚 8(+PII ASR)을 한 런으로. dan 17종 세 팔을 같은 seed로 순차로 잰다.
# night_run_pi.sh 구조를 그대로 옮겼다. 근거는 DECISIONS.md D-060 하나뿐이다.
#
#   1 dan_c_base  타겟 직접
#   2 dan_c_none  게이트웨이, 검사기 0개      (통제군을 PII보다 먼저 — 중간에 끊겨도 빚 4는 완결)
#   3 dan_c_pii   게이트웨이, pii_mask
#
# 약 30시간. 비교는 scripts/paired_arms.py (프롬프트 단위 짝 t, 무효 조건 V1~V6).
# 베이스라인은 이 런의 통제군·PII 비교 전용이다 — README·EVAL의 베이스라인 값을 바꾸지 않는다.
#
# ★ 먼저 런북(docs/RUNBOOK_GPU.md) §0~§2를 사람이 통과시킨다. D-060 2절: garak 전에
#   정상셋 OFF(검사기 0) / ON(pii_mask) 100문항 RUNS=1 (빚 8의 FPR·지연, 타겟 생존 확인 겸).
#
# 그다음 백그라운드로 걸고 집에 간다(터미널이 닫혀도 살아남게 nohup):
#     nohup bash scripts/night_run_ctl.sh >> results/night_ctl.log 2>&1 &
#
# 아침/다음 학원 방문 때 런북 §0-1을 지킨다 — docker compose up -d 를 치기 전에
# §4-0으로 컨테이너 로그부터 건진다.
#
# 세 팔은 같은 seed로 돈다(D-057 8절). 같은 프롬프트를 받았는지는 paired_arms.py V1이
# 산출물(프롬프트 해시)로 대조한다. PROBES는 night_run.sh의 DAN_PROBES와 한 글자도 다르면
# 안 된다(D-022) — tests/test_paired_arms.py P0가 대조한다.
cd /home/smhrd/project/llm-security-gateway || exit 1
set -a
source .env
set +a

PROBES=dan.DanInTheWild,dan.Ablation_Dan_11_0,dan.AutoDANCached,dan.AntiDAN,dan.ChatGPT_Developer_Mode_RANTI,dan.ChatGPT_Developer_Mode_v2,dan.ChatGPT_Image_Markdown,dan.DAN_Jailbreak,dan.DUDE,dan.Dan_10_0,dan.Dan_11_0,dan.Dan_6_0,dan.Dan_6_2,dan.Dan_7_0,dan.Dan_8_0,dan.Dan_9_0,dan.STAN
SEED=20260819
LOG=results/night_ctl.log
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
  say "START $NAME (probes=dan17 seed=$SEED)"
  bash scripts/run_garak.sh "$WHERE" "$PROBES" 10 "$NAME" "$SEED" >> "$LOG" 2>&1
  docker wait "garak_$NAME" >> "$LOG" 2>&1
  CODE=$(docker inspect "garak_$NAME" --format '{{.State.ExitCode}}')
  say "END $NAME exit=$CODE"
  [ "$CODE" = 0 ]
}

say "D-060 밤샘 시작 — dan 세 팔 (base / none / pii_mask)"
run_arm target "" dan_c_base && run_arm gateway "" dan_c_none && run_arm gateway pii_mask dan_c_pii
say "D-060 밤샘 종료"
