# 변경 기록

## 0.2.0 — 2026-11-10

- 릴리스 공정(D-130): 태그 `v<버전>`을 푸시하면 `.github/workflows/release.yml`이 태그 = `pyproject.toml` 버전 = 이 파일의 절을 확인한 뒤 이미지 둘
  (`ghcr.io/<owner>/llm-security-gateway`·`llm-security-gateway-detect`, 태그 `<버전>`·`latest`)을 빌드 → Trivy 취약점 스캔(HIGH·CRITICAL 전부를 표로 남기고, 고칠 수 있는 것이 하나라도 있으면 **아무것도 올리지 않는다**) → SBOM(syft, SPDX JSON) →
  GHCR에 버전 태그 푸시 → cosign keyless 서명과 SBOM 증명 → `latest` → GitHub 릴리스(이 절 + 이미지 다이제스트 + 검증 명령, SBOM 첨부 — `scripts/release_notes.py`). 작업은 셋이다 — build(서드파티 코드 없음, 이미지 파일의 SHA-256을 작업 출력으로) → scan(스캐너, 읽기 권한뿐) →
  publish(푸시·서명 권한 — 해시가 맞는 이미지 파일만 올리고, 받은 파일은 작업 폴더 밖에 푼다). 액션은 커밋 SHA로 고정했다. 탐지 사이드카 이미지에 내장 모델의 라이선스 고지(`/licenses/`, Horizon 모델의 LICENSE·NOTICE)를 싣는다.
  검증 방법은 [운영 — 업그레이드](docs/operations.md#업그레이드). dependabot(pip·github-actions·docker, 주마다 — PR은 제안), CI `secrets` 작업(gitleaks, 푸시·PR 범위 —
  `.gitleaks.toml`은 합성 키 경로 `eval/`·`tests/`와 `detect/models.json`의 SHA-256만 허용). 이미지는 linux/amd64만. k8s 견본의 이미지 태그 0.2.0, 사이드카 포트(8081)를 막는 NetworkPolicy 견본(`deploy/k8s/networkpolicy.yaml`)
- 실 공급자 확인 2 준비(D-133): 실제 GPT·Gemini·Claude 모델 앞에서 가림·복원(되풀이·스트리밍·도구 인자·2턴)을 보는 `scripts/check_real_providers.py` — 상류는 여러 공급자를 한 키로 부르는 라우터. 기준·상한(요청 90건)을 사전 등록했고
  `--stub`으로 세 API × 네 검사의 배선을 확인했다. **실제 실행은 아직 하지 않았다**(등록 커밋 뒤)
- v1.0 기준의 자와 가격 초안(D-132): `scripts/poc_gate.py` — 감사 로그에서 mask로 돈 구간(14일 이상, 빈 날 없이)의 의심 잔여 비율과 게이트웨이 몫 실패 비율(5xx + 스트림 도중 실패, 상류 장애·클라이언트 끊김 제외)을 재서 각각 0.1% 미만인지 판정한다
  (분모 1,000건 미만은 판정 불가). `docs/pricing.md`(초안 — 코드는 전부 Apache-2.0, 유료는 배포 단위 연간 지원 계약)

- 공개 데모(D-131, 선택): 비교 데모 웹(`web/app.py`)에 **공개 모드** `WEB_PUBLIC=1` — 상류는 두 팔 모두 스텁 고정(`WEB_ON_TARGET`·`.env`를 읽지 않는다), `/api/chat` 본문 8,192바이트 상한(413 — 게이트웨이 팔의 4,096보다 커서 '너무 큰 본문' 장면이 게이트웨이의 413까지 간다)·본문 5초 기한(408),
  방문자별·전체 분당 요청 상한(429 — `WEB_RATE_PER_MINUTE` 20·`WEB_RATE_TOTAL_PER_MINUTE` 300, 방문자 주소는 `WEB_CLIENT_IP_HEADER`), 한 번에 한 요청(동시에 쓰는 방문자가 서로의 글을 '상류가 받은 것'으로 보던 것을 막는다 — 재현 24팔 중 19팔),
  요청이 끝나면 스텁의 수신 기록 삭제, 감사 로그 1MiB 상한. 데모 이미지 `web/Dockerfile`(공개 모드 기본·비root), Fly.io 견본 `deploy/demo/fly.toml`. 로컬 데모(`python3 web/app.py`)는 그대로다
