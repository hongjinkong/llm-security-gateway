# LLM Security Gateway

LLM 앱과 AI 공급자 사이에 두는 자체 호스팅 프록시다. **밖으로 나가는 개인정보·자격 증명을 같은 모양의 가짜 값으로 바꿔 보내고 응답에서 되돌리며,
프롬프트 인젝션을 관측(선택하면 차단)하고, 요청마다 감사 한 줄을 남긴다.** OpenAI Chat Completions·Responses, Anthropic Messages
세 API를 스트리밍·도구 호출까지 그대로 통과시킨다. 앱과 모델 코드는 고치지 않는다 — 클라이언트의 `base_url`과 API 키(게이트웨이 키)만 바꾼다.
공급자 키는 게이트웨이 한 곳에만 둔다.

> **상태**: 0.1.0. 상용화 계획([`PLAN.md`](PLAN.md))을 순서대로 진행 중이다. 결정 기록은 [`DECISIONS.md`](DECISIONS.md)(D-108부터).
> 연구 단계의 측정 수치·측정 장치·결정 D-001~D-107은 `research-final` 태그에 있다(`git show research-final:README.md`).

---

## 1. 무엇을 하나

```
클라이언트 (OpenAI SDK · Anthropic SDK · OpenAI 호환 앱 — base_url과 api_key(게이트웨이 키)만 바꾼다)
    │  POST /v1/chat/completions · /v1/responses · /v1/messages   (스트리밍·도구 호출 포함) · GET /v1/models
    ▼
게이트웨이 :8080   그 밖의 경로·메서드는 404(상류에 연결하지 않음) → 클라이언트 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 파싱(400)
    요청  인젝션 룰 관측(또는 차단) → 모든 역할(system·도구 결과·RAG 문서 포함)의 텍스트와 도구 인자 속 개인정보·자격 증명을 같은 모양의 가짜 값으로 교체
    상류  허용 목록의 헤더만 넘기고 공급자 키를 단다(쿠키·X-Forwarded-*·조직 헤더·게이트웨이 키는 넘기지 않는다)
    응답  가짜 값을 원래 값으로 복원(스트리밍은 조각 경계·채널별, thinking·reasoning은 손대지 않음) · 요청마다 감사 로그 한 줄(원문 없음)
    │
    ▼
상류  OpenAI · Anthropic · OpenAI 호환 서버(로컬 Ollama 등)
```

- **상류는 `010-8419-3027` 같은 가짜 값을 보고 보통의 값으로 다룬다.** 모델이 "가려졌다"고 눈치채지 않고 도구 인자에도 그대로 쓰며,
  사용자는 원래 값을 돌려받는다. 상류 로그에는 가짜 값이 남는다(상류 운영자는 그것이 대체값인지 알 수 없다 — 의도된 선택).
- **원문은 저장하지 않는다.** 가짜 값과 원래 값의 대응은 요청 하나의 메모리에만 있고 응답이 끝나면 버린다. 감사 로그에는 크기와 지문만 남는다.
- **같은 원문은 언제나 같은 가짜 값이 된다.** 가짜 값은 대체값 키(`GATEWAY_SURROGATE_KEY`)로 정해지므로 다음 턴 이력에 다시 와도 바이트가 같다 —
  프롬프트 캐시와 Anthropic thinking 서명이 깨지지 않는다.
- **인젝션은 기본으로 막지 않는다.** 룰은 정규식 둘이고 정상 문장("ignore the instructions in the PDF and summarize")도 걸린다.
  적중은 감사에 남고(`would_block`), 운영자가 `GATEWAY_INJECTION=block`으로 켠다.

바로 보기: `python3 web/app.py`(브라우저 비교 화면) 또는 `python3 scripts/demo.py`(터미널) — Docker·외부 공급자 없이 여섯 장면을 보여 준다(3절).
아래는 웹 화면 기록이다(대체값 도입 전의 GIF라 "상류가 실제로 받은 것"에 가짜 값 대신 `[PII:…]` 토큰이 보인다).

![데모 — 게이트웨이 없음 vs 있음](docs/demo.gif)

---

## 2. 막지 못하는 것

- **형식이 없는 개인정보·기밀.** 탐지는 주민등록번호·카드번호·전화번호(국내·국제 `+국가번호`·괄호 지역번호)·이메일, 그리고 접두사가 고정된 키
  (OpenAI·Anthropic·AWS·GitHub·Google·Slack)·JWT·PEM 개인 키뿐이다. 이름·주소·계좌번호·여권·운전면허·IBAN·서술형 민감정보는 그대로 나간다.
