# 탐지 사이드카(`detect/`) — 이름·주소·직장 NER

게이트웨이와 따로 도는 컨테이너다(FastAPI + ONNX Runtime + tokenizers, torch 없음). 이름·주소·직장처럼 정규식으로 잡을 수 없는 개인정보를 한국어 NER 모델로 찾는다.
게이트웨이는 정책이 `pii_kinds`에 `person`·`address`·`org`를 넣고 `GATEWAY_DETECT_URL`을 줬을 때만 부른다(D-126, 기본 꺼짐 — 지연을 받아들이는 정책만 켠다).
기본 모델은 측정한 다섯 가운데 F1이 합성 문장·실제 대화(KDPII) 둘 다 0.85를 넘은 유일한 `1T/veil-pii-ko-lite` INT8(0.963·0.895)이다 — x86 4 vCPU에서 510토큰 HTTP p95 201.5ms로
처음의 '+40ms' 게이트는 넘지 못했다(D-125). 빠른 모델(KoELECTRA-small)은 실제 대화에서 많이 틀린다(KDPII 정밀도 0.45·재현율 0.55). 수치와 근거는 [`DECISIONS.md`](../DECISIONS.md)의 D-125·D-126.
18단계(인젝션 분류기)가 같은 사이드카에 작업을 더하고, 새 후보가 나오면 같은 자로 다시 잰다.

```
POST /v1/detect  {"texts": [{"id", "role", "text"}], "tasks": ["pii_ner"]}
                 → {"results": [{"id", "pii_ner": [{"start", "end", "label", "kind", "score"}]}], "ms"}
GET  /health     → {"status": "ok", "tasks": {"pii_ner": {"model", "revision", "license", "sha256"}}}
```

- 원문을 저장·기록하지 않는다(접근 로그 끔, 오류 본문에 요청 내용 없음). 인증이 없으므로 같은 파드·내부 네트워크에만 연다.
- 모델은 [`models.json`](models.json)의 이름 하나다 — HF 저장소·커밋 SHA 리비전·파일 SHA-256 고정. 열 때 해시를 다시 재서 다르면 기동하지 않는다.
- 환경변수: `DETECT_MODEL`(이름, 기본 `veil-ko-lite-int8`) · `DETECT_MODEL_DIR`(받은 모델 폴더) · `DETECT_THREADS`(ONNX 스레드, 기본 4).

## 재기

```bash
python3.12 -m venv .venv-detect && .venv-detect/bin/pip install -r detect/requirements.txt pytest httpx
.venv-detect/bin/python -m detect.fetch veil-ko-lite-int8 atonlee-small-int8 --dir models    # 고정 리비전에서 받아 SHA-256 확인
DETECT_MODEL_DIR=models .venv-detect/bin/python -m pytest -q detect/tests                    # 디코더·HTTP 계약
.venv-detect/bin/python -m detect.evaluate --model atonlee-small-int8 --dir models           # F1: 합성 200문장 + KDPII test
.venv-detect/bin/python -m detect.bench --model atonlee-small-int8 --dir models              # 지연: 32~510토큰 HTTP p50·p95
docker build -f detect/Dockerfile --build-arg MODEL=veil-ko-lite-int8 .                       # 이미지(빌드 때 모델을 받는다)
```

CI의 `detect` 워크플로가 `detect/`·`eval/ner/`가 바뀔 때 x86 러너에서 같은 것을 재고 작업 요약에 남긴다.

## 출처

모델은 각 저장소의 라이선스를 따른다(`models.json`의 `license` — 모두 Apache-2.0). `decode.py`의 조사 떼기 규칙은
[1T/veil-pii-ko-lite](https://huggingface.co/1T/veil-pii-ko-lite)의 `veil.py`(Apache-2.0, Wontae Kim)에서 옮겨 왔다. 평가셋 출처는 [`eval/ner/SOURCES.md`](../eval/ner/SOURCES.md).
