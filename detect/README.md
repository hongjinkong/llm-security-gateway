# 탐지 사이드카(`detect/`) — 이름·주소·직장 NER · 인젝션 분류기

게이트웨이와 따로 도는 컨테이너다(FastAPI + ONNX Runtime + tokenizers, torch 없음). 이름·주소·직장처럼 정규식으로 잡을 수 없는 개인정보를 한국어 NER 모델로 찾는다.
게이트웨이는 정책이 `pii_kinds`에 `person`·`address`·`org`를 넣고 `GATEWAY_DETECT_URL`을 줬을 때만 부른다(D-126, 기본 꺼짐 — 지연을 받아들이는 정책만 켠다).
기본 모델은 측정한 다섯 가운데 F1이 합성 문장·실제 대화(KDPII) 둘 다 0.85를 넘은 유일한 `1T/veil-pii-ko-lite` INT8(0.963·0.895)이다 — x86 4 vCPU에서 510토큰 HTTP p95 201.5ms로
처음의 '+40ms' 게이트는 넘지 못했다(D-125). 빠른 모델(KoELECTRA-small)은 실제 대화에서 많이 틀린다(KDPII 정밀도 0.45·재현율 0.55). 수치와 근거는 [`DECISIONS.md`](../DECISIONS.md)의 D-125·D-126.
같은 사이드카의 둘째 작업은 **인젝션 분류기**다(D-127) — 텍스트 하나에 인젝션 점수(0~1)를 내고, 게이트웨이의 가드레일 웹훅 계약(`POST /v1/guard`)을 구현한다
(`GATEWAY_GUARD_URL=http://127.0.0.1:8081/v1/guard`). 이미지 기본 모델은 다섯 후보를 공개 평가셋 v1(D-123)로 재서 고른 `Horizon-Labs/prompt-injection-guard-base`(mmBERT-base, INT8 641MB, Apache-2.0)다(D-127 §6) —
판정 조작 문구 양성대조(D-054)에서 잡힌 공격의 8.9%가 뒤집혀 게이트웨이의 `block`에는 권하지 않는다(관측 전용). **기본으로 싣지 않는다** — 메모리가 약 1.2GiB 늘고(M2 물리 점유: NER만 0.6GiB → 함께 1.8GiB, 여는 동안 최대 2.6GiB) 창 하나(512토큰)가 M2에서 약 0.6초다.
`DETECT_INJECTION_MODEL=horizon-guard-base-int8`로 켠다. **이어 학습한 모델 `injection-ko-small-int8`**(D-128, 아래 '이어 학습')은 봉인 홀드아웃 한국어 97.5%·영어 93.8%, 양성대조 최대 0.7%로 네 게이트를 넘어 채택됐다 —
Hugging Face에 올라간 뒤 이미지 기본이 된다(그때까지 `models.json`에 `published: false`, 로컬 결과 폴더로만 싣는다). INT8 255MB, M2 스레드 4 p95 32토큰 17.8ms·510토큰 216.7ms(base의 약 1/3).
긴 텍스트는 512토큰 창을 128토큰 겹쳐 밀고 창들의 최댓값을 낸다. 텍스트마다 점수를 캐시한다(SHA-256 → 점수 4,096개, 원문 없음).

```
POST /v1/detect  {"texts": [{"id", "role", "text"}], "tasks": ["pii_ner", "injection"]}
                 → {"results": [{"id", "pii_ner": [{"start", "end", "label", "kind", "score"}], "injection": 점수}], "ms"}
POST /v1/guard   {"texts": [{"role", "text"}]} → {"verdict": "allow"|"block", "score"}      (점수 = 텍스트들의 최댓값, 문턱 이상이면 block)
GET  /health     → {"status": "ok", "tasks": {"pii_ner": {"model", "revision", "license", "sha256"}, "injection": {…, "threshold"}}}
```

- 원문을 저장·기록하지 않는다(접근 로그 끔, 오류 본문에 요청 내용 없음). 인증이 없으므로 같은 파드·내부 네트워크에만 연다.
- 모델은 [`models.json`](models.json)의 이름 하나다 — HF 저장소·커밋 SHA 리비전·파일 SHA-256 고정. 열 때 해시를 다시 재서 다르면 기동하지 않는다.
- 환경변수: `DETECT_MODEL`(NER 이름, 기본 `veil-ko-lite-int8`, 비면 NER 없음) · `DETECT_INJECTION_MODEL`(분류기 이름, 비면 없음 — 이미지 기본은 비어 있다) ·
  `DETECT_GUARD_THRESHOLD`(`/v1/guard`의 문턱, 0 초과 1 이하 — 없으면 그 모델의 `threshold`, 그것도 없으면 기동 거부) · `DETECT_INJECTION_MAX_TOKENS`(분류기 한 요청의 비용 상한, 기본 2,048 —
  캐시 밖 글을 새 글부터 상한까지만 재고 나머지는 `/v1/guard` 응답의 `unscored`) ·
  `DETECT_MODEL_DIR`(받은 모델 폴더) · `DETECT_THREADS`(ONNX 스레드, 기본 4).
- 싣지 않은 작업을 청하면 400 `invalid_tasks`, 분류기 없이 `/v1/guard`는 404. 두 작업은 줄을 따로 서고(작업마다 한 번에 추론 하나), 상한을 모두 센 뒤에 추론한다.
  글 속에 글자로 쓴 특수 토큰(`<eos>`·`[SEP]`)은 분류기에 특수 토큰으로 가지 않는다.

## 재기

