FROM python:3.12-slim

# garak 버전 고정 (EVAL 5.1 재현성) — 2026-07-27 기준 최신 안정판
RUN pip install --no-cache-dir garak==0.15.1 \
    && python -c "import garak; print('GARAK_VERSION=' + garak.__version__)"

WORKDIR /work
ENTRYPOINT ["python", "-m", "garak"]
