# 변경 기록

## 미출시

- 쉽게 읽는 제품 설명서(`docs/overview/LLM보안게이트웨이_제품설명서.pdf`, 원본 `overview.html`): 앱·웹이 아닌 자체 설치형 서버라는 점, 지켜 주는 범위, 구조·요청 흐름 그림, 시나리오 6개와 오류 표, 화면 A~E(비교 데모·대시보드 예시·감사 줄·설정 파일), 도입 4단계, 한계, 숫자, 진행 상황과 v1.0 모습, FAQ·용어 풀이
- 실 공급자 2턴 확인(D-114): Claude(`claude-haiku-5-5`) 앞에서 둘째 턴이 thinking 서명 검사 400 없이 프롬프트 캐시를 읽었다 — 요청마다 난수였던 옛 코드는 5/5가 400
  (`docs/verification/multiturn_claude.md`, `scripts/check_multiturn_claude.py`)
- PII 평가 코퍼스와 CI 게이트(D-115): 합성 양성 500·음성 1,000·어려운 사례(`eval/pii/`), 종류별 재현율·오탐률과 Wilson 구간(`score.py`), `tests/test_pii_corpus.py`
- 정규화(D-116): 전각 숫자·문자·제로폭·서식 문자·대시 변형을 정규화해 탐지하고 원문 위치에 가짜 값을 넣는다(복원은 원문 그대로). 인젝션 룰도 정규화한 텍스트를 본다
- 오탐 축소(D-116): 구분자·문맥어 없는 약한 주민번호와 발급사 범위(국내 전용 9 포함) 밖 카드 꼴은 감사(`unmasked`)에만 남기고 가리지 않는다 —
  합성 업무 문장 오탐 12.3% → 0.3%
- 한국 식별자(D-117): 외국인등록번호(`frn`, 주민번호에서 분리)·여권·운전면허를 가리고, 사업자·법인등록번호·계좌번호·IPv4는 탐지해 감사에 남긴다
  (`GATEWAY_PII_DETECT_KINDS`, 기본 `account,brn,crn,ipv4`). 인터넷 전화 070. 종류 설정의 모르는 이름은 기동 실패. 코퍼스에 양성 700·음성 200, README에 종류별 커버리지 표
- 설정 객체화(D-118): `Settings.from_env`·`create_app(settings)`, `main.py`를 설정·중계·감사 줄 모양으로 나눔. `.env`를 스스로 읽지 않는다(`uvicorn --env-file .env`).
  **지운 설정**: `GATEWAY_INJECTION_SCOPE`(차단은 늘 이번 턴), `GATEWAY_CHAT_UPSTREAM_PATH`, `GATEWAY_DETECTORS`. `/__gateway/info`에서 `chat_upstream_path`가 빠졌다.
  테스트는 게이트웨이를 프로세스 안에서 띄운다(69초 → 18초), CI에 mypy
- 설정 파일(D-119): `GATEWAY_CONFIG`(TOML) — 클라이언트별 정책(`[policies.*]` 인젝션·PII·허용 모델), API별 상류(`[upstreams.chat|responses|messages]`,
  공급자 키는 `key_env` 환경변수)로 OpenAI와 Anthropic을 한 게이트웨이에서. 클라이언트 키는 SHA-256으로만 든다(`keygen --hash`). 허용 모델 밖은 403 `model_not_allowed`.
  info·감사 줄에 설정 버전(`config`)과 정책(`policy`). `scripts/check_sdks.py`(한 게이트웨이에 두 SDK)
- 관측(D-120): 감사 줄에 `model`·`usage`(입력·출력·캐시 토큰, 스트리밍 포함 — Chat 스트림은 `include_usage`를 넣어 받고 클라이언트가 요청하지 않았으면 그 조각을 뺀다),
  응답에 새로 나온 PII 수 `pii_new`·`gateway_pii_new_total`(가리지 않음), 상류 요청 헤더 `x-gateway-request-id`. 문구 카탈로그 `GATEWAY_LANG=ko|en`
  (차단 문구·가린 이력 자리표시·기동 거부·설정 오류)
- 배포·문서(D-121): `deploy/compose.yml`(로컬 체험 — 게이트웨이 + 스텁 상류), `deploy/k8s/`(kustomize — Deployment 레플리카 2·Service·PodDisruptionBudget,
  설정 파일 ConfigMap·키 Secret 생성기라 바꾸고 apply하면 롤링 재시작, Pod Security `restricted`), 문서 `docs/configuration.md`·`docs/operations.md`(키 회전·로그·지표·용량)·
  `docs/api-compat.md`·`SECURITY.md`·`README.en.md`, 문서와 코드의 환경변수·설정 키를 맞추는 테스트, CI에 배포 견본 검사(compose 문법·kustomize 렌더·k8s 스키마).
  **바뀐 동작**: 설정 파일 `key_env`가 가리키는 환경변수가 비어 있어도 기동 실패(예전에는 키 없이 보내 요청마다 상류 401). README의 설정 표는 `docs/configuration.md`로 옮겼다