- **비텍스트**(이미지·PDF 원본)와 텍스트가 아닌 블록은 보지 않는다.
- **사고 과정에는 가짜 값이 보인다.** Anthropic thinking과 Responses reasoning 요약은 상류가 서명한 그대로 돌려주므로(바꾸면 다음 턴이 거절되고, 복원하면 원래 값이
  다음 턴에 thinking에 담겨 상류로 간다) 그 안에서는 가짜 값이 보인다.
- **룰이 모르는 공격.** 인젝션 룰은 알려진 영어 문구에만 듣는다. 동의어·인코딩·역할 헤더 위조는 잡지 못하고, 한국어 공격 탐지율은 잰 적이 없다.
- **출력 방향.** 모델이 새로 내보낸 개인정보는 사용자에게 그대로 간다.
- **대체값 복원 실패는 조용하다.** 모델이 가짜 값을 알아볼 수 없게 바꿔 쓰면(구분자·대소문자 변경은 복원된다) 사용자는 가짜 값을 받는다.
  응답 헤더 `x-gateway-pii: issued=N restored=M`, 감사의 `pii_issued`·`pii_restored`·`pii_suspect`, 지표 `gateway_pii_suspect_total`(남은 가짜 값 + 가짜 값의
  끝 4자리·이메일 로컬파트만 나타난 경우)로 보인다. 가짜 이메일은 예약 도메인(`example.com`·`.net`·`.org`)이라 실제 주소가 되지 않지만,
  **가짜 휴대전화 번호는 실제로 쓰이는 번호일 수 있다** — 국내에는 공식 가상 번호 대역이 없다. 복원에 실패하면 사용자가 제3자의 번호를 받을 수 있다.
- **세 API와 `GET /v1/models` 밖의 공급자 기능**(파일·임베딩·배치·`count_tokens` 등)은 게이트웨이로 쓸 수 없다(404).
- **요청 간 연결.** 같은 대체값 키 아래 같은 원문은 늘 같은 가짜 값이라, 공급자 로그에서 같은 값을 담은 요청끼리 이어 볼 수 있다. 키를 바꾸면 끊긴다.
  키와 가짜 값이 함께 있으면 전화번호처럼 공간이 작은 값은 되짚을 수 있으므로 키는 공급자 키와 같은 등급으로 보관한다.
- **운영 제약.** 레이트리밋·지표는 워커(프로세스)별이다. 클라이언트 키는 이름일 뿐 권한 구분이 없다. Responses API의
  `previous_response_id`처럼 상류에 저장된 대화는 게이트웨이가 볼 수 없고 복원하지 못한다.

---

## 3. 실행

Python 3.12 이상이 필요하다.

```bash
git clone <이 저장소>
cd llm-security-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

테스트와 lint — 가짜 상류를 쓰므로 외부 공급자·Docker가 필요 없다. 테스트 데이터는 전부 합성이다.

```bash
pytest -q
ruff check .
```

한 명령 데모 — 스텁 상류와 게이트웨이를 임시 포트에 띄우고, 여섯 장면(개인정보·API 키·assistant 이력·이번 턴 차단·이력 가림·413)에서
상류가 받은 것과 사용자가 받은 것을 나란히 보여 준다.

```bash
python3 scripts/demo.py
```

브라우저 비교 화면 — 같은 요청을 게이트웨이 없음·있음에 나란히 보내고, 상류가 실제로 받은 것·사용자가 받은 답·감사 한 줄을 보여 준다.
기본은 스텁 상류이고, 있음 쪽만 실제 공급자로 바꿀 수 있다(`WEB_ON_TARGET=https://api.anthropic.com WEB_ON_MODEL=claude-opus-5-5`,
키는 `ANTHROPIC_API_KEY`). 없음 쪽은 언제나 스텁이고, 실제 공급자 모드에서는 인젝션 프리셋이 꺼진다 — 외부 공급자에 공격 문장을 보내지 않는다.

```bash
python3 web/app.py
```

직접 띄워 보기 (터미널 둘):

```bash
uvicorn tests.stub_target:app --port 8000
```

```bash
GATEWAY_CLIENT_KEYS=demo=demo-key GATEWAY_SURROGATE_KEY="$(python3 -m gateway keygen)" TARGET_URL=http://localhost:8000 \
  uvicorn gateway.main:app --port 8080
```

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Authorization: Bearer demo-key' -H 'Content-Type: application/json' \
  -d '{"model":"stub-model","messages":[{"role":"user","content":"제 번호는 010-2345-6789입니다"}]}'
