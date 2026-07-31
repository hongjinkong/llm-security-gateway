#!/usr/bin/env bash
# dan 베이스라인 상태 점검 (읽기 전용). 사용: bash check.sh
cd "$(dirname "$0")"
C=baseline_dan

echo "===== 1. 컨테이너 상태 ====="
docker ps -a --filter "name=$C" --format '{{.Names}} | {{.Status}}'

echo; echo "===== 2. 현재 진행 (마지막 로그) ====="
docker logs "$C" 2>&1 | tail -4

echo; echo "===== 3. 시작된 프로브 (/17) ====="
docker logs "$C" 2>&1 | grep -oE "probes\.dan\.[A-Za-z0-9_]+" | sort -u | nl

echo; echo "===== 4. 에러 누적 개수 (0~소수면 정상) ====="
docker logs "$C" 2>&1 | grep -icE "timeout|error|traceback|500"

echo; echo "===== 5. 결과 리포트 줄 수 (늘면 정상) ====="
REPORT=$(ls -t garak/logs/garak_runs/*.report.jsonl 2>/dev/null | head -1)
echo "파일: $REPORT"; wc -l "$REPORT" 2>/dev/null

echo; echo "===== 6. 모델 상주 / GPU ====="
ollama ps
nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used --format=csv,noheader

echo; echo "===== 7. 완주 여부 ====="
STATUS=$(docker ps -a --filter "name=$C" --format '{{.Status}}')
if echo "$STATUS" | grep -q "Exited (0)"; then
  echo "✅ 완주 성공. garak 프로브별 요약:"
  docker logs "$C" 2>&1 | grep -iE "PASS|FAIL|run complete" | tail -30
elif echo "$STATUS" | grep -q "Exited"; then
  echo "⚠️ 비정상 종료. 마지막 40줄:"
  docker logs "$C" 2>&1 | tail -40
else
  echo "⏳ 아직 실행 중 (Up). 위 2번 진행바 참고."
fi
