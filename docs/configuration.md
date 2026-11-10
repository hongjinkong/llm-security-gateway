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
| `GATEWAY_ADMIN_KEY` | (없음) | `/__gateway/info`·`/__gateway/metrics`·`/__gateway/stats`(`Authorization: Bearer`)와 대시보드(`/__gateway/dashboard` — 화면에 키를 넣는다)를 여는 관리 키. 없으면 모두 404 — [운영 — 대시보드](operations.md#대시보드) |
| `GATEWAY_SURROGATE_KEY` | (없음) | 결정적 대체값 키, 32자 이상. 어느 정책이든 `mask`면 필수(없거나 짧으면 **기동 실패**). 원문을 되짚을 수 있는 키라 공급자 키와 같은 등급으로 보관한다. 바꾸는 절차는 [운영 — 키 회전](operations.md#키-회전) |
| `GATEWAY_PII` | `mask` | `mask`(같은 모양의 가짜 값으로 바꾸고 응답에서 복원) · `detect`(감사에만 남김) · `off` |
| `GATEWAY_PII_KINDS` | 정규식 12종(`rrn,frn,passport,driver,card,phone,email,secret,brn,crn,account,ipv4`) | 탐지할 종류(쉼표). 종류는 [README 탐지 종류](../README.md#탐지-종류). **이름·주소·직장**(`person`·`address`·`org`)은 기본에 없다 — 더하면 탐지 사이드카가 찾는다(`GATEWAY_DETECT_URL` 필수, 아래 '이름·주소 가림') |
| `GATEWAY_PII_DETECT_KINDS` | `account,brn,crn,ipv4,org` | `mask` 모드에서도 가리지 않고 감사(`unmasked`)에만 남길 종류. 빈 값이면 탐지한 종류를 모두 가린다 |
| `GATEWAY_PII_ROLES` | `user,assistant,tool,system` | 가릴 역할(쉼표). `developer`·Responses `instructions`는 `system`이다 |
| `GATEWAY_DETECT_URL` | (없음) | 탐지 사이드카([`detect/`](../detect/README.md)) 주소 — 예: `http://127.0.0.1:8081`(k8s 같은 파드)·`http://detect:8081`(compose). 어느 정책이든 `pii_kinds`에 `person`·`address`·`org`를 넣었는데(그리고 `pii_mode`가 `off`가 아닌데) 비어 있으면 **기동 실패**. 모양은 `http(s)://호스트[:포트]`만 — 경로·쿼리·다른 스킴은 기동 실패 |
| `GATEWAY_DETECT_TIMEOUT` | `10` | 한 요청의 이름·주소 탐지 전체 기한(초, 0보다 큰 수 — 아니면 기동 실패) — 긴 요청은 12,000자마다 사이드카 호출 하나(창 하나 1~6초, [운영](operations.md#탐지-사이드카)). 넘으면 아래 `GATEWAY_DETECT_FAIL` |
| `GATEWAY_DETECT_FAIL` | `closed` | 사이드카가 실패(연결 거부·5xx·시간 초과·이상한 응답)했을 때 가리는 이름·주소가 켜진 `mask` 정책의 동작 — `closed`: 상류에 보내지 않고 503 `detect_unavailable`(`retry-after: 1`) · `open`: 정규식 종류만 가리고 보낸다(감사 `ner_error`). `detect` 정책과 감사만 종류(`org` 기본)는 늘 통과한다 |
| `GATEWAY_INJECTION` | `observe` | `observe`(적중을 감사에만, `would_block`) · `block`(이번 턴이 걸리면 상류 없이 차단 응답, 이력의 걸린 턴은 가림) · `off` |
| `GATEWAY_GUARD` | `off` | 가드레일 웹훅(아래 '가드레일 웹훅') — `observe`(판정·점수를 감사에만, block 판정이면 `would_block`) · `block`(block 판정이면 상류 없이 차단 응답) · `off` |
| `GATEWAY_GUARD_URL` | (없음) | 웹훅 주소 — 탐지 사이드카의 인젝션 분류기면 `http://127.0.0.1:8081/v1/guard`(k8s 같은 파드)·`http://detect:8081/v1/guard`(compose). 어느 정책이든 `guard`를 켰는데 비어 있으면 **기동 실패**. 모양은 `http(s)://호스트[:포트][/경로]` — 쿼리·조각·다른 스킴은 기동 실패 |
| `GATEWAY_GUARD_TIMEOUT` | `5` | 한 요청의 웹훅 전체 기한(초, 0보다 큰 수). 넘으면 아래 `GATEWAY_GUARD_FAIL` |
| `GATEWAY_GUARD_FAIL` | `open` | 웹훅이 실패(연결 거부·200 아닌 응답·시간 초과·이상한 응답)했을 때 `block` 정책의 동작 — `open`: 판정 없이 보낸다(감사 `guard_error`) · `closed`: 상류에 보내지 않고 503 `guard_unavailable`(`retry-after: 1`). `observe`는 늘 통과한다 |
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
| `FORWARDED_ALLOW_IPS` | `127.0.0.1,::1` | `X-Forwarded-For`를 믿을 프록시 주소(기본은 루프백뿐 — uvicorn 0.53부터 IPv6 `::1` 포함). 그 밖에서 온 헤더는 무시된다 — 감사 `ip`와 무인증 레이트리밋이 쓴다 |
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
| `[policies.<이름>] guard` | `observe`·`block`·`off` | `GATEWAY_GUARD` | 켜면 `GATEWAY_GUARD_URL` 필수 |
| `[policies.<이름>] pii_mode` | `mask`·`detect`·`off` | `GATEWAY_PII` | |
| `[policies.<이름>] pii_kinds` | 종류 목록 | `GATEWAY_PII_KINDS` | `person`·`address`를 더하면 이 정책만 이름·주소를 가린다 |
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
pii_detect_kinds = []       # 계좌·사업자·IP까지 가린다(pii_kinds는 default — 여기서는 환경변수의 기본, 정규식 열두 종류)
allowed_models = ["gpt-4.1*", "claude-sonnet-*"]

[policies.names]            # 이름·주소까지 가린다 — GATEWAY_DETECT_URL이 있어야 뜬다(직장 org는 넣지 않았으므로 찾지도 않는다)
pii_kinds = ["rrn", "frn", "passport", "driver", "card", "phone", "email", "secret", "brn", "crn", "account", "ipv4", "person", "address"]

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

## 이름·주소 가림 (`person`·`address`·`org`)

정규식이 아니라 한국어 NER 모델(탐지 사이드카 `detect/`, 별도 컨테이너)이 찾는다. **기본은 꺼져 있다** — 정책의 `pii_kinds`(또는 `GATEWAY_PII_KINDS`)에 `person`·`address`를 더하고
`GATEWAY_DETECT_URL`을 주면 켜진다. 정확도는 모델의 것(합성 문장 F1 0.96·실제 대화 0.90 — 놓침·잘못 가림 각각 약 10%)이고, 요청마다 사이드카 왕복이 더해진다
(x86 4 vCPU에서 510토큰 약 200~370ms, 러너 CPU에 따라 — 매 턴 다시 오는 이력은 캐시에서 나와 새 메시지만 간다). 규칙과 한계는 [README 탐지 종류](../README.md#탐지-종류)·[운영 — 탐지 사이드카](operations.md#탐지-사이드카),
배포 모양은 [`deploy/compose.yml`](../deploy/compose.yml)(서비스 `detect`)·[`deploy/k8s/gateway.yaml`](../deploy/k8s/gateway.yaml)(같은 파드의 둘째 컨테이너)이다.

- `org`(직장)는 기본 감사만(`GATEWAY_PII_DETECT_KINDS`)이다 — 회사 이름을 가짜로 바꾸면 '삼성전자 주가' 같은 질문의 답이 망가진다. 가리려면 거기서 뺀다.
- `address`는 번지·건물 번호·동·호·층처럼 숫자가 든 토큰이 있을 때만 가리고, 시·도·구·역·나라 이름뿐이면 감사만이다('서울 날씨'를 가리면 질문이 바뀐다).
- 가짜 이름은 성 + 이름(마지막 글자의 받침 부류가 원문과 같아 뒤따르는 조사가 맞는다), 가짜 주소는 시·도·시·군·구를 두고 도로·동·건물·번호를 바꾼다(번호는 자릿수와 마지막 자리 유지).
- 사이드카가 실패하면 `GATEWAY_DETECT_FAIL`(`closed` 기본 — 503 `detect_unavailable`, `open` — 정규식 종류만 가리고 보냄). `detect` 정책은 늘 통과한다.

## 가드레일 웹훅 (`GATEWAY_GUARD`)

인젝션을 룰 말고 다른 판정기(분류기·사내 가드레일 서비스)로도 본다(D-127). **기본은 꺼져 있다** — `GATEWAY_GUARD`(또는 정책 키 `guard`)를 `observe`나 `block`으로 두고
`GATEWAY_GUARD_URL`을 주면 켜진다. 게이트웨이는 요청마다 웹훅을 한 번 부른다:

```
POST GATEWAY_GUARD_URL  {"texts": [{"role": "user", "text": "…"}, {"role": "tool", "text": "…"}]}
→ 200 {"verdict": "allow" | "block", "score": 0~1}        (그 밖의 키는 무시한다)
```

- **보내는 텍스트**: 이번 턴(글이 든 마지막 user 메시지부터 끝까지 — 빈 user 메시지를 덧붙여도 앞 글이 빠지지 않는다)의 사용자 글(`user`)과 도구 결과·첨부 문서(`tool` — Anthropic `document`·`search_result` 포함, 범위는 [API 호환 — 검사 범위](api-compat.md#api별-검사복원-범위))뿐이다. 같은 메시지의 파트는 하나로 이어
  메시지마다 항목 하나다. system 프롬프트·모델의 답(assistant)·이전 턴은 보내지 않는다(이전 턴은 그 턴일 때 이미 판정했다). 텍스트가 없으면 부르지 않는다.
- **웹훅은 공급자와 같은 텍스트를 본다**: 체인의 마지막(PII 뒤)에 서므로 **정책이 가리는 종류만 가짜 값**이다. 감사만 종류(기본 계좌·사업자·법인·IP·직장), 켜지 않은 종류(이름·주소는 기본 꺼짐),
  `pii_mode`가 `detect`·`off`인 정책의 텍스트는 원문 그대로 웹훅에 간다 — 외부 서비스를 웹훅으로 쓰면 그곳이 또 하나의 처리자가 된다. 같은 파드·내부망의 판정기를 권한다.
- `observe`: 막지 않는다. 감사 줄 검사기 항목(`injection_guard`)에 `guard_verdict`·`guard_score`, `block` 판정이면 `would_block: true`(대시보드 결과 '기록만', 사유 `injection_guard`).
- `block`: `block` 판정이면 룰 차단과 같은 200 차단 응답(`gateway_blocked: true`, 사유·점수는 응답에 없고 감사에만), 상류는 부르지 않는다(사유 `injection_guard_block`).
- 실패(연결 거부·200 아닌 응답·`GATEWAY_GUARD_TIMEOUT` 초과·모양이 틀린 응답)는 감사 `guard_error`(`connect`·`http_<상태>`·`timeout`·`bad_response`)와 지표
  `gateway_guard_errors_total{reason}`에 남고, `observe`는 판정 없이 보낸다. `block`에서 웹훅이 **입력을 거절**하면(400·413·422 — 너무 크거나 많다) `GATEWAY_GUARD_FAIL`과 상관없이
  막는다 — 통과시키면 글을 부풀리기만 해도 판정을 피한다. 그 밖의 실패는 `open`(기본)이면 판정 없이 보내고 `closed`면 503 `guard_unavailable`(`retry-after: 1`).
  웹훅이 일부 텍스트를 재지 못했다고 하면(응답의 선택 키 `unscored` — 판정하지 못한 텍스트 수) `block`은 막고 `observe`는 감사 `guard_unscored`로 남긴다.
  `block`을 쓰면 `closed`를 권한다 — `open`이면 웹훅을 바쁘게 만들거나(동시 요청) 끊어 판정을 피할 수 있다.
- 웹훅에는 인증 헤더를 달지 않는다 — 같은 파드나 내부망에 둔다. 외부 가드레일 서비스는 계약이 다르므로 이 계약을 받는 작은 어댑터를 같은 클러스터에 두고, 어댑터가 그 서비스의 키를 든다.

**탐지 사이드카의 인젝션 분류기를 웹훅으로**: 사이드카([`detect/`](../detect/README.md))의 `POST /v1/guard`가 이 계약을 구현한다. 분류기는 이미지에 들어 있지만 기본으로 싣지 않는다 —
사이드카에 `DETECT_INJECTION_MODEL=horizon-guard-base-int8`(메모리 약 +1.2GiB), 게이트웨이에 `GATEWAY_GUARD=observe`와 `GATEWAY_GUARD_URL`(같은 파드면 `http://127.0.0.1:8081/v1/guard`,
compose면 `http://detect:8081/v1/guard`). 점수는 텍스트들의 (512토큰 창들의) 최댓값이고, 문턱(`DETECT_GUARD_THRESHOLD`, 기본은 모델의 운영 문턱 — dev 정상셋 오탐 1%)을 넘으면 `block`이다.
한 요청에서 캐시에 없는 글은 새 글부터 비용 상한 `DETECT_INJECTION_MAX_TOKENS`(기본 2,048)까지만 재고 나머지는 `unscored`로 알린다. 이미지에 든 공개 모델(`horizon-guard-base-int8`)로는 `block`을 권하지 않는다 — 가짜 판정 JSON을 붙이면
잡힌 공격의 8.9%가 빠져나간다(D-127 양성대조). 한국어 데이터로 이어 학습한 `injection-ko-small-int8`(D-128 — 양성대조 최대 0.7%, 봉인 홀드아웃 한국어 97.5%)은 Hugging Face에 올라간 뒤 기본이 된다 — 그때까지는 `models.json`의 `published: false`
항목이라 `DETECT_INJECTION_MODEL=injection-ko-small-int8`로 실으려면 `models/`에 학습 결과 폴더가 있어야 한다. 정확도·지연·메모리·한계는 [운영 — 가드레일 웹훅](operations.md#가드레일-웹훅)과 DECISIONS D-127·D-128.
