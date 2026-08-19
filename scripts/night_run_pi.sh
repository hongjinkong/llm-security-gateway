#!/usr/bin/env bash
# 빚 3 — promptinject 두 팔(베이스라인 + injection_rule,pii_mask)을 하룻밤에 순차로 잰다.
# night_run.sh(dan 전용)의 promptinject 판이다. 통제군(검사기 0개)은 넣지 않는다 — 그건 빚 4다.
#
# ★ 먼저 런북(docs/RUNBOOK_GPU.md) §0~§2를 사람이 통과시킨다:
#     git pull(D-057 확인) / docker compose build gateway / preflight / verify /
#     FPR·지연 재측정 후 FPR 2.0% 확인.  ← 이게 통과해야 아래를 건다.
#
# 그다음 이 스크립트를 백그라운드로 걸고 집에 간다(터미널이 닫혀도 살아남게 nohup):
#     nohup bash scripts/night_run_pi.sh >> results/night_pi.log 2>&1 &
#
# 아침/다음 학원 방문 때 런북 §0-1을 지킨다 — docker compose up -d 를 치기 전에
# §4-0으로 컨테이너 로그부터 건진다. 안 그러면 사고 조사 증거가 컨테이너 교체와 함께 지워진다.
#
# 두 팔은 같은 seed로 돈다(D-057 8절). 제너레이터 이름도 통일돼(gateway_rest.json)
# 두 팔이 글자 단위로 같은 프롬프트를 받는다. 확인은 런북 §0 / MEASUREMENT §2 참조.
cd /home/smhrd/project/llm-security-gateway || exit 1
set -a
source .env
set +a

PROBES=promptinject
SEED=20260819
LOG=results/night_pi.log
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
  say "START $NAME (probes=$PROBES seed=$SEED)"
  bash scripts/run_garak.sh "$WHERE" "$PROBES" 10 "$NAME" "$SEED" >> "$LOG" 2>&1
  docker wait "garak_$NAME" >> "$LOG" 2>&1
  CODE=$(docker inspect "garak_$NAME" --format '{{.State.ExitCode}}')
  say "END $NAME exit=$CODE"
  [ "$CODE" = 0 ]
}

say "빚3 밤샘 시작 — promptinject 두 팔"
run_arm target "" pi_base && run_arm gateway injection_rule,pii_mask pi_rule
say "빚3 밤샘 종료"
