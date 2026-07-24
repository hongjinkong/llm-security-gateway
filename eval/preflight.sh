#!/usr/bin/env bash
# preflight.sh — 측정 전 환경 준비 및 확인
# WSL 재시작 시 Ollama 모델이 내려가 첫 요청이 500으로 실패하는 문제를 막는다.
# num_ctx는 AnythingLLM이 사용하는 값과 맞춘다 (재로드 방지).
set -e
cd "$(dirname "$0")/.."
set -a; source .env; set +a

docker compose up -d >/dev/null
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$TARGET_URL" || true)
  [ "$code" = "200" ] && break
  sleep 2
done
echo "타겟 앱          : $code"

curl -s http://localhost:11434/api/generate \
  -d '{"model":"gemma3:4b","prompt":"hi","stream":false,"options":{"num_ctx":4096}}' -o /dev/null
curl -s http://localhost:11434/api/embed \
  -d '{"model":"bge-m3","input":"x","options":{"num_ctx":1000}}' -o /dev/null
echo "모델 예열        : $(ollama ps | tail -n +2 | wc -l)개"

docker compose exec -T target-app \
  curl -s -o /dev/null -w "컨테이너→Ollama : %{http_code}\n" http://host.docker.internal:11434
