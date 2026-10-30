# 게이트웨이 이미지(D-108·D-109). 베이스는 다이제스트로 고정한다 — 태그는 옮겨진다. 올릴 때 다이제스트와 조회 날짜를 함께 바꾼다.
# python:3.12-slim 멀티 아키텍처 인덱스, 2026-10-30 조회
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# pyproject.toml의 고정 의존성으로 패키지를 설치하고 소스는 지운다 — 이미지에는 설치된 패키지만 남는다(LICENSE는 메타데이터에 들어간다).
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY gateway/ ./gateway/
RUN pip install --no-cache-dir . \
 && rm -rf /src \
 && useradd --system --uid 10001 --no-create-home gateway
WORKDIR /

# 비root로 돈다. 감사 로그는 stdout(`-`) — 컨테이너 런타임이 모은다. 파일로 쓰려면 쓰기 가능한 볼륨과 GATEWAY_LOG_PATH를 준다.
USER 10001
ENV PYTHONUNBUFFERED=1 \
    GATEWAY_LOG_PATH=-
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/__gateway/health', timeout=2)"]

# 워커 수는 uvicorn이 읽는 WEB_CONCURRENCY로 정한다(기본 1). 볼트가 요청 단위라 워커를 늘려도 복원은 깨지지 않는다 — 레이트리밋·지표는 워커별이다.
# 프록시 뒤에 두면 신뢰할 프록시 주소를 FORWARDED_ALLOW_IPS로 준다(기본 127.0.0.1 — 그 밖에서 온 X-Forwarded-For는 무시된다).
# 스트림은 오래 열려 있으므로 동시 연결 상한을 넉넉히 둔다. 넘으면 uvicorn이 503을 준다.
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-graceful-shutdown", "25", "--limit-concurrency", "1000"]