```bash
python3.12 -m venv .venv-detect && .venv-detect/bin/pip install -r detect/requirements.txt pytest httpx
.venv-detect/bin/python -m detect.fetch veil-ko-lite-int8 atonlee-small-int8 horizon-guard-base-int8 --dir models    # 고정 리비전에서 받아 SHA-256 확인
DETECT_MODEL_DIR=models .venv-detect/bin/python -m pytest -q detect/tests                    # 디코더·HTTP 계약
.venv-detect/bin/python -m detect.evaluate --model atonlee-small-int8 --dir models           # F1: 합성 200문장 + KDPII test
.venv-detect/bin/python -m detect.bench --model atonlee-small-int8 --dir models              # 지연: 32~510토큰 HTTP p50·p95
.venv-detect/bin/python -m detect.evaluate_injection --model horizon-guard-base-int8 --dir models            # 인젝션: dev 언어·유형별 + recall@FPR(전체·깨끗한 부분집합)
.venv-detect/bin/python -m detect.evaluate_injection --model horizon-guard-base-int8 --dir models --control  # D-054 양성대조(조작 문구 6종)
.venv-detect/bin/python -m detect.bench --model horizon-guard-base-int8 --dir models          # 분류기 지연(같은 버킷)
docker build -f detect/Dockerfile --build-arg MODEL=veil-ko-lite-int8 .                       # 이미지(빌드 때 두 모델을 받는다 — INJECTION_MODEL=로 비우면 분류기 없음)
```

Llama Prompt Guard 2(86M·22M)는 비교 후보다 — 승인 저장소라 토큰이 필요하고(`hf auth login`, `fetch.py`가 `~/.cache/huggingface/token`을 읽는다) safetensors만 있어
torch가 있는 스크래치 가상환경에서 `python -m detect.export pg2-86m --dir models`로 ONNX를 만든다(Llama 4 Community 라이선스 — 이미지 기본으로 쓰지 않는다).
홀드아웃(`--holdout`)은 채택·문턱을 dev로 정한 뒤 단계의 최종 측정에서만 연다(D-123 §2-3).

CI의 `detect` 워크플로가 `detect/`·`eval/ner/`·`eval/injection/`이 바뀔 때 x86 러너에서 같은 것(분류기는 채택 모델의 dev 점수와 지연)을 재고 작업 요약에 남긴다.

## 이어 학습(D-128)

인젝션 분류기를 한국어 데이터로 이어 학습한다(PLAN 18-1). 학습은 torch가 필요해 **따로 둔 가상환경**(`.venv-train`, 정확히 고정한 `requirements-train.txt`)에서 돌리고, 사이드카 이미지에는 torch가 들어가지 않는다.
학습 데이터는 `eval/injection/train/`(빌더 `build.py` — dev의 학습 쪽 절반 + 평가셋이 쓰지 않은 공개 행 + 에이전트가 쓴 한국어 정상 + 결정적 변형·판정 조작 꼬리, 출처·라이선스는 그 폴더의 `SOURCES.md`)이고
평가 그룹(dev-eval·홀드아웃)과 그룹·문장이 겹치지 않는다(`tests/test_d128_train.py`). 기준 가중치는 `models.json`의 `purpose: train-base` 항목(`horizon-guard-base-src`·`-small-src`, safetensors, 제작자 SHA256SUMS와 같은 해시).

```bash
python3.12 -m venv .venv-train && .venv-train/bin/pip install -r detect/requirements-train.txt
.venv-train/bin/python -m detect.fetch horizon-guard-base-src --dir models                        # 기준 가중치(1.23GB), small은 horizon-guard-small-src(563MB)
.venv-train/bin/python -m detect.train --base horizon-guard-base-src --out models/injection-ko-base   # 기본 설정 = D-128 §2-2(시드·학습률·3 epoch·임베딩 동결), GPU 길이 512
.venv-train/bin/python -m detect.train --base horizon-guard-small-src --out models/injection-ko-small --max-len 256 --batch 8 --accum 4   # 맥북(M2 8GB)용
.venv-detect/bin/python -m detect.evaluate_injection --model <models.json 이름> --dir models --exclude-train   # dev-eval(학습 그룹 뺌)로 운영 문턱·표
```

결과 폴더에 safetensors·토크나이저·`onnx/model.onnx`(fp32)·`onnx/model_quantized.onnx`(INT8 — 임베딩 Gather만, 제작자와 같은 설정)·`manifest.json`(학습 설정·데이터 SHA-256·코드 커밋·파일 해시·양자화 확인)·`README.md`(모델 카드)·`train_log.json`이 남는다.
같은 명령·시드·데이터·장치면 같은 결과가 나온다(장치가 다르면 점수 ±1%p 안을 재현으로 본다). 사이드카가 쓰려면 `models.json`에 그 이름(`task: injection`·`trained`·`threshold`·파일 해시)을 더하고 HF 저장소에 올린 뒤 `revision`을 채운다 — 게이트·수치는 DECISIONS D-128 §6.

## 출처

모델은 각 저장소의 라이선스를 따른다(`models.json`의 `license` — 이미지에 들어가는 것은 모두 Apache-2.0, 비교만 한 Llama Prompt Guard 2는 Llama 4 Community). `decode.py`의 조사 떼기 규칙은
[1T/veil-pii-ko-lite](https://huggingface.co/1T/veil-pii-ko-lite)의 `veil.py`(Apache-2.0, Wontae Kim)에서 옮겨 왔다. 평가셋 출처는 [`eval/ner/SOURCES.md`](../eval/ner/SOURCES.md).