- 부하·안정성(D-122): `scripts/load.py`(지연을 넣은 스텁 앞에서 스트리밍·비스트리밍 동시 부하 — 지연 백분위·복원·교차 누출·RSS·열린 파일·대체값 세션), 지표 `gateway_vault_sessions`.
  **상류 연결 풀 교체**: httpx 클라이언트 하나를 함께 쓰던 것을 연결 하나짜리 클라이언트를 빌려 쓰는 풀로 바꿨다 — httpcore 1.0.9가 동시 요청을 같은 유휴 연결에 겹쳐
  배정해, 동시 100(스트림 50 + 비스트리밍 50)에서 초당 60건에 머물고 p95가 4초를 넘었다. 이제 초당 223건이고 게이트웨이 경유 지연이 스텁 직접과 같다.
  상류의 쉬는 연결은 4초 뒤 버린다(상류 서버 keep-alive 5초와의 경합 502). 풀이 찬 503의 감사 `error`는 `PoolTimeout` 대신 `upstream_busy`.
  k8s 견본은 `UVICORN_TIMEOUT_KEEP_ALIVE=75`(인그레스·LB 유휴 시간보다 길게)
- 리뷰 수정(D-122 §6, 다차원 리뷰 + 반박 검증 35건): 상류 연결 풀이 요청을 만들다 실패해도(한국어 User-Agent 등) 연결을 돌려준다 — 돌려주지 않아 연결 100개를 잃으면
  모든 요청이 503이었다. 요청·응답 헤더는 받은 바이트 그대로 넘긴다(비ASCII 값이 500이던 것). 풀은 먼저 온 요청부터 받고, 첫 연결은 기동 때 만든다(클라이언트 생성 오류는 기동 실패).
  클라이언트가 끊은 스트림은 감사 `error: ClientDisconnect`(예전에는 정상 200처럼 남았다), 끊김·취소 중에도 상류 닫기·대체값 세션 해제·감사 한 줄을 끝까지 한다.
  본문 상한 413의 감사 `error: request_too_large`, `/v1/messages`의 500은 Anthropic 형식, 키 값의 앞뒤 공백을 뗀다. 지표 `gateway_vault_sessions{policy}`(정책마다)·
  `gateway_upstream_connections_in_use{upstream}`. k8s 종료 유예 35초(여유 5초), 만든 ConfigMap·Secret에 레이블(키 회전 뒤 옛 Secret 정리)
- 인젝션 평가셋 v1(D-123): `eval/injection/` — 공개 데이터셋 13개(한국어 5)·한국어 업무 문장과 하드 네거티브 717(에이전트 작성, 두 검증자 확인)·기존 한국어 코퍼스와 결정적 변형으로
  6,871행(dev 5,492·봉인 홀드아웃 1,379 — 같은 원문의 번역·합성·팀까지 한 그룹으로 나눔). `build.py`(고정 리비전, 결정적, 바이트 재현), `score.py`(재현율·오탐률·Wilson 95%·recall@FPR,
  언어·유형·출처별), `SOURCES.md`(출처·라이선스·고지). 지금 룰의 기준선: 재현율 8.7%(한국어 5.9%), 오탐률 2.7% — README '막지 못하는 것'에 적었다
