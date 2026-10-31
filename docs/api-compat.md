# API 호환 범위

게이트웨이는 세 API의 요청을 파싱해 텍스트를 검사·마스킹하고, 응답에서 가짜 값을 원래 값으로 되돌린다. 그 밖의 경로는 받지 않는다(404, 상류에 연결하지 않음).
클라이언트는 `base_url`과 `api_key`(게이트웨이 키)만 바꾼다 — OpenAI SDK는 `http://게이트웨이/v1`, Anthropic SDK는 `http://게이트웨이`.

## 경로

| 메서드·경로 | 상류 표(`[upstreams.*]`) | 하는 일 |
|---|---|---|
| `POST /v1/chat/completions` | `chat` | 검사·마스킹 → 상류 → 복원(스트리밍 포함) |
| `POST /v1/responses` | `responses` | 같음 |
| `POST /v1/messages` | `messages` | 같음. 쿼리 문자열(SDK 베타 경로의 `?beta=true` 등)도 넘긴다 |
| `GET /v1/models` | `anthropic-version` 헤더가 있으면 `messages`, 없으면 `chat` | 키 검증·레이트리밋·헤더 허용 목록만 지나 그대로 중계(본문 없음) |
| `GET /__gateway/health` | — | 인증 없이 `{"status": "ok"}`만. readiness 용 |
| `GET /__gateway/info` | — | 관리 키(`GATEWAY_ADMIN_KEY`, `Authorization: Bearer`)만. 버전·코드 지문·설정 버전·상류·검사기 — [운영](operations.md#업그레이드) |
| `GET /__gateway/metrics` | — | 관리 키만. Prometheus 텍스트 — [운영](operations.md#지표) |
| `GET /__gateway/stats` | — | 관리 키만. 대시보드의 데이터(JSON — 누적과 최근 200줄). 형식이 바뀔 수 있으니 수집은 metrics로 한다 — [운영](operations.md#대시보드) |
| `GET /__gateway/dashboard` | — | 관리 키가 설정된 게이트웨이에만 있다. 인증 없이 데이터 없는 정적 화면을 주고, 화면이 탭에 넣은 키로 stats를 읽는다 — [운영](operations.md#대시보드) |

info·metrics·stats는 `Authorization: Bearer` 관리 키가 맞을 때만 200이다 — 키 없음·틀린 키·`?key=`·Basic·관리 키 미설정은 404. 이 경로들은 감사 로그·지표·레이트리밋에 들어가지 않는다.
그 밖의 경로·메서드는 404이고 상류에 연결하지 않는다(어떤 메서드가 있는지 알리지 않으려고 405도 404로 답한다). 끝에 `/`를 붙인 경로(`/v1/chat/completions/` 등)도 리다이렉트(307) 없이 404다. FastAPI 기본 문서 경로(`/docs`·`/redoc`·`/openapi.json`)는 없다.

처리 순서: 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 파싱(400) → 허용 모델(403) → 인젝션 → PII → 상류 → 복원 → 감사 한 줄.
401·429·413·403은 본문을 검사하지도 중계하지도 않는다.

## API별 검사·복원 범위

가리는 텍스트는 아래 자리뿐이다. 적지 않은 필드(도구 정의의 설명·스키마, `response_format`, `metadata` 등)는 보지 않고 그대로 보낸다.
가릴 역할은 `GATEWAY_PII_ROLES`(기본 전부)로 좁힌다. 복원은 응답의 문자열 값마다 하고, 사고 과정(Anthropic `thinking`·`redacted_thinking`, Responses `reasoning`)은 요청·응답 모두 손대지 않는다 —
바꾸면 상류가 다음 턴을 거절하고, 복원하면 원래 값이 다음 턴에 사고 과정에 담겨 상류로 간다. 그래서 사고 과정에서는 가짜 값이 보인다.

**Chat Completions** (`/v1/chat/completions`)
- 가린다: `messages[].content`(문자열이나 `text` 파트) — system·developer·user·assistant·tool 역할, assistant의 `tool_calls[].function.arguments`.
- 보지 않는다: `image_url`·`input_audio`·`file` 파트, `prediction`, 도구 정의.
- 스트리밍: choice마다 본문·도구 인자 채널을 조각 경계에 걸쳐 복원한다(`n` > 1 포함). usage를 받으려고 상류 요청에 `stream_options.include_usage`를 넣고,
  클라이언트가 요청하지 않았으면 usage만 담은 마지막 조각을 클라이언트 스트림에서 뺀다 — 그 필드를 모르는 OpenAI 호환 서버는 400을 낼 수 있다.
- `logprobs`의 토큰·바이트는 복원하지 않는다(가짜 값이 토큰 여러 개로 쪼개져 있다).

**Responses** (`/v1/responses`)
- 가린다: `instructions`(system), `input` 문자열, 항목 목록의 메시지 파트(`input_text`·`output_text`·`text`), `function_call.arguments`, `function_call_output.output`.
- 보지 않는다: `input_image`·`input_file` 파트, `reasoning` 항목(`encrypted_content` 포함), 서버 측 도구 항목(`web_search_call`·`file_search_call`·`code_interpreter_call`·`mcp_call` 등),
  사용자 정의 도구(`custom_tool_call`·`custom_tool_call_output`) — **사용자 정의 도구의 입출력에 든 개인정보는 그대로 나간다**.
- 스트리밍: 출력·내용 번호마다 채널, 전체 텍스트를 담은 `*.done`·`response.completed` 이벤트도 복원한다.
- `previous_response_id`·`conversation`: 상류로 넘기지만, 상류에 저장된 이전 턴은 게이트웨이가 볼 수 없다. 이전 턴은 이미 가짜 값으로 저장돼 있고(같은 원문 = 같은 가짜 값),
  **이번 요청에 없던 값이 답에 나오면 가짜 값 그대로 받는다** — 복원은 이번 요청에서 가린 값만 한다. 대화 이력을 클라이언트가 매번 보내는 방식(`input` 목록)을 권한다.
- 응답 조회·취소(`GET /v1/responses/{id}` 등)는 404라 `background` 모드는 쓸 수 없다.

**Messages** (`/v1/messages`)
- 가린다: `system`(문자열·text 블록), `messages[].content`의 문자열·text 블록, `tool_result` 내용(문자열·text 블록 — tool 역할), `tool_use.input`의 문자열 값,
  텍스트 `document`(`source.type: text` — system 역할로 다룬다).
- 보지 않는다: image·PDF `document`(base64·URL·파일 ID), `search_result` 블록, 서버 도구 블록(`server_tool_use`·`web_search_tool_result` 등), 도구 정의.
- 스트리밍: content block 번호가 채널이다. thinking 블록은 건너뛴다.

## 서버 측 도구와 원격 MCP

공급자가 실행하는 도구(OpenAI `web_search`·`file_search`·`code_interpreter`·원격 MCP, Anthropic web search·web fetch·code execution·MCP 커넥터)는 **가짜 값을 받는다**.
값 자체에 결과가 달린 도구 — 예를 들어 원격 MCP로 사내 CRM에서 전화번호로 고객을 찾는 것 — 는 없는 값이나 다른 사람을 찾는다. 결과 텍스트에 가짜 값이 있으면 응답에서 복원은 된다.
클라이언트 측 도구(function calling·tool use)는 된다: 게이트웨이가 도구 인자를 원래 값으로 복원해 클라이언트에 주고, 클라이언트가 돌린 결과(tool 역할)는 다음 요청에서 다시 가린다.

## 지원하지 않는 기능 (404)

| 기능 | 경로 예 | 비고 |
|---|---|---|
| 임베딩 | `/v1/embeddings` | 요구가 있으면 결정적 대체값으로 경로를 더한다(PLAN 조건부) |
| 파일 | `/v1/files`(OpenAI·Anthropic) | 올린 파일과, 요청에서 파일 ID로 가리킨 내용은 게이트웨이가 볼 수 없다 |
| 오디오 | `/v1/audio/*`(전사·음성 합성) | Chat의 오디오 입출력 파트도 보지 않는다 |
| 이미지 생성 | `/v1/images/*` | |
| 토큰 세기 | `/v1/messages/count_tokens`, `/v1/responses/input_tokens` | |
| 배치 | `/v1/batches`, `/v1/messages/batches` | |
| 응답 조회·저장 대화 | `GET /v1/responses/{id}`, `/v1/conversations` | |
| Realtime | `/v1/realtime`(WebSocket) | |
| 옛 completions | `/v1/completions` | |
| 그 밖 | 모더레이션·파인튜닝·벡터 스토어·Assistants | |

## 헤더

- 상류로 넘기는 요청 헤더: `content-type` `accept` `user-agent` `anthropic-version` `anthropic-beta` `openai-beta` `idempotency-key`, 그리고 게이트웨이의
  `x-gateway-request-id`(감사 줄 `request_id`와 같다 — 사내 상류의 로그와 잇는다). 공급자 키는 상류 형식으로 단다(`/v1/messages`·`anthropic-version`은 `x-api-key`, 그 밖은 `Bearer`).
  클라이언트의 인증 헤더는 `GATEWAY_AUTH=off`일 때만 넘긴다(켜져 있으면 그것은 게이트웨이 키다). 공급자 키가 없으면 `openai-organization`·`openai-project`도 넘긴다.
  쿠키·`X-Forwarded-*`·`accept-encoding`·SDK 계측 헤더는 넘기지 않는다.
- 클라이언트로 넘기는 응답 헤더: `content-type` `cache-control` `retry-after` `retry-after-ms` `x-should-retry`, 그리고 게이트웨이의 `x-gateway-request-id`와
  `x-gateway-pii: issued=N restored=M`(가짜 값을 발급한 비스트리밍 응답, 스트리밍은 발급 수만). 상류의 요청 ID는 감사 줄 `upstream_request_id`에만 남는다.
  상류 쿠키는 저장하지도 보내지도 않는다.

## 오류

게이트웨이가 만든 오류 본문은 그 API의 형식이다 — `/v1/messages*`는 Anthropic 형식(`{"type": "error", "error": {"type", "message"}}`), 그 밖은 OpenAI 형식
(`{"error": {"message", "type", "param", "code"}}`). 스트리밍 요청이어도 오류는 JSON이다. 상류가 낸 오류는 상태 코드·본문을 그대로 넘긴다
(스트림 도중 상류가 보낸 오류 이벤트도 그대로 넘기고 감사 `error`에 `upstream_stream_error`를 남긴다 — 상태는 이미 보낸 200).
예외: 동시 연결이 1,000(쉬는 연결 포함)을 넘으면 uvicorn이 형식 없는 텍스트 503(`Service Unavailable`)을 준다 — 게이트웨이 앞에서 끊는 것이다.

| 상태 | code(OpenAI 형식) | 언제 | 상류 호출 |
|---|---|---|---|
| 400 | `invalid_json` 등 | 본문 파싱 실패 | 없음 |
| 401 | `invalid_api_key` | 게이트웨이 키가 없거나 틀림 | 없음 |
| 403 | `model_not_allowed` | 정책의 허용 모델 밖 | 없음 |
| 404 | `not_found` | 허용 목록 밖의 경로·메서드 | 없음 |
| 413 | `request_too_large` · `too_many_findings` | 본문 상한 · 탐지 상한 | 없음 |
| 429 | `rate_limit_exceeded` | 분당 상한(`retry-after`) | 없음 |
| 500 | `internal_error` | 게이트웨이 내부 예외 — `x-gateway-request-id`로 감사 줄을 찾는다 | — |
| 502 | `upstream_unavailable` · `upstream_response_too_large` | 상류 연결 실패 · 비스트리밍 응답이 32MiB 초과 | 시도함 |
| 503 | `upstream_busy` · `gateway_busy` | 빈 상류 연결을 5초 기다려도 없음 · 진행 중인 대체값 세션이 상한(워커·정책당 2,000) — 둘 다 `retry-after: 1` | 없음 |
| 504 | `upstream_timeout` | 상류 연결(5초)·쓰기(30초)·읽기(`GATEWAY_TIMEOUT`) 시간 초과. 스트림 도중이면 이미 200을 보냈으므로 스트림이 끊기고 감사 `error`에 남는다 | 시도함 |

## 차단 응답 (`GATEWAY_INJECTION=block`)

차단은 HTTP 200의 정상 응답 모양으로 돌려준다 — SDK가 오류로 다루지 않는다. 상류는 부르지 않는다. 사유는 넣지 않고(감사에만) 문구 끝에 `(요청 ID: …)`를 붙인다.

| API | 모양 |
|---|---|
| Chat | `finish_reason: "content_filter"`, `gateway_blocked: true`(스트리밍은 조각 하나 + `[DONE]`) |
| Responses | `status: "incomplete"`, `incomplete_details.reason: "content_filter"`, `gateway_blocked: true` |
| Messages | `stop_reason: "refusal"`, `gateway_blocked: true` |

## 상류

- 실 API로 확인한 상류: Anthropic API(지금 코드, 2턴 — [`docs/verification/multiturn_claude.md`](verification/multiturn_claude.md)). OpenAI API는 연구 단계 코드로만
  실 API를 확인했다(`gpt-4o-mini`, `research-final` 태그의 D-087) — 지금 코드는 공식 SDK(OpenAI·Anthropic Python)를 스텁 앞에서 세 API로 점검한다.
- OpenAI 호환 서버(Ollama·vLLM 등)는 `/v1/...` 경로를 그대로 받으면 된다. 경로가 다른 곳(Azure OpenAI 배포 경로, Gemini의 `/v1beta/openai/…`, AWS Bedrock, Google Vertex)은 지원하지 않는다.
