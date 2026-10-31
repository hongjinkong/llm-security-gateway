# 설정

게이트웨이는 환경변수와 (선택) 설정 파일 하나로 설정한다. 둘 다 **기동할 때 한 번** 읽는다 — 바꾸면 재시작해야 한다
(k8s 견본은 `kubectl apply -k`가 롤링 재시작을 만든다, [운영](operations.md)). 고르는 값·종류·역할의 틀린 값, 설정 파일의 모르는 키·틀린 값은 기동 실패이고
메시지는 `GATEWAY_LANG`의 언어다. 숫자 형식 오류는 파이썬 오류 문장(영어)으로 실패한다. 주소(URL)는 검사하지 않는다 — 틀리면 요청 때 502다.
`.env`는 스스로 읽지 않는다 — `uvicorn gateway.main:app --env-file .env`로 넘긴다(견본 [`.env.example`](../.env.example)).

처음 띄울 때 필요한 것은 셋이다.

1. **클라이언트 키** — `GATEWAY_CLIENT_KEYS` 또는 설정 파일 `[[clients]]`. 둘 다 없으면 기동하지 않는다.
2. **대체값 키** — `GATEWAY_SURROGATE_KEY`(32자 이상). PII `mask` 모드(기본)면 없을 때 기동하지 않는다.
3. **상류** — `TARGET_URL` + `GATEWAY_UPSTREAM_KEY`, 또는 설정 파일 `[upstreams.*]`(API마다 주소와 키).

키는 `python -m gateway keygen`으로 만든다(설정 파일에 넣을 클라이언트 키는 `--hash` — 키와 `key_sha256 = "…"` 줄을 낸다).

## 환경변수