- 보안 백서 + 법적 위치 메모 + PoC 키트(D-129): `docs/security-whitepaper.md`(데이터 흐름·저장하지 않는 것·대체값 키·위협 모델·한계, 숫자마다 결정 번호),
  `docs/legal-position.md`(PIPA 가명처리와의 관계 — **변호사 검토 전 초안**, 확인 항목 8), `scripts/poc_report.py`(고객 샘플 JSONL → 종류별 탐지 수·오탐 후보(값의 모양)·복원률·처리 시간 리포트,
  원문·가짜 값은 리포트에 넣지 않는다). 리뷰 반영(2026-11-10): 백서의 틀린 주장 수정 — **가짜 전화·카드·주민번호 꼴은 실제 값과 겹칠 수 있다**(예약 대역은 이메일뿐), 볼트 상한은 새 요청 거절,
  키 회전은 복원을 깨지 않는다, 감사 줄에는 탐지 위치·길이도 있다, 웹훅은 가리지 않는 종류를 원문으로 받는다. 메모의 제28조의4 항 번호·적용 한정과 단정 표현, 확인 항목 8개. 리포트의 '모양'은 허용한 글자만 그대로 낸다
- 인젝션 분류기 한국어 이어 학습(D-128): `Horizon-Labs/prompt-injection-guard-small`을 한국어 중심 학습 데이터 13,932행으로 이어 학습한 `injection-ko-small-int8`(INT8 268MB, 운영 문턱 0.9833)이 사전 등록한 네 게이트를 넘어 **채택** —
  봉인 홀드아웃(두 번째 개봉) 한국어 공격 97.5%(이미지에 든 공개 모델 guard-base는 61.7%)·영어 93.8%, 정상 오탐은 한국어 1.5%(경계)·영어 5.3%·전체 2.3%(문턱은 개발셋 오탐 1%로 고른 값 — 홀드아웃 오탐을 1%로 맞추면 한국어 90.6%·영어 84.1%),
  D-054 양성대조 최대 0.7%(guard-base는 8.9% — 기저 셋이 다르다). 학습 쪽을 뺀 dev(dev-eval)는 한국어 85.9%. 리뷰 반영(2026-11-10): 올릴 폴더에 기준 모델의 LICENSE·NOTICE, `tokenizer.json`은 기준 모델 파일 그대로(학습 길이 256이 박혀 있었다),
  manifest에 커밋 전 변경 여부와 스크립트 해시, `train_log.json`의 절대 경로 제거, `detect.train`의 인자 검증·실패 시 중단, `detect.fetch`가 아직 올리지 않은 모델을 알려 줌.
  **관측 기간 뒤 `block`에 써도 된다**. 이미지 기본값은 Hugging Face에 올린 뒤 바꾼다(그때까지 `models.json`에 `published: false`). 학습 데이터 빌더 `eval/injection/train/build.py`(dev의 학습 쪽 절반 + 평가셋이 쓰지 않은 공개 행 + 에이전트 작성 한국어 정상 543 +
  결정적 변형 7종·판정 조작 꼬리 12종 — 평가 그룹과 그룹·문장이 겹치지 않고 D-054 문구는 쓰지 않는다, `tests/test_d128_train.py`), 학습 스크립트 `detect/train.py`(따로 둔 가상환경 `detect/requirements-train.txt`, 기준 모델 safetensors 항목 `horizon-guard-base-src`·`-small-src`,
  safetensors → ONNX → INT8(Gather만) → manifest·모델 카드, M2 CPU 25분), 평가 `detect.evaluate_injection --exclude-train`(dev-eval). base(308M) 이어 학습은 GPU 기계 몫으로 남았다.
