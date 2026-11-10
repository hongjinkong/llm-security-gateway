# 탐지 사이드카 이미지(D-125·D-127). 게이트웨이 이미지와 의존성을 나눈다 — onnxruntime·모델은 여기에만 있다. 베이스는 게이트웨이와 같은 다이제스트다.
# python:3.12-slim 멀티 아키텍처 인덱스, 2026-11-10 조회(Python 3.12.16, Debian 13.7)
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# 베이스를 빌드한 뒤 나온 Debian 보안 갱신을 적용한다(D-135, 게이트웨이 이미지와 같다). 목록은 같은 층에서 지운다
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY detect/requirements.txt detect/requirements.txt
RUN pip install --no-cache-dir -r detect/requirements.txt \
 && useradd --system --uid 10001 --no-create-home detect
COPY detect/__init__.py detect/app.py detect/classify.py detect/decode.py detect/fetch.py detect/ner.py detect/models.json detect/
# 내장 모델의 라이선스 고지(D-130 리뷰) — 이 이미지는 모델 가중치를 담아 배포한다. Horizon 모델의 LICENSE·NOTICE는 아래 fetch가 모델 폴더에 함께 받는다(models.json의 files)
COPY LICENSE detect/THIRD_PARTY_NOTICES.md /licenses/
# 가중치는 빌드할 때 고정 리비전에서 받아 SHA-256을 맞춘다(fetch.py) — 실행 중에는 네트워크가 필요 없다. 기동 때 NER이 해시를 다시 잰다.
# 모델은 models.json의 이름이다(--build-arg MODEL=…·INJECTION_MODEL=…). NER 기본은 F1이 두 셋 다 0.85를 넘은 유일한 후보(D-125 — 게이트웨이가 D-126부터 쓴다),
# 인젝션 분류기는 D-127 채택 모델(가드레일 웹훅 POST /v1/guard)의 파일만 이미지에 둔다 — **기본으로 싣지 않는다**(메모리 +1.2GiB, D-127 §6). 켜려면 실행할 때
# DETECT_INJECTION_MODEL=horizon-guard-base-int8. 분류기 파일을 빼고 빌드하려면 --build-arg INJECTION_MODEL=
ARG MODEL=veil-ko-lite-int8
ARG INJECTION_MODEL=horizon-guard-base-int8
RUN python -m detect.fetch $MODEL $INJECTION_MODEL --dir /models && chmod -R a+rX /models

USER 10001
ENV PYTHONUNBUFFERED=1 \
    DETECT_MODEL=$MODEL \
    DETECT_INJECTION_MODEL= \
    DETECT_MODEL_DIR=/models \
    DETECT_THREADS=4
EXPOSE 8081

# 시작 유예 180초 — 인젝션 분류기(base)까지 실으면 기동이 1분을 넘는다(M2 Docker VM 4GB에서 88초, 2026-11-10). 유예는 healthy 판정을 늦추지 않는다
HEALTHCHECK --interval=10s --timeout=3s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=2)"]

# 접근 로그를 끈다 — 요청 기록 자체를 남기지 않는다. 인증이 없으므로 같은 파드(또는 내부 네트워크)의 게이트웨이만 닿게 둔다.
# 종료 유예 25초 — 추론 중인 요청은 끝까지 돌고(한 요청은 토큰 16,384개 상한), 그보다 길면 끊는다(게이트웨이 이미지와 같은 값).
CMD ["uvicorn", "detect.app:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log", "--timeout-graceful-shutdown", "25"]