이 표의 이름은 `tests/test_d121_docs.py`가 코드(`Settings.from_env`가 읽는 이름)와 맞춘다.

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `TARGET_URL` | `http://localhost:8000` | 설정 파일에 없는 API의 상류 주소. 상류 경로는 받은 경로 그대로다 — 주소에 경로가 있으면 그 뒤에 붙는다(`https://host/openai` → `https://host/openai/v1/chat/completions`). 쿼리 문자열도 넘긴다 |
| `GATEWAY_CLIENT_KEYS` | (없음) | 클라이언트 키 `이름=키,이름2=키2`(이름을 빼면 키 지문 앞 8자). 정책은 `default`. 클라이언트는 `Authorization: Bearer`나 `x-api-key`로 낸다. 읽을 때 SHA-256으로 바꿔 든다. 설정 파일 `[[clients]]`와 합쳐지고, 둘 다 비면 **기동 실패** |
| `GATEWAY_AUTH` | (켬) | `off`면 클라이언트 키 없이 받는다 — 로컬 실험만. 그때 클라이언트의 인증 헤더는 상류로 넘어간다. 공급자 키(`GATEWAY_UPSTREAM_KEY`·`key_env`)와 함께 쓰면 **기동 실패** |
| `GATEWAY_CONFIG` | (없음) | 설정 파일(TOML) 경로 — 아래 '설정 파일'. 없으면 환경변수만으로 뜬다 |
| `GATEWAY_UPSTREAM_KEY` | (없음) | 설정 파일에 없는 상류의 공급자 키. 상류 형식으로 단다 — `/v1/messages`와 `anthropic-version`을 보낸 요청은 `x-api-key`, 그 밖은 `Authorization: Bearer`. 없으면 공급자 키 없이 보낸다(클라이언트의 `openai-organization`·`openai-project`는 넘긴다) |
| `GATEWAY_ADMIN_KEY` | (없음) | `/__gateway/info`·`/__gateway/metrics`를 여는 관리 키(`Authorization: Bearer`). 없으면 둘 다 404 |
| `GATEWAY_SURROGATE_KEY` | (없음) | 결정적 대체값 키, 32자 이상. 어느 정책이든 `mask`면 필수(없거나 짧으면 **기동 실패**). 원문을 되짚을 수 있는 키라 공급자 키와 같은 등급으로 보관한다. 바꾸는 절차는 [운영 — 키 회전](operations.md#키-회전) |
| `GATEWAY_PII` | `mask` | `mask`(같은 모양의 가짜 값으로 바꾸고 응답에서 복원) · `detect`(감사에만 남김) · `off` |
| `GATEWAY_PII_KINDS` | 전부(`rrn,frn,passport,driver,card,phone,email,secret,brn,crn,account,ipv4`) | 탐지할 종류(쉼표). 종류는 [README 탐지 종류](../README.md#탐지-종류) |
| `GATEWAY_PII_DETECT_KINDS` | `account,brn,crn,ipv4` | `mask` 모드에서도 가리지 않고 감사(`unmasked`)에만 남길 종류. 빈 값이면 탐지한 종류를 모두 가린다 |
| `GATEWAY_PII_ROLES` | `user,assistant,tool,system` | 가릴 역할(쉼표). `developer`·Responses `instructions`는 `system`이다 |
| `GATEWAY_INJECTION` | `observe` | `observe`(적중을 감사에만, `would_block`) · `block`(이번 턴이 걸리면 상류 없이 차단 응답, 이력의 걸린 턴은 가림) · `off` |
| `GATEWAY_LANG` | `ko` | 사용자·운영자 문구 — `ko`·`en`(차단 문구·가린 이력 자리표시·기동 거부·설정 오류). API 오류 본문은 언제나 영어 |
| `GATEWAY_BLOCKED_MESSAGE` | (카탈로그 문구) | 차단 응답 문구. 끝에 `(요청 ID: …)`가 붙는다 |
| `GATEWAY_MAX_BODY_BYTES` | `1048576`(1MiB) | 요청 본문 상한. 넘으면 검사기·상류 없이 413 `request_too_large`. 긴 문맥 모델을 쓰면 올린다(메모리는 [운영 — 용량](operations.md#용량)) |
| `GATEWAY_MAX_FINDINGS` | `5000` | `mask` 모드 한 요청의 탐지 상한. 넘으면 대체값을 하나도 만들지 않고 413 `too_many_findings`, 상류 없음 |
| `GATEWAY_MAX_CONNECTIONS` | `100` | 상류마다 동시에 쓸 수 있는 연결 수(주소·시간 제한이 같은 상류는 함께 쓴다). 다 쓰는 중이면 먼저 온 요청부터 5초까지 기다리고, 넘으면 503 `upstream_busy` |
| `GATEWAY_RATE_PER_MINUTE` | `0`(끔) | 클라이언트(무인증이면 IP)마다 분당 상한. 넘으면 429 + `retry-after`, 상류 없음. 워커별로 센다 |
| `GATEWAY_TIMEOUT` | `600` | 설정 파일에 `timeout`이 없는 상류의 읽기 대기(초). 연결 5초·쓰기 30초·풀 대기 5초는 고정. 연결·쓰기·읽기 어느 시간 제한이든 넘으면 504 `upstream_timeout`(스트림 도중의 읽기 시간 초과는 이미 200을 보낸 뒤라 스트림이 끊기고 감사 `error`에 남는다). 대체값 매핑은 가장 긴 상류 시간 제한보다 60초 더 산다 |
| `GATEWAY_LOG_PATH` | `logs/gateway.jsonl`(이미지는 `-`) | 감사 로그. `-`면 stdout |
| `GATEWAY_LOG_MAX_BYTES` | `104857600`(100MiB) | 감사 로그 파일 회전 크기(파일일 때만) |
| `GATEWAY_LOG_BACKUPS` | `5` | 회전한 감사 로그를 남길 개수(파일일 때만) |

이미지의 실행 명령(uvicorn)이 읽는 변수:

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `WEB_CONCURRENCY` | `1` | 워커(프로세스) 수. 지표·레이트리밋·대체값 세션 상한이 워커별이라 1로 두고 파드·컨테이너 수로 늘리기를 권한다 |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | `X-Forwarded-For`를 믿을 프록시 주소. 그 밖에서 온 헤더는 무시된다 — 감사 `ip`와 무인증 레이트리밋이 쓴다 |
| `UVICORN_TIMEOUT_KEEP_ALIVE` | `5` | 쉬는 클라이언트 연결을 닫기까지의 초. 인그레스·LB 뒤에서는 그 유휴 시간(보통 60초)보다 길게 — k8s 견본은 75. 쉬는 연결도 동시 연결 상한(1,000)에 든다 |

## 설정 파일 (`GATEWAY_CONFIG`)

한 게이트웨이로 OpenAI와 Anthropic을 함께 쓰고, 클라이언트(팀·앱)마다 정책을 달리 준다. 공급자 키는 파일에 두지 않고 `key_env`가 가리키는 환경변수(k8s Secret)에서 읽는다.
클라이언트 키도 해시만 둔다. 모르는 표·키, 틀린 값, 없는 정책을 가리키는 클라이언트, 없거나 빈 환경변수를 가리키는 `key_env`는 기동 실패다.

이 표의 키는 `tests/test_d121_docs.py`가 코드와 맞춘다.

| 키 | 값 | 기본 | 뜻 |
|---|---|---|---|
| `[[clients]] name` | 문자열 | (필수) | 감사 줄 `client`, 레이트리밋 단위. 키를 바꿀 때 같은 이름으로 두 줄을 둘 수 있다 |
| `[[clients]] key_sha256` | 소문자 16진 64자 | (필수) | 클라이언트 키의 SHA-256(`keygen --hash`의 둘째 줄). 같은 해시가 두 번이면 기동 실패 |
| `[[clients]] policy` | 정책 이름 | `default` | 이 클라이언트에 쓸 정책 |
| `[policies.<이름>] injection` | `observe`·`block`·`off` | `GATEWAY_INJECTION` | |
| `[policies.<이름>] pii_mode` | `mask`·`detect`·`off` | `GATEWAY_PII` | |
| `[policies.<이름>] pii_kinds` | 종류 목록 | `GATEWAY_PII_KINDS` | |
| `[policies.<이름>] pii_detect_kinds` | 종류 목록 | `GATEWAY_PII_DETECT_KINDS` | 빈 목록이면 모두 가린다 |
| `[policies.<이름>] pii_roles` | 역할 목록 | `GATEWAY_PII_ROLES` | |
| `[policies.<이름>] allowed_models` | fnmatch 글롭 목록 | (모두) | 밖의 모델은 403 `model_not_allowed`, 검사기·상류 없음 |
| `[upstreams.<api>] base_url` | URL | `TARGET_URL` | `<api>`는 `chat`·`responses`·`messages`(어댑터 이름) |
| `[upstreams.<api>] key_env` | 환경변수 이름 | (없음) | 공급자 키를 담은 환경변수. 없으면 키를 달지 않는다 — `GATEWAY_UPSTREAM_KEY`를 넘겨받지 않는다(다른 공급자의 키일 수 있다) |
| `[upstreams.<api>] timeout` | 초 | `GATEWAY_TIMEOUT` | 읽기 대기 |

- 정책의 빠진 값은 `[policies.default]`를 따르고, `default`의 빠진 값은 환경변수를 따른다.
- `GET /v1/models`는 `anthropic-version` 헤더가 있으면 `messages` 상류, 없으면 `chat` 상류로 간다. 파일에 없는 API는 `TARGET_URL`·`GATEWAY_UPSTREAM_KEY`·`GATEWAY_TIMEOUT`.
- 파일 SHA-256 앞 12자가 `/__gateway/info`의 `config`와 감사 줄의 `config`에, 요청의 정책 이름이 감사 줄 `policy`에 남는다.

```toml
[[clients]]
name = "support-bot"
key_sha256 = "…"            # keygen --hash의 둘째 줄
policy = "strict"

[policies.default]          # 빠진 값은 환경변수를 따른다
injection = "observe"

[policies.strict]
injection = "block"
pii_mode = "mask"
pii_detect_kinds = []       # 계좌·사업자·IP까지 가린다(pii_kinds는 default — 여기서는 환경변수의 기본, 열두 종류 전부)
allowed_models = ["gpt-4.1*", "claude-sonnet-*"]

[upstreams.chat]
base_url = "https://api.openai.com"
key_env = "OPENAI_API_KEY"

[upstreams.responses]
base_url = "https://api.openai.com"
key_env = "OPENAI_API_KEY"

[upstreams.messages]
base_url = "https://api.anthropic.com"
key_env = "ANTHROPIC_API_KEY"
timeout = 600
```

k8s 견본 설정은 [`deploy/k8s/gateway.toml`](../deploy/k8s/gateway.toml)이다.
