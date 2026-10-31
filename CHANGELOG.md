# 변경 기록

## 미출시

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