```

실제 공급자 앞에 두기 — 공급자 키는 게이트웨이 환경변수 한 곳에만 있고, 클라이언트는 게이트웨이 키를 쓴다(`python -m gateway keygen`으로 만든다).

```bash
GATEWAY_CLIENT_KEYS="app=$(python3 -m gateway keygen)" GATEWAY_SURROGATE_KEY="$(python3 -m gateway keygen)" \
  GATEWAY_UPSTREAM_KEY=sk-ant-... TARGET_URL=https://api.anthropic.com uvicorn gateway.main:app --port 8080
```

클라이언트는 `base_url`을 `http://localhost:8080`(Anthropic SDK) 또는 `http://localhost:8080/v1`(OpenAI SDK)로, `api_key`를 게이트웨이 키로 바꾼다.
공식 SDK로 확인하려면 SDK를 별도 venv에 깔고 그 파이썬을 넘긴다: `python3 scripts/check_openai_sdk.py --sdk-python <openai가 깔린 파이썬>`,
`python3 scripts/check_anthropic_sdk.py --sdk-python <anthropic이 깔린 파이썬>`.

Docker — 비root(uid 10001)로 돌고, 감사 로그는 stdout으로 나간다. 워커 수는 `WEB_CONCURRENCY`(기본 1), 프록시 뒤에 두면
신뢰할 프록시 주소를 `FORWARDED_ALLOW_IPS`로 준다(기본 127.0.0.1 — 그 밖에서 온 `X-Forwarded-For`는 무시된다).

```bash
docker build -f gateway/Dockerfile -t llm-security-gateway .
docker run -p 8080:8080 -e GATEWAY_CLIENT_KEYS=... -e GATEWAY_SURROGATE_KEY=... -e GATEWAY_UPSTREAM_KEY=... -e TARGET_URL=... llm-security-gateway
```

---

## 4. 설정 — 환경변수

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `TARGET_URL` | `http://localhost:8000` | 상류(공급자) 주소. Chat Completions의 상류 경로만 `GATEWAY_CHAT_UPSTREAM_PATH`로 바꿀 수 있다(Gemini) |
| `GATEWAY_CLIENT_KEYS` | (없음 — **기동 실패**) | 클라이언트 키 `이름=키,이름2=키2`. `Authorization: Bearer`나 `x-api-key`로 낸다. 로컬 실험만 `GATEWAY_AUTH=off` |
| `GATEWAY_UPSTREAM_KEY` | (없음) | 공급자 키. 상류 형식으로 단다 — `/v1/messages`와 `anthropic-version`을 보낸 요청은 `x-api-key`, 그 밖은 `Bearer`. `GATEWAY_AUTH=off`와 함께 쓰면 기동 실패 |
| `GATEWAY_ADMIN_KEY` | (없음) | `/__gateway/info`·`/__gateway/metrics`를 여는 관리 키(`Authorization: Bearer`). 없으면 둘 다 404 |
| `GATEWAY_SURROGATE_KEY` | (없음 — mask 모드면 **기동 실패**) | 결정적 대체값 키(32자 이상, `python -m gateway keygen`). 바꾸면 진행 중인 대화는 다음 턴에 이력 바이트가 바뀐다(캐시 미스 한 번) |
| `GATEWAY_PII` | `mask` | `mask`(대체값으로 바꾸고 응답에서 복원) · `detect`(감사에만) · `off`. 종류는 `GATEWAY_PII_KINDS`(기본 `rrn,card,phone,email,secret`), 역할은 `GATEWAY_PII_ROLES`(기본 `user,assistant,tool,system`, `developer`는 system) |
| `GATEWAY_INJECTION` | `observe` | `observe`(적중을 감사에만, `would_block`) · `block`(이번 턴이 걸리면 차단, 이력의 걸린 턴은 가림) · `off` |
| `GATEWAY_MAX_BODY_BYTES` | 1MiB | 넘으면 검사기·상류를 부르지 않고 413 |
| `GATEWAY_MAX_FINDINGS` | 5000 | `mask` 모드에서 한 요청의 탐지 상한. 넘으면 대체값을 하나도 만들지 않고 413(`too_many_findings`), 상류 없음 |
| `GATEWAY_MAX_CONNECTIONS` | 100 | 상류 연결 풀 크기. 풀이 차서 5초 기다리면 503 + `retry-after: 1`(`upstream_busy`) |
| `GATEWAY_RATE_PER_MINUTE` | 0(끔) | 클라이언트(무인증이면 IP)마다 분당 상한. 넘으면 429 + `retry-after`, 상류 없음 |
| `GATEWAY_TIMEOUT` | 600 | 상류 읽기 대기(초). 연결 5초·쓰기 30초·풀 대기 5초는 고정. 대체값 매핑은 이보다 60초 더 산다 |
| `GATEWAY_LOG_PATH` | `logs/gateway.jsonl` | 감사 로그. `-`면 stdout. 파일이면 `GATEWAY_LOG_MAX_BYTES`(100MiB)·`GATEWAY_LOG_BACKUPS`(5)로 회전 |
| `GATEWAY_DETECTORS` | (없음) | 저수준 검사기 목록(쉼표). **설정돼 있으면 위 PII·INJECTION 설정을 무시한다** — 테스트용. 빈 값은 검사기 없음 |