- 운영 대시보드(D-124): `GET /__gateway/dashboard` — 요청마다 가림·차단·거절 결과와 사유, 타일 8개, 종류별 가린 수, 최근 200줄을 2초마다 보여 주는 읽기 전용 화면
  (한 파일, 외부 자원 없음, CSP 해시). 관리 키가 설정된 게이트웨이에만 있고, 키는 탭의 `sessionStorage`에만 둔다. 데이터는 `GET /__gateway/stats`(관리 키 —
  형식이 바뀔 수 있으니 수집은 metrics로). `scripts/traffic.py`(합성 시험 트래픽 16장면을 보내고 대시보드의 줄과 대조), 지표 `gateway_outcomes_total{outcome,reason}`·
  `gateway_pii_unmasked_total{kind}`. `scripts/load.py`·`web/app.py`가 기동 때 대시보드 주소와 관리 키를 찍는다.
  **바뀐 점**: `gateway_pii_masked_total`은 실제로 가린 것만 센다 — detect 정책의 찾은 수가 빠진다(그 수는 `gateway_pii_unmasked_total`).
  감사 `error`가 파싱 400(`invalid_json`·`invalid_messages`·`invalid_request`·`invalid_stream`)과 허용 목록 밖 404·405(`not_found`)에도 붙는다.
  스트림 도중 AI 회사가 보낸 오류 이벤트는 감사 `error: upstream_stream_error`(예전에는 정상 200처럼 남았다).
  Responses 스트림의 감사 `pii_restored`·`gateway_pii_restored_total`은 복원한 자리마다 한 번 센다 — 전에는 조각·`*.done`·`response.completed`에서
  되풀이해 최대 5배로 셌다(이제 비스트리밍과 같은 수다). 인증 실패(401) 감사 줄의 `policy`는 null(전에는 `default`, 인증을 끈 게이트웨이의 줄은 그대로 `default`).
  `gateway_upstream_connections_in_use`는 주소가 같고 `timeout`이 다른 풀이 있으면 합이 아니라 가장 바쁜 풀의 값이다(상한이 풀마다 따로다).
  **보안**: FastAPI 기본 문서 경로(`/docs`·`/redoc`·`/openapi.json`·`/docs/oauth2-redirect`)를 없앴다 — 인증 없이 200이었고, `/docs`는 CDN 스크립트를 읽고
  `/openapi.json`은 관리 경로까지 나열했다(D-109 허용 목록 위반). 끝에 `/`가 붙은 경로(`/v1/chat/completions/` 등)는 307 리다이렉트(Location은 요청의 Host로 만든다)
  대신 404다. `model`에 짝 없는 서로게이트(`\ud800` 같은 JSON 이스케이프)를 넣은 요청은 감사 줄 없이 처리됐다(D-120부터) — 이제 감사 줄이 남는다.
  그 줄이 최근 200줄에 있는 동안 `/__gateway/stats`가 500이던 것,
  본문 어디든 짝 없는 서로게이트가 있으면 본문을 다시 쓰는 요청(가림·Chat 스트림)과 차단 응답이 500이던 것도 고쳤다(JSON 이스케이프로 보낸다)

## 0.1.0 — 2026-10-30

첫 제품 판. 연구 단계(D-001~D-107)의 마지막 코드(`research-final` 태그, `34c16fb`)를 제품 저장소로 정리했다(D-108).

- OpenAI Chat Completions·Responses, Anthropic Messages 세 API 중계(스트리밍·도구 호출 포함)
- 개인정보·자격 증명을 같은 모양의 가짜 값으로 바꿔 보내고 응답에서 복원(요청 단위 메모리, 원문 무저장).
  가짜 값은 `GATEWAY_SURROGATE_KEY`로 정해지는 결정적 값이라 다음 턴 이력의 바이트가 바뀌지 않는다(D-111)
- 클라이언트 키 인증, 공급자 키는 게이트웨이에만 보관
- 프롬프트 인젝션 룰: 기본 관측, 선택 차단
- 감사 로그(원문 없음)·회전, Prometheus 지표, 레이트리밋
- Apache-2.0 라이선스, `pyproject.toml` 패키징, CI(ruff·pytest·이미지 빌드)
- 보안 경계(D-109): 경로 허용 목록(세 POST + `GET /v1/models`, 그 밖은 404), 요청·응답 헤더 허용 목록, 상류 쿠키 저장 안 함,
  `/__gateway/info`·`/__gateway/metrics`는 관리 키 필요, `GATEWAY_AUTH=off` + 상류 키는 기동 실패, 비root·다이제스트 고정 이미지(uvicorn 접근 로그 끔 — 쿼리 값 누출)
- 마스킹 범위(D-112): 모든 역할(system·developer·도구 결과·RAG 텍스트 문서)을 가린다(`GATEWAY_PII_ROLES`로 좁힘). thinking·reasoning은 요청·응답 모두 손대지 않는다
- 복원(D-113): 도구 인자는 안쪽 JSON 이스케이프로 텍스트 그대로 복원(PEM·개행 값도 인자 JSON이 깨지지 않음, 스트리밍 포함), `x-gateway-pii` 헤더,
  감사 `pii_issued`·`pii_restored`·`pii_suspect`, 지표 `gateway_pii_suspect_total`, 가짜 이메일은 예약 도메인
- 가용성(D-110): 볼트 발급 선형, 탐지 상한 413, 정규식 스레드 오프로드, 상류 풀·타임아웃 분리(503·504), 긴 대체값 스트림 복원, 볼트 용량 503, 응답 32MiB 상한
