# 공개 데모 이미지(D-131) — 비교 데모 웹(web/app.py)을 공개 모드로 띄운다. 게이트웨이 둘과 스텁 상류 둘이 같은 컨테이너 안에서 돈다(밖으로 나가는 요청이 없다).
# 빌드 문맥은 저장소 루트다(문맥에 넣을 것은 web/Dockerfile.dockerignore가 정한다):  docker build -f web/Dockerfile -t llm-gateway-demo .
# 베이스는 게이트웨이 이미지와 같은 다이제스트다 — 올릴 때 함께 올린다.
# python:3.12-slim 멀티 아키텍처 인덱스, 2026-10-30 조회
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

# 게이트웨이는 패키지로 설치하고 소스는 지운다(gateway/Dockerfile과 같다). 그 밖에 싣는 것은 web/과 스텁·프로세스 도구뿐이다 — 테스트 러너는 넣지 않는다.
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY gateway/ ./gateway/
RUN pip install --no-cache-dir . \
 && rm -rf /src \
 && useradd --system --uid 10001 --no-create-home demo
WORKDIR /app
COPY web/ ./web/
COPY tests/__init__.py tests/procs.py tests/stub_target.py ./tests/

# 비root로 돈다. 감사 로그는 임시 폴더(/tmp)에 두고 1MiB를 넘으면 비운다 — 볼륨이 필요 없다.
USER 10001
# WEB_PUBLIC=1: 상류는 스텁 고정, 본문 상한, 레이트리밋, 방문자 분리. 공개하는 곳에서는 끄지 않는다. 프록시 뒤에 두면 그 프록시가 채우는 방문자 주소 헤더를 WEB_CLIENT_IP_HEADER로 정한다(fly.toml 참고).
ENV PYTHONUNBUFFERED=1 \
    WEB_PUBLIC=1
EXPOSE 8090

# info는 두 게이트웨이까지 부른다 — 자식 프로세스가 죽으면 실패한다
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/api/info', timeout=2)"]

# 접근 로그는 끈다 — 방문자 주소와 쿼리를 남기지 않는다. 동시 연결 상한을 넘으면 uvicorn이 503을 준다.
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8090", "--no-access-log", "--log-level", "warning", "--limit-concurrency", "200"]
