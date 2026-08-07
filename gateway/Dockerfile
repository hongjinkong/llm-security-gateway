# 게이트웨이 이미지. garak 컨테이너가 이름으로 찾아올 수 있게 compose 네트워크에 올린다.
FROM python:3.12-slim

WORKDIR /app
COPY requirements-gateway.txt .
RUN pip install --no-cache-dir -r requirements-gateway.txt

COPY gateway/ ./gateway/

ENV PYTHONUNBUFFERED=1 \
    GATEWAY_LOG_PATH=/logs/gateway.jsonl
EXPOSE 8080

# --workers 1: 토큰 볼트가 프로세스 메모리에 있다. 워커를 늘리면 세션이 흩어져
# 마스킹한 워커와 복원할 워커가 달라진다. 공유 저장소를 도입하기 전까지는 1로 고정.
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