- 처리 순서: 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 파싱(400) → 인젝션 → PII → 상류 → 복원 → 감사 한 줄. 401·429·413은 본문을 검사하지도 중계하지도 않는다.
- 차단(`block` 모드)은 HTTP 200의 정상 응답으로 돌려준다 — Chat `finish_reason=content_filter`, Messages `stop_reason=refusal`, Responses `status=incomplete`(`content_filter`),
  모두 `gateway_blocked: true`와 문구 끝의 `(요청 ID: …)`. 사유는 넣지 않는다(감사에만). 상류는 부르지 않는다.
- 스트리밍(`stream: true`)은 상류 SSE를 조각마다 흘려보내며 채널(텍스트·도구 인자·content block)마다 조각 경계에 걸린 대체값을 복원한다.
  감사 줄은 스트림이 끝난 뒤 한 줄. 스트리밍의 `x-gateway-pii`에는 발급 수만 있다(복원 수는 감사에). 오류(400·401·404·413·429·502·503·504)는 스트리밍 요청에도 JSON이고 형식은 API를 따른다(Messages는 Anthropic 오류 형식).
  503은 상류 연결 풀이 찼거나(`upstream_busy`) 진행 중인 대체값 세션이 상한(워커당 2,000)에 닿았을 때(`gateway_busy`)다 — 둘 다 `retry-after: 1`.
  비스트리밍 상류 응답이 32MiB를 넘으면 502(`upstream_response_too_large`).
- 상류로 넘기는 요청 헤더는 `content-type` `accept` `user-agent` `anthropic-version` `anthropic-beta` `openai-beta` `idempotency-key`뿐이다.
  클라이언트의 인증 헤더는 `GATEWAY_AUTH=off`일 때만 넘긴다(켜져 있으면 그것은 게이트웨이 키다). 공급자 키가 없으면 `openai-organization`·`openai-project`도 넘긴다.
  클라이언트로 넘기는 응답 헤더는 `content-type` `cache-control` `retry-after` `retry-after-ms` `x-should-retry`와 게이트웨이의 `x-gateway-request-id`뿐이다.
  상류 요청 ID는 감사 줄 `upstream_request_id`에 남는다. 상류 쿠키는 저장하지도 보내지도 않는다.
- `/__gateway/health`는 인증 없이 `{"status": "ok"}`만 준다. 버전·코드 지문·상류·검사기는 `/__gateway/info`, Prometheus 지표(요청·차단·마스킹·복원·잔여·지연)는
  `/__gateway/metrics` — 둘 다 `GATEWAY_ADMIN_KEY`가 있어야 보인다.

---

## 5. 구조

```
gateway/    프록시 본체(main) · 인증(auth) · API 어댑터(api/: chat·anthropic·responses) · 검사기(detectors/) ·
            대체값(surrogate)·볼트(vault)·스트리밍 복원(streaming) · 감사 로그(audit)·지표(metrics)·레이트리밋(ratelimit)
  data/       injection_corpus.jsonl — 인젝션 룰 회귀 테스트 입력
web/        데모 웹 — 브라우저 비교 화면
scripts/    터미널 데모 · OpenAI·Anthropic SDK 점검
tests/      단위·통합 테스트 + 스텁 상류(tests/stub_target.py)
eval/benign/all100.jsonl   정상 질문 100문항 — 인젝션 룰 오탐 회귀 테스트 입력
```

---

## 6. 라이선스

[Apache-2.0](LICENSE).