- 인젝션 분류기 + 가드레일 웹훅(D-127): 게이트웨이가 이번 턴의 사용자 글·도구 결과·첨부 문서(공급자에게 갈 것과 같은 텍스트 — 체인의 마지막이라 정책이 가리는 종류만 가짜 값)를 웹훅에 보내 판정을 받는다 —
  `GATEWAY_GUARD=off|observe|block`(기본 `off`, 정책 키 `guard`)·`GATEWAY_GUARD_URL`·`GATEWAY_GUARD_TIMEOUT`(5초)·`GATEWAY_GUARD_FAIL`(`open` 기본 / `closed` — block에서 503 `guard_unavailable`).
  계약 `POST {"texts": [{"role","text"}]}` → `{"verdict": "allow"|"block", "score"}`. 관측은 감사 줄에 `guard_verdict`·`guard_score`(block 판정이면 `would_block`, 결과 `observed`/`injection_guard`),
  차단은 룰 차단과 같은 200 차단 응답(`injection_guard_block`). 지표 `gateway_guard_errors_total{reason}`, stats `guard_errors`, 대시보드 줄 `guard`, `/__gateway/info`의 `guard`.
  탐지 사이드카에 작업 `injection`(`Horizon-Labs/prompt-injection-guard-base` INT8, 512토큰 창 최댓값, 텍스트 점수 캐시)과 `POST /v1/guard`를 더했다 — 다섯 후보를 평가셋 v1로 재서 골랐다
  (정상 오탐 1% 문턱에서 봉인 홀드아웃 한국어 61.7%·영어 55.1%, 룰은 dev 한국어 5.9%). 판정 조작 문구 양성대조에서 8.9%가 뒤집혀(기준 5%) **관측 전용**으로 권한다.
  분류기는 이미지에 들어 있지만 기본으로 싣지 않는다(`DETECT_INJECTION_MODEL`로 켠다 — 사이드카 메모리 약 +1.2GiB).
  평가 도구 `detect/evaluate_injection.py`(깨끗한 부분집합·D-054 양성대조), PG2 비교용 `detect/export.py`. compose·k8s 견본은 켜는 방법만 적었다(기본 꺼짐).
  지표 `gateway_guard_verdicts_total{verdict}`, 웹훅 응답의 선택 키 `unscored`(재지 못한 텍스트 — block이면 막음).
  **가림 범위를 넓혔다**: Anthropic `document`의 내용 원본·`title`·`context`, `search_result`, `tool_result` 안의 문서·검색 결과도 가린다(전에는 원문 그대로 나갔다).
  깊게 중첩된 JSON 요청은 500이 아니라 400 `invalid_json`.
  **바뀐 것**: 사이드카 이미지가 분류기 모델도 받는다(`ARG INJECTION_MODEL`), `python -m detect.fetch`는 이름을 꼭 받는다
- 이름·주소 가림(D-126, 정책에서 켬): PII 종류 `person`·`address`·`org`를 더했다 — 정규식이 아니라 탐지 사이드카(`detect/`, 한국어 NER `1T/veil-pii-ko-lite` INT8)가 찾는다.
  **기본은 꺼짐**(`GATEWAY_PII_KINDS` 기본은 정규식 12종 그대로) — 정책 `pii_kinds`에 `person,address`를 더하고 `GATEWAY_DETECT_URL`을 주면 켜진다(없으면 기동 실패). `org`는 기본 감사만.
  새 환경변수 `GATEWAY_DETECT_URL`·`GATEWAY_DETECT_TIMEOUT`(10초)·`GATEWAY_DETECT_FAIL`(`closed` — 503 `detect_unavailable`·`open`). 가짜 이름은 성 + 이름(받침 부류 유지), 가짜 주소는 시·도·시·군·구 유지,
  복원은 발급한 문자열 찾기(공백 변형 포함), 이력은 캐시(텍스트 해시)로 사이드카에 다시 가지 않는다. 겹치면 정규식 우선, 시·도만인 주소는 감사만. 감사 `ner_ms`·`ner_error`, 대시보드 종류 15.
  compose에 서비스 `detect`, k8s 견본에 같은 파드의 둘째 컨테이너. 지표 `gateway_detect_errors_total{reason}`·stats `detect_errors`·대시보드 줄 `ner_error`(사이드카 실패 — `open`에서는 이것만이 신호).
  **바뀐 기본값**: `GATEWAY_PII_DETECT_KINDS` 기본에 `org`가 더해졌다(켜지 않으면 영향 없음)
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
- 탐지 사이드카·한국어 NER 게이트(D-125): `detect/` — 게이트웨이와 따로 도는 컨테이너(ONNX Runtime + tokenizers, `POST /v1/detect`·`GET /health`, 원문 무기록, 모델 리비전·SHA-256 고정, 이미지 `detect/Dockerfile`). NER 평가셋 `eval/ner/`(합성 200문장·KDPII test 4,799행)와 점수, x86 지연 측정 워크플로(`.github/workflows/detect.yml`). 후보 45개를 조사해 다섯을 쟀으나 게이트(x86 512토큰 이하 p95 ≤ 40ms·F1 ≥ 0.85)를 넘은 모델이 없어 **이름·주소 탐지는 v1.0에 넣지 않는다** — 게이트웨이 동작은 바뀌지 않았다

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
