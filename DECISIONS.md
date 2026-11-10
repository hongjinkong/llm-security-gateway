# DECISIONS.md — 의사결정 기록

> 모든 결정은 날짜와 근거를 남긴다. 최신이 맨 끝이다.
> 연구 단계의 결정 D-001~D-107(측정·기각·종결·서비스 전환)은 `research-final` 태그에 있다 — `git show research-final:DECISIONS.md`.
> 코드·테스트 주석에 남은 옛 결정 번호와 문서 경로(`docs/…`, `scripts/mutate_*.py`, `SCOPE`, `EVAL` 등)도 그 태그를 가리킨다.
> 실행 순서는 [`PLAN.md`](PLAN.md)를 따른다. 결정마다 근거·결정·버린 대안·완료 기준·한계를 먼저 적고, 끝나면 결과 절을 채운다.

---

## D-108. 제품 저장소로 정리 — 연구 산출물은 `research-final` 태그로, LICENSE·pyproject·CI (2026-10-30, PLAN 1단계)

### 1. 근거

- 추적 파일 약 1.0GB 중 98%가 `results/`(측정 원자료)다. 제품을 받는 사람에게 필요 없는 것이 트리 대부분을 차지한다.
- `LICENSE`가 없어 누구도 합법적으로 쓰거나 고칠 수 없고, `pyproject.toml`이 없어 `pip install`로 설치할 수 없다.
- CI는 `pytest` 한 단계이고, `tests/test_ci_readme_sync.py`가 워크플로 모양을 README와 맞추게 강제해 CI를 넓히면 실패한다.
- 723개 테스트 중 344개는 연구 하네스(측정 실행기·집계기·변이 검사) 검증이다. 제품 코드를 고칠 때마다 이것들을 함께 끌고 간다.

### 2. 결정

1. 이 폴더를 그대로 제품 저장소로 쓴다(PLAN 결정 표 2번). 정리 직전 커밋 `34c16fb`에 주석 태그 `research-final`을 단다.
2. 트리에서 뺀다(태그에 남는다): `results/` `garak/` `target/` `docs/`(README가 쓰는 `docs/demo.gif`만 남김) `eval/`(인젝션 룰 오탐 회귀 테스트가 쓰는
   `eval/benign/all100.jsonl`만 남김) `SCOPE.md` `EVAL_CRITERIA.md` 옛 `DECISIONS.md` `docker-compose.yml` `requirements.txt` `requirements-gateway.txt`
   `.github/workflows/cpu-tests.yml` `gateway/.gitkeep`, `scripts/`는 `demo.py`·`check_openai_sdk.py`·`check_anthropic_sdk.py`만 남긴다.
   연구 하네스 테스트 19개(test_canary test_canary_fn_scan test_canary_k test_ci_junit_check test_ci_readme_sync test_cluster_ci test_d090 test_d094
   test_fpr_link_time test_fpr_report test_matched_baseline test_multiturn_run test_night_chain_oa test_openai_compose test_paired_arms test_rescore_blocking
   test_setup_target test_validate_encoding test_validate_oa_arm)를 뺀다. 제품 테스트 17개 파일과 도우미(`conftest.py`·`stub_target.py`·`chain_app.py`)가 남는다.
   무시된 로컬 데이터(`target/storage/`·`logs/`·`.env`)는 지우지 않고 계속 무시한다.
3. `LICENSE`: Apache-2.0 원문 그대로(오프라인 원문 `packaging-26.2.dist-info/licenses/LICENSE.APACHE`, 첫 줄 `Apache License` / `Version 2.0, January 2004`).
4. `pyproject.toml`: 배포 이름 `llm-security-gateway`, import 이름 `gateway`, 0.1.0, `requires-python = ">=3.12"`, 빌드 백엔드 hatchling(버전 고정),
   런타임 의존성은 옛 `requirements-gateway.txt`의 고정 버전 4개 그대로, `dev` 추가 의존성 `pytest==9.1.1`·`ruff==0.17.3`, pytest `testpaths = ["tests"]`.
   `requirements-gateway.txt`는 지우고 Dockerfile은 `pip install .`로 설치한다.
5. `gateway/version.py`에 `VERSION`(`importlib.metadata`, 설치 안 된 소스 트리면 `0+unknown`)을 두고 `/__gateway/health`에 `version`으로 싣는다. 코드 지문은 그대로.
6. CI `.github/workflows/ci.yml`: Python 3.12·3.14에서 `pip install -e ".[dev]"` → `ruff check .` → `pytest -q`, 별도 잡에서 `docker build -f gateway/Dockerfile .`.
   액션은 옛 워크플로의 SHA 고정을 그대로 쓴다.
7. ruff는 E·F를 켜고 E501(줄 길이)만 끈다. 걸린 7건(쓰지 않는 import 3, 모호한 변수명 `l` 2, 자리표시 없는 f-string 1, 같은 이름 재import 1)은 고친다.
8. README는 제품 중심(무엇을 하나·막지 못하는 것·실행·설정·구조·라이선스)으로 줄이고 연구 수치·측정 장치·코드 지문 문구를 뺀다. `research-final`을 가리키는 한 줄을 둔다.
9. `.env.example`은 제품 변수(`TARGET_URL`·`GATEWAY_CLIENT_KEYS`·`GATEWAY_UPSTREAM_KEY`)만 둔다. `.dockerignore`를 더한다(`.env`·`.git`·`.venv`·로컬 산출물).
   `.gitignore`에 `.claude/settings.local.json`·`*.egg-info/`·`.ruff_cache/`, 연구 로컬 데이터 `target/`를 둔다.
10. `CHANGELOG.md`(0.1.0). `PLAN.md`와 `.claude/commands/next-step.md`를 추적한다.

### 3. 버린 대안

- **새 히스토리의 제품 저장소**: 메모리·원격·CI 연속성이 끊긴다. 클론 크기 문제는 PLAN 조건부 표('공개 출시 직전 클론 크기가 문제')로 미룬다.
- **setuptools**: 소스 트리에 `*.egg-info`·`build/`를 만들고, 패키지 데이터(`gateway/data/*.jsonl`)를 따로 적어야 한다. hatchling은 패키지 폴더를 통째로 넣는다.
- **E501을 켜고 전체 서식 정리**: 933건이다. 이력과 리뷰를 흐리고 이 단계의 목적이 아니다.
- **`requirements-gateway.txt` 유지**: 의존성 출처가 둘이 되어 어긋난다.
- **연구 테스트를 제품 테스트로 옮기기**: 검증 대상(측정 스크립트)이 트리에서 빠진다. 제품 동작은 남는 17개 파일이 지킨다.

### 4. 완료 기준

| # | 기준 | 명령 | 기대 |
|---|---|---|---|
| 1 | 전체 테스트 | `pytest -q` | 전부 통과 |
| 2 | lint | `ruff check .` | 통과 |
| 3 | 추적 용량 | `git ls-files -z \| xargs -0 du -ch \| tail -1`(새 파일을 더한 뒤) | 5MB 미만 |
| 4 | 옛 기록 보존 | `git show research-final:DECISIONS.md \| head -3` | 옛 결정 기록 머리말 |
| 5 | 설치 | `pip install -e ".[dev]"` 뒤 health의 `version` | `0.1.0`(테스트 `test_health_reports_code_and_detectors`) |
| 6 | 이미지 | `docker build -f gateway/Dockerfile .` | 성공(Docker가 없으면 CI) |

### 5. 한계

- 히스토리는 그대로라 클론 크기는 줄지 않는다.
- 코드·테스트 주석의 옛 결정 번호와 지운 문서·스크립트 경로는 하나씩 고치지 않았다(머리말 셋째 줄로 갈음).
- 판정 동등성 재생(`scripts/d107_equivalence.py`)과 변이 검사(`scripts/mutate_*.py`)는 태그에만 남는다. 이후 변경은 pytest와 단계별 완료 기준이 지킨다.
- 카나리 검사기(`gateway/detectors/canary.py`)는 2단계에서 지운다. 그 테스트(`test_canary`)를 이번에 뺐으므로 그때까지 카나리 코드는 테스트가 없다.
- `VERSION`은 설치된 메타데이터에서 읽는다. 편집 설치 뒤 `pyproject.toml` 버전만 올리면 다시 설치할 때까지 옛 값이 보인다.

### 6. 결과 (2026-10-30)

| # | 기준 | 결과 |
|---|---|---|
| 1 | `pytest -q` | 379 통과(Python 3.14.7 `.venv` 50초, 3.12 새 venv 46초). 정리 전 723 — 계획의 추정 '제품 410'과 달리 남은 17개 파일은 379개다 |
| 2 | `ruff check .` | 통과(3.14·3.12). E·F 중 E501만 끔(933건), 나머지 7건 수정 |
| 3 | 추적 용량 | 3.2MB(새 파일 포함, `docs/demo.gif` 2.6MB). 정리 전 1.0GB |
| 4 | `git show research-final:DECISIONS.md \| head -3` | 옛 머리말 `# DECISIONS.md — 의사결정 기록` 확인. 태그는 로컬에만 있다 — 푸시는 사용자 몫 |
| 5 | 설치 | `pip install -e ".[dev]"`(3.14·3.12) 성공, health `version` = `0.1.0`. 휠에 `gateway/data/*.jsonl`과 `LICENSE`가 들어간다 |
| 6 | 이미지 | 처음에는 Docker 데몬이 꺼져 있어 못 했다. 같은 날 데몬을 켠 뒤 `docker build -f gateway/Dockerfile .` 성공(24초, 244MB, arm64) — D-109 결과 절의 컨테이너 확인 참고 |

- 트리에서 뺀 추적 파일 458개. 무시된 로컬 데이터(`target/storage/` 등)는 그대로 있다. `scripts/demo.py`는 정리 뒤에도 그대로 돈다.
- 못 한 것: CI 실행 확인(푸시 뒤). 로컬 이미지 빌드는 같은 날 뒤에 했다.

---

## D-109. 보안 경계 — 경로·헤더 허용 목록, 관리 엔드포인트 분리, 옛 경로·카나리 제거, 컨테이너 강화 (2026-10-30, PLAN 2단계)

### 1. 근거 (PLAN 부록 A, 2026-10-30 검토의 재현)

- 캐치올 라우트(`/{full_path:path}`, 메서드 7개)가 어떤 경로든 상류로 중계하고 상류 키를 단다. 게이트웨이 키 하나로 파일 삭제·파인튜닝·조직 API까지 운영자 계정으로 닿는다.
- 요청 헤더는 3개, 응답 헤더는 4개만 뗀다. `Cookie`·`X-Forwarded-*`·`OpenAI-Organization`이 상류로, 상류의 `openai-organization`·`set-cookie`·레이트리밋 헤더가 클라이언트로 간다.
- `GATEWAY_AUTH=off`에 상류 키가 있으면 누구나 운영자 키로 상류를 쓰는 무인증 중계가 된다.
- 무인증 `/__gateway/health`가 상류 주소·검사기 구성·카나리 지문을, `/__gateway/metrics`가 PII 처리량을 공개한다.
- 세 POST 경로 밖의 본문은 옛 바이트 검사(AnythingLLM 측정 입구)로 가고, multipart 본문은 재직렬화로 깨진다. 그 검사 경로와 카나리 관측은 연구용이고 제품 경로에 없다.
- 이미지가 root로 돌고, 베이스 태그가 고정되지 않았고, HEALTHCHECK가 없다. `--workers 1`의 근거(프로세스 메모리 볼트 공유)는 D-107의 요청 단위 볼트로 사라졌다.

### 2. 결정

1. **경로 허용 목록**: `POST /v1/chat/completions` `POST /v1/responses` `POST /v1/messages` `GET /v1/models`만 받는다. 그 밖의 경로와, 아는 경로의 다른 메서드는
   404(API 오류 형식 — `/v1/messages*`는 Anthropic, 나머지는 OpenAI)이고 상류에 연결하지 않는다. 캐치올 라우트를 없앤다.
   `GET /v1/models`는 본문이 없으므로 검사기를 거치지 않고 키 검증·레이트리밋·헤더 허용 목록만 지나 중계한다.
2. **옛 경로 코드 삭제**: `detectors/pii.py`의 `doc is None` 분기와 `_session_spans`·`_outside`·`normalized_text`, `detectors/injection.py`의 `user_text`·`USER_FIELDS`·바이트 분기,
   `_relay`의 AnythingLLM 형식 차단 응답, 쓰는 곳이 없어지는 `openai_api.py`의 도우미. 검사기는 언제나 어댑터의 `doc`를 본다.
3. **카나리 삭제**: `detectors/canary.py`, `GATEWAY_CANARY_*`, health의 `canary_fp`, `version.canary_fingerprint`, 카나리 테스트. `detectors/noop.py`는 테스트만 쓰므로 `tests/chain_app.py`로 옮긴다.
4. **요청 헤더 허용 목록**: `content-type` `accept` `user-agent` `anthropic-version` `anthropic-beta` `openai-beta` `idempotency-key`만 넘긴다(hop-by-hop·`host`·`content-length`·
   `accept-encoding`·`cookie`·`x-forwarded-*`는 목록에 없으므로 늘 떨어진다). 상류 키가 있으면 상류 형식의 키를 단다 — `/v1/messages`이거나 `anthropic-version`을 보낸 요청
   (Anthropic SDK의 `GET /v1/models`)은 `x-api-key`, 그 밖은 `Authorization: Bearer`. 상류 키가 없는 통과 모드에서는 `openai-organization`·`openai-project`도 넘긴다.
   **계획과 다른 점**: 클라이언트의 인증 헤더(`authorization`·`x-api-key`)는 게이트웨이 인증이 꺼져 있을 때만 넘긴다. 인증이 켜져 있으면 그 헤더는 게이트웨이 키이고,
   상류 키가 없다고 그것을 상류로 보내면 게이트웨이 키가 제3자에게 샌다(옛 테스트 `test_a2_without_upstream_key_the_client_header_is_forwarded`가 그 동작을 지켰다).
5. **응답 헤더 허용 목록**: `content-type` `cache-control` `retry-after` `retry-after-ms` `x-should-retry`. 게이트웨이 자신의 `x-gateway-*`는 그대로.
   상류 요청 ID(`x-request-id`, 없으면 `request-id`)는 클라이언트에 넘기지 않고 감사 줄 `upstream_request_id`에 적는다.
6. `GATEWAY_AUTH=off`인데 `GATEWAY_UPSTREAM_KEY`가 있으면 기동 실패.
7. **관리 엔드포인트**: `/__gateway/health`는 인증 없이 `{"status": "ok"}`만. 상세(`version`·`code`·`target`·`chat_upstream_path`·`detectors`)는 `/__gateway/info`로 옮기고,
   그것과 `/__gateway/metrics`는 `GATEWAY_ADMIN_KEY`를 `Authorization: Bearer`로 냈을 때만 응답한다. 관리 키가 없거나 틀리면 404(있는지도 알리지 않는다).
8. **Dockerfile**: 비root 사용자, 베이스 이미지 다이제스트 고정, `HEALTHCHECK`(파이썬 표준 라이브러리로 health 조회), `--workers 1` 제거(uvicorn이 읽는 `WEB_CONCURRENCY`로 조절),
   `--timeout-graceful-shutdown 25`, `--limit-concurrency 1000`(스트림이 오래 열려 있으므로 넉넉히), 감사 로그 기본 stdout(`GATEWAY_LOG_PATH=-`), 낡은 주석 정리.
   프록시 뒤에 둘 때 신뢰할 프록시는 uvicorn의 `FORWARDED_ALLOW_IPS`로 정한다(README). 기본값(127.0.0.1)이면 그 밖에서 온 `X-Forwarded-For`는 무시된다.

### 3. 버린 대안

- **거부 목록(위험한 경로만 막기)**: 공급자가 API를 늘릴 때마다 뚫린다. 제품이 검사하는 것은 세 API뿐이다.
- **알 수 없는 경로를 검사 없이 통과**: 검사하지 않는 중계에 운영자 키를 붙이는 것이 이번 결함 그 자체다.
- **헤더 거부 목록 확장**: 상류가 새 헤더를 만들 때마다 샌다. 허용 목록이 짧고 SDK 동작에 필요한 것은 이것뿐이다(`x-stainless-*` 같은 SDK 계측 헤더는 떨어져도 동작한다).
- **관리 키 없을 때 info·metrics를 401**: 엔드포인트가 있다는 사실을 알린다. 404가 같은 보호를 더 적게 드러낸다.

### 4. 완료 기준 (`tests/test_d109_boundary.py`)

| # | 기준 |
|---|---|
| B1 | `DELETE /v1/files/x`, `POST /v1/fine_tuning/jobs`, `GET /v1/organization/users` → 404이고 스텁 상류 수신 0건 |
| B2 | 아는 경로의 다른 메서드(`GET /v1/chat/completions`, `OPTIONS /v1/messages`) → 404, 수신 0건, 오류 형식은 경로를 따른다 |
| B3 | `GET /v1/models` → 스텁 상류가 상류 키를 받는다(Bearer, `anthropic-version`이 있으면 `x-api-key`) |
| B4 | 상류 키 모드에서 클라이언트의 `Cookie`·`OpenAI-Organization`·`X-Forwarded-For`가 상류에 닿지 않는다 |
| B5 | 상류의 `openai-organization`·`set-cookie`·`x-request-id`가 클라이언트에 닿지 않고, 감사 줄 `upstream_request_id`에 상류 요청 ID가 있다 |
| B6 | 통과 모드(인증 끔·상류 키 없음)에서 `OpenAI-Organization`과 클라이언트 키가 상류에 간다. 인증 켬·상류 키 없음이면 게이트웨이 키가 상류에 가지 않는다 |
| B7 | `GATEWAY_AUTH=off` + 상류 키 → 기동 실패(종료 코드가 0이 아님) |
| B8 | 무인증 health는 `{"status": "ok"}`뿐. 관리 키 없는 게이트웨이의 metrics·info는 404, 관리 키가 있으면 틀린 키 404·맞는 키 200 |
| B9 | 이미지 기본 명령이 uvicorn 접근 로그를 끈다 — 쿼리 값 누출(같은 날 컨테이너 확인에서 찾아 더함) |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

옛 경로·카나리를 쓰던 테스트는 같은 뜻을 세 API 경로로 옮기거나(본문·헤더·쿼리 보존, 413, 감사 한 줄, 차단 응답) 대상이 없어졌으면 지운다(옛 경로 sessionId·PEM 바이트 검사, 카나리).

### 5. 한계

- 허용 목록 밖의 공급자 기능(파일·임베딩·`count_tokens`·배치 등)은 게이트웨이로 쓸 수 없다. 필요하면 PLAN 조건부 표의 트리거로 경로를 더한다.
- 요청 헤더를 줄였으므로 공급자가 새 필수 헤더를 요구하면 목록을 고쳐야 한다.
- `WEB_CONCURRENCY`를 늘리면 레이트리밋·지표는 워커별이다(README 한계).
- 상류 TLS 검증·프록시 설정은 httpx 기본값 그대로다.

### 6. 결과 (2026-10-30)

- B1~B8 전부 통과(`tests/test_d109_boundary.py` 18건). 전체 `pytest -q` 386 통과(Python 3.14.7, 3.12 새 venv), `ruff check .` 통과.
- **구현 중 찾아 고친 결함**: 상류 httpx 클라이언트(모든 요청이 공유)의 기본 쿠키 저장소가 상류의 `set-cookie`를 저장해 **다음 요청 — 다른 클라이언트의 요청 —
  에 붙여 보냈다**. 스텁 `/v1/models`를 두 번 불러 재현(`__cf_bm=stub`이 둘째 요청에 붙음). 모든 도메인을 거부하는 `CookieJar` 정책으로 저장·전송을 끄고, B4가 이를 지킨다.
- 공식 SDK 점검(스텁 상류): OpenAI 3.41.0 8/8, Anthropic 2.3.0 6/6 — Anthropic 점검은 D-107 §8에서 미실행이던 것이다. 데모 `scripts/demo.py` 6장면 정상.
- 이미지: Docker 데몬이 꺼져 있어 빌드는 CI 몫이다. 대신 이미지의 설치 경로를 흉내 냈다 — 새 Python 3.12 venv에 `pip install .`, `/`에서 Dockerfile과 같은 옵션으로
  uvicorn 기동 → health `{"status":"ok"}`, info `version` 0.1.0, `gateway`는 site-packages에서 import. 베이스 다이제스트는 2026-10-30에 레지스트리에서 조회했다.
- 테스트 정리: 옛 AnythingLLM 경로를 쓰던 8개 파일을 세 API 경로로 옮겼다(본문·쿼리·인증 보존, 413, 감사 한 줄, 차단 응답 모양, L-005 이스케이프 독립성은 어댑터 경로로).
  대상이 없어져 지운 것: 옛 경로 PEM 바이트·sessionId(D-102 #4·#5), 캐치올 다중 헤더(#6), 옛 경로 연결 실패 500, `user_text`·`normalized_text` 단위 테스트 4, 카나리 2.
  `x-ratelimit-*` 응답 헤더는 이제 넘기지 않는다(운영자 계정의 한도) — 해당 단언을 뒤집었다.
- 카나리를 지우며 스트림 끝의 응답 검사기 재실행(`_stream_steps`의 `run_response`)과 `StreamRestorer.content_in`도 지웠다 — 카나리만 쓰던 것이다.
- 계획과 다른 점: §2-4(인증을 켠 게이트웨이는 상류 키가 없어도 클라이언트 인증 헤더를 넘기지 않는다). 404의 오류 type은 Anthropic 실제 값 `not_found_error`.
- **컨테이너 확인(같은 날 뒤에, Docker Desktop 29.9.2, arm64)**: 빌드 성공(베이스 다이제스트 그대로), uid 10001, `/src` 없음, `gateway`는 site-packages, `LICENSE`·데이터 파일 포함.
  호스트 스텁에 붙여 기동 → HEALTHCHECK `healthy`(6초), health `{"status":"ok"}`, 관리 키 없는 info·metrics 404, 마스킹(상류 수신에 원래 전화·system 이메일 없음)·복원·스트리밍 복원,
  키 없음 401, `DELETE /v1/files/x` 404·스텁 수신 0, `docker stop` 0.38초·종료 코드 0(lifespan 정리), 대체값 키 없이 기동하면 종료 코드 3.
- **컨테이너 확인에서 찾아 고친 결함**: uvicorn **접근 로그가 쿼리 문자열을 값까지 컨테이너 로그에 남겼다**(`GET /v1/models?phone=010-…` 재현) — 감사 로그가 2026-09-22부터
  일부러 빼는 값의 뒷문이고, stdout이 감사 JSONL과 섞였다(비JSON 줄 15개). 이미지 기본 명령에 `--no-access-log`를 넣었다 → 로그 속 원래 값 0건, stdout은 감사 JSONL만,
  기동·오류 로그는 stderr. B9(`test_b9_container_command_turns_off_the_access_log`)가 기본 명령을 지킨다. README의 운영 예시에도 넣었다.
- 못 한 것: CI `docker` 잡은 빌드만 한다(컨테이너 기동 확인은 위의 수동 확인뿐).

---

## D-110. 가용성 — 볼트 선형 발급, 탐지 상한, 스레드 오프로드, 상류 풀, 보류 상한, 볼트 수명, 응답 크기 상한 (2026-10-30, PLAN 3단계)

### 1. 근거 (2026-10-30 검토의 직접 재현)

- `TokenVault.token_for`가 새 값마다 세션의 모든 원본·대체값으로 충돌 검사 집합을 다시 만든다 — 고유 전화 1,000/2,000/4,000개에 0.50/2.19/6.84초.
  같은 입력의 `find_all`은 20,000건에 0.05초라 병목은 볼트다. 워커가 하나면 그동안 health도 응답하지 못한다.
- 요청당 탐지 건수에 상한이 없다. 정규식 검사(`find_all`·`match_rules`)가 이벤트 루프 위에서 돈다.
- 상류 클라이언트의 타임아웃 600초가 연결·풀 대기에도 걸리고, 풀 크기를 정할 수 없다.
- 스트림 보류 상한 `MAX_HOLD = 128`이 고정이라 168자 `sk-proj-` 대체값은 조각 경계에 걸리면 복원되지 않는다(직접 재현: 보류 길이 0). D-107 결정문은 원래
  '이 요청에서 발급한 가장 긴 대체값'을 상한으로 정했다.
- 볼트 TTL(600초)이 상류 타임아웃(600초)과 같아 긴 스트림 도중 세션이 만료될 수 있고, 용량(2,000)을 넘으면 진행 중인 세션을 조용히 밀어내 복원이 깨진다.
- 비스트리밍 상류 응답을 크기 제한 없이 메모리에 읽는다.

### 2. 결정

1. **볼트 발급 O(1)**: 세션에 `taken`(쓸 수 없는 정규화 키 — 원본·대체값) 집합을 두고 발급할 때 넣는다. 만료 정리(`_purge_expired`)는 1초에 한 번만 돈다
   (요청마다 세션 전체를 훑으면 세션 수 × 발급 수가 된다).
2. **탐지 상한** `GATEWAY_MAX_FINDINGS`(기본 5000): mask 모드에서 한 요청의 탐지가 이를 넘으면 **대체값을 하나도 발급하기 전에** 거절한다 — 413(그 API의 오류 형식,
   code `too_many_findings`), 상류 호출 없음. 가리지 못한 값을 내보내지 않는다. detect 모드는 관측만 하므로 막지 않는다.
3. **스레드 오프로드**: 순수 함수 `find_all`·`match_rules`만, 검사할 텍스트가 16K자를 넘을 때 `asyncio.to_thread`로 돌린다. 볼트 조작·doc 변경은 이벤트 루프에 둔다.
4. **상류 클라이언트**: `httpx.Timeout(connect=5, read=GATEWAY_TIMEOUT, write=30, pool=5)`, `httpx.Limits(max_connections=GATEWAY_MAX_CONNECTIONS)`(기본 100).
   풀 대기 초과(`PoolTimeout`)는 503 + `retry-after: 1`(code `upstream_busy`) — 상류에는 보내지 않았다.
5. **스트림 보류 상한** = 이 요청에서 발급한 가장 긴 대체값 길이(16K자 상한). `MAX_HOLD`를 없앤다. 128자 이하 대체값은 지금처럼 진접두사 집합으로, 더 긴 대체값(자격 증명)은
   KMP 실패 함수로 '꼬리가 대체값의 앞부분인가'를 본다 — 진접두사 집합은 길이의 제곱 메모리·시간이라 PEM(수 KB)에 쓸 수 없다.
6. **볼트 수명**: TTL = `GATEWAY_TIMEOUT` + 60초. 스트림의 모든 상류 조각(ping·thinking 포함)에서 세션을 갱신한다. 용량(2,000 세션)을 넘으면 진행 중인 세션을 밀어내지 않고
   새 요청을 503(`retry-after: 1`, code `gateway_busy`)으로 거절한다.
7. **비스트리밍 응답 상한** 32MiB: 상류 응답은 언제나 머리만 받고 본문을 상한까지 읽는다. 넘으면 502(code `upstream_response_too_large`). SSE는 조각마다 흘려보내므로 상한이 없다.

### 3. 버린 대안

- **볼트 발급을 스레드로**: 볼트는 이벤트 루프의 모든 요청이 공유한다. 잠금 없이 스레드에서 바꾸면 경합이 생긴다. O(1)로 만들면 옮길 이유가 없다.
- **탐지 상한 초과분만 가리지 않고 통과**: 가리지 못한 값이 상류로 나간다. 마스킹 제품의 실패 방향은 거절이다.
- **용량 초과 시 LRU 축출 유지**: 진행 중 응답의 복원이 조용히 깨진다(사용자가 가짜 값을 받는다). 거절은 보이고 다시 시도할 수 있다.
- **보류 상한을 고정 16K로**: 짧은 대체값만 발급한 요청에서도 매 조각 16K자 꼬리를 훑는다.
- **응답 복원 경로(`restore`의 `find_all`)도 오프로드**: 6단계가 응답 복원을 필드별로 다시 짠다. 그때 함께 본다.

### 4. 완료 기준 (`tests/test_d110_availability.py`)

| # | 기준 |
|---|---|
| V1 | 볼트 발급 1,000개 대비 4,000개 시간 비가 8 미만(지금 약 14배) |
| V2 | 고유 전화 5,000개 본문이 1초 안에 끝나고 모두 가려진다. 5,001개면 413(`too_many_findings`)이고 스텁 상류 수신 0건 |
| V3 | 168자 `sk-proj-` 대체값이 스트리밍 조각 경계(3자 조각)에 걸려도 복원된다. PEM(1,000자 넘음)도 |
| V4 | `Limits(max_connections=1)`로 띄우고 동시에 두 요청을 보내면 하나는 503(`retry-after: 1`) |
| V5 | 볼트 용량이 차면 새 세션은 `VaultFull`이고 기존 세션은 복원된다. 게이트웨이는 503(`gateway_busy`) |
| V6 | 32MiB를 넘는 비스트리밍 상류 응답은 502 |
| V7 | 16K자를 넘는 검사 텍스트에서 `find_all`·`match_rules`가 이벤트 루프 밖(다른 스레드)에서 돈다 |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- 응답 복원(`restore`·`residual`의 `find_all`)은 아직 이벤트 루프 위다. 32MiB 응답이면 수 초 막힐 수 있다 — 6단계에서 필드별 복원으로 바꿀 때 오프로드한다.
- 16K자를 넘는 대체값(긴 인증서 체인 등)은 스트림 조각에 걸리면 복원되지 않는다 — 감사의 `residual_tokens`로 보인다.
- KMP 보류는 조각마다 보류 중인 꼬리 전체를 다시 훑는다. 수 KB의 PEM이 3자 조각으로 오면 응답 하나에 수백만 글자 연산이다(측정은 결과 절).
- 용량 503은 프로세스(워커)별이다.

### 6. 결과 (2026-10-30)

- V1~V7 전부 통과(`tests/test_d110_availability.py` 11건). 전체 `pytest -q` 397 통과, `ruff check .` 통과.
- 수치: 고유 전화 5,000개 요청 0.19초(예전 4,000개 6.84초의 볼트 발급이 병목이었다). 1,000 → 4,000개 발급 시간 비는 선형(테스트 상한 8).
  1.3KB PEM과 168자 `sk-proj-` 대체값이 3자 조각 스트림(수백 조각)에 걸쳐 복원 — PEM 스트림 한 건 0.15초. 짧은 대체값만 발급한 세션은 128자 꼬리만 본다.
- 기존 테스트 변경: 볼트 용량 테스트를 '밀어내지 않고 거절'로 바꿨다(`test_capacity_is_bounded_without_evicting_live_sessions`). D-102 #1의 치환 속도 테스트(같은 번호 74,000회)는
  기본 탐지 상한에 걸리므로 상한을 명시적으로 풀어 치환 속도만 본다.
- 만료 정리를 1초 간격으로 줄이면서, 복원·보류·발급 건수 조회는 그 세션의 만료를 따로 본다(`_live`) — TTL 뒤 복원 금지(2026-09-22 결함)를 그대로 지킨다.
- 못 한 것: 응답 복원 경로의 오프로드(6단계), 실제 다중 워커 기동 확인(15단계 부하에서).

---

## D-111. 결정적 대체값 + 7단계 실측 사전 등록 (2026-10-30, PLAN 4단계)

### 1. 근거

- `surrogate.py`가 요청마다 난수로 대체값을 만든다. 둘째 턴부터 이력의 같은 메시지가 다른 바이트로 상류에 간다. 현행 Claude 모델의 thinking 서명은 앞선 메시지 바이트에
  묶이고 어긋나면 기본 400이며, 프롬프트 캐시는 바이트 prefix 일치라 PII가 처음 나온 턴부터 매번 미스다. 둘 다 공급자 문서 근거이고 실 API로는 아직 재현하지 않았다(§6, PLAN 7단계).

### 2. 결정

1. `GATEWAY_SURROGATE_KEY`: PII mask 모드면 필수, 32자 이상(`python -m gateway keygen` 출력은 35자). 없거나 짧으면 기동 실패. detect·off 모드는 필요 없다.
2. 생성기는 `rng`를 받는다(`surrogate.make(kind, value, rng)`). 볼트가 값마다 시드 = HMAC-SHA256(키, 종류 + "\0" + `norm_key(종류, 값)`)로 `random.Random(시드)`를 만들어 넘긴다.
   모양 규칙(접두사·구분자·Luhn·생년월일)은 그대로다. 키 없이 만든 `TokenVault`(테스트·도구)는 볼트마다 무작위 키를 쓴다 — 그 볼트 안에서만 결정적이다.
3. 한 요청 안에서 두 원문이 같은 대체값(정규화 키)을 받으면 시드에 카운터를 붙여 다시 만든다(최대 20회). `# ponytail:` 주석에 천장을 적었다 — 그 값만 다른 턴과 바이트가 달라질 수 있다.
4. 키는 환경변수(K8s Secret) 하나, 회전은 수동이다(PLAN 결정 표 8번). 법률 검토 전까지 PIPA '추가정보'로 다룬다 — 키와 대체값이 있으면 공간이 작은 값(전화번호 약 10^8)은 전수
   대입으로 원문을 되짚을 수 있다. 클라이언트 키·공급자 키와 같은 등급으로 보관한다.

### 3. 버린 대안

- **FF1 형식 보존 암호화**: 키만 있으면 볼트 없이 복호화된다(매핑이 곧 암호문). 무겁고, PLAN 조건부 표(서버 저장 대화 복원 요구)의 트리거다.
- **매핑 영속 저장(Redis·DB)**: 결정 표 4번 — 원문을 어디에도 저장하지 않는다.
- **클라이언트가 준 대화 ID로 시드**: 클라이언트가 고르는 값이라 추측·재사용할 수 있고, 무상태 API에는 대화 ID가 없다.

### 4. 완료 기준 (`tests/test_d111_deterministic.py`)

| # | 기준 |
|---|---|
| R1 | 같은 키·같은 값 100회 → 같은 대체값(요청·볼트가 달라도). 다른 키 → 다른 대체값 |
| R2 | 한 요청 안에서 서로 다른 원문이 같은 대체값을 받지 않는다(생성기를 바꿔 겹침을 강제해도 카운터로 갈린다) |
| R3 | 모양 규칙 테스트(`test_d107_surrogate`)가 그대로 통과 |
| R4 | 2턴 대화(스텁): 턴 1에 상류가 받은 user 메시지와 턴 2 이력 속 같은 메시지가 바이트까지 같고, 턴 2 이력의 assistant는 턴 1에 상류가 낸 답과 같다 |
| R5 | mask 모드에 키가 없거나 32자 미만이면 기동 실패, detect 모드는 키 없이 뜬다 |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- **요청 간 연결**: 같은 키 아래 같은 원문은 늘 같은 가명이다. 공급자 로그에서 같은 값을 담은 요청끼리(사용자·대화가 달라도) 이어 볼 수 있다. 줄이려면 키를 회전하거나
  클라이언트별 키를 둔다(12단계 정책에서 검토).
- **키 회전**: 새 키 생성 → 배포(롤링). 배포 동안 키가 다른 레플리카가 섞이면 같은 원문이 레플리카마다 다른 대체값이 되고, 진행 중인 대화는 회전 뒤 첫 턴에 이력 바이트가 바뀐다 —
  그 턴은 캐시 미스이고, thinking 서명 검사가 엄격하면 400이 날 수 있다. 트래픽이 적을 때 짧게 회전하고 레플리카 간 키를 오래 섞지 않는다(14단계 운영 문서에 옮긴다).
- 카운터로 다시 만든 값은 턴마다 겹치는 상대가 다르면 바이트가 달라질 수 있다(드물다).
- `random.Random`의 `random()` 수열은 시드가 같으면 버전 간 같다고 보장되지만 `choice`·`randint`는 형식 보장이 없다(3.2 이후 바뀐 적은 없다). 파이썬 메이저 버전 교체는 키 회전처럼 다룬다.

### 6. 7단계 실측 사전 등록 (이 결정이 커밋된 뒤에만 실행한다)

- **질문**: 결정적 대체값이 실제 Claude API에서 둘째 턴의 thinking 서명 검사와 프롬프트 캐시를 지키는가. 옛 코드(요청마다 난수)는 깨뜨리는가.
- **모델**: `claude-haiku-5-5`. 모델 이름이 거절되면 `claude-sonnet-5-5`(바꾼 사실을 기록). 비스트리밍, `max_tokens` 1024.
- **두 팔**: A(옛) = `research-final`(34c16fb)을 `git worktree`로 꺼내 다른 포트에 띄운 게이트웨이. B(새) = 측정 시점의 main(4~6단계 반영). 두 팔 모두 같은 상류 키·같은 클라이언트 스크립트.
- **대화**: 팔마다 5개, 각 2턴(요청 총 20건). 대화마다 다른 합성 전화(`010-XXXX-XXXX`)·이메일(`@example.com`). system에는 합성 업무 문서(사내 규정)를 넣는다 — 그 모델의
  캐시 최소 길이(실행 시 claude-api 스킬의 prompt-caching 문서로 확인)의 두 배 이상. `cache_control`은 턴 1 user 메시지의 마지막 블록에 둔다(턴 2에서도 같은 블록) —
  system만 캐시되면 옛 팔도 캐시 읽기가 생겨 두 팔이 갈리지 않는다.
  턴 1 user: 연락처를 알려 주며 정상 업무 질문. 턴 2: 게이트웨이가 돌려준 턴 1 응답(thinking 블록 포함)을 그대로 assistant로 붙이고, 연락처를 다시 말해 달라는 user.
- **서명 검사 명시**: 모든 요청에 `anthropic-beta: thinking-binding-controls-2026-08-01`과 `thinking: {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "error"}}`.
  API가 이 헤더·필드를 거절하면(400 invalid_request로 그 이름을 가리킴) 그 사실을 기록하고 둘 다 빼고 한 번 다시 돈다 — 그때 400 기준은 기본 동작에만 적용한다.
- **기록**(키·원문 없이 `docs/verification/multiturn_claude.jsonl`): 팔, 대화, 턴, 상태 코드, 오류 문구(400이면), 응답의 `input_transformations`(있으면), `usage`(input·output·
  cache_creation·cache_read), 감사의 `issued`·`restored`·`residual_tokens`, 원래 값이 사용자에게 보인 답에 복원됐는지, 누적 비용(usage × 단가).
- **성공 기준**:
  - B: 10건 중 400 0건, 턴 2의 `cache_read_input_tokens > 0`이 5/5 대화, 10건 모두 `residual_tokens == 0`이고 모델이 되풀이한 원래 값이 사용자 답에 복원.
  - A(양성 대조): 5개 대화 중 하나 이상에서 턴 2가 400(prefix 불일치)이거나 `cache_read_input_tokens == 0`. 재현되지 않으면 그대로 적는다(주장이 약해질 뿐 B의 실패는 아니다).
  - 비용 ≤ $1. 누적 추정 비용이 $1에 닿으면 즉시 멈추고 거기까지를 결과로 적는다.
- **데이터 원칙**: 정상 요청·합성 PII만. 공격 문장 없음. 결과에 키·원문을 남기지 않는다.

### 7. 결과 (2026-10-30)

- R1~R5 통과(`tests/test_d111_deterministic.py` 13건), R3 모양 규칙(`test_d107_surrogate`)은 테스트를 고치지 않고 그대로 통과. 전체 `pytest -q` 410 통과, `ruff check .` 통과.
- 2턴 스텁 대화에서 턴 1 user 메시지의 직렬화 조각이 턴 2 상류 본문에 바이트 그대로 들어가고, 턴 2 이력의 assistant는 턴 1에 상류가 낸 답(대체값 포함)과 같다.
- 게이트웨이를 띄우는 곳(테스트 `make_stack`, `web/app.py`, `scripts/demo.py`, SDK 점검 둘)에 대체값 키를 넣었다. 데모 6장면·OpenAI SDK·Anthropic SDK 점검 재통과.
- §6의 사전 등록은 이 결정이 커밋된 뒤에만 실행한다(PLAN 7단계). 실행 결과는 7단계 결정의 결과 절에 적는다.

---

## D-112. 마스킹 범위를 모든 역할로 + thinking·reasoning은 손대지 않는다 (2026-10-30, PLAN 5단계)

### 1. 근거

- `openai_api.py`의 `PII_ROLES`가 user·assistant뿐이다. 직접 재현: Chat `tool` 메시지 속 전화·이메일이 상류에 평문 그대로 갔다. 에이전트·RAG 앱에서 개인정보는 대부분
  도구 결과와 system 문서(검색된 고객 기록)로 들어온다.
- 비스트리밍 응답은 JSON 텍스트 전체를 정규식으로 복원해 Anthropic `thinking` 블록의 텍스트까지 원래 값으로 바꾼다. 클라이언트가 그 응답을 다음 턴에 그대로 보내면
  (1) thinking 텍스트가 서명과 달라져 상류가 거절하고, (2) thinking 블록은 요청 마스킹 대상이 아니므로 **원래 값이 thinking 안에 담겨 상류로 간다**.
  Responses 스트림의 전체 텍스트 이벤트(`response.completed` 등)도 reasoning 요약까지 복원한다.

### 2. 결정

1. `PII_ROLES` 기본을 user·assistant·tool·system으로 넓힌다(어댑터가 developer·`instructions`를 system으로 정규화한다). `GATEWAY_PII_ROLES`(쉼표, `developer`는 system의 별칭)로 좁힌다 —
   `GATEWAY_PII_ROLES=user,assistant`면 옛 동작. 모르는 역할 이름은 기동 실패.
   **D-073을 뒤집는 근거**: D-073은 system·tool 속 값을 가리면 '답에 필요한 값을 훼손한다'고 봤다. 토큰(`[PII:phone:1]`) 시절에는 맞았다. 지금은 같은 모양의 결정적 가짜 값이라
   (D-107 B·D-111) 모델은 system·도구 결과·이력 어디서나 같은 가짜 값을 보고 그것으로 추론·도구 호출을 하며, 사용자는 원래 값을 돌려받는다. 훼손되는 것은 값의 실제 내용에
   기대는 추론(번호의 지역 판단 등)뿐이고, 그것은 user 역할에서도 이미 같다.
2. 세 어댑터의 텍스트 참조를 확인했다: Chat `system`·`developer`·`tool` 메시지(문자열·text 파트), Anthropic `system`·`tool_result`, Responses `instructions`·`function_call_output`은
   이미 TextRef로 나온다. 빠진 곳 하나를 채운다 — Anthropic `document` 블록의 텍스트 원본(`source.type == "text"`의 `data`, RAG 문서).
3. Anthropic `thinking`·`redacted_thinking` 블록(과 `signature`), Responses `reasoning` 항목은 요청 마스킹도 응답 복원도 하지 않는다. 응답 복원은 JSON을 파싱해 문자열 값마다 하고
   (`gateway/api/base.py`의 `map_strings`), 그 세 종류의 객체는 통째로 건너뛴다. 비스트리밍 본문과 Responses 스트림의 전체 텍스트 이벤트가 같은 함수를 쓴다. 스트림 델타는
   지금처럼 text·도구 인자 델타만 복원한다(thinking·요약 델타는 원래 손대지 않았다). JSON이 아닌 응답은 지금처럼 텍스트 전체를 복원한다.
4. 감사의 `residual_tokens`는 복원 대상 텍스트(사고 과정 밖)에서만 센다 — thinking 속 가짜 값은 의도된 것이다.
5. 문서: thinking·reasoning 요약에는 가짜 값이 보일 수 있다(README 한계).

### 3. 버린 대안

- **thinking을 복원하고 다음 턴 요청에서 다시 가리기**: 같은 바이트로 되돌린다는 보장이 없고(모델이 값을 변형해 쓸 수 있다), 서명이 그 바이트에 묶여 있다. 손대지 않는 것이 유일하게 안전하다.
- **어댑터별 응답 필드 목록**: 6단계가 도구 인자 안쪽 JSON을 따로 다룰 때 필요한 곳만 더한다. 지금은 '사고 과정만 빼고 모든 문자열'이 더 짧고 빠뜨리는 필드가 없다.

### 4. 완료 기준 (`tests/test_d112_roles.py`)

| # | 기준 |
|---|---|
| M1 | Chat `tool`·`system`·`developer`, Anthropic `system`·`tool_result`·`document`(텍스트), Responses `instructions`·`function_call_output` 속 합성 전화·이메일이 상류에 평문으로 가지 않는다 |
| M2 | 에이전트 루프 2요청(스텁): 도구 결과 속 값이 가려지고 최종 답에서 원래 값으로 돌아온다 |
| M3 | thinking 블록 바이트가 응답(비스트리밍·스트리밍)에서 바뀌지 않고, 그대로 다음 턴에 보내면 스텁의 서명 검사를 통과하며 원래 값이 상류에 가지 않는다. Responses reasoning 요약도 그대로 |
| M4 | `GATEWAY_PII_ROLES=user,assistant`면 tool·system이 평문으로 간다(옛 동작), 모르는 역할 이름은 기동 실패 |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- thinking·reasoning 요약을 사용자에게 보여 주는 앱은 가짜 값을 보여 준다.
- 비텍스트(이미지·PDF 원본)와 Anthropic `search_result` 블록 같은 다른 블록은 여전히 보지 않는다.
- system에 같은 고객 기록이 매번 들어가면 그 값의 가짜 값도 매번 같다(D-111) — 캐시에는 좋고, 요청 간 연결은 D-111 §5와 같다.

### 6. 결과 (2026-10-30)

- M1~M4 통과(`tests/test_d112_roles.py` 15건). 전체 `pytest -q` 425 통과, `ruff check .` 통과.
- 옛 동작(D-073·D-085: system·tool 평문)을 단언하던 테스트 5건을 새 동작으로 뒤집었다(`test_d107_api` c1·c4, `test_openai_gateway` 둘, `test_upstream_contract` 하나).
  Messages 사례의 발급 수는 2 → 4(system·tool_result의 이메일도 가린다).
- 스텁에 thinking 서명 흉내(`thinking_sig` — 텍스트 바이트의 해시)와 reasoning 요약, 에이전트 루프(`stub-agent`)를 더했다. 비스트리밍·스트리밍 thinking과 Responses 요약이
  바이트 그대로 오고, 그대로 다음 턴에 보내면 서명 검사를 통과하며 원래 값이 thinking에 담겨 상류로 가지 않는다.
- 스트림 감사의 잔여는 이제 복원 대상 채널로 내보낸 텍스트에서만 센다(`StreamRestorer.visible_text`, 옛 `out_text`는 지웠다).

---

## D-113. 응답 필드별 복원 + 복원 가시화 + 안전한 가짜 이메일 (2026-10-30, PLAN 6단계)

### 1. 근거

- 도구 인자(`function.arguments`·Responses `arguments`)는 **문자열 안의 JSON**이다. 복원한 원래 값에 줄바꿈·따옴표가 있으면(PEM) 안쪽 JSON이 깨진다 — 비스트리밍은 바깥 JSON만,
  스트리밍 인자 채널(Chat 도구 인자·Anthropic `partial_json`·Responses 인자)은 아무 이스케이프 없이 끼웠다.
- 응답 JSON이 `<`를 `<`로 쓰는 상류(HTML 이스케이프 직렬화)에서는 텍스트 정규식이 대체값을 놓쳤다. 5단계(D-112)에서 JSON을 파싱해 문자열마다 복원하게 바뀌었으므로 여기서 고정한다.
- 복원 결과가 클라이언트에 보이지 않는다. `residual`은 대체값의 정확 일치만 세서, 모델이 가짜 번호의 끝 4자리만 말하거나 국제 형식으로 바꿔 쓰면 0으로 보고한다.
- 가짜 이메일이 실제로 있을 수 있는 도메인에서 나온다(원래 도메인 글자를 섞는다). 복원에 실패하면 사용자가 제3자의 주소를 받는다.

### 2. 결정

1. **도구 인자**: 비스트리밍 응답의 `arguments` 문자열은 안쪽 JSON 문자열 이스케이프를 적용해 **텍스트 그대로** 복원한다 — 모델이 쓴 인자의 바이트(공백·순서)가 그대로라 다음 턴 이력과
   캐시가 깨지지 않는다. 복원 전에는 JSON으로 읽혔는데 복원 뒤 읽히지 않으면(숫자 자리의 대체값 등) 그 문자열만 파싱 → 문자열 값마다 복원 → 다시 직렬화한다. 스트리밍은 셰이프가
   'JSON 텍스트 채널'(Chat 도구 인자, Anthropic `tool_use`의 `partial_json`, Responses 인자)을 알려 주고, 그 채널에는 같은 이스케이프를 적용한다. thinking은 여전히 손대지 않는다(D-112).
2. **가시화**: 비스트리밍 응답 헤더 `x-gateway-pii: issued=N restored=M`(발급이 있었을 때만). 스트리밍은 머리가 본문보다 먼저 나가므로 `issued=N`만 싣는다. 감사 줄에
   `pii_issued`·`pii_restored`·`pii_suspect`를 맨 위 필드로 둔다(집계가 response_detectors를 뒤지지 않게).
3. **의심 잔여** `gateway_pii_suspect_total`(감사 `pii_suspect`): 복원 뒤 사용자에게 보이는 텍스트에 (a) 남은 대체값 수(`residual`)와 (b) 발급한 대체값의 식별 조각 — 전화·카드의
   끝 4자리, 이메일 로컬파트 — 이 원래 값에는 없는데 나타난 대체값 수를 더한다. `issued>0 && restored==0`은 모델이 값을 되풀이하지 않은 정상 응답과 구별되지 않으므로 쓰지 않는다.
4. **가짜 이메일 도메인**은 RFC 2606 예약 도메인 `example.com`·`example.net`·`example.org` 중 하나(결정적 시드로 고른다). 로컬파트는 지금처럼 같은 글자 부류의 무작위.
5. **가짜 전화번호**: 2026-10-30에 확인한 범위에서 국내 휴대전화의 공식 '가상 번호' 대역은 없다(미국 555-0100~0199 같은 지정이 없고, 영화진흥위원회가 영화 제작사에 개별 번호를
   주는 정도다). 그래서 대역을 바꾸지 않고 **복원에 실패하면 사용자가 실제 제3자의 번호를 받을 수 있다**는 위험을 README 한계에 적고, (3)의 의심 잔여로 감시한다.

### 3. 버린 대안

- **도구 인자를 늘 파싱·재직렬화**: 계획의 기본안이지만 모델이 낸 인자의 바이트가 바뀐다(공백·이스케이프). OpenAI 형식에서는 그 바이트가 다음 턴 이력이 되므로 캐시 prefix가 깨진다.
  텍스트 복원 + 안쪽 이스케이프를 먼저 하고, JSON이 깨질 때만 파싱 경로를 쓴다.
- **가짜 번호를 미할당처럼 보이는 꼴(010-0xxx)로**: 공식 근거가 없고, 같은 모양 원칙(탐지 패턴에 다시 걸려야 복원된다)과 충돌할 수 있다.

### 4. 완료 기준 (`tests/test_d113_restore.py`)

| # | 기준 |
|---|---|
| F1 | 도구 인자에 PEM(개행)·따옴표가 든 값이 들어가도 복원 뒤 `json.loads(arguments)`가 성공하고 원래 값과 같다 — Chat·Responses 비스트리밍, Chat·Anthropic 스트리밍 |
| F2 | 상류가 `<`를 `<`로 직렬화해도 `<`에 붙은 대체값이 복원된다 |
| F3 | 이메일 대체값이 예약 도메인(`example.com`·`.net`·`.org`)이고 다시 이메일로 탐지된다 |
| F4 | `x-gateway-pii` 헤더(비스트리밍 issued·restored, 스트리밍 issued)와 감사 `pii_issued`·`pii_restored`·`pii_suspect`가 맞다 |
| F5 | 모델이 가짜 번호의 끝 4자리만 말하면 `pii_suspect` ≥ 1이고 지표 `gateway_pii_suspect_total`이 는다. 정상 복원·값을 말하지 않은 답은 0 |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- 끝 4자리 조각은 우연히 같은 숫자가 답에 나오면(날짜·금액) 의심으로 센다 — 지표는 경보가 아니라 추세용이다.
- 스트리밍의 `x-gateway-pii`에는 복원 수가 없다(감사에만).
- 비스트리밍 응답 복원은 여전히 이벤트 루프 위다(D-110 §5) — 문자열 단위로 나뉘었지만 32MiB 응답이면 수 초가 걸릴 수 있다.

### 6. 결과 (2026-10-30)

- F1~F5 통과(`tests/test_d113_restore.py` 12건). 전체 `pytest -q` 437 통과, `ruff check .` 통과.
- **구현 중 찾아 고친 결함 둘**(스트림 인자 채널의 PEM): (1) 128자 이하 자격 증명은 진접두사 집합 경로로 갔는데, 그 경로는 공백을 정규화하지 않아 `BEGIN PRIVATE`의 빈칸에서
  보류가 끊겼다 → 자격 증명은 길이와 무관하게 KMP(정규화) 경로로. (2) 조각 끝이 `\n` 이스케이프의 역슬래시 뒤에서 끊기면 그 역슬래시를 일반 글자로 봐 보류가 끊겼다 →
  조각 끝의 외로운 역슬래시는 정규화에서 건너뛴다. 이스케이프로 원래보다 길어지므로 KMP 창은 가장 긴 대체값의 2배다(D-110 §2-5의 '보류 상한'을 이만큼 넓혔다).
- 테스트 PEM에 따옴표를 넣으면 원문에서는 정규식이 `"`에서 멈추고 JSON 인자 안에서는 `\"`를 이스케이프 쌍으로 보아 더 길게 잡혀 복원되지 않는다. 실제 PEM 본문(base64)에는
  따옴표가 없으므로 시험값에서 뺐고, 이스케이프가 필요한 원래 값은 개행 구분 전화번호로 시험한다.
- 기존 테스트 변경: 이메일 모양 규칙(TLD 유지 → 예약 도메인), 복원 meta의 정확 비교에 `suspect` 추가, 스텁 판정 표식의 `example.com`을 테스트 주소 넷으로 좁혔다.
- 가짜 전화번호 대역: 공식 가상 번호 대역을 찾지 못했다(검색 2026-10-30 — 영화진흥위원회가 영화 제작사에 개별 번호를 주는 정도). README 한계에 제3자 번호 위험을 적었다.

---

## D-114. 실 공급자 2턴 확인 — D-111 §6 사전 등록 실행 (2026-10-30, PLAN 7단계)

### 1. 근거

- D-111이 대체값을 결정적으로 바꾼 이유(둘째 턴의 thinking 서명 검사와 프롬프트 캐시)는 공급자 문서 근거였고 실 API로 재현하지 않았다. 사전 등록(D-111 §6)은 `4c1731c`에 커밋됐다.
- 2026-10-30 claude-api 스킬 문서로 확인한 것: Claude Haiku 5.5는 thinking이 기본으로 켜져 있고(adaptive, 표시 기본 `omitted` — thinking 텍스트는 빈 문자열이고 서명만 온다),
  대화 이력 편집 검사(preserved thinking)를 한다 — 2026-08-31 이후 만든 계정은 기본 강제, 그 전 계정은 요청이 `thinking.block_binding.prefix_mismatch_behavior`를 넣을 때만 강제한다.
  최소 캐시 길이 512토큰(문서가 '쓰기 전에 확인'이라 적음), 단가 입력 $0.10·출력 $0.50/MTok(프롬프트 10만 토큰 이하), 캐시 읽기 0.1배·5분 캐시 쓰기 1.25배.
- 샌드박스에서 `api.anthropic.com`에 닿는다(무인증 `GET /v1/models` → 401). 세션이 직접 실행한다.

### 2. 결정 (사전 등록이 정하지 않은 실행 세부만 — 질문·두 팔·대화 수·성공 기준·비용 상한은 D-111 §6 그대로)

1. `scripts/check_multiturn_claude.py`가 httpx로 와이어 형식을 직접 보낸다. 이 측정의 핵심은 게이트웨이가 돌려준 JSON `content`를 그대로 다음 턴에 붙이는 것인데,
   SDK는 응답을 모델 객체로 바꿨다가 다시 직렬화하고 프로젝트 의존성에도 없다.
2. 옛 팔 A: `git worktree add --detach <임시 폴더> research-final`, 그 폴더를 작업 폴더로 같은 venv의 uvicorn을 띄운다. `/__gateway/health`의 코드 지문이 `ac56e263ddc6`(D-107)이
   아니면 보내지 않는다. 새 팔 B: 현재 트리, `/__gateway/info`의 지문이 현재 코드 지문과 같아야 한다. 두 팔 모두 제품 기본 검사기(injection observe + pii mask —
   시작 때 확인), 클라이언트 키(`GATEWAY_CLIENT_KEYS`)와 같은 상류 키(`GATEWAY_UPSTREAM_KEY` = `.env`의 `ANTHROPIC_API_KEY`). B의 대체값 키는 실행마다 무작위로 만든다.
3. 순서: 대화마다 A 2턴 → B 2턴. 시간에 따른 차이가 두 팔에 고르게 간다.
4. system: 가상 쇼핑몰의 환불·교환 규정(합성, 개인정보 꼴 없음 — 보내기 전에 탐지기로 0건 확인). 길이는 무료 `count_tokens`(개인정보 없이 system만)로 재고, 최소 캐시 길이의 두 배
   (1,024토큰)에 못 미치면 보내지 않는다. 모델 이름이 거절되는지도 이 무료 호출에서 먼저 본다(거절되면 `claude-sonnet-5-5`, 사전 등록대로 기록).
5. 턴 1 user: 반품 가능 여부와 고객 부담 금액을 규정에서 따지고 연락처를 넣은 회신 초안을 쓰게 한다 — 추론이 필요해야 thinking 블록이 생기고, 그래야 턴 2가 서명 검사를 받는다.
   effort는 넣지 않는다(기본 medium). 턴 2 user: 연락처를 한 줄씩 다시 적어 달라.
6. 기록(사전 등록 항목에 더해): 턴 1 응답의 thinking 블록 수 = 턴 2가 다시 보낸 수(서명 검사가 실제로 돌았는지), `stop_reason`, B의 `suspect`, 시도 번호. 오류 문구 속 합성 값은
   `<원문>`으로 바꾼다. 답 본문은 남기지 않고 원래 값이 있었는지만 남긴다.
7. 판정의 조작적 정의: 복원 = 응답마다 `residual_tokens == 0`(B는 `suspect == 0`도)이고 턴 2 답에 원래 전화·이메일이 둘 다 있다. A의 400은 오류 문구가 '다른 대화에 묶임'
   (`different conversation`)일 때만 prefix 불일치로 센다.
8. `--stub`: 스텁 상류(`stub-thinking`)로 두 팔의 배선만 확인한다(비용 0, 판정 없음, 기록은 임시 폴더).

### 3. 버린 대안

- SDK(`anthropic`)로 보내기 — §2-1.
- `drop_block` 모드: 400 대신 `input_transformations`로 보고받는다. 사전 등록이 `error`(400)를 기준으로 정했다.
- effort `high`: thinking이 더 확실히 생기지만 사전 등록의 `max_tokens` 1024 안에서 답이 잘릴 수 있다.

### 4. 완료 기준 (= D-111 §6 성공 기준)

| # | 기준 |
|---|---|
| P1 | B: 10건 중 400 0건 |
| P2 | B: 턴 2 `cache_read_input_tokens > 0`이 5/5 대화 |
| P3 | B: 10건 모두 잔여 0(의심 잔여 0 포함), 턴 2 답에 원래 전화·이메일 |
| P4 | A(양성 대조): 대화 하나 이상에서 턴 2가 400(prefix 불일치)이거나 `cache_read_input_tokens == 0`. 재현되지 않으면 그대로 적는다(B의 실패는 아니다) |
| P5 | 누적 비용 ≤ $1 |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- 대화 5개·모델 하나·하루. 두 팔의 차이는 기제를 확인할 뿐 비율을 추정하지 않는다.
- 요청마다 `prefix_mismatch_behavior: "error"`를 넣어 계정 생성일과 무관하게 검사를 강제했다. 그 필드 없이 보내는 클라이언트는 2026-08-31 이전 계정에서 400 없이 통과한다 —
  서명만 보면 옛 코드도 '동작하는 것처럼' 보인다. 캐시 미스는 계정과 무관하다.
- 스트리밍·도구 호출·OpenAI 형식은 재지 않는다.

### 6. 결과 (2026-10-30)

- **사전 등록 성공 기준 충족, 옛 팔 재현.** 요약 [`docs/verification/multiturn_claude.md`](docs/verification/multiturn_claude.md), 원자료 같은 폴더의 jsonl(22줄, 키·합성 원문·답 본문 없음).
  모델 `claude-haiku-5-5`(거절되지 않음), 베타 헤더·`block_binding` 받아들여짐(다시 돌지 않음), system 5,192토큰(`count_tokens`), 비용 $0.0130.
- P1 B 400 0/10 · P2 B 턴 2 캐시 읽기 5/5(5,443~5,447토큰 — 대화마다 턴 1의 캐시 쓰기와 같은 양) · P3 B 잔여 0·의심 0, 턴 2 답 5/5에 원래 전화·이메일(복원 2) ·
  **P4 A 턴 2 400 5/5** — ``Invalid `signature` in `thinking` block. The block is bound to a different conversation. … first at `messages.0.content.0` `` · P5 $0.0130.
  B의 턴 2는 대화마다 thinking 블록 1개를 실제로 다시 보냈다(서명 검사가 돌았다), `input_transformations`는 10건 모두 `[]`.
- **계획과 다른 점**: 턴 1은 10건 모두 `stop_reason: max_tokens`(출력 1,024 — 사전 등록값)이고 답에 연락처가 없었다. 턴 1 답의 복원은 시험되지 않았다. 서명·캐시 질문에는
  영향이 없고 비스트리밍 Messages 응답 복원은 턴 2에서 5/5 확인했다. 다시 재지 않는다 — 더 큰 `max_tokens`로 다시 재려면 새 사전 등록이 먼저다.
- 바꾼 것: `scripts/check_multiturn_claude.py`(새), `tests/conftest.py`의 `serve`에 `cwd`(다른 작업 트리의 게이트웨이), README 1절에 확인 한 줄.
  `--stub`으로 두 팔 배선을 먼저 확인했다(옛 팔은 비스트리밍 thinking까지 복원해 턴 1 복원 수가 4 — D-112가 고친 결함이 옛 코드에 그대로 보인다).
- 전체 `pytest -q` 438 통과(게이트웨이 코드 변경 없음), `ruff check .` 통과.

---

## D-115. PII 평가 코퍼스 + CI 오탐 게이트(기준선) (2026-10-30, PLAN 8단계)

### 1. 근거

- 지금 PII 오탐 수치는 HR 한 도메인 89문항의 1.0%(Wilson 95% 0.2~5.4%)뿐이고 종류별 재현율은 잰 적이 없다. 9단계(정규화·오탐 축소)와 10단계(식별자 확장)가 탐지를 바꾸기 전에
  같은 자를 만들어 지금 값을 잰다. 검토 추정: 13~19자리 숫자의 약 10%가 Luhn을 통과해 카드로 가려진다.
- 마스킹은 `find_all`이 낸 것을 신뢰도(strong·weak)와 무관하게 전부 가린다(`PIIDetector.inspect`). 그래서 자는 `find_all`을 직접 잰다 — 탐지 = 마스킹이다.

### 2. 결정

1. `eval/pii/make_corpus.py`(시드 고정, 표준 라이브러리만)가 `eval/pii/corpus.jsonl`과 `eval/pii/hard.jsonl`을 쓴다. 두 파일을 커밋하고, 테스트가 생성기 출력과 바이트까지 같은지
   본다 — 자가 몰래 바뀌지 않는다. 한 줄: `{"id", "set": "pos"|"neg", "group", "text", "spans": [{"kind", "start", "end"}], "ctx"}`.
2. **양성** 종류마다 100건(500건), 문장 하나에 값 하나, 정답 구간은 값을 끼워 넣을 때 기록한다. 위치(앞·가운데·끝·괄호·JSON·조사 붙음)와 구분자를 섞는다.
   - rrn: 검증식 통과 50·실패 50(2020-10 이후 번호는 검증식이 없다 — 둘 다 진짜 주민번호다), 하이픈·공백·구분자 없음, 문맥어(주민·생년 등) 있음·없음을 섞는다(`ctx`).
     성별 자리는 1~4만 — 외국인등록번호(5~8)는 10단계에서 따로 넣는다.
   - card: 발급사 범위(Visa 4·Master 51~55·2221~2720·Amex 34/37·JCB 3528~3589·UnionPay 62)와 길이, Luhn 통과만. **Luhn 실패 군은 두지 않는다** — Luhn을 통과하지 않는
     번호는 카드 번호가 아니고, 오타 난 카드 번호의 정답은 정할 수 없다.
   - phone: 휴대전화(하이픈·붙임·점·공백), 옛 01X, 서울 02·지역번호, 괄호 지역번호, `+82`, 외국 번호, 인터넷 전화 070.
   - email: 예약 도메인(`example.com`·`.net`·`.org`·`*.example`)만, 점·밑줄·하이픈·숫자·`+`·대문자·하위 도메인.
   - secret: OpenAI·Anthropic·AWS·GitHub·Google·Slack·JWT·PEM(본문은 무작위).
3. **음성** 1,000건 = 10묶음 × 100: 주문·상품 코드·바코드, 송장, 타임스탬프, Snowflake ID, IMEI, diff 줄, 로그, 버전, 내선·대표번호, 금액·날짜·수량. 개인정보가 없다 —
   무엇이든 잡히면 오탐이다. 앞자리 0인 무작위 숫자는 만들지 않는다(전화번호 꼴과 겹친다). IPv4·계좌·사업자번호는 10단계가 종류로 넣을 수 있어 음성에 넣지 않는다.
4. **어려운 사례** `hard.jsonl`: 손으로 고른 양성·음성(전각 숫자·제로폭·대시 구분자·글자에 붙은 번호·IMEI·바코드·`git@` 주소·`sk-`로 시작하는 낱말 등). 지금 틀리는 꼴을
   일부러 넣었다 — 게이트에 넣지 않고 점수표에 따로 보인다.
5. **점수** `eval/pii/score.py`: 양성은 같은 종류의 탐지가 정답 구간을 **전부 덮을 때만** 맞힘(일부만 덮으면 값이 샌다). 음성은 그 종류의 탐지가 하나라도 있으면 그 종류의 오탐,
   아무 종류든 있으면 전체 오탐. 종류별 재현율·오탐률과 Wilson 95% 구간, 묶음별 표를 마크다운으로 낸다.
6. **게이트** `tests/test_pii_corpus.py`: 목표는 종류마다 오탐 1% 이하(1,000건 중 10건)와 전체 오탐 1% 이하, 체크섬 종류(rrn·card) 재현율 99% 이상. 기준선이 목표를 넘으면
   게이트는 목표, 못 미치면 기준선 값(건수)에 둔다 — 9단계가 조인다. 게이트 값은 테스트에 숫자로 적어, 바꾸려면 결정을 먼저 적게 한다.

### 3. 버린 대안

- 공개 PII 데이터셋: 한국 식별자 꼴과 숫자 밀도 높은 업무 문장이 거의 없고, 실제 개인정보가 섞일 수 있다.
- 매번 생성(파일 없이): 생성기 코드를 고치면 자가 조용히 바뀐다. 파일을 커밋하고 재현을 시험한다.
- 일부 덮음도 맞힘으로: 가린 뒤에도 값의 일부가 상류로 간다.

### 4. 완료 기준

| # | 기준 |
|---|---|
| E1 | `make_corpus.py`를 다시 돌리면 두 파일이 바이트까지 같다(테스트) |
| E2 | 양성 500(종류마다 100)·음성 1,000·정답 구간이 값과 맞다(생성기 자체 검사) |
| E3 | `score.py`가 종류별·묶음별 표와 Wilson 구간을 낸다(테스트가 실행) |
| E4 | 게이트 테스트가 CI(pytest)에서 돈다. 기준선 표가 이 결정에 있다 |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- 합성 문장이다 — 실제 트래픽의 분포가 아니다. 오탐률은 '숫자가 빽빽한 업무 문장'이라는 어려운 쪽 표본의 값이고, 일반 대화의 오탐률은 이보다 낮을 것이다.
- 한 문장에 값 하나. 값이 여러 개 붙어 있는 표·CSV는 재지 않는다.
- 생성 규칙이 탐지 규칙을 닮을 위험: 양성 꼴은 탐지 정규식이 아니라 실제 번호 체계(발급사 범위·지역번호·키 형식)에서 골랐고, 지금 못 잡는 꼴(070·대시·전각)도 넣었다.

### 6. 결과 (2026-10-30)

- E1~E4 통과(`tests/test_pii_corpus.py` 4건). 코퍼스 1,500줄(228KB)·어려운 사례 27줄. 생성기는 3.14와 3.12에서 바이트까지 같은 파일을 낸다(CI 행렬).
- **기준선**(`python3 eval/pii/score.py`, 커밋 시점 탐지):

| 종류 | 재현율 | 95% 구간 | 오탐(음성 1,000건) | 95% 구간 |
|---|---|---|---|---|
| rrn | 100/100 | 96.3~100.0% | 6 (0.6%) | 0.3~1.3% |
| card | 100/100 | 96.3~100.0% | **117 (11.7%)** | 9.9~13.8% |
| phone | **96/100** | 90.2~98.4% | 0 | 0.0~0.4% |
| email | 100/100 | 96.3~100.0% | 0 | 0.0~0.4% |
| secret | 100/100 | 96.3~100.0% | 0 | 0.0~0.4% |
| 전체 | 496/500 (99.2%) | 98.0~99.7% | **123 (12.3%)** | 10.4~14.5% |

  - 놓친 양성 4건은 모두 인터넷 전화 070(4/4) — 전화 패턴의 접두사에 070이 없다. 나머지 묶음은 전부 맞혔다(주민번호 검증식 실패·구분자 없음 포함).
  - 오탐은 card가 거의 전부다: IMEI 100/100(15자리, Luhn을 통과하도록 만들어지는 번호), Snowflake 8, 주문·바코드 5, 송장 3, 밀리초 타임스탬프 1. rrn 6은 주문(국내 바코드
    880으로 시작하는 EAN-13 — 앞 6자리가 '88년 월일'로 읽힌다)과 13자리 송장. diff·로그·버전·내선·금액 묶음은 0.
  - 어려운 사례: 전각 숫자·제로폭·en 대시·하이픈 앞뒤 공백·점 구분 카드·전각 @·영문자에 붙은 번호를 놓친다(17건 중 8건 맞힘). IMEI·국내 바코드·`git@` 주소·`sk-learn…`
    낱말·날짜-일련번호 주문번호를 오탐한다(10건 중 5건 통과).
- **게이트**(테스트에 숫자로): 재현율 하한 rrn 99·card 99(목표), phone 96·email 100·secret 100(목표 없음 → 기준선). 오탐 상한 rrn·phone·email·secret 10(목표),
  card 117·전체 123(기준선 — 목표 10에 못 미친다, 9단계가 조인다).
- **보강(같은 날, 커밋 전)**: GitHub push protection이 코퍼스의 합성 Slack 토큰 8건을 'Slack API Token'으로 막았다 — 생성기가 실제 봇 토큰 형식(`xoxb-` + 숫자 12 + 숫자 13 + 영숫자 24) 그대로 만들었다. 같은 글자를 6자 묶음으로 다시 자른다(`slack()`, 난수 소비가 같아 다른 1,492줄은 바이트까지 그대로).
  우리 패턴(`xox[abprs]-[A-Za-z0-9-]{10,}`)에는 그대로 걸려 점수·게이트는 바뀌지 않았다(secret/slack 8/8). 한계: Slack 재현율은 실제 형식이 아닌 꼴로 잰 값이고,
  Google·AWS 같은 정확한 길이의 키는 우리 패턴이 곧 실제 형식이라 다르게 만들 수 없다 — 이번에는 막히지 않았다.
  독립 검증(2026-10-30): 새 모양은 구조를 보는 공개 Slack 패턴(trufflehog v3·gitleaks·truffleHog v2) 어디에도 맞지 않고, 글자 집합만 보는 패턴(detect-secrets·
  secrets-patterns-db)과 우리 패턴에는 맞는다. gitleaks 기본 규칙은 코퍼스의 다른 합성 키(Anthropic·GitHub·AWS·JWT·PEM·Google)를 여전히 보고한다 —
  CI에 비밀 검사를 넣을 때는 `eval/pii/`만 허용 목록에 둔다(PLAN 20단계).
- 전체 `pytest -q` 442 통과, `ruff check .` 통과.

---

## D-116. 정규화 + 오탐 축소 — 전각·제로폭·대시, 문맥 없는 약한 주민번호, 발급사 범위 밖 카드 (2026-10-30, PLAN 9단계)

### 1. 근거 (D-115 기준선)

- 정규화 층이 없다. 어려운 사례에서 전각 숫자(`０１０－…`)·제로폭 공백·en 대시(`–`)로 쓴 전화·주민번호·카드, 전각 `＠` 이메일을 모두 놓친다. 인젝션 룰도 같은 우회에 열려 있다.
- 오탐 123/1,000(12.3%)의 95%가 카드다 — IMEI 100/100(15자리, 원래 Luhn을 맞추게 만드는 번호), Snowflake 8, 주문·바코드 5, 송장 3. 주민번호 오탐 6은 구분자 없는 13자리
  (국내 바코드 `880…`의 앞 6자리가 '88년 월일'로 읽힌다, 13자리 송장)다.
- 국내 전용 카드는 첫 자리 9로 시작한다(MII 9 = 국가 지정, 원래 `9410` + 국가번호 — 토스페이먼츠 개발자 문서 'BIN', 나무위키 'BIN(카드)'의 `9300`·`9400`·`9416`·`9445`·`9490` 예,
  2026-10-30 검색).

### 2. 결정

1. **정규화**(`patterns.normalize`): 글자마다 NFKC(전각 숫자·문자·`＠`·NBSP), 서식 문자(Unicode Cf — 제로폭·방향 제어·태그 문자) 제거, 대시 변형(‐ ‑ ‒ – — ― − ﹘ ﹣)은 `-`,
   가운뎃점(· ・ ㆍ)은 `.`. 한글 음절과 호환 자모는 그대로 둔다(NFKC가 호환 자모를 조합형으로 바꾼다 — 탐지와 무관하고 인젝션 어휘를 흔든다). 바뀐 글자의 (정규화 위치, 길이, 원문 위치)만
   기록하고 그 사이는 1:1로 본다 — 원문 위치 되돌리기는 이분 탐색이다. ASCII 텍스트는 그대로(빠른 길).
2. `find_all`은 정규화한 텍스트에서 찾고 **원문 위치**를 돌려준다. 호출자(검사기·볼트·테스트)는 바뀌지 않는다 — 대체값은 원문 자리에 들어가고, 복원은 사용자가 쓴 원문(전각 그대로)을
   돌려준다. 볼트는 대체값을 정규화한 값으로 만들고(상류는 ASCII 모양을 본다), 복원 키(`norm_key`)도 정규화한다.
3. **가릴지(`Finding.mask`)**: 탐지는 그대로 다 내고, 가리지 않을 것만 표시한다 — 볼트는 표시와 무관하게 모든 탐지로 대체값을 되찾는다(가리지 않는 꼴의 대체값도 복원돼야 한다).
   - 주민번호: 검증식 통과는 가린다. 실패(2020-10 이후 번호는 검증식이 없다)는 구분자(하이픈·공백)가 있으면 가리고, **구분자 없는 13자리는 문맥어**(주민·생년·등록번호·외국인·RRN·
     resident)가 앞뒤 20자 안에 있을 때만 가린다.
   - 카드(Luhn 통과 13~19자리): 발급사 범위와 길이가 맞으면 가린다 — Visa 4(13·16·19), Master 51~55·2221~2720(16), Amex 34·37(15), JCB 3528~3589(16~19),
     UnionPay 62·Discover 6011·644~649·65(16~19), Diners 300~305·36·38·39(14~19), 국내 전용 9(16). 범위 밖은 카드 문맥어(카드·card·신용·credit·비자·visa·마스터·
     master·amex·jcb·은련·unionpay)가 앞뒤 20자 안에 있을 때만. 계획의 목록(4·51~55·2221~2720·34·37·35·62)에 Discover·Diners·국내 전용을 더했다 — 빼면 지금 가리는
     카드가 문맥 없이는 새게 된다.
   - 가리지 않는 탐지는 감사에 남는다: 검사기 meta의 `pii`는 가린 것만(지표 `gateway_pii_masked_total`이 맞게), `unmasked`에 종류별 건수, 위치 목록의 항목에 `"mask": false`.
     mask 모드의 413 상한(D-110)은 가리는 건수로 센다.
4. 인젝션 룰은 정규화한 텍스트를 본다(위치를 쓰지 않으므로 텍스트만 바꾼다).
5. 점수(`eval/pii/score.py`)는 **가리는 것만** 센다 — 감사에만 남는 탐지는 값이 상류로 가므로 맞힘이 아니고, 텍스트를 바꾸지 않으므로 오탐도 아니다. 코퍼스는 바꾸지 않는다(같은 자).
6. 게이트를 목표로 조인다: 오탐 종류마다·전체 10건(1%) 이하, card 재현율 99 이상. **rrn은 검증식 통과 값의 재현율 99%**(체크섬 종류의 목표를 체크섬이 있는 값에 둔다) —
   구분자·문맥 없는 검증식 실패 값은 설계상 감사만 남기므로 전체 rrn 재현율은 측정값에 두고 결과에 적는다. phone·email·secret은 기준선 그대로.

### 3. 버린 대안

- 텍스트 전체 NFKC 후 정렬로 위치 맞추기: 글자 수가 바뀌면 위치가 어긋난다. 글자 단위로 기록한다.
- 문맥 없는 약한 주민번호를 떨어뜨리기(탐지에서 뺌): 그 꼴의 대체값을 응답에서 되찾지 못한다. 탐지하되 가리지 않는다.
- 카드 문맥어에 '결제'·'승인': 주문·정산 문장에 흔해 범위 밖 주문번호를 가리게 된다.
- 점 구분 카드(`4111.1111.…`)와 하이픈 앞뒤 공백 주민번호: 소수점·범위 표기와 겹친다. 어려운 사례로 남긴다.

### 4. 완료 기준 (`tests/test_d116_normalize.py`, `tests/test_pii_corpus.py`)

| # | 기준 |
|---|---|
| N1 | 정규화 위치 되돌리기: 전각·제로폭·대시·NBSP·확장 글자(`①`·`㈜`)가 섞여도 탐지 구간이 원문의 값 전체를 정확히 덮는다 |
| N2 | 전각·제로폭·대시로 쓴 전화·주민번호·카드·이메일이 가려지고(상류는 ASCII 대체값), 응답에서 사용자가 쓴 원문 그대로 복원된다 |
| N3 | 구분자 없는 약한 주민번호: 문맥 없으면 가리지 않고 감사(`unmasked`)에 남는다, 문맥어가 있으면 가린다. 하이픈 꼴·검증식 통과는 문맥 없이 가린다 |
| N4 | IMEI는 가리지 않는다, 범위 밖 Luhn 숫자열은 카드 문맥어가 있으면 가린다, 국내 전용 9·Discover·Diners는 가린다 |
| N5 | 가리지 않는 꼴의 대체값(범위 밖 카드 대체값, 문맥 없는 주민번호 대체값)도 응답에서 복원된다 |
| N6 | 인젝션 룰이 전각·제로폭으로 쓴 공격 문구에 걸린다 |
| N7 | 게이트 목표 통과(위 2-6), 어려운 사례의 정규화 묶음(전각·제로폭·대시) 맞힘 |
| N8 | 1MiB 탐지 시간 기록(한국어 + 특수 글자 섞음) |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- 문맥어 창은 앞뒤 20자 고정이다. 표·CSV처럼 머리줄에만 '주민번호'가 있으면 그 아래 구분자 없는 약한 번호는 가리지 않는다.
- 발급사 범위는 2026-10 기준의 공개 표다. 새 범위가 생기면 문맥어 없이는 새어 나간다(감사의 `unmasked`로 보인다).
- 태그 문자(U+E0000대)는 지우기만 한다 — 그 안에 숨긴 ASCII를 풀어 인젝션 룰에 보이지는 않는다.
- 정규화는 글자 단위 NFKC라 결합 문자열의 조합 차이는 보지 않는다(숫자·기호 탐지에는 무관).

### 6. 결과 (2026-10-30)

- N1~N8 통과(`tests/test_d116_normalize.py` 31건), 게이트를 목표로 조였다(`tests/test_pii_corpus.py`). 전체 `pytest -q` 473 통과, `ruff check .` 통과. 데모 6장면·Anthropic SDK
  점검 재통과(OpenAI SDK는 점검용 venv에 없어 돌리지 않았다 — OpenAI 경로는 pytest가 본다).
- **코퍼스 점수**(같은 자, D-115 대비):

| 종류 | 재현율 D-115 → D-116 | 오탐(음성 1,000건) D-115 → D-116 |
|---|---|---|
| rrn | 100 → **98** | 6 → **1** |
| card | 100 → 100 | 117 → **2** |
| phone | 96 → 96 | 0 → 0 |
| email | 100 → 100 | 0 → 0 |
| secret | 100 → 100 | 0 → 0 |
| 전체 | 496/500 → 494/500 (98.8%, 95% 97.4~99.4%) | 123 → **3** (0.3%, 95% 0.1~0.9%) |

  - rrn에서 빠진 2건은 설계대로다 — 검증식 실패·구분자 없음·문맥어 없음(`rrn/fail-nosep` 8/10). 검증식을 통과하는 주민번호는 55/55. 남은 오탐 3건: 주문(rrn 1·card 1 —
    범위 안에 든 Luhn 통과 번호와 검증식까지 맞은 13자리), Snowflake 1(19자리 Visa 꼴). IMEI 100 → 0, 송장 3 → 0, 타임스탬프 1 → 0.
  - 게이트: 오탐 종류마다·전체 10 이하(목표), card 재현율 99·검증식 통과 rrn 99%(목표), rrn 전체 98(측정값), phone 96·email 100·secret 100(기준선).
- **어려운 사례**: 양성 8/17 → 14/17(전각 전화·주민번호·카드·`＠`, 제로폭, en 대시를 맞힘). 아직 놓침: 영문자에 붙은 번호, 하이픈 앞뒤 공백 주민번호, 점 구분 카드.
  음성 5/10 → 7/10(IMEI·국내 바코드 통과). 아직 오탐: `git@github.com:` 주소(이메일), `sk-learn-…` 낱말(자격 증명), 날짜-일련번호 주문번호(하이픈 꼴 주민번호).
- 1MiB(한국어 + 전각·제로폭·㈜ 섞음) `find_all` 0.17초(맥북). ASCII 텍스트는 정규화 없이 지나간다.
- 계획과 다른 점: 카드 발급사 목록에 Discover·Diners·국내 전용 9를 더했다(§2-3). rrn 재현율 목표를 검증식 통과 값에 둔다(§2-6). 점수는 가리는 탐지만 센다(§2-5).

---

## D-117. 한국 식별자 확장 — 외국인등록번호·여권·운전면허·사업자·법인·계좌·IPv4, 인터넷 전화 070 (2026-10-30, PLAN 10단계)

### 1. 근거

- 법정 고유식별정보 4종(주민등록번호·여권번호·운전면허번호·외국인등록번호, 개인정보 보호법 시행령 제19조) 중 주민번호만 잡는다. 외국인등록번호는 주민번호 패턴의
  성별 자리 5~8로 걸려 `rrn`이라 불리고, 여권·운전면허는 잡지 못한다. D-115 기준선에서 인터넷 전화 070을 4/4 놓쳤다.
- Presidio(MIT)가 한국 인식기 5종을 공식 지원한다 — 2026-10-30 `microsoft/presidio` main의
  `presidio-analyzer/presidio_analyzer/predefined_recognizers/country_specific/korea/`를 읽고 대조했다. '한국형 PII'는 차별점이 아니라 따라가야 할 기준이다.

| 종류 | Presidio(패턴·점수·검증) | 이 결정 |
|---|---|---|
| KR_RRN | `\d{2}(0[1-9]\|1[0-2])(0[1-9]\|[12]\d\|3[01])(-?)[1-4]\d{6}` 0.5. 지역 자리(8~9번째) ≤ 95이고 검증식 (11 − 합 mod 11) mod 10이 맞으면 True, 아니면 None(버리지 않음) | 그대로(D-116): 실제 날짜(윤년), 구분자 `-`·공백, 검증식은 등급, 구분자 없는 약한 값은 문맥어. 지역 자리는 보지 않는다(2020-10 이후 임의 번호) |
| KR_FRN | 같은 꼴, 성별 5~8. 검증식 (13 − 합 mod 11) mod 10 | 주민번호 패턴에서 성별 5~8을 `frn`으로 가른다. 검증식은 등급, 가릴지는 주민번호와 같은 규칙 |
| KR_BRN | `\d{3}-\d{2}-\d{5}` 0.1, `\d{10}` 0.05. 가중치 1,3,7,1,3,7,1,3,5 + ⌊5·9번째/10⌋, (10 − 합 mod 10) mod 10, 실패는 False | 하이픈 꼴 + 검증식만 |
| KR_PASSPORT | `[MmSsRrOoDd]\d{3}[A-Za-z]\d{4}` 0.1(2021-12 차세대), `[MmSsRrOoDd]\d{8}` 0.05(구형), 검증 없음, 문맥어 여권·passport | 대문자만. 신형은 문맥 없이 가리고, 구형(글자 + 8자리)은 문맥어가 있을 때만 가린다 |
| KR_DRIVER_LICENSE | `(\d{2})[- ]?(\d{2})[- ]?(\d{6})[- ]?(\d{2})` 0.05, 지역 11~26·28 | 하이픈 꼴(2-2-6-2) + 같은 지역 목록 |

  Presidio에 없는 것: 법인등록번호 — 앞 12자리에 1·2를 번갈아 곱한 합(자리 나눔 없음)의 (10 − 합 mod 10) mod 10(공개 구현 gist `susemeee/ccf35b90806bc29ee465420696cd2e26`,
  공시된 삼성전자 130111-0006246으로 검산: 합 34 → 6). 계좌번호 — 은행별 묶음(나무위키 '계좌번호', 은행별 형식 표 nanumtip.com, 2026-10-30 검색).
  운전면허 지역은 2014-07부터 숫자(서울 11·부산 12·경기 13…, 도로교통공단·재외공관 공지 '운전면허번호 지역표기 변경'). IPv4는 표준 라이브러리 `ipaddress`.

### 2. 결정

1. **탐지는 모양만, 문맥어는 가릴지(`Finding.mask`)만 정한다**(D-116 §2-3을 넓힌다). 볼트는 응답을 같은 패턴으로 훑어 대체값을 되찾으므로, 대체값은 문맥어 없이도 같은 종류로
   다시 걸려야 한다. 그래서 문맥 없이는 너무 흔한 꼴(구분자 없는 10·12자리, 띄어 쓴 계좌)은 종류로 넣지 않는다 — 문맥어로만 찾으면 응답에서 문맥 없이 돌아온 대체값을
   못 되찾아 사용자가 가짜 번호를 받는다.
2. 새 종류(`Finding.kind`)와 규칙:

| 종류 | 탐지(모양) | 가린다(`mask`) | 대체값(D-111 결정적 시드) | 기본 |
|---|---|---|---|---|
| `frn` 외국인등록번호 | 주민번호 패턴, 실제 날짜, 성별 5~8 | 검증식 통과, 구분자 있음, 또는 문맥어(주민·생년·등록번호·외국인·RRN·FRN·resident·alien·foreigner) | 주민번호와 같고 성별 5~8 | 가림 |
| `passport` 여권 | `[MSROD]` + 8자리, 또는 + 3자리 + 대문자 + 4자리. 앞뒤에 영숫자·하이픈 없음 | 신형은 늘, 구형은 문맥어(여권·passport) | 첫 글자 유지, 숫자→숫자, 대문자→대문자 | 가림 |
| `driver` 운전면허 | `\d{2}-\d{2}-\d{6}-\d{2}`, 앞 2자리가 지역(11~26·28) | 늘 | 지역 2자리 유지, 나머지 무작위 | 가림 |
| `brn` 사업자등록번호 | `\d{3}-\d{2}-\d{5}` + 검증식 | 늘 | 앞 5자리(세무서·구분) 유지, 일련 4자리 무작위, 검증 숫자 계산 | **감사만** |
| `crn` 법인등록번호 | `\d{6}-\d{7}` + 검증식, 주민번호 꼴이 아닐 때(아래 4) | 늘 | 앞 7자리 유지, 나머지 무작위, 검증 숫자 계산 | **감사만** |
| `account` 계좌번호 | 하이픈 묶음 길이가 은행별 꼴(3-2-4-3·6-2-6·3-6-2-3·3-4-4-2·3-4-4-3·3-2-6·3-3-6·4-3-6·3-6-5·3-6-3·4-2-7·4-4-4·4-4-4-1·3-2-5-1) | 문맥어(계좌·입금·송금·이체·예금·은행·뱅크·주요 은행 이름·account·bank) | 앞 3자리 유지, 나머지 무작위, 묶음 유지 | **감사만** |
| `ipv4` | 점 네 묶음(0~255), 앞에 영숫자·점·`_`·`-`·`글자/`(UA 토큰) 없음, 뒤에 `.숫자` 없음. 공인 주소(`is_global`, 멀티캐스트 제외)이고 끝 묶음이 0이 아닐 때만 | 버전 문맥어(버전·빌드·펌웨어·version·build·release·firmware)가 없을 때 | 첫 묶음 유지, 나머지 무작위 공인 주소(끝 1~254) | **감사만** |
| `phone` | 국내 접두사에 인터넷 전화 070 추가 | 그대로 | 070 유지 | 가림 |

3. 하이픈 묶음 숫자는 패턴 하나(`GROUPED_RE`)로 찾고 묶음 길이로 사업자(3-2-5)·법인(6-7)·운전면허(2-2-6-2)·계좌를 가른다 — 정규식 한 번에 네 종류.
4. **겹침**: 우선순위 secret > rrn > frn > crn > account > card > phone > driver > brn > email > passport > ipv4. 주민번호 꼴(실제 날짜 + 성별 1~8)은 주민·외국인 번호다 —
   틀려도 '가림' 쪽으로 틀린다. 예외 하나: 주민·외국인 검증식이 맞지 않는 하이픈 6-7이 법인 검증식에 맞고 앞뒤 20자 안에 '법인'이 있으면 법인등록번호로 본다
   (서울 주식회사의 `110111-1…`처럼 주민번호 꼴인 법인번호가 많다). 계좌를 카드보다 앞에 둔다 — 은행 꼴의 숫자가 Luhn을 우연히 맞춰 문맥 없는 카드로 잡히면
   계좌 문맥어가 있어도 가리지 못한다. 이메일은 여권보다 앞 — `M12345678@…`의 로컬파트만 여권으로 가리면 도메인이 남는다.
5. **기본 모드**: 사람을 식별하는 번호(rrn·frn·passport·driver)와 card·phone·email·secret은 가린다. 계좌(계획대로 — 은행마다 꼴이 다르고 검증식이 없다)·사업자·법인 번호
   (공개 의무가 있는 사업체 식별자)·IPv4(개발 대화의 서버 주소가 대부분이라 가리면 질문의 뜻이 바뀐다)는 탐지해 감사(`unmasked`)에만 남긴다. 새 설정
   `GATEWAY_PII_DETECT_KINDS`(쉼표, 기본 `account,brn,crn,ipv4`) — 목록에서 빼면 가린다. `GATEWAY_PII_KINDS`의 기본은 모든 종류. 두 설정 모두 모르는 이름은 기동 실패.
6. 볼트: 새 숫자 종류(frn·crn·brn·driver·account)는 복원 키가 숫자열이다. 스트림 보류는 점이 든 꼬리(`203.47`)도 대체값의 앞부분으로 본다.
7. **코퍼스**: 기존 1,500줄은 바이트까지 그대로 두고(같은 자로 비교), 다른 시드로 양성 700(새 종류마다 100)·음성 200(업무 코드 `codes`·네트워크 `network`)을 뒤에 붙인다.
   어려운 사례에 지원하지 않는 꼴(구분자 없는 면허·사업자·계좌, 지역명 면허, 소문자 여권, 050 안심번호)과 새 음성을 더한다. 점수는 그대로 '가리는 탐지'를 센다 —
   기본 감사만인 종류는 "운영자가 가리기로 켰을 때"의 값이다.
8. **게이트**: 오탐 종류마다·전체 1% 이하(음성 1,200건 중 12건). 재현율은 검증식·지역이 있는 종류(driver·brn) 99 이상, frn은 검증식 통과 값 99%, ipv4 99,
   crn·passport·account는 문맥에 달린 측정값(결과에 적는다), phone은 070이 들어와 100.
9. README에 종류별 커버리지 표(검증식·기본 모드·한계).

### 3. 버린 대안

- 구분자 없는 꼴을 문맥어가 있을 때만 탐지: 1항의 복원 실패. 지원하지 않는 꼴로 README에 적는다.
- 계좌·IPv4를 기본으로 가리기: 계좌는 계획의 기본값(감사만)을 따른다. IP는 `8.8.8.8`·서버 주소처럼 질문의 대상인 경우가 많다. 접속 로그를 다루는 팀은 켠다.
- 공인 IP 대체값을 문서용 대역(TEST-NET 세 개, 762개)에서: 로그 한 덩어리의 고유 주소 수에 모자라 발급이 충돌하고, 모델이 '예시 주소'로 알아본다.
- 사설·예약 IP도 탐지(감사만): 대체값이 늘 공인 주소라 복원에 필요 없고, `127.0.0.1` 같은 줄마다 감사가 시끄러워진다.
- 운전면허 지역명 꼴(`서울 07-111111-10`): 2014-07부터 숫자로 바뀌었고 10년 갱신 주기를 지나 거의 사라졌다. 스트림 조각 경계에서 지역명과 숫자가 갈리면 되찾지 못한다.
- 법인번호를 늘 주민번호보다 앞에: 2020-10 이후 주민번호(검증식 없음)의 10%가 법인 검증식을 우연히 맞춰, 기본 감사만인 `crn`으로 빠져 새어 나간다.

### 4. 완료 기준 (`tests/test_d117_kr_ids.py`, `tests/test_pii_corpus.py`)

| # | 기준 |
|---|---|
| K1 | 새 종류마다 양성 꼴이 그 종류로 잡히고 구간이 값 전체다. 검증식·지역·날짜·묶음이 틀린 꼴과 사설·예약 IP는 잡히지 않는다 |
| K2 | 성별 5~8은 `frn`. 주민 꼴 법인번호는 '법인' 문맥 + 법인 검증식 + 주민 검증식 실패일 때만 `crn` |
| K3 | 가릴지: 구형 여권·계좌는 문맥어가 있을 때만, IPv4는 버전 문맥어가 없을 때만 |
| K4 | 대체값: 모양·검증식·유지 자리가 지켜지고 다시 같은 종류로 잡히며, 같은 키·같은 원문은 같은 대체값 |
| K5 | 기본 감사만 종류는 가리지 않고 `unmasked`에 남는다. `GATEWAY_PII_DETECT_KINDS=`(빈 값)이면 가린다. 두 설정의 모르는 이름은 기동 실패 |
| K6 | 새 종류의 대체값이 응답에서 복원된다 — JSON 응답과 스트림 조각 경계(숫자·점·영문 꼬리) |
| K7 | 070 탐지, 대체값이 070을 유지 |
| K8 | 코퍼스 기존 1,500줄이 바이트까지 그대로, 2항 게이트 통과(3.12·3.14에서 같은 파일) |
| K9 | 1MiB `find_all` 시간 기록(D-116 0.17초) |
| — | 전체 `pytest -q`·`ruff check .` 통과 |

### 5. 한계

- 구분자 없는 운전면허·사업자·계좌번호, 띄어 쓴 계좌, 지역명 운전면허, 소문자 여권, 050 안심번호는 잡지 못한다(어려운 사례에 남긴다).
- 계좌 꼴은 은행 표의 묶음 길이뿐이다(은행 코드·검증식 없음). 평생계좌(전화번호 꼴)는 전화로 잡히고, 표에 없는 꼴은 놓친다. 묶음이 같은 송장·관리번호는 감사에 `account`로 남는다.
- 구형 여권(글자 + 8자리)은 문맥어가 앞뒤 20자 안에 없으면 가리지 않는다 — 표의 머리줄에만 '여권번호'가 있으면 새어 나간다(D-116 §5와 같은 한계).
- '법인' 문맥 없는 주민 꼴 법인번호는 주민번호로 가려진다(라벨이 틀리고 상류는 주민번호 꼴 가짜 값을 본다).
- 4묶음 버전 번호가 버전 문맥어 없이 쓰이면 공인 IP로 잡힌다. IPv6는 보지 않는다. 가짜 IP는 실제로 쓰이는 공인 주소일 수 있다.
- 여권 종류 글자는 Presidio·Microsoft Purview 정의(M·S·R·O·D)를 따랐다 — 그 밖의 글자로 시작하는 여권은 놓친다.

### 6. 결과 (2026-10-30)

- K1~K9 통과(`tests/test_d117_kr_ids.py` 114건), 게이트 갱신(`tests/test_pii_corpus.py`). 전체 `pytest -q` 586 통과, `ruff check .` 통과. 코퍼스 생성기·점수표는
  3.12와 3.14에서 바이트까지 같다. 데모 6장면·Anthropic SDK 점검(6/6) 재통과 — OpenAI SDK는 점검용 venv에 없어 돌리지 않았다(OpenAI 경로는 pytest가 본다).
- 바꾼 기존 테스트: `test_pii.py`의 계좌 두 문장(예전에는 미탐지가 정답 — 이제 `account`이고 전화로 오인하지 않는다), `test_d102_fixes.py`의 비교 기준
  (후보 생성은 `patterns.candidates`를 받아 겹침 해소만 비교한다 — 종류마다 탐지 규칙을 테스트에 복제하지 않는다).
- **코퍼스 점수**(가리기로 켰을 때, 음성 1,200건):

| 종류 | 재현율 | 묶음 | 오탐 |
|---|---|---|---|
| rrn | 98/100 | 검증식 통과 55/55, 실패·구분자 없음·문맥 없음 8/10 | 1 |
| frn | 95/100 | 검증식 통과 57/57, 실패·구분자 없음 5/10 | 0 |
| passport | 80/100 | 차세대 47/47, 구형 33/53(놓친 20건은 모두 문맥어 없는 문장) | 0 |
| driver | 100/100 | | 0 |
| card | 100/100 | | 2 |
| phone | **96 → 100** | 070 4/4 | 0 |
| email·secret | 100/100 | | 0 |
| brn | 100/100 | | 0 |
| crn | 89/100 | 일련번호 0으로 시작 48/48, 1~9로 시작 41/52(놓친 11건은 '법인' 없는 주민 꼴 — rrn으로 가려졌다) | 0 |
| account | 64/100 | 놓친 36건은 모두 문맥어 없는 문장 | 0 |
| ipv4 | 100/100 | | 0 |
| 전체 | 1126/1200 (93.8%, 95% 92.3~95.1%) | | **3 (0.2%, 95% 0.1~0.7%)** — 새 음성 200건(codes·network)은 0 |

  - 게이트: 오탐 종류마다·전체 12 이하(1%). 재현율 하한 driver·brn·ipv4·card 99(목표), rrn·frn 검증식 통과 값 99%(목표), phone 100·email 100·secret 100(기준선),
    rrn 98·frn 95·passport 80·crn 89·account 64(문맥에 달린 측정값).
  - 코퍼스의 앞 1,500줄은 바이트까지 그대로다(테스트가 SHA-256으로 본다) — D-115·D-116 수치와 같은 자로 비교된다. 새 양성은 탐지가 지원하는 꼴만이다(1항).
- **어려운 사례**: 양성 14/17 → 16/27, 음성 7/10 → 9/13. 새 사례 13건 중 맞힘은 주민 꼴 법인번호 + '법인'(crn)과 070, 통과는 사설 IP와 `D20261030`.
  지원하지 않는 꼴 7건(지역명·구분자 없는 면허, 구분자 없는 사업자·계좌, 띄어 쓴 계좌, 소문자 여권, 050)은 놓치고, '법인' 없는 주민 꼴 법인번호는 rrn으로 가리며,
  문맥어 없는 4묶음 버전(`패키지 2.4.1.3`)은 IPv4로 오탐한다 — 모두 README 표에 적었다.
- 1MiB `find_all`: D-116의 N8 글 0.17초 → 0.19초(같은 글, 정규식 세 번 더), 새 종류가 빽빽한 1MiB 0.31~0.36초(맥북).
- 계획과 다른 점: 계획은 계좌만 '기본 detect'라 했는데 사업자·법인·IPv4도 기본 감사만으로 두었다(§2-5). 구분자 없는 꼴과 지역명 운전면허는 넣지 않았다(§2-1, §3).
  외국인등록번호는 따로 종류가 되었지만 기본 가림은 그대로다(예전에도 rrn으로 가려졌다). 코퍼스는 새로 만들지 않고 다른 시드로 뒤에 붙였다.

---

## D-118. 설정 객체화 + main 분리 + 프로세스 안 테스트 + mypy (2026-10-30, PLAN 11단계)

### 1. 근거

- 설정이 `gateway/main.py`의 import 시점 전역(환경변수 20여 개)이고 `load_dotenv()`가 import 때 `.env`를 읽는다. 그래서 설정이 다른 게이트웨이를 띄우려면 테스트마다
  uvicorn 서브프로세스가 필요하고(테스트 586개 69초, 스택 53번 — 스택마다 프로세스 둘), 개발자의 `.env`가 테스트 게이트웨이에 새어 든다.
- `main.py` 660줄에 설정·체인 조립·미들웨어·감사 줄 모양·라우팅·관리 엔드포인트·상류 중계·스트림 펌프가 함께 있다.
- 낡은 설정: `GATEWAY_INJECTION_SCOPE=all`(다중 턴에서 이력의 공격 문장 하나로 대화 전체가 막힌다 — 연구 단계 측정 FPR 100%), `GATEWAY_CHAT_UPSTREAM_PATH`(Gemini 경로
  하나를 위한 설정 — 12단계가 상류별 설정으로 바꾼다), `GATEWAY_DETECTORS`(저수준 검사기 목록 — 테스트·데모만 쓴다).
- 타입 검사가 없다.

### 2. 결정

1. `gateway/settings.py`: `Settings`(frozen dataclass)와 `Settings.from_env(env=os.environ)` — 환경변수를 한 번 읽어 값을 바꾸고 고르는 값(`GATEWAY_INJECTION`·`GATEWAY_PII`·
   종류·역할)을 검증한다. 검사기 체인 조립(`build_chain(settings, registry)`)도 여기. 기동 거부(클라이언트 키 없음, 무인증 + 상류 키, mask인데 대체값 키 없음)는 지금처럼 lifespan에서 한다
   — import만으로는 실패하지 않는다.
2. `gateway/main.py`는 `create_app(settings, registry=DETECTOR_REGISTRY)`와 라우팅·미들웨어·관리 엔드포인트만. uvicorn용 `app = create_app(Settings.from_env())`는 남긴다.
   상류 중계·스트림 펌프는 `gateway/relay.py`, 감사 줄 모양(`record`·쿼리 키·체인 필드)은 `gateway/audit.py`로 옮긴다. 새 파일은 둘(settings·relay).
3. `.env` 자동 로드를 없앤다 — `uvicorn --env-file .env`(python-dotenv는 uvicorn의 `--env-file`이 쓰므로 의존성에 남는다).
4. 낡은 설정 제거: `GATEWAY_INJECTION_SCOPE`(차단은 늘 이번 턴), `GATEWAY_CHAT_UPSTREAM_PATH`, `GATEWAY_DETECTORS` 환경변수. 저수준 검사기 목록은 `Settings.detectors` 필드로만 남는다
   (테스트·임베딩용, 환경변수 없음). 데모·웹·SDK 점검 스크립트는 제품 설정(`GATEWAY_INJECTION`·`GATEWAY_PII`)으로 바꾼다.
5. **테스트 하네스**: `make_stack`이 스텁과 게이트웨이를 **이 프로세스의 스레드에서** uvicorn으로 띄운다(포트는 지금처럼 따로). 게이트웨이는 `create_app(Settings.from_env(env))` —
   환경변수 대신 dict를 넘기므로 개발자 환경이 새어 들지 않는다. 스텁은 앱 하나를 여러 포트에 띄우고, 받은 본문·경로 기록을 서버 포트별로 나눈다.
   서브프로세스는 다른 작업 트리(D-114 옛 팔)·stdout 로그·`python -m uvicorn` 기동 실패처럼 프로세스 자체를 보는 테스트만 쓴다.
6. CI에 mypy(관대한 설정: `ignore_missing_imports`, 엄격 옵션 없음, `gateway/`만)를 더한다. 버전은 고정한다.

### 3. 버린 대안

- 계획의 `httpx.ASGITransport` 픽스처: 응답을 다 모은 뒤 돌려줘 스트리밍 조각 경계가 사라지고(스트림 복원 테스트가 약해진다), 테스트 53곳의 `httpx.post(stack.gateway + …)`를
  모두 클라이언트 객체 호출로 고쳐야 한다. 스레드 uvicorn은 실제 HTTP·실제 스트리밍 그대로이고 테스트 호출부가 바뀌지 않는다 — 목적(프로세스 기동 비용, 설정 주입)은 같다.
- 설정 검증을 전부 import 때: `app = create_app(Settings.from_env())`가 import 시점이라, 키가 없는 환경에서 `gateway.main`을 import하는 도구·테스트가 깨진다.
- `injection_rule`(이력까지 보는 차단 검사기) 삭제: 테스트 여러 곳이 '어디에든 공격 문장이 있으면 막는' 검사기로 쓴다. 제품 설정에서만 뺀다.
- pydantic-settings: 의존성이 하나 는다. dataclass 하나로 충분하다.

### 4. 완료 기준

| # | 기준 |
|---|---|
| C1 | `Settings.from_env`가 모든 설정을 읽고, 고르는 값·종류·역할의 틀린 값은 ValueError. 기동 거부 셋은 lifespan에서(테스트) |
| C2 | 한 프로세스에 설정이 다른 게이트웨이 둘을 띄워도 서로의 설정을 보지 않는다(테스트) |
| C3 | `.env`를 읽지 않는다 — 작업 폴더의 `.env`가 `Settings.from_env({})`에 영향이 없다(테스트) |
| C4 | 지운 세 환경변수는 효과가 없다(테스트), README·데모·스크립트에서 사라진다 |
| C5 | `main.py` 300줄 이하, 순환 import 없음 |
| C6 | 전체 `pytest -q` 시간 전후 기록(전 69초), `ruff check .`·`mypy` 통과, CI에 mypy |
| — | 데모·Anthropic SDK 점검 재통과 |

### 5. 한계

- 스레드 uvicorn은 테스트 프로세스 하나에 이벤트 루프가 여럿이다 — 프로세스 전역 상태(로깅 설정 등)를 건드리는 코드는 서로 보인다.
- 키 회전은 여전히 재시작이 필요하다(설정 파일·다시 읽기는 12단계).

### 6. 결과 (2026-10-30)

- C1~C6 통과(`tests/test_d118_settings.py` 15건). 전체 `pytest -q` 599 통과 — **69초 → 18초**(같은 맥북, 세 번 18~20초), `ruff check .`·`mypy`(25파일) 통과.
  데모 6장면·Anthropic SDK 점검(6/6) 재통과.
- `main.py` 660 → 260줄(create_app·라우팅·미들웨어·관리 엔드포인트). 새 파일 `settings.py`(136줄)·`relay.py`(238줄), 감사 줄 모양은 `audit.py`로.
  설정을 읽는 곳은 `Settings.from_env` 하나다(`gateway/api/chat.py`의 실행 중 환경변수 읽기도 없앴다).
- 지운 설정은 효과가 없다(테스트): `GATEWAY_INJECTION_SCOPE=all`을 줘도 `injection_rule_turn`, `GATEWAY_CHAT_UPSTREAM_PATH`를 줘도 받은 경로 그대로, info에 `chat_upstream_path` 없음.
  데모·웹·OpenAI SDK 점검은 `GATEWAY_INJECTION=block`(+ 기본 mask)로 바꿨다 — 검사기 구성은 그대로 `injection_rule_turn,pii_mask`.
- 하네스: `make_stack`은 스텁·게이트웨이를 스레드 uvicorn으로 띄운다. 스텁 기록은 서버 포트별. `GATEWAY_DETECTORS`는 하네스가 `Settings.detectors`로 옮긴다
  (테스트 호출부는 그대로). 시험용 검사기는 `tests/chain_app.py`의 `REGISTRY`를 `make_stack` 첫 인자로 넘긴다. 서브프로세스가 남은 곳: stdout 로그·`python -m uvicorn` 기동
  거부·`.env` 미로드(C3) 테스트와 데모·SDK·실 공급자 스크립트. 프로세스 안 ASGI 테스트(D-110 V4~V6, 볼트 해제)는 `create_app`으로 새 앱을 만든다.
- mypy가 찾은 9건은 동작을 바꾸지 않고 고쳤다: 무인증 판정을 `client_keys is None`으로(타입 좁힘), 스트림 채널 참조를 `streaming.ref` 하나로(기본 인자 람다 셋을 대신),
  어댑터·예외 처리기에 단언, 감사 meta에 타입.
- 테스트 프로세스 안에서 uvloop 0.22가 3.14에 내는 `asyncio.iscoroutinefunction` 사용 중단 경고가 보이게 됐다 — pytest 설정에서 그 경고만 거른다.
- 계획과 다른 점: `httpx.ASGITransport` 대신 스레드 uvicorn(§3), `GATEWAY_DETECTORS`는 환경변수만 지우고 `Settings.detectors`로 남김, 이력까지 보는 `injection_rule` 검사기는
  테스트용으로 남김(제품 설정에서만 뺐다).

---

## D-119. 설정 파일 + API별 상류 + 클라이언트 정책 + 해시 키 + 허용 모델 (2026-10-30, PLAN 12단계)

### 1. 근거

- 클라이언트 키는 이름뿐이고 정책·허용 모델이 없다 — 팀마다 PII 모드·인젝션 처리를 달리 줄 수 없다.
- 상류 URL·키가 하나라 OpenAI(Chat·Responses)와 Anthropic(Messages)을 쓰려면 게이트웨이를 둘 띄워야 한다.
- 클라이언트 키를 평문으로 보관·비교한다(환경변수·메모리 모두).

### 2. 결정

1. `GATEWAY_CONFIG`(TOML, 표준 라이브러리 `tomllib`)를 `Settings.from_env`가 읽는다. 없으면 지금과 같다(환경변수만). 표:
   - `[[clients]]` `name`·`key_sha256`(소문자 16진 64자)·`policy`(없으면 `default`).
   - `[policies.<이름>]` `injection`·`pii_mode`·`pii_kinds`·`pii_detect_kinds`·`pii_roles`·`allowed_models`. 빠진 값은 환경변수로 정한 기본 정책을 따른다. `default` 정책을 고칠 수도 있다.
   - `[upstreams.<api>]` — api는 어댑터 이름 `chat`·`responses`·`messages`. `base_url`·`key_env`(공급자 키를 담은 **환경변수 이름** — 키는 파일에 두지 않는다)·`timeout`.
     없는 api는 `TARGET_URL`·`GATEWAY_UPSTREAM_KEY`·`GATEWAY_TIMEOUT`(하위 호환). 파일에 적은 상류는 `key_env`가 없으면 공급자 키를 달지 않는다 — `GATEWAY_UPSTREAM_KEY`(다른 공급자의 키일 수 있다)를 넘겨받지 않는다.
   - 모르는 표·키, 틀린 값, 없는 정책을 가리키는 클라이언트, `key_env`가 가리키는 환경변수가 없음 → ValueError(기동 실패).
2. **해시 키**: 클라이언트 키는 SHA-256으로만 들고 비교한다 — 환경변수 `GATEWAY_CLIENT_KEYS`의 평문 키도 읽을 때 해시한다. 비교는 낸 키의 해시와 모든 항목을 `hmac.compare_digest`로.
   `python -m gateway keygen --hash`는 키와 설정 파일에 넣을 `key_sha256 = "…"` 줄을 낸다.
3. **정책마다 검사기 체인**(시작할 때 만든다). 요청의 정책은 키 → 클라이언트 → 정책, 무인증이면 `default`. 대체값 키는 하나라 정책이 달라도 같은 원문은 같은 대체값이다.
4. **API별 상류**: 상류마다 연결 풀 하나(`httpx.AsyncClient`). `/v1/models`는 `anthropic-version` 헤더가 있으면 `messages`, 아니면 `chat` 상류로 보낸다. 공급자 키는 그 상류의 키만 단다.
   무인증(`GATEWAY_AUTH=off`)에 공급자 키가 하나라도 있으면 기동 실패(D-109를 상류마다).
5. **허용 모델**: 정책의 `allowed_models`(fnmatch 글롭 목록)가 있으면 요청의 `model`이 하나에 맞아야 한다. 아니면 403 — 그 API의 오류 형식(`permission_error`, 코드 `model_not_allowed`),
   검사기·상류 호출 없음. 없으면 모든 모델.
6. **설정 버전**: 파일 바이트 SHA-256 앞 12자를 `/__gateway/info`의 `config`와 감사 줄 `config`에. 감사 줄에 `policy`(정책 이름)도. 파일이 없으면 `null`.
7. 완료 확인용 `scripts/check_sdks.py`: 스텁 둘(OpenAI 쪽·Anthropic 쪽)과 설정 파일을 쓴 게이트웨이 **하나**를 띄우고, 두 SDK 점검 스크립트를 `--gateway`로 그 게이트웨이에 붙여 돌린다.

### 3. 버린 대안

- 상류를 공급자 이름(`openai`·`anthropic`)으로: 어댑터와 1:1이 아니라 `/v1/models`·호환 서버(Ollama의 OpenAI 호환 입구) 배치가 모호하다. 어댑터 이름이면 요청 경로로 바로 정해진다.
- 공급자 키를 파일에: 설정 파일이 비밀이 된다(저장소·이미지에 들어가기 쉽다). 키는 환경변수(K8s Secret)로만.
- 정책을 요청마다 체인 하나에 인자로: 검사기마다 정책을 알아야 한다. 정책 수만큼 체인을 만드는 쪽이 검사기를 바꾸지 않는다.
- bcrypt·scrypt 같은 느린 해시: 키는 `keygen`의 32바이트 무작위라 사전 공격 대상이 아니고, 요청마다 비교한다. SHA-256으로 충분하다.
- 허용 모델 밖의 모델을 조용히 기본 모델로 바꾸기: 클라이언트가 모르는 채 다른 모델의 답을 받는다.

### 4. 완료 기준 (`tests/test_d119_config.py`)

| # | 기준 |
|---|---|
| G1 | 설정 파일의 세 표를 읽고, 틀린 파일(모르는 키·값·정책·환경변수 없음·해시 꼴)은 ValueError. 파일 없으면 예전과 같다 |
| G2 | 해시 키 인증: 파일의 `key_sha256`과 환경변수 평문 키 모두 통한다. 메모리에 평문 키가 없다. `keygen --hash` 출력이 설정에 그대로 쓰인다 |
| G3 | 정책: 클라이언트마다 PII·인젝션이 다르게 적용된다(같은 게이트웨이) |
| G4 | 허용 모델 밖은 403(세 API의 오류 형식), 상류·검사기 호출 없음 |
| G5 | API별 상류: Chat·Responses는 OpenAI 쪽 스텁, Messages는 Anthropic 쪽 스텁으로 가고 각자의 키만 단다. `/v1/models`는 헤더로 고른다 |
| G6 | 설정 버전이 info와 감사 줄에, 정책 이름이 감사 줄에 |
| G7 | `scripts/check_sdks.py` — OpenAI SDK·Anthropic SDK 점검이 한 게이트웨이에서 함께 통과 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 |

### 5. 한계

- 설정을 바꾸면 재시작해야 한다(다시 읽기 없음). 키 회전은 새 해시를 더하고 재시작한 뒤 옛 해시를 빼고 다시 재시작한다.
- 정책은 클라이언트 단위다 — 같은 클라이언트의 요청마다 다르게 줄 수 없다. 허용 모델은 `model` 문자열만 본다(별칭·버전 해석 없음).
- `/v1/models` 목록은 거르지 않는다(허용 모델이 아닌 모델도 목록에 보인다).

### 6. 결과 (2026-10-30)

- G1~G7 통과(`tests/test_d119_config.py` 24건, `scripts/check_sdks.py`). 전체 `pytest -q` 623 통과(19초), `ruff check .`·`mypy` 통과.
- G7: 스텁 둘 + 설정 파일(`[upstreams.messages]`만) 게이트웨이 하나에 OpenAI SDK 2.48.0(8/8)·Anthropic SDK 0.125.0(6/6)이 함께 통과했고, OpenAI 쪽 스텁은
  `/v1/chat/completions`·`/v1/responses`만, Anthropic 쪽 스텁은 `/v1/messages`만 받았다. 두 점검 스크립트에 `--gateway`(떠 있는 게이트웨이에 붙기)를 더했다.
  점검용 venv(`/tmp/sdkvenv`)의 `python`이 3.9이고 `pip`이 3.14 쪽에 설치하던 것을 찾아 `python -m pip`로 openai를 깔았다 — 사용자 할 일의 OpenAI SDK 점검도 이것으로 끝났다.
- 바뀐 내부 모양: `Settings.client_keys`(평문 → 이름) → `Settings.clients`(SHA-256 → `Client(name, policy)`), `Auth(clients)`·`Auth.upstream_headers(path, pairs, key)`,
  `app.state.client` → `app.state.upstreams`(API → 풀·키, 같은 주소·시간 제한이면 풀 하나), `app.state.chains`·`app.state.policies`(정책마다). 프로세스 안 테스트는
  `tests.conftest.install`로 state를 넣는다. 감사 줄에 `policy`·`config`, info에 `config`·`upstreams`·`policies`.
- 볼트 TTL은 세 상류 시간 제한 중 가장 긴 것 + 60초(D-110을 상류마다).
- 계획과 다른 점: 상류 표 이름은 공급자가 아니라 어댑터(`chat`·`responses`·`messages`, §3). 파일에 적은 상류는 `key_env` 없이는 키를 달지 않는다(§2-1).

---

## D-120. 감사 usage·모델 + 출력 방향 관측 + 문구 카탈로그(ko·en) + 상류에 요청 ID (2026-10-30, PLAN 13단계)

### 1. 근거

- 감사 줄에 모델·토큰 사용량이 없어 비용·예산을 집계할 수 없다(client·api·config는 D-107·D-119에 있다).
- 모델이 새로 내보낸 개인정보(출력 방향)는 세지 않는다 — 연구 단계에서는 카나리로만 셌다.
- 차단 문구·가린 이력 자리표시·기동 거부와 설정 오류 문구가 한국어로 박혀 있다. 결정 표 #10은 한국어 기본, 영문 병행(`GATEWAY_LANG=en`)이다.
- 상류가 사내 서비스면 게이트웨이 감사 줄과 상류 로그를 이을 손잡이가 없다.

### 2. 결정

1. 감사 줄에 `model`(요청의 model 문자열)과 `usage` — `{"input", "output", "cache_read", "cache_write"}`(토큰 수, 공급자가 주지 않은 항목은 0), usage가 없으면 `null`.
   - 비스트리밍: 응답 JSON의 `usage`(Chat `prompt_tokens`·`completion_tokens`·`prompt_tokens_details.cached_tokens`, Responses `input_tokens`·`output_tokens`·
     `input_tokens_details.cached_tokens`, Messages `input_tokens`·`output_tokens`·`cache_read_input_tokens`·`cache_creation_input_tokens`).
   - 스트리밍: Messages는 `message_start`의 usage에 `message_delta`의 usage를 덮어 합치고, Responses는 `response.completed`의 usage. Chat은 상류 요청에
     `stream_options.include_usage: true`를 넣어 받고, 클라이언트가 그것을 요청하지 않았으면 usage만 담은 조각(`choices: []`)을 클라이언트 스트림에서 뺀다(유일하게 조각을 버리는 경우).
2. **출력 방향 관측** `pii_new`(감사)·`gateway_pii_new_total`(지표): 사용자에게 보이는 응답 텍스트(사고 과정 밖)에서, 그 요청에서 가린 원문·발급한 대체값이 아닌 PII·비밀 건수.
   그 정책이 가리는 종류만 센다(감사만 종류 제외). 가리지 않는다. detect 모드에서도 센다. 잔여·의심과 같은 탐지 한 번으로 센다.
3. **문구 카탈로그** `gateway/messages.py`: 차단 문구·요청 ID 꼬리·가린 이력 자리표시·기동 거부·설정 오류. `GATEWAY_LANG=ko`(기본)·`en`, 그 밖은 기동 실패.
   `GATEWAY_BLOCKED_MESSAGE`가 있으면 그것이 우선이다. API 오류 본문(`invalid or missing API key` 등)은 지금처럼 영어 — 공급자 API의 관례이고 SDK가 읽는다.
4. 상류 요청 헤더에 `x-gateway-request-id`(게이트웨이 요청 ID). 공급자에게도 간다 — 임의 16진 16자라 정보가 없다.

### 3. 버린 대안

- usage를 응답 바이트에서 정규식으로: JSON 구조가 공급자마다 다르다. 이미 파싱하는 객체에서 읽는다.
- Chat 스트림 usage를 토큰 수 추정(tiktoken 등): 의존성이 늘고 틀린다. 상류가 세게 한다.
- 출력 방향 PII를 가리기: 사용자가 모델에게서 받아야 할 값일 수 있다(주소록 질의 등). 이번에는 관측만.
- 설정 오류를 영어로만: 국내 운영자가 기본 사용자다(결정 표 #5).

### 4. 완료 기준 (`tests/test_d120_observe.py`)

| # | 기준 |
|---|---|
| O1 | 세 API × 스트리밍·비스트리밍 모두 감사 줄에 `model`·`usage`. Messages 스트림은 두 이벤트를 합친다 |
| O2 | Chat 스트림: 상류는 `include_usage`를 받고, 요청하지 않은 클라이언트의 스트림에는 usage 조각이 없다. 요청한 클라이언트는 그대로 받는다 |
| O3 | `pii_new`: 응답에 새로 나온 PII는 세고, 복원된 원문·남은 대체값·감사만 종류는 세지 않는다. 스트림·detect 모드도. 지표에 합산 |
| O4 | 카탈로그: ko·en 문구가 차단 응답·가린 이력·기동 거부·설정 오류에 쓰인다. 모든 키에 두 언어가 있다. `GATEWAY_LANG=fr`은 기동 실패 |
| O5 | 상류가 `x-gateway-request-id`를 받고 그 값이 감사 줄의 `request_id`와 같다 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 |

### 5. 한계

- `stream_options`를 모르는 OpenAI 호환 서버는 이 필드로 400을 낼 수 있다(OpenAI·vLLM·Ollama는 받는다). usage를 주지 않는 상류면 `usage`는 `null`이다.
- 클라이언트가 스트림을 중간에 끊으면 usage가 오기 전이라 `null`이다.
- `pii_new`는 탐지 패턴이 아는 꼴뿐이다(이름·주소는 모른다).

### 6. 결과 (2026-10-30)

- O1~O5 통과(`tests/test_d120_observe.py` 16건). 전체 `pytest -q` 639 통과(20초), `ruff check .`·`mypy` 통과. `scripts/check_sdks.py`(OpenAI SDK 8/8 — Chat 스트림에
  `stream_options`를 넣은 뒤에도 — Anthropic SDK 6/6, 한 게이트웨이)·데모 6장면 재통과.
- usage: 어댑터마다 `usage_raw`(응답 객체·스트림 이벤트에서 공급자 usage를 꺼냄)와 `normalize_usage`(감사 모양). 스트림 복원기가 이벤트의 usage를 덮어 합친다 —
  Messages 스트림은 `message_start`(입력 1·캐시 읽기 2·쓰기 4) + `message_delta`(출력 9)가 한 줄이 된다(스텁에 캐시 항목을 넣어 확인).
- 출력 방향: `PIIDetector.response_stats`가 잔여·의심·새 PII를 탐지 한 번으로 센다(예전에는 잔여와 의심이 따로 훑었다). 발급이 없는 응답도 새 PII가 있으면 기록한다 —
  그래서 응답마다 탐지가 한 번 돈다(예전에는 발급이 없으면 건너뛰었다).
- 바꾼 기존 테스트: 복원 meta를 그대로 비교하던 셋(`new: 0`이 더해졌다), '발급이 없으면 기록 없음'(이제 새 PII가 있으면 건수만 남긴다).
- 계획과 다른 점: 감사의 client·api·config는 이미 있었다(D-107·D-119) — model·usage만 더했다. API 오류 본문은 카탈로그에 넣지 않았다(§2-3).

---

## D-121. 배포 패키지(compose·k8s) + 제품 문서(설정·운영·API 호환·보안 제보·영문 README) + 문서 동기화 테스트 (2026-10-31, PLAN 14단계)

### 1. 근거

- 설치 경로가 README의 `docker run` 한 줄뿐이다. 레플리카·헬스·종료 유예·비밀 보관을 고객이 처음부터 짜야 한다.
- 설정·운영 지식이 README 4절과 결정 기록에 흩어져 있다. 키 회전 절차는 D-111 §5가 "14단계 운영 문서에 옮긴다"고 남겼다 — 그런데 D-114가 실제로 본 것은
  캐시 미스만이 아니다. 진행 중인 대화의 이력 바이트가 바뀌면 Anthropic은 thinking 서명을 `bound to a different conversation` 400으로 거절한다.
- 미지원 기능(`previous_response_id`, embeddings, files, 서버 측 도구 등)이 README 한 줄뿐이라 도입 검토 때 답할 문서가 없다. 취약점 제보 경로가 없다.
- 문서의 환경변수 목록이 코드와 어긋나도 막는 것이 없다(D-118이 지운 변수 셋만 README에서 확인한다).

### 2. 결정

1. **로컬 체험** `deploy/compose.yml`: 게이트웨이(`gateway/Dockerfile` 빌드, 읽기 전용 루트) + 스텁 상류(같은 이미지에 `tests/stub_target.py`를 읽기 전용으로 마운트 —
   스텁 이미지를 따로 만들지 않는다). 포트는 127.0.0.1에만 연다. 키는 체험용 고정값이고 문서·파일에 운영 금지를 적는다. `GATEWAY_INJECTION`만 셸에서 덮어쓴다.
2. **k8s** `deploy/k8s/`, kustomize(`kubectl apply -k`, kubectl 내장): `gateway.yaml`(Deployment·Service·PodDisruptionBudget), `gateway.toml`(설정 파일 →
   configMapGenerator), `secret.env.example`(→ `secret.env`, 커밋 안 함 → secretGenerator), `kustomization.yaml`.
   - 생성되는 ConfigMap·Secret 이름에 내용 해시가 붙는다 — 설정·키를 바꾸고 apply하면 Deployment가 롤링 재시작된다. 게이트웨이는 설정을 다시 읽지 않으므로
     재시작이 곧 적용이고, 나중에 다시 뜬 파드만 새 키를 받아 레플리카 사이에 대체값 키가 섞이는 일이 없다.
   - Deployment: 레플리카 2, readiness = `/__gateway/health`, preStop `sleep 5` + uvicorn 종료 유예 25초 = `terminationGracePeriodSeconds: 30`,
     비root 10001·읽기 전용 루트·권한 상승 없음·capabilities 전부 뗌·seccomp RuntimeDefault(Pod Security `restricted`), 노드 분산(soft), 워커 1 —
     지표·레이트리밋·볼트 상한이 프로세스 단위라 파드 수로 늘린다. PDB `minAvailable: 1`. Service ClusterIP 8080.
   - 클라이언트 키는 해시로 설정 파일(ConfigMap)에 둔다(D-119). Secret에는 대체값·관리·공급자 키만.
   - 이미지는 `ghcr.io/hongjinkong/llm-security-gateway:0.1.0`(20단계 릴리스가 올린다 — 그 전에는 직접 빌드한 주소로 바꾼다).
3. **문서**: `docs/configuration.md`(환경변수 전부·설정 파일 키 전부 — README 4절을 옮긴다), `docs/operations.md`(배포·키 회전·로그 수집·지표·용량·업그레이드),
   `docs/api-compat.md`(지원 경로와 API별 검사·복원 범위, 미지원 기능, 헤더·오류·차단 응답 모양 — README 4절의 나머지를 옮긴다),
   `SECURITY.md`(GitHub 비공개 취약점 제보, 범위 — README 2절의 알려진 한계는 취약점이 아니다), `README.en.md`(영문 한 파일 — 결정 표 #10).
   README(한국어) 4절은 필수 변수와 링크로 줄인다.
4. **문서 동기화 테스트** `tests/test_d121_docs.py`: `Settings.from_env`가 실제로 읽는 환경변수 이름(읽은 키를 기록하는 매핑으로 잰다)이
   `docs/configuration.md`·`README.en.md`의 환경변수 표와 같다(uvicorn 변수 제외). 설정 파일 키 표가 코드의 키 집합과 같다(`CLIENT_KEYS`·`POLICY_KEYS`·`UPSTREAM_KEYS`로
   이름을 붙인다). 견본 설정 파일이 `Settings.from_env`로 읽히고, 견본들(`.env.example`·`secret.env.example`·compose)의 변수는 코드가 읽는 이름(또는 설정 파일의 `key_env`)이다.
   문서의 상대 링크가 가리키는 파일이 있다.
5. CI docker 작업에 `docker compose -f deploy/compose.yml config -q`와 `kubectl kustomize deploy/k8s`(견본 `secret.env`로) — 렌더만 하고 클러스터는 없다.
6. 기동 거부 문구(`no_client_keys`)에 설정 파일 `[[clients]]`를 넣는다 — k8s 견본은 클라이언트가 비어 있어 처음 올리면 이 문구를 본다.

### 3. 버린 대안

- **Helm 차트**: 값 파일·템플릿을 유지할 이유가 아직 없다(PLAN: 고객이 요구할 때). kustomize는 kubectl에 들어 있다.
- **평문 매니페스트 + Secret 견본 YAML**: `kubectl apply -f deploy/k8s/`가 빈 견본으로 실제 Secret을 덮어쓸 수 있고, ConfigMap·Secret을 바꿔도 파드가 재시작되지 않는다
  (§2-2의 키 섞임).
- **스텁 전용 이미지**: 게이트웨이 이미지에 fastapi·uvicorn·탐지 패턴이 이미 있다 — 스텁 파일 하나만 마운트한다.
- **운영·API 문서 영문 병행**: 결정 표 #10은 `README.en.md`만이다. 영문 README에 환경변수 표를 두고 같은 테스트로 맞춘다.
- **문서의 환경변수 표를 코드에서 생성**: '뜻' 열은 사람이 쓴다. 이름 집합만 테스트로 맞춘다.
- **`kubectl apply --dry-run=client`**: 이 맥에는 클러스터 컨텍스트가 없어 kubectl이 서버 탐색에서 멈춘다(사용자 확인 2026-10-31). 대신 `kubectl kustomize`(오프라인 렌더)와
  kubernetes-validate(오프라인 스키마, `--strict`)로 잰다.

### 4. 완료 기준 (`tests/test_d121_docs.py`)

| # | 기준 |
|---|---|
| S1 | `docker compose -f deploy/compose.yml up`으로 뜬 게이트웨이(읽기 전용 루트·비root)에 OpenAI SDK 8/8·Anthropic SDK 6/6(`--gateway`, `GATEWAY_INJECTION=block`) |
| S2 | `kubectl kustomize deploy/k8s` 렌더가 kubernetes-validate `--strict`를 통과. 레플리카 2·readiness·preStop 5·유예 30·PDB·restricted 보안 문맥이 렌더에 있다 |
| S3 | 문서 동기화: 환경변수 표 둘 = 코드가 읽는 이름, 설정 키 표 = 코드, 견본 설정 파일이 읽힌다, 견본 변수 이름이 코드의 것, 문서의 상대 링크가 있다 |
| S4 | 문서: `docs/configuration.md`·`docs/operations.md`·`docs/api-compat.md`·`SECURITY.md`·`README.en.md` |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 |

### 5. 한계

- 스키마 검증만이다 — 실제 클러스터(서버 dry-run 포함)에는 올려 보지 않았다. 사용자 할 일에 Docker Desktop Kubernetes를 켠 뒤의 확인을 둔다.
- 자원 요청·상한은 유휴 메모리 실측과 본문 상한으로 잡은 잠정값이다. 부하 측정은 15단계다.
- 문서 동기화 테스트는 이름만 맞춘다 — 기본값·뜻이 맞는지는 사람이 본다.
- compose의 키는 체험용 고정값이다(127.0.0.1에만 열린다). 이미지 주소(GHCR)는 20단계 릴리스 전까지 비어 있다.
- 게이트웨이는 TLS를 하지 않는다 — 인그레스·서비스 메시에서 끝낸다(운영 문서).

### 6. 결과 (2026-10-31)

- **S1 통과.** `GATEWAY_INJECTION=block docker compose -f deploy/compose.yml up --build`로 뜬 게이트웨이(읽기 전용 루트·uid 10001·healthy)에 OpenAI SDK 2.48.0 8/8·
  Anthropic SDK 0.125.0 6/6(`--gateway`). 스텁이 받은 본문에는 가짜 번호(`010-5248-9756`)만 있었다. 최종 코드로 이미지를 다시 빌드해 한 번 더 통과.
  이 맥의 8080은 다른 프로젝트 컨테이너가 쓰고 있어 호스트 포트를 `HOST_PORT`·`STUB_HOST_PORT`로 바꿀 수 있게 했다(18080·18000으로 확인).
- **S2 통과.** `kubectl kustomize deploy/k8s` 렌더(ConfigMap·Secret 이름에 내용 해시, Deployment의 참조가 그 이름으로 바뀐다) 5개 리소스가 kubernetes-validate 1.37.0
  `--strict`로 k8s 1.37·1.28 스키마를 통과했다. 견본 설정(`gateway.toml` + 클라이언트 한 줄)과 비밀을 읽기 전용·uid/gid 10001 컨테이너에 넣어 띄우니 info의 상류가 API별로
  갈렸고 키 없는 요청은 401(상류 호출 없음)이었다. 이미지에 preStop의 `sleep`이 있다.
- **S3 통과.** `tests/test_d121_docs.py` 19건(3.14·3.12). 변이 7개 — 표의 변수 이름, 지운 변수 언급, 설정 키 오타, 깨진 앵커, 깨진 파일 링크, 종료 유예 20초, compose의 없는 변수 —
  를 모두 잡는다. 문서의 상대 링크는 GitHub 앵커 규칙(소문자·기호 삭제·공백은 -)으로 머리글까지 확인한다.
- **S4**: `docs/configuration.md`·`docs/operations.md`·`docs/api-compat.md`·`SECURITY.md`·`README.en.md`. README 4절(설정 표)을 `docs/configuration.md`로 옮겼고(274 → 236줄),
  2절에 Responses 사용자 정의 도구(보지 않는다)와 공급자 쪽 도구(가짜 값을 받는다)를 더했다 — 문서를 쓰며 어댑터를 다시 읽다 찾은 한계다.
- **용량 자료(잠정, 15단계 전)**: 1MiB 요청(가짜 값 2,242개, 스텁이 같은 크기로 되돌린다) 50건 동시 → 모두 200, 23.5초(워커 1), 메모리 유휴 36MiB → 최대 256MiB → 끝난 뒤 122MiB.
  첫 시도는 요청마다 가짜 값이 2만 개를 넘어 50건 모두 413 `too_many_findings`였다(상한이 동작). k8s 자원은 요청 CPU 500m·메모리 256Mi, 메모리 상한 1Gi로 잡았다.
- 전체 `pytest -q` 658 통과(3.14 19.7초, 3.12도), `ruff check .`·`mypy` 통과.
- **결정에 없던 변경**: 설정 파일 `key_env`가 가리키는 환경변수가 **비어 있어도** 기동 실패로 바꿨다(예전에는 없을 때만). 견본 `secret.env`를 채우지 않고 올리면 기동은 되고
  요청마다 상류 401이 났을 것이다. `settings.py`에 키 집합 이름(`CLIENT_KEYS`·`UPSTREAM_KEYS`)을 붙였다.
- 계획과 다른 점: kustomize(§3), 클라이언트 키는 해시로 ConfigMap에(Secret에는 대체값·관리·공급자 키), compose 호스트 포트 변수.
- 못 한 것: 실제 클러스터 apply와 서버 dry-run(kubectl 컨텍스트 없음 — 사용자 할 일), GHCR 이미지(20단계), 부하 시험(15단계), GitHub 비공개 취약점 제보 켜기(사용자 할 일).
- 15단계(D-122 §6) 리뷰가 이 단계의 산출물도 고쳤다: k8s 종료 유예 30 → 35초(여유 0초였다), 생성기 레이블과 키 회전 뒤 옛 Secret 정리 절차, 문서의 틀린 서술 14건
  (설정 예시의 상속, 지표 뜻, 타임아웃·오류 형식, 실 API 확인 범위, 측정 환경 표시 등), `.env.example`, 문서 테스트의 변수 이름 경계.

---

## D-122. 부하·안정성 — 동시 스트림 지연 백분위·오류율, 30분 soak, 볼트 세션 지표 (2026-10-31, PLAN 15단계)

### 1. 근거

- 용량 수치가 D-121의 1MiB 버스트 한 점뿐이다. 동시 스트림·지연 백분위·오류율도, 오래 돌 때의 누수(메모리·파일·대체값 세션)도 잰 적이 없다.
- PLAN 조건부 표의 트리거('목표 부하에서 게이트웨이 p95 > 50ms → 런타임 교체 검토')를 판정할 수치가 없다.
- 503 `gateway_busy`를 정하는 양(진행 중인 대체값 세션 수)을 밖에서 볼 수 없다.

### 2. 결정

1. `scripts/load.py`(httpx 비동기, 새 의존성 없음): 스텁(지연 주입)과 게이트웨이를 서브프로세스로 띄우고 잰다.
   - 게이트웨이는 이미지와 같은 서버 설정이다 — 워커 1, `--no-access-log --limit-concurrency 1000 --timeout-graceful-shutdown 25`, 이벤트 루프 asyncio·HTTP h11
     (이미지에는 uvloop·httptools가 없다 — 개발 venv에는 있어 그대로 두면 이미지보다 빠르게 잰다). 정책은 기본(PII mask + 인젝션 observe).
   - 부하: 스트리밍 작업자 S개(기본 50)와 비스트리밍 작업자 P개(기본 50)가 정한 시간 동안 쉬지 않고 요청한다. 세 API(chat·messages·responses)를 돌아가며 쓰고,
     요청마다 다른 합성 전화번호(작업자·순번으로 만든다)를 넣는다 — 응답에 그 요청의 원래 번호가 있는지(복원), 다른 요청의 번호가 섞였는지(교차 누출)를 센다.
   - 스텁 지연: 첫 바이트 전 `STUB_DELAY_MS`, 스트림 조각 사이 `STUB_CHUNK_MS`(스텁에 환경변수 둘을 더한다. 없으면 지금과 같다). load.py 기본 300ms·20ms.
   - 잰다: 비스트리밍 지연, 스트림의 첫 내용 조각(TTFT)과 전체 시간의 p50·p95·p99, 같은 부하를 스텁에 바로 보낸 기준선(`--baseline`), 감사 줄의 `gateway_ms`(게이트웨이 자체 처리 시간)
     백분위, 오류(2xx 아님·예외)·복원 실패·교차 누출 건수, 처리량.
   - soak: `--duration`을 길게 주고 `--sample` 초마다 게이트웨이 프로세스의 RSS·열린 파일 수·`gateway_vault_sessions`를 적는다(`ps`·`lsof`/`/proc` — psutil 없음).
     RSS 증가율 = 마지막 4분의 1 평균 ÷ 처음 4분의 1 평균 − 1(첫 표본은 워밍업이라 뺀다).
   - 결과는 마크다운으로 stdout, 원자료는 `--out` JSON.
2. 지표 `gateway_vault_sessions`(게이지): 이 워커에서 진행 중인 대체값 세션 수(정책 합). 정책·워커당 2,000에 닿으면 503 `gateway_busy`.
3. 결과를 `docs/operations.md` '용량'에 표로 둔다 — 측정 환경(맥북 M2 8코어, 부하 생성기와 같은 기계, Python 3.14)과 함께. x86 서버의 값이 아니라고 적는다.
4. CI 스모크 `tests/test_d122_load.py`: load.py를 몇 초·작은 동시성으로 돌려 오류 0·복원 100%·교차 누출 0(스크립트 배선이 썩지 않게), 지표 게이지.

### 3. 버린 대안

- **locust·k6**: 새 의존성이고, 복원·교차 누출 같은 응답 검사를 따로 짜야 한다. httpx 비동기로 충분하다.
- **Docker 컨테이너에 부하**: macOS Docker Desktop의 포트 전달이 지연·오류에 섞인다. 서버 설정을 이미지와 맞춘 로컬 프로세스로 잰다.
- **psutil**: 새 의존성. `ps -o rss=`와 `lsof -p`(macOS)·`/proc/<pid>/fd`(Linux)로 읽는다.
- **uvloop·httptools를 이미지에 넣기**: 수치가 트리거에 닿을 때만 검토한다(PLAN 조건부 표).

### 4. 완료 기준 (`tests/test_d122_load.py`, `scripts/load.py`)

| # | 기준 |
|---|---|
| L1 | 60초 부하(스트림 50 + 비스트리밍 50): 오류 0, 복원 실패 0, 교차 누출 0. 게이트웨이 지연 p50·p95·p99와 기준선 표 |
| L2 | 30분 soak(같은 부하): 오류 0, RSS 증가 10% 미만, 열린 파일 수·볼트 세션 수가 늘지 않는다(끝난 뒤 볼트 세션 0) |
| L3 | `gateway_vault_sessions`: 스트림이 열려 있는 동안 1 이상, 끝나면 0 |
| L4 | 수치가 `docs/operations.md` '용량'에 있다 |
| L5 | CI 스모크(몇 초 부하에서 오류 0·복원 100%·교차 누출 0) |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 |

### 5. 한계

- 맥북(arm64) 로컬 프로세스의 수치다. 부하 생성기·스텁·게이트웨이가 같은 CPU를 나눠 쓴다. x86 서버·컨테이너 CPU 상한 아래에서는 다르다 — 배포 뒤 감사 줄 `gateway_ms`로 다시 본다.
- 스텁의 답은 짧다(요청 문장을 되풀이). 실제 공급자의 큰 응답·긴 스트림에서 복원 비용은 응답 크기에 비례해 는다.
- 워커 1 기준이다. 여러 워커·여러 파드의 합은 재지 않았다.

### 6. 결과 (2026-10-31)

- **찾은 병목(결정에 없던 변경 1)**: 첫 60초 부하는 오류 3(502 2·ReadError 1), 초당 60건, 비스트리밍 p50 821ms(스텁 직접 305ms)였다. cProfile로 보니 게이트웨이 시간의 73%가
  httpcore 1.0.9 연결 풀의 배정 루프였다. 두 결함이 겹쳤다 — (1) 쉬는 연결을 셀 때 전체 연결 수를 연결마다 다시 세어(O(n²)) `max_keepalive`(기본 20)를 넘으면 쓴 연결을 바로 닫고,
  (2) 배정이 연결을 예약하지 않아 기다리는 요청 여럿이 같은 쉬는 연결에 배정되고 하나만 쓴다. 작업자마다 클라이언트를 따로 두니 같은 부하가 초당 303건·1초 넘는 요청 0이었다.
  httpcore·httpx가 최신이라 고친 판이 없다. **상류 연결 풀을 바꿨다**: `relay.UpstreamPool` — 연결 하나짜리 httpx 클라이언트를 빌려 쓰고 응답 본문을 닫을 때(`_Returning`) 돌려준다.
  TLS 설정은 하나를 함께 쓴다(클라이언트마다 만들면 개당 약 9ms·0.2MiB). 부하 생성기도 같은 문제를 겪어 작업자마다 클라이언트를 둔다.
- **찾은 누수(결정에 없던 변경 2)**: 클라이언트가 응답 전에 끊는 실험(동시 88건)에서 대체값 세션 17개가 남고 감사 줄 2개가 빠졌다. Starlette는 끊김을 앱 작업의 anyio 취소로 처리하고,
  그 취소는 정리 코드의 다음 await에서 다시 터진다. 스트림 마무리를 한 번만 도는 `finish`로 묶어 취소를 막고 돌리고(`anyio.CancelScope(shield=True)`), 본문 생성기가 시작도 못 한 경우를
  위해 응답 객체(`_Stream.__call__`)와 미들웨어에도 안전망을 두었다. 미들웨어는 `CancelledError`에도 감사 줄을 쓴다.
- **다차원 리뷰 + 반박 검증**(울트라코드 워크플로, 에이전트 77): 리뷰어 5(동시성·회귀·배포 보안·문서 정확성·도구) → 발견 35 → 발견마다 검증자 2~3이 반박 시도 → 35 모두 남음.
  고친 것: 요청을 만들다 실패하면(비ASCII 헤더 — 한국어 User-Agent) 빌린 연결을 잃어 100번이면 모든 요청 503(high, 두 리뷰어가 따로 찾음 — 헤더를 받은 바이트 그대로 넘기고 반환을
  try 안으로), 스트림 응답을 만들다 실패하면 연결·세션·감사 줄을 잃음, 클라이언트가 끊은 스트림이 정상 200으로 기록됨(uvicorn이 ASGI 2.3이라 Starlette가 끊김을 삼킨다 → `ClientDisconnect`),
  풀 대기자가 순서대로 받지 못함(→ 기다리는 순서대로 넘겨줌), 첫 클라이언트를 늦게 만들어 생성 오류가 기동을 막지 못함(→ 기동 때 만듦), 413 감사 사유 없음, `/v1/messages`의 500이 OpenAI 형식,
  키 값의 앞뒤 공백, k8s 종료 유예 여유 0초(→ 35초), 키 회전 뒤 옛 Secret 남음(→ 생성기 레이블과 정리 절차), 문서 14건, 부하 스크립트의 검증 6건(가렸는지 확인 안 함 등), 문서 테스트 정규식.
  수정마다 회귀 테스트를 더했고, 수정을 하나씩 되돌리면 그 테스트가 실패함을 확인했다(7/7).
- **L1 통과**(최종 코드, 60초, 스트림 50 + 비스트리밍 50): 13,367건(초당 219) — 오류·복원 실패·교차 누출 0, 감사 줄 = 요청, 200 응답은 모두 가짜 값을 발급했다.
  게이트웨이 경유 p50·p95·p99는 비스트리밍 315·362·409ms(스텁 직접 319·352·397), 스트림 첫 조각 313·364·781ms(314·346·605), 감사 `gateway_ms` 4.0·18.5·30.7ms, CPU 요청당 2.2ms.
- **L2 통과**(최종 코드, 30분, 상류 연결 80 — 늘 20개가 대기): 323,416건, 판정 10개 모두 통과(503 0), RSS 53~80MiB·증가율 −2.4%, 열린 파일 일정, 끝난 뒤 세션·연결 0.
  고치기 전 코드의 30분(연결 100): 402,926건, 오류 0, RSS +3.8%.
- **L3·L5 통과**: `gateway_vault_sessions{policy}`(정책마다 — 상한이 정책마다라 합으로는 503을 읽을 수 없다는 리뷰 지적)와 `gateway_upstream_connections_in_use{upstream}`을 더했다.
  `tests/test_d122_load.py` 12건(부하 스크립트 스모크, 게이지, 끊김 누수, 리뷰 회귀), 부하 스크립트 서버 인자가 Dockerfile CMD와 같은지 테스트.
- **L4**: `docs/operations.md` '용량'에 표·soak·큰 요청·상한·자원 근거.
- 전체 `pytest -q` 670 통과(3.14 30초·3.12), `ruff check .`·`mypy` 통과. compose 두 SDK 점검을 최종 이미지로 다시 통과.
- 계획과 다른 점: 결정 §2에 없던 상류 풀 교체·취소 안전망·지표 하나 더(빌려 간 연결), k8s 견본 `UVICORN_TIMEOUT_KEEP_ALIVE=75`(인그레스 유휴 시간보다 길게 — 측정이 아니라 알려진 동작,
  이미지 기본 5초가 환경변수로 바뀜을 컨테이너로 확인). 조건부 트리거(게이트웨이 p95 > 50ms)는 닿지 않았다 — 감사 `gateway_ms` p95 18.5ms.
- 못 한 것·한계: x86 서버·컨테이너 CPU 상한 아래의 수치, 여러 워커·파드의 합, 비스트리밍 요청을 클라이언트가 끊은 경우의 감사(상류가 답하면 200으로 남는다 — 응답을 보낼 곳이 없을 뿐).

---

## D-123. 인젝션 평가셋 v1(한국어 중심) + 점수 스크립트 + 룰 기준선 (2026-10-31, PLAN 16단계)

### 1. 근거

- 인젝션 탐지 수치는 연구 단계의 garak 템플릿 매칭(헤드라인 74.5% → 0.2%)뿐이다. 동의어 하나로 14/14가 빠졌고, 한국어 공격 탐지율은 잰 적이 없다(부록 A).
- 정상셋은 HR 질문 100문항(고유 89)뿐이라 오탐률을 말할 수 없다. 17·18단계(분류기·웹훅)를 같은 자로 비교하려면 판정기와 무관한 셋과 점수 규칙이 먼저 있어야 한다.
- 2026-10-31 조사(데이터셋 카드·라이선스·리비전을 에이전트가 하나씩 확인): 재배포 가능한 한국어 인젝션셋이 여럿 있다(아래 표). 공격을 우리가 만들 필요가 없다.

### 2. 결정

1. **구성** — 공격은 공개 데이터셋 + 기존 `gateway/data/injection_corpus.jsonl` 59건 + 그 59건의 결정적 변형뿐이다. LLM으로 공격을 만들거나 번역하지 않는다. 정상은 공개 데이터셋 +
   `eval/benign/all100.jsonl` + 에이전트가 쓴 한국어 업무 문장·하드 네거티브(정상 문장은 써도 된다 — PLAN 16단계). 고정 리비전(커밋 SHA)에서 받아 결정적으로 뽑는다(난수 없음, id의 SHA-256 순).

   | 출처 | 라이선스 | 쓰는 행 | 언어 | 유형 |
   |---|---|---|---|---|
   | `gateway/data/injection_corpus.jsonl`(연구 단계 자체 작성) | 본 저장소 | 공격 59 + 결정적 변형(동의어·띄어쓰기·전각·제로폭·base64) | ko | direct·role_spoof / encoding |
   | `xxxjjhhh/korean_guardrail_test` @cd91a65d | CC-BY-4.0 | 전부(중복 제거): 공격 ≈317 · 정상 ≈251 | ko | direct / benign |
   | `kimchunsik03/KoreanGuardrail` @cd4c93cb | CC-BY-4.0 | 공격 씨앗 301, 정상 하드 네거티브 씨앗 204, 벤치마크의 난독화 변형(5기법 × 강도 1.0) | ko | direct·role_spoof·indirect / encoding / hard_negative |
   | `JHC56/korean-prompt-injection-registers` @d348b1fd | BSD-2-Clause(번역) + Apache-2.0(deepset) | deepset 문항의 한국어 7말투(공격 273·정상 861). Tensor Trust 부분은 라이선스 불명이라 뺀다 | ko | direct·role_spoof / benign |
   | `tristan-kim/guardrail4agent-sft` @bd89cc6b | Apache-2.0 | S3(도구 결과 속 인젝션)·S5(시스템 프롬프트 추출)·safe 표본 | ko | indirect·direct / benign |
   | `taeyun16/korean-service-query-gating-v1` @9f0cc771 | MIT | core 표본 | ko | benign |
   | `deepset/prompt-injections` | Apache-2.0 | 전부 662(공격 263·정상 399) | en·other | direct / benign |
   | `Lakera/gandalf_ignore_instructions` @04737b65 | MIT | 표본(‘ignore’ 문구로 골라진 셋이라 따로 보고) | en | direct |
   | `meta-llama/PurpleLlama` prompt_injection.json @f64eebd5 | MIT | security-violating 180(logic-violating은 시스템 프롬프트에 달린 라벨이라 뺀다) | en·other | direct·indirect |
   | `microsoft/BIPIA` 공격 문자열 @a004b69e | MIT | 250(문서에 심는 간접 공격) | en | indirect |
   | `uiuc-kang-lab/InjecAgent` | MIT | 고유 공격 지시 62(도구 결과에 심는 간접 공격) | en | indirect |
   | `ethz-spylab/ctf-satml24` | MIT | 사용자 턴이 둘 이상인 공격 대화 표본 | en | multi_turn |
   | `drakkeng/outilsia-injections-prompt-multilingue` @94be44f2 | CC-BY-4.0 | 전부 383(공격 229 — 난독화 포함, 정상은 출처가 만든 하드 네거티브 154) | en·other(ko 2) | 전 유형 / hard_negative |
   | `leolee99/NotInject` | MIT | 전부 339(트리거 단어가 든 정상 문장) | en·other | hard_negative |
   | `eval/benign/all100.jsonl`(연구 단계) | 본 저장소 | 100 | ko | benign |
   | 에이전트 작성(이 단계) | 본 저장소 | HR·고객 지원·개발·금융·의료·법률 업무 문장과 하드 네거티브(‘지시사항 무시’ ‘개발자 모드’ ‘DAN 프로젝트’ ‘시스템 프롬프트 작성법’ 등) | ko | benign / hard_negative |

   빼는 것: 유해 요청 셋(MultiJail·Salad-Data·PolyGuardPrompts·JBB behaviors — 인젝션이 아니다), in-the-wild 탈옥 원본(연구용 한정 문구)과 그 번역·사본
   (`MarkrAI/ko-jailbreak`의 template 행, `jackhhao/jailbreak-classification` — §6 리뷰에서 뺐다), 라이선스 조건이 불분명한 셋(tom-gibbs 다중 턴·XL-SafetyBench·Tensor Trust 파생),
   전체 llmail 라벨 파일(수백 MB).
2. **스키마**(JSONL 한 줄): `id`, `label`(1 공격·0 정상), `text`(다중 턴은 `turns` 문자열 목록), `lang`(ko·en·other), `type`(direct·indirect·role_spoof·encoding·multi_turn·
   benign·hard_negative), `role`(user·tool — 간접 공격과 문서형 정상은 tool), `group`(같은 원문의 변형·말투·번역·합성이 공유 — 출처를 넘어도 한 가족, 홀드아웃은 그룹째로 나눈다),
   `source`, `transform`(변형이면). 같은 문장은 셋 전체에 하나만 둔다.
   - 유형: direct 사용자가 직접 지시를 뒤집거나 역할을 바꾸거나 시스템 프롬프트를 묻는다 · indirect 문서·메일·도구 결과에 심은 지시 · role_spoof 가짜 역할 머리·대화 마크업
     (`System:`·`[SYSTEM]`·`<|im_start|>`) · encoding 난독화(전각·제로폭·띄어쓰기·자모 분해·초성·base64·rot13·leet 등) · multi_turn 여러 턴에 걸친 공격.
3. **홀드아웃 봉인**: 그룹의 SHA-256 첫 바이트로 20%를 `holdout.jsonl`에 둔다. 파일 SHA-256을 이 결정 §6에 적고 테스트가 지킨다. 룰·임계값·분류기 조정에 쓰지 않는다 —
   점수는 `dev.jsonl`로 내고, 홀드아웃은 단계의 최종 측정(18단계 분류기 게이트)에만 한 번 쓰고 그때마다 결정에 적는다.
4. **점수** `eval/injection/score.py`: 판정기 = `(item) -> 점수 0~1` 함수 하나(룰은 0/1, 분류기·웹훅은 17·18단계가 더한다). 전체·언어별·유형별 재현율과 오탐률(Wilson 95%),
   recall@FPR 1%·0.5%(점수형은 정상셋에서 그 오탐률을 넘지 않는 가장 낮은 문턱, 0/1 판정기는 오탐률이 넘으면 '미달'). 원문은 출력하지 않는다(그룹·id만).
5. **기준선**: 지금 룰(R1·R2, `match_rules`)의 dev 점수를 §6과 README '막지 못하는 것'에 적는다. 테스트가 그 숫자를 고정한다 — 룰을 바꾸면 결정과 함께 갱신한다.
6. **라이선스 준수**: `eval/injection/SOURCES.md`에 출처·리비전·라이선스·저작권자·바꾼 것(CC-BY의 변경 표시)을 적고, MIT·BSD 고지문을 함께 둔다.
7. 크기: 데이터 파일 합계 5MB 이하(긴 템플릿·메일은 표본을 줄인다).

### 3. 버린 대안

- **공격을 LLM으로 만들거나 영어 공격을 한국어로 번역**: PLAN이 금지한다. 측정 대상(우리 탐지기)과 같은 편향을 셋에 심는다.
- **우리가 쓴 한국어 문장만으로 정상셋**: 우리 탐지기를 아는 사람이 쓴 문장은 쉬운 쪽으로 치우친다 — 공개 한국어 정상셋(서비스 질의·가드레일 정상·말투 번역)을 함께 쓴다.
- **유해 요청셋을 공격으로**: 인젝션 탐지기의 일이 아니다(가드레일 영역). 섞으면 재현율이 의미를 잃는다.
- **행 단위 무작위 홀드아웃**: 같은 원문의 말투·난독화 변형이 dev와 홀드아웃에 갈라지면 홀드아웃이 새지 않는다는 보장이 없다 — 그룹째로 나눈다.
- **세션이 매번 받아 쓰기(데이터 미동결)**: 상류가 바뀌면 숫자가 바뀐다. 받은 결과를 저장소에 고정하고 SHA-256을 기록한다.

### 4. 완료 기준 (`tests/test_d123_injection_eval.py`)

| # | 기준 |
|---|---|
| E1 | 셋 파일·해시·라이선스 표(SOURCES.md)가 있고, 모든 줄이 스키마를 지킨다(id 유일, label·lang·type·role 값, group 단위 분할 — dev와 홀드아웃이 그룹을 공유하지 않는다) |
| E2 | 정상 2,000 이상, 그중 하드 네거티브 20% 이상, 한국어 공격·정상이 각각 있다 |
| E3 | 홀드아웃 SHA-256이 결정과 같다 |
| E4 | `score.py`가 dev에서 룰 판정기의 표를 내고, 숫자가 결정의 기준선과 같다(CI 스모크) |
| E5 | 원문이 점수 출력에 나오지 않는다 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 |

### 5. 한계

- 공개셋의 라벨 잡음(deepset의 '역할 요청'이 공격 라벨, gandalf의 'ignore' 선택 편향, ctf 대화의 성공 라벨 등)과 LLM 합성 출처(KoreanGuardrail 절반·guardrail4agent·
  서비스 질의셋·NotInject)를 그대로 안는다. 출처별 표를 따로 내서 한 출처가 전체 숫자를 끌지 않게 본다.
- 같은 원문의 변형·말투가 여럿이라 행 수보다 독립 표본이 적다 — Wilson 구간이 실제보다 좁다.
- 다중 턴 공격은 영어(ctf, 공격 팀 단위로 묶어 77대화)뿐이다 — 한국어 다중 턴은 없다. 우리가 쓴 한국어 정상 문장은 우리 시각의 문장이다.

### 6. 결과 (2026-10-31)

- **셋**: 6,871행 = dev 5,492 + 봉인 홀드아웃 1,379(20.1%), 1.96MiB. 공격 3,360(한국어 2,028) · 정상 3,511(한국어 2,608, 하드 네거티브 1,022 = 29%).
  `eval/injection/build.py`가 고정 리비전(datasets-server 출처는 받은 날짜)에서 받아 결정적으로 만든다 — 두 번 만들어 바이트가 같았다.
  - `holdout.jsonl` SHA-256 **5548bb27ec5fd0a8005dedacfeb932dafc5484eec99532890394860e549aed0f**
  - `dev.jsonl` SHA-256 **371b58ddb701cb9f1174abf56f8fdfc60a46d2bfa936e5ed006c97ad57b25d39**
  - 출처·라이선스·바꾼 것·고지문은 `eval/injection/SOURCES.md`. 한국어 업무 문장·하드 네거티브는 에이전트 9개가 쓰고(720) 두 검증자가 하드 네거티브를 따로 읽어 3개를 뺐다(717, `benign_ko.jsonl`).
- **룰 기준선(dev, `python3 eval/injection/score.py`)**: 재현율 **230/2,630 = 8.7%**(7.7~9.9%), 오탐률 **76/2,862 = 2.7%**(2.1~3.3%), recall@FPR 1%·0.5% **미달**(0/1 판정기의 오탐률이 넘는다).
  - 언어별 재현율: 한국어 94/1,592 = 5.9% · 영어 126/788 = 16.0% · 그 밖 10/250 = 4.0%. 유형별: 직접 12.6% · 간접 5.1% · 역할 위조 2.9% · 난독화 2.9% · 다중 턴 17.7%.
  - 오탐: 일반 정상 0/2,034(0.0~0.2%), 하드 네거티브 76/828 = 9.2%(한국어 64/435 = 14.7%). 한국어 오탐률 64/2,138 = 3.0%.
  - 출처별로 보면 'ignore' 문구로 골라진 gandalf만 45%대다 — 연구 단계 헤드라인(74.5% → 0.2%)이 템플릿 문구 매칭이었다는 부록 A의 지적이 같은 자로 확인됐다.
- **리뷰 + 반박 검증**(울트라코드 워크플로, 에이전트 74): 리뷰어 4(빌드·점수·라이선스·테스트) → 발견 35 → 31 남음(4 반박). 고친 것:
  JHC56 한국어 말투가 원문 deepset 행과 다른 그룹이라 홀드아웃의 12%가 dev의 번역이거나 번역을 dev에 둠(→ 원문과 한 그룹), ctf 대화가 같은 팀의 같은 첫 턴을 되풀이(→ 팀 단위 그룹·팀마다 10),
  deepset '쌓은' 합성 문장과 원문이 다른 그룹(→ 포함 관계로 묶음), 셋 전체 중복 미제거(→ 98행 뺌, 라벨 충돌 0), in-the-wild 원본의 번역(ko-jailbreak)·사본(jackhhao) 포함(→ 뺌),
  유형 오분류(역할 바꾸기 → direct, 에둘러 묻는 시스템 프롬프트 요청 → direct, drakkeng 정상 → hard_negative), 언어 휴리스틱(악센트 → other, 변형은 원문 언어),
  CC BY 4.0 라이선스 주소·drakkeng 인용·NotInject 저작권줄, 점수 스크립트의 언어별 recall@FPR·'미달' 건수·문턱 정밀도·줄 나누기, 테스트(셋 전체 중복 금지·dev 해시 고정·짧은 원문 누출 검사).
  반박된 4: base64 래퍼(결정적 변형의 일부), `--holdout`의 문턱 선택(그 셋의 정상으로 고르는 것이 recall@FPR의 정의), 'inf' 문턱 표시, README 라이선스 절.
- `tests/test_d123_injection_eval.py` 8건(E1~E5 + 문턱 규칙 단위 테스트): 홀드아웃·dev 바이트 해시 고정, 기준선 숫자 고정, 원문 비출력. 홀드아웃 바이트 1개·룰 어휘 1개를 바꾸면 각각 실패함을 확인했다.
- 계획과 다른 점: ko-jailbreak·jackhhao를 뺐다(§2-1 표에서 지움), 한국어 다중 턴은 없다, datasets-server 출처(deepset·gandalf·ctf·NotInject)는 리비전 대신 받은 날짜와 저장소 고정으로 재현한다.
- 못 한 것·한계: 공개셋의 라벨 잡음과 LLM 합성 출처는 그대로다(§5). 홀드아웃은 아직 한 번도 열지 않았다 — 18단계 분류기 게이트에서 처음 쓴다.

## D-124. 운영 대시보드(읽기 전용) — 요청마다 가림·차단·거절 결과와 사유, 시험 트래픽 16장면 (2026-10-31, PLAN 16-1단계)

### 1. 근거

- 사용자 요청(2026-10-31): 설명서 화면 C 같은 운영 대시보드를 제품에 넣고, 시험할 때 무엇을 어떻게 막았는지가 보여야 한다.
- 지금 처리 결과를 보는 길은 둘뿐이다 — 관리 키로 여는 Prometheus 텍스트, 감사 JSONL(이미지에서는 stdout). 체험·시험 환경에는 Grafana가 없다.
  화면 B(`web/app.py`)는 자기가 띄운 스택만 보여 준다. compose·k8s·PoC 설치에는 화면이 없다.
- 감사 레코드에는 원문이 없고 지표도 이미 그 레코드에서 센다(`AuditLog(on_write=Metrics.observe)`). 같은 훅에 결과 분류와 최근 줄만 더하면 된다.
- 검토 중 FastAPI 기본 문서 경로(`/docs`·`/redoc`·`/openapi.json`·`/docs/oauth2-redirect`)가 인증 없이 200임을 재현했다(D-109 허용 목록 위반) —
  `/docs`는 cdn.jsdelivr.net 스크립트를 읽는다. 관리 키를 담는 화면과 같은 출처에 제3자 스크립트가 남아서는 안 된다.
- 감사 `error`가 비는 4xx가 둘 있다 — 파싱 400과 허용 목록 밖 404·405. 결과 분류의 사유가 비게 된다.
- 지금 지표의 `observe`는 모양이 이상한 레코드에서 예외를 낸다(재현: `Metrics().observe({"detectors": [{"detector": "pii_mask", "pii": "phone"}]})` → AttributeError).
  `AuditLog.write`가 `on_write`를 try 없이 부르고 미들웨어의 `audit.write`도 try 밖이라 그 요청이 500이 된다. 집계·화면 버그가 프록시 요청을 깨면 안 된다.
- `gateway_pii_masked_total`에 detect 정책의 찾은 수가 섞인다(`observe`가 `pii`·`pii_mask` 둘 다 센다) — '가린 수'가 아니다.

### 2. 결정

결정 표 13번 그대로다: 게이트웨이 안 읽기 전용 화면, 데이터는 관리 키 Bearer, 키는 탭의 sessionStorage에만, 숫자는 프로세스 하나의 누적 + 최근 200줄, 2초 갱신.
새 의존성·환경변수·컨테이너는 없다.

1. **같은 출처 정리** — `FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)`. 네 경로 모두 404(허용 목록 밖과 같은 응답).
   끝에 '/'가 붙은 경로도 307(Location은 요청의 Host) 대신 404 `not_found`다(리뷰 뒤 더함 — 307 줄이 '그대로 전달'로 세어졌다).
2. **감사 `error` 빈칸 채우기** — 파싱 400은 `ApiError.code`(`invalid_json`·`invalid_messages`·`invalid_request`·`invalid_stream`), 허용 목록 밖 404·405는 `not_found`.
   이제 게이트웨이가 낸 4xx·5xx 감사 줄에는 모두 사유 코드가 있다.
3. **결과 분류** `gateway/metrics.py`의 `outcome(rec) -> (결과, 사유)` — 위에서부터 처음 맞는 것. 사유는 공백 없는 코드다.

   | 순서 | 조건 | 결과 | 사유 |
   |---|---|---|---|
   | 1 | `blocked` | `blocked` | `blocked_by`(검사기 이름) |
   | 2 | `error` ∈ `REJECTED` | `rejected` | 그 코드 |
   | 3 | `error` ∈ `UPSTREAM_ERRORS` | `upstream_error` | 그 코드(상태는 보지 않는다 — 스트림 도중이면 200) |
   | 4 | 그 밖에 `error`가 있음 | `failed` | 예외 이름(내부 500, 클라이언트 끊김 `ClientDisconnect`, 처리 중 취소 `CancelledError` — 스트림 도중 끊김·종료 유예 초과) |
   | 5 | 상태 400 이상 | `upstream_error` / `rejected` | `upstream_ms`가 있으면 `upstream_<상태>`(상류 응답 그대로), 없으면 `http_<상태>` |
   | 6 | `transformed` | `masked` | 개인정보를 가렸으면 `pii_mask`, 이력 턴만 가렸으면 `masked_turns`(그 밖의 검사기면 그 이름) |
   | 7 | 인젝션 관측 적중(`would_block`) / 가리지 않은 탐지 | `observed` | `injection_observe` / `unmasked` |
   | 8 | 나머지 | `passed` | `none` |

   - `REJECTED` 12: unauthorized·rate_limited·request_too_large·too_many_findings·model_not_allowed·invalid_json·invalid_messages·invalid_request·invalid_stream·not_found·
     gateway_busy·upstream_busy.
   - `UPSTREAM_ERRORS`: `httpx.RequestError`의 하위 클래스 이름 전부(httpx 모듈에서 읽는다 — ConnectError·ReadTimeout·RemoteProtocolError…) + `response_too_large` +
     `upstream_stream_error`(리뷰 뒤 더함 — 머리 200 뒤 상류가 스트림 안에 보낸 오류 이벤트: Messages·Responses `type: error`, Responses `response.failed`, Chat `{"error": …}`.
     `StreamRestorer.failed`가 최상위만 보고, 이벤트는 그대로 클라이언트에 간다. 그 뒤 클라이언트가 끊어도 이 코드다 — 먼저 일어난 원인).
   - 결과 7가지와 화면 라벨: masked 가림 후 전달 · passed 그대로 전달 · observed 기록만 · blocked 차단 · rejected 거절 · upstream_error AI 회사 오류 · failed 오류·끊김.
4. **최근 줄** `row(rec)` — 고정 키 19개(`ROW_KEYS`): ts·request_id·client·policy·api·model(앞 64자, 짝 없는 서로게이트는 `Adapter.model`이 '?'로)·status·outcome·reason·gateway_ms·upstream_ms(null = 상류 응답 없음)·
   masked{종류: 수}(pii_mask의 `pii`)·unmasked{종류: 수}(detect 정책의 `pii` + pii_mask의 `unmasked`)·masked_turns·rules(앞 5개, {rule, trigger, object}, trigger·object 앞 40자)·
   issued·restored·suspect·new(감사 줄의 `pii_*` — 스트림의 restored는 조각에서 센 수와 끝 이벤트(Responses completed·incomplete·failed, 응답 전체)에서 센 수 중
   큰 쪽이다. 리뷰 뒤 — 비스트리밍과 같은 단위). 싣지 않는 것: ip·path·query_keys·req_sha256_12·findings(위치)·usage·upstream_request_id·config. 원문·가짜 값은 처음부터 레코드에 없다.
5. **`Metrics`** — `masked`는 pii_mask만 센다(뜻 바로잡기), 새 `unmasked`·`outcomes`(Counter[(결과, 사유)])·`recent`(deque 200, 최신이 앞)·`started`(ISO 밀리초)·`pid`.
   `observe`는 몸통 전체를 try로 감싼다 — 실패하면 그 레코드의 남은 집계와 줄을 버리고 예외를 올리지 않는다(감사 줄은 이미 써졌다).
   `snapshot()`은 락 안에서 복사한다. 평균은 횟수가 0이면 null. 지표 둘을 더한다: `gateway_outcomes_total{outcome,reason}`·`gateway_pii_unmasked_total{kind}`.
6. **경로**(모두 GET, `/__gateway/*`라 감사·지표·레이트리밋에 들어가지 않는다)
   - `/__gateway/dashboard`: 관리 키가 설정된 게이트웨이에만 있다(아니면 404). 인증 없이 정적 HTML만 준다 — 데이터·키·버전이 없다(주소창 이동으로는 Bearer 헤더를 실을 수 없다).
     CSP `default-src 'none'; script-src 'sha256-…'; style-src 'sha256-…'; img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none';
     require-trusted-types-for 'script'` + nosniff·no-referrer·no-store. 해시는 import 때 `gateway/dashboard.html`의 유일한 `<script>`·`<style>` 블록에서 계산한다 —
     블록 수가 하나가 아니거나 파일이 없으면 기동 실패. 해시 전에 줄 끝을 LF로 바꾼다(브라우저와 같다 — 리뷰 뒤 더함, `.gitattributes`도 LF로 체크아웃).
   - `/__gateway/stats`: `_is_admin`(Bearer + `hmac.compare_digest`)만 200 JSON, 나머지(키 없음·틀린 키·`?key=`·Basic·관리 키 미설정)는 404. no-store·nosniff, CORS 헤더 없음.
     키: started·now·pid·max_connections·requests·status{"200": n}·outcomes(7가지 늘)·reasons[{outcome, reason, count}](많은 순)·masked·unmasked·injection{observe, block}·
     restored·residual·suspect·new·gateway_ms_avg((Σtotal − Σupstream) ÷ 횟수 = 감사 gateway_ms 평균)·upstream_ms_avg·vault_sessions{정책: n}·
     upstreams{주소: 빌려 간 연결 — 주소가 같고 timeout이 다른 풀은 가장 바쁜 풀(상한과 같은 단위, 리뷰 뒤 합에서 바꿈)}·recent[줄…].
     호스트 이름은 싣지 않는다(스크린샷에 장비 이름이 남지 않게 — 프로세스는 started·pid로 가른다).
   - 세션·연결 게이지 계산은 `_gauges(request)` 하나를 metrics와 stats가 함께 쓴다. `code_fingerprint()`가 `dashboard.html`도 해시한다.
7. **화면** `gateway/dashboard.html`(한 파일, 400줄 이내, 패키지 안이라 휠·이미지에 함께 실린다) — 규칙은 PLAN 16-1이 원본이다. 요점:
   - 속성 없는 `<style>`·`<script>` 하나씩, 줄 끝 LF만, 외부 자원 없음, `<link rel="icon" href="data:,">`, 정적 `<p id="nojs">`(스크립트가 지운다), 키 카드 `id="key"`.
   - 값은 `createElement`·`textContent`·`replaceChildren`만. innerHTML·인라인 이벤트·`style=` 속성 없음(막대는 CSSOM `el.style.width`나 `<meter>`).
   - 키는 sessionStorage에만, fetch는 `Authorization: Bearer`·`cache: "no-store"`·`credentials: "omit"`. 404면 키를 지우고 안내한다.
     키 칸은 `type=password` + `autocomplete="one-time-code"`(리뷰 뒤 — autocomplete=off는 Chrome이 무시하고 키를 비밀번호로 저장하자고 물었다).
   - (리뷰 뒤) 표는 통째로 다시 그리지 않는다 — 줄 노드를 요청 ID로 재사용해 초점·선택·펼친 상세가 갱신에 살아남는다. 값이 같으면 글자를 다시 쓰지 않는다.
   - 구역: 키 카드 → 머리 띠(info: 버전·코드 지문·설정 버전·정책별 검사기, 시작 시각·pid, 갱신 시각, [멈춤]·[잠금]) → 타일 8개 → 처리 결과 7가지·사유별 건수 → 종류별 가린 수(12종 막대 + 기록만 한 줄) →
     최근 요청 표(200줄, 결과 필터·찾기, 줄을 누르면 그 줄 JSON) → 바닥글.
   - **traffic.py와의 계약**: 최근 요청 표의 줄은 `<tr data-rid="<request_id>">`이고, 결과 라벨(위 3의 한국어)은 배지 `<span class="badge o-<결과>">`,
     '어떻게 처리했나' 문장은 `<td class="how">`, 의심·새 값 배지는 그 다음 복원 칸에 있다(리뷰 뒤 칸별로 — 줄 전체 글자로 찾으면 틀린 배지도 통과했다).
     문장 규칙(종류 이름은 아래 사전):
     - masked/pii_mask: `가짜 값으로 바꿔 보냄 — 전화번호 1 · 이메일 1 → 2개 되돌림`(+ 가리지 않은 것이 있으면 ` · 기록만: 계좌번호 1`, 이력 가림이 있으면 ` · 이력 1턴 가림`)
     - masked/masked_turns: `이력 1턴 가림(R1 지시 무효화)` 뒤에 `— 이번 턴은 그대로 보냄`(+ 가리지 않은 것이 있으면 ` · 기록만: 계좌번호 1` — 리뷰 뒤 더함)
     - blocked: `인젝션 룰 R1 지시 무효화(ignore + instructions) — 이번 턴 차단, 상류 호출 없음`(인젝션이 아닌 검사기면 `<검사기> 차단 — 상류 호출 없음`)
     - observed/injection_observe: `인젝션 룰 R1 적중 — 기록만(차단 꺼짐), 그대로 보냄`
     - observed/unmasked: `전화번호 1 찾음 — 가리지 않음(원래 값이 나감, 기록만)`
     - rejected: `<사유 라벨>(<HTTP> <코드>) — 상류 호출 없음`(예: `허용 안 된 모델(403 model_not_allowed) — 상류 호출 없음`)
     - upstream_error: `AI 회사가 429를 줌 — 그대로 전달` · `AI 응답 시간 초과(504 ReadTimeout)` · `AI 회사 연결 실패·끊김(502 ConnectError)` · `AI 응답이 너무 큼(502 response_too_large)` —
       상태가 200이면 `(스트림 도중, <코드>)` · `AI 회사가 스트림 도중 오류를 보냄 — 그대로 전달(200 upstream_stream_error)`
     - failed: `응답 도중 끊김(ClientDisconnect)`(200) · `클라이언트가 끊음(500 ClientDisconnect)`(본문을 보내다 끊음) · `처리 중 취소됨(500 CancelledError)`(종료 유예를 넘긴 요청) ·
       `게이트웨이 내부 오류(500 <예외 이름>)`
     - passed: `그대로 보냄 — 찾은 것 없음`
     - '상류 호출 없음'은 blocked·rejected 줄에만 붙는다(이 줄은 upstream_ms가 늘 null). 복원 칸: `복원/발급`, suspect > 0이면 `의심 n`, new > 0이면 `새 값 n` 배지.
   - **라벨 사전**(화면·`docs/operations.md` '대시보드' 절이 같은 말을 쓴다): 종류 rrn 주민등록번호 · frn 외국인등록번호 · passport 여권번호 · driver 운전면허번호 · card 카드번호 ·
     phone 전화번호 · email 이메일 · secret 자격 증명 · brn 사업자등록번호 · crn 법인등록번호 · account 계좌번호 · ipv4 IP 주소. 룰 R1 지시 무효화 · R2 역할 전환·제약 해제.
     사유: unauthorized 키 없음·틀림 · rate_limited 분당 한도 · request_too_large 본문 상한 · too_many_findings 개인정보가 너무 많음 · model_not_allowed 허용 안 된 모델 ·
     invalid_* 요청 형식 오류 · not_found 허용 목록 밖 경로 · gateway_busy 게이트웨이 바쁨 · upstream_busy AI 연결 가득 · upstream_<상태> AI 회사가 준 오류 그대로 전달 ·
     시간 초과 예외(ConnectTimeout·ReadTimeout·WriteTimeout·PoolTimeout) AI 응답 시간 초과 · 그 밖의 UPSTREAM_ERRORS AI 회사 연결 실패·끊김 · response_too_large AI 응답이 너무 큼 ·
     upstream_stream_error AI 회사가 스트림 도중 오류를 보냄 ·
     ClientDisconnect 클라이언트가 끊음 · CancelledError 처리 중 취소됨(스트림 도중 끊김·종료 유예 초과 — 리뷰 뒤 나눔) · 그 밖의 예외 게이트웨이 내부 오류 · injection_rule_turn 이번 턴의 수상한 지시 · pii_mask 개인정보를 가짜 값으로 바꿈 ·
     masked_turns 이력의 수상한 턴을 가림 · injection_observe 수상한 지시 — 기록만 · unmasked 가리지 않는 개인정보 — 기록만 · none 해당 없음.
8. **시험 트래픽** `scripts/traffic.py`: 스텁과 게이트웨이를 서브프로세스로 띄우고(셸의 `GATEWAY_*`·`TARGET_*`·`STUB_*`·`UVICORN_*`를 지운다) 16장면(PLAN 16-1 표)을 보낸 뒤,
   stats의 recent에서 요청 ID로 줄을 찾아 기대(결과·사유·종류)와 대조한다. 클라이언트 app(기본 정책)·strict(설정 파일 — `injection = "block"`, `allowed_models = ["stub-*"]`)·
   audit(설정 파일 — `pii_mode = "detect"`). 관리 키 `traffic-admin`(체험값), 대체값 키는 실행마다 새로, `GATEWAY_MAX_BODY_BYTES=4096`·`GATEWAY_TIMEOUT=1`, 감사 로그는 임시 파일.
   플래그 `--rounds N`(어긋나면 종료 코드 1, 0 = Ctrl-C까지)·`--port`·`--shot PNG`(W8). 외부 공급자 옵션은 두지 않는다.
   (리뷰 뒤) SIGTERM도 Ctrl-C처럼 정리한다, N회를 다 돌기 전에 멈추면 1, 음수 회차·범위 밖 포트는 2, Chrome이 없거나 실행하지 못하면 2('Chrome을 실행하지 못했다'),
   환경변수 CI가 있으면 Chrome에 `--no-sandbox`(여기서 만든 로컬 페이지만 연다). 장면 1·2·3은 restored를 정확히 본다. 장면 9는 대체값 끝 4자리가 원래 번호에 들어가는 키(2/10,000)를 다시 만든다.
9. **연결**: load.py·web/app.py·compose 머리 주석에 대시보드 주소와 관리 키 한 줄, `GATEWAY_ADMIN_KEY` 설명 여섯 곳을 "info·metrics·stats·대시보드를 연다. 없으면 모두 404"로.

### 3. 버린 대안

- **Grafana만 쓰기**: 체험·시험 환경에 없고, 요청별 처리(무엇을 왜 막았나)는 지표로 못 본다. 여러 파드 합산·기간 그래프가 필요해지면 조건부 표의 Grafana 견본으로 간다.
- **별도 서비스·컨테이너**: 설치 단위가 늘고 감사 레코드를 다시 실어 날라야 한다. 같은 프로세스의 같은 훅이면 된다.
- **감사 파일 읽기**: 이미지는 감사 로그를 stdout으로 쓴다 — 읽을 파일이 없다.
- **SSE·WebSocket 실시간**: `EventSource`는 Authorization 헤더를 달 수 없다(키를 URL에 실어야 한다). 2초 폴링이면 충분하다.
- **이력 저장(파일·DB)**: 영속 저장은 '하지 않는 것'이다. 장기 보관은 감사 로그·Prometheus 몫.
- **쿠키 세션·Basic·URL 키**: 쿠키는 CSRF·로그인 흐름이 필요하고, Basic은 브라우저가 자격 증명을 기억하며, URL 키는 기록·Referer로 샌다.
- **키를 JS 메모리에만 두기**: 새로고침마다 다시 넣어야 한다. sessionStorage는 탭을 닫으면 사라진다 — 탭 수명이 적당하다.
- **프레임워크·차트 라이브러리·CDN**: CSP 해시 하나로 묶을 수 없고 공급망이 는다. 막대는 CSS로 된다.
- **게이트웨이 안에서 파드 합산**: 파드끼리 통신·저장이 필요하다. 파드 하나씩 port-forward로 보고 합산은 Prometheus가 한다.
- **두 번째 링(차단·거절만 담기)**: 지금은 링 하나로 충분하다(`# ponytail:` 주석에 천장).
- **Playwright**: 새 의존성. headless Chrome의 `--dump-dom`·`--screenshot`으로 확인한다.

### 4. 완료 기준 (`tests/test_d124_dashboard.py`, `scripts/traffic.py`)

| # | 기준 |
|---|---|
| W1 | `/docs`·`/redoc`·`/openapi.json`·`/docs/oauth2-redirect` 404. stats는 Bearer 관리 키에만 200 JSON — 키 없음·틀린 키·`?key=`·Basic·관리 키 미설정은 404. stats에 `Access-Control-Allow-Origin` 없음. router의 `/__gateway/*`는 모두 GET |
| W2 | 관리 키가 있으면 dashboard 200 `text/html`(인증 없이), 없으면 404. CSP 지시어 전부·`'unsafe-inline'`·`'unsafe-eval'` 없음, 해시 = 본문의 유일한 `<script>`·`<style>`의 sha256(테스트가 따로 계산). nosniff·no-referrer·no-store. 본문에 innerHTML·outerHTML·insertAdjacentHTML·document.write·eval·new Function·localStorage·document.cookie·`style=`·인라인 `on…=`·`http://`·`https://`·관리 키 값 없음. `<link rel="icon" href="data:,">`·`id="nojs"` 있음. `\r` 없음 |
| W3 | `outcome()` 표 테스트가 8규칙을 모두 지난다(PLAN 16-1의 모양 목록). 소스 검사: `gateway/`의 `upstream_error = "…"` 리터럴·`ApiError`·`ChatRequestError`가 내는 코드(기본값 포함)·`too_many_findings`가 모두 `REJECTED`나 `UPSTREAM_ERRORS`에 든다. 실제 요청에서 파싱 400의 감사 `error`가 `invalid_json`, 경로 404가 `not_found` |
| W4 | 합성 전화·이메일·키·주민번호·공격 문장을 보낸 뒤 stats에 보낸 원문도, 스텁이 받은 가짜 값도 없다. 줄 키 = `ROW_KEYS`. 1,000자 model → 64자, 1,000자 트리거·목적어 → 40자, 룰 10개 → 5개. 최악의 줄(12종 masked·unmasked, 한국어로 채움) JSON ≤ 2.5KB, 200줄 ≤ 0.5MB |
| W5 | 205건 → recent 200건·최신이 먼저. dashboard·stats·info를 여러 번 불러도 카운터·recent 그대로. 모양이 이상한 레코드(detectors None, pii 문자열, 필드 누락)에도 observe가 예외를 올리지 않는다. test_e2 둘 그대로 통과 |
| W6 | 같은 순간 stats의 requests·masked·unmasked·outcomes·injection·restored·suspect·new = `/__gateway/metrics`. requests = 감사 줄 수 |
| W7 | `python3 scripts/traffic.py --rounds 1 --port <빈 포트>` 종료 코드 0, 16장면 일치, 결과 6가지(masked·passed·observed·blocked·rejected·upstream_error). CI에서 돈다 |
| W8 | (세션 — 리뷰 뒤로는 W7 테스트도 Chrome이 있으면 `--shot`을 붙여 돈다. CI는 `--no-sandbox`, Chrome을 실행하지 못하면 W7만 확인하고 건너뜀) `--shot docs/dashboard.png` 0으로 끝남: ① headless Chrome `--dump-dom`으로 실제 서버 화면 — CSP 아래 스크립트가 돌아 `nojs`가 사라지고 키 카드가 보인다(hidden 없음), 연 뒤 stats requests 그대로 ② 마지막 stats·info를 넣은 `file://` 사본(fetch 대체 스크립트 + 같은 CSP의 meta, 그 스크립트 해시를 더하고 frame-ancestors는 뺌)을 1280×1600으로 찍는다 ③ 같은 사본의 `--dump-dom`에서 16장면 요청 ID 줄마다 결과 라벨·핵심어(칸별 — 배지·`td.how`·복원 칸), 사본이 부른 fetch마다 주소에 '?'·키가 없고 Bearer 머리·no-store·omit(리뷰 뒤 더함). PNG ≤ 600KB, 세션이 열어 본다 |
| W9 | compose로 띄워 dashboard가 같은 CSP로 200(HTML이 이미지에 있다), `local-admin-key`로 stats 200, 머리 주석의 curl이 recent 맨 앞에 masked(phone 1). load.py 30초 판정 통과·대시보드 주소 출력, 감사 gateway_ms(비스트리밍) p95 ≤ D-122의 18.5ms × 1.5 |
| W10 | api-compat의 `/__gateway/*` 집합 = router. operations '대시보드' 절·지표 표·로그 표, 관리 키 설명 여섯 곳, README·README.en·CHANGELOG·compose 주석, 설명서 HTML·PDF 갱신. 설명서에 '하나뿐'·'숫자만 제공'·'제품에 없음'·'제공하지 않음'·'지어낸 값' 0건. 새 의존성·환경변수 없음(test_s3 22개). 전체 `pytest -q`·`ruff check .`·`mypy` 통과 |

### 5. 한계

- 프로세스(파드)마다 따로이고 재시작하면 0이다. 여러 파드를 Service 너머로 보면 폴링마다 다른 파드의 숫자가 보인다 — 파드 하나씩 port-forward로 본다.
- 최근 200건만 남는다. 부하 중에는 차단·거절 줄도 몇 초 안에 밀려난다(두 번째 링은 필요해질 때).
- 화면은 한국어다(코드 이름을 함께 적는다).
- 관리 키가 설정돼 있으면 화면 경로가 있다는 사실이 드러난다(정적 HTML — 데이터는 없다). 관리 키로 최근 요청 요약까지 열린다(원문·가짜 값·위치·IP는 없다).
- 스트림은 끝나야 줄이 생긴다.
- traffic.py는 게이트웨이가 스스로 내는 rate_limited(429)·gateway_busy·upstream_busy(503)·내부 오류(500)·끊김을 만들지 않는다(상류 429 전달은 장면 15).
- (리뷰 뒤 더함) 틀린 관리 키는 감사·지표·레이트리밋에 남지 않는다(D-109·§2-6, 클라이언트 키 401도 레이트리밋 앞이다) — 추측을 막는 것은 키 길이다.
  배포 문서대로 `python -m gateway keygen`(192비트) 키를 쓴다. 견본의 짧은 키(local-admin-key·traffic-admin 등)는 127.0.0.1 전용이다.
- (리뷰 뒤 더함) 비스트리밍 요청을 클라이언트가 기다리다 끊으면 게이트웨이가 알지 못해 상류 응답대로 200으로 남는다(D-122). 본문을 보내다 끊으면 500 `ClientDisconnect`라 5xx 비율에 든다.
- (리뷰 뒤 더함) 키 칸의 비밀번호 저장 확인은 Chrome(헤드리스)에서만 쟀다. 다른 브라우저가 묻으면 저장하지 않는다(operations에 적음).
- (리뷰 뒤 더함) 델타 없이 Responses 끝 이벤트(`*.done`·`response.completed`)로만 온 텍스트의 새 PII·의심·잔여는 세지 않는다 — 조각 텍스트에서만 센다(복원 수는 센다).
- (리뷰 뒤 더함) traffic.py `--shot`에서 Chrome이 120초 안에 끝나지 않으면 실패(1)다 — 화면 스크립트가 멈춘 회귀와 가를 수 없다. CI 러너의 Chrome은 세션에서 확인하지 못했다
  (`--no-sandbox`로 띄우고, 띄우지 못하면 W7만 확인한 뒤 건너뛴다 — CI는 `pytest -q -rs`로 사유를 찍는다).

### 6. 결과 (2026-10-31)

- **구현**: `gateway/metrics.py`(outcome·row·링·snapshot, 217줄), `gateway/main.py`(stats·dashboard·CSP·문서 경로 끄기·`redirect_slashes=False`), `gateway/dashboard.html`(400줄 — 상한에 닿았다),
  `scripts/traffic.py`(375줄), `tests/test_d124_dashboard.py`(88건). 빌드는 울트라코드 워크플로(병렬 빌드 → 통합)로 했다.
- **검사**: 전체 `pytest -q` **767 passed**(약 38초, 이 단계 전 678), `ruff check .`·`mypy`(26파일) 통과. 코드 지문 `c80e49196a66`.
- **W7·W8**: `traffic.py --rounds 1 --shot docs/dashboard.png` 종료 0 — 16/16 일치, ① 실제 서버 화면에서 스크립트가 돎(nojs 없음·키 카드 보임)·stats requests +0,
  ② 1280×1600 라이트 416KB, ③ 사본 16/16 줄의 배지·문장·복원 칸 + 사본이 부른 fetch 4회 모두 Bearer 머리·no-store·omit·주소에 '?' 없음. PNG를 열어 확인했다.
  W7 테스트도 Chrome이 있으면 `--shot`을 붙여 돈다. 사본에서 fetch에 `?k=` 키를 붙이면 ③이 잡아 종료 1이다.
- **W4**: 최악의 줄(12종 masked·unmasked, 잘린 값, 가장 긴 사유 `upstream_stream_error`) 2,380B ≤ 2.5KB, 200줄 477,210B ≤ 0.5MB.
- **W9 컨테이너**(compose, `HOST_PORT=18080` — 8080은 다른 컨테이너): 리뷰 수정 뒤 다시 빌드해 확인. dashboard 200 `text/html`, 이미지의 HTML이 저장소와 바이트가 같고 CSP 해시가 같다,
  nosniff·no-referrer·no-store. 머리 주석의 curl → recent 맨 앞 masked/pii_mask phone 1, 복원 1/1, 스텁은 진짜 번호를 받지 않음. `/__gateway/stats/`·`/v1/chat/completions/`(끝 '/')·
  `/docs`·`/openapi.json`·틀린 키 404. info 코드 지문 = 저장소. 컨테이너의 화면을 headless Chrome으로 열어 스크립트가 CSP 아래에서 돎.
- **W9 부하**(`load.py --duration 30`, 리뷰 1차 수정 뒤 — 2차 수정은 직렬화 대체·끊김 사유 한 줄로 핫 패스가 아니다): 6,751건(비스트리밍 4,680·스트림 2,071), 판정 10/10(오류·복원 실패·교차 누출 0,
  감사 줄 = 요청, 모두 가림, 끝난 뒤 세션·연결 0, RSS −0.4%). 감사 gateway_ms 비스트리밍 p50 3.3 · **p95 14.4** · p99 91.3ms(기준 ≤ 27.75), 스트림(요청 쪽) p95 11.4ms.
  게이트웨이 경유 비스트리밍 p95 347.0ms vs 스텁 직접 337.1ms. 기동 때 대시보드 주소를 찍는다.
- **통합 중 찾아 고친 것(결정에 없던 동작 변경 2)**: Responses 스트림의 복원 수가 대체값 하나에 5로 세어졌다(조각·done·part·item·completed — 화면 '5/1') → 조각에서만 센다.
  인증 실패(401) 줄의 policy가 `default`였다 → null(무인증 게이트웨이는 그대로). 화면의 R2(목적어 없음) 차단 문장이 'undefined'를 보일 수 있었다 → 고침. 셋 다 회귀 테스트·옛 코드에서 실패 확인.
- **리뷰 + 반박 검증**(워크플로, 에이전트 100): 리뷰어 7(보안·백엔드·도구·테스트·문서·설명서·화면) → 발견 46 → **44 남음**(2 반박: 클라이언트가 정한 model이 stats에 실린다 — 명세가 정한 앞 64자이고 원문은 메시지 본문이다,
  설명서 8장에 여러 서버면 다른 서버의 줄이 없다는 말이 빠졌다 — 같은 쪽 '알아 둘 점'에 있다). 수정은 파일이 겹치지 않는 다섯 갈래로 병렬(에이전트 5), 이어서 갈래마다 회의적 검증자(에이전트 5)가 원래 실패를 다시 일으켜 봤다 — 41 fixed·3 partial·새 low 9건.
  partial 3(1024px 가로 넘침, CI에서 화면 확인 건너뜀이 안 보임, `?token=` 같은 키 누출을 정적 검사가 놓침)과 새 9건을 고친 뒤 전체를 다시 돌렸다. 고친 것 가운데 동작이 바뀐 것:
  - 보안·정확성: `model`의 짝 없는 서로게이트로 감사 줄이 사라지고 stats가 다음 200건 동안 500(`Adapter.model`이 '?'), 본문을 다시 쓰는 요청(가림·Chat 스트림)·차단 응답의 500(JSON 이스케이프로 보냄),
    끝 '/' 307(Host 반사)이 '그대로 전달'로 세어짐(`redirect_slashes=False`), CRLF 체크아웃에서 CSP가 스크립트를 막음(해시 전 LF 정규화 + `.gitattributes`).
  - 분류: 스트림 안의 공급자 오류 이벤트가 '가림 후 전달'로 보임(→ `upstream_stream_error`, 그 뒤 끊겨도), 델타 없는 Responses 스트림의 복원 0(→ 끝 이벤트 수와 큰 쪽),
    같은 주소 두 풀의 연결 합을 풀 하나의 상한과 비교(→ 가장 바쁜 풀), `CancelledError`를 '클라이언트가 끊음'으로만 적음(→ '처리 중 취소됨' — 종료 유예 초과 500도 이 코드).
  - 화면: Chrome이 관리 키를 비밀번호로 저장하자고 물음(→ `autocomplete="one-time-code"`, 저장 판정 0 확인), 2초마다 표를 통째로 다시 그려 초점·선택·펼친 상세를 잃음(→ 줄 재사용),
    선택이 있으면 ▸가 안 열림, 같은 값도 다시 써서 고른 글자가 풀림, 사유 16개에서 자름, 빈 상태가 40px 칸에 접힘, 날짜 없음, 첫 1분 분당 평균 과소·공백 뒤 '지금 초당' 왜곡,
    본문 업로드 중 끊김을 '응답 도중'으로 적음, 이력 가림 줄에서 '기록만' 꼬리 빠짐, 긴 이름의 가로 넘침, 밝은 모드 대비 4.5:1 미만(다시 시작 띠 포함), 라이브 영역을 hidden에서 꺼냄.
  - 도구: SIGTERM에 고아 서버, 포트·회차 검사 없음, 회차를 못 채워도 0, ③이 줄 전체 글자로 찾음(→ 칸별 + fetch 기록), ①이 정적 id만 봄, 복원 수를 하한으로만 봄,
    장면 9가 키에 따라 0.025% 확률로 실패, `UVICORN_*`가 섞임(`serve()`가 `--host 127.0.0.1`), Chrome 실패(2)가 어긋난 회차(1)를 덮음, Chrome 실행 실패·멈춤의 구분.
  - 테스트: 분류 우선순위·경계 사례(7개 더함), 명세 값(ROW_KEYS·REJECTED·RECENT 200)을 글자로, stats 본문 계약, row 값 전체 대조, 405 not_found, 키 취급 정적 검사,
    라벨 사전(화면·operations 표), 설명서 금지어, 코드 지문이 화면을 포함함. 테스트 갈래의 변이 36개가 모두 잡혔다.
  - 문서: CHANGELOG에 바뀐 동작들, operations의 끊김 분류·결과 표·keygen 안내·한계, `.env.example` keygen, api-compat의 끝 '/' 404·스트림 오류.
- **설명서**: 화면 C를 실제 스크린샷(전체 폭)으로, 7장·1~2쪽·11장을 16-1 반영, 10장 '자동 테스트 767개·검토 지적 110건 처리(고치거나 한계로 적음)'.
  PDF를 다시 만들었다 — **21쪽**(전에 20쪽 — 화면 C가 전체 폭이 됐다), 13~14쪽(화면 C)·18~19쪽(10·11장)을 열어 넘침이 없음을 확인, PDF 글자에서 금지어 5개 0건.
- **계획과 다른 점**: 위 리뷰 수정의 동작 변경(§2에 '리뷰 뒤'로 적었다), W8이 W7 테스트 안에서도 돈다(CI는 `--no-sandbox`, 띄우지 못하면 W7만 확인하고 건너뜀 — `pytest -q -rs`),
  설명서 21쪽, 관리 키 길이 하한은 두지 않았다(클라이언트 키와 같은 처지 — keygen 안내와 §5 한계로).
- **못 한 것·남은 것**: GitHub ubuntu 러너에서 Chrome이 뜨는지는 확인하지 못했다(다음 CI 결과로 본다 — 뜨지 못하면 W7 '건너뜀' 사유가 찍힌다). 키 저장 판정은 Chrome에서만 쟀다.
  화면의 작은 잔여: 스크롤 맨 위(0)에서 펼친 상세는 새 줄만큼 밀린다(Chrome 앵커링이 0에서 듣지 않는다), 머리 띠의 pid·시작 시각 선택은 '마지막 갱신'과 함께 풀린다,
  자정을 넘기고 새 줄이 없으면 어제 줄 날짜가 다음 갱신 때 붙는다, 표를 멈춘 채 잠갔다 다시 열면 '표 계속'까지 표가 비어 있다(전부터). `load.py`는 SIGTERM에 트레이스백과 130으로 끝난다.
  §5의 한계(프로세스마다 따로, 200줄, 델타 없는 Responses 텍스트의 새 PII 등)는 그대로다.

## D-125. 탐지 사이드카(`detect/`) + 한국어 PII NER 채택 게이트 (2026-11-01, PLAN 17단계)

### 1. 근거

- 정규식 탐지는 모양이 정해진 식별자 12종뿐이다. 이름·주소·직장은 문맥으로만 알 수 있어 지금은 그대로 상류로 간다(README '막지 못하는 것').
  결정 표 7번이 NER 채택 게이트를 정해 두었다: x86 CPU에서 512토큰 이하 p95 +40ms 이하, F1 0.85 이상, 미달이면 v1.0에서 뺀다.
- 후보 조사(2026-11-01, 에이전트 8 — HF 메타데이터·카드·config·라이선스만 읽고 가중치는 받지 않음, 후보 45개): 모델과 학습 데이터 모두 상업 자체 호스팅에 쓸 수 있고,
  한국어를 학습했고, 이름·주소 라벨이 있고, safetensors나 ONNX인 것은 여덟이다(§6 표). 나머지는 라이선스 불명·비상업(CC-BY-NC-ND, ai4privacy 200k·400k)·
  공유 조건(CC-BY-SA)·한국어 미학습(어휘에 한글이 없거나 미세 조정 언어에 없음)·이름이나 주소 라벨 없음·pickle 가중치만·카드 없음으로 뺐다.
- 크기가 판정을 가른다. 512토큰 한 창의 계산은 임베딩 밖 매개변수에 비례한다 — KoELECTRA-base급(85M, 약 97 GFLOP)은 CPU 4코어에서 수백 ms이고,
  KoELECTRA-small급(9.5M, 약 13 GFLOP)이어야 40ms 근처에 온다.
- 탐색 측정(이 결정을 적기 전, Apple M2, 스레드 4): veil(KoELECTRA-base) 합성 셋 F1 0.963·510토큰 HTTP p95 180ms, atonlee(KoELECTRA-small) F1 0.895·p95 40.2ms(argmax 디코딩 뒤 약 36ms).
  **게이트의 공식 측정은 §2-6의 x86 러너 측정과 §2-4의 KDPII 측정이고, 둘 다 이 결정을 적은 뒤에 처음 돈다.**

### 2. 결정

1. **사이드카** `detect/` — 게이트웨이와 따로 도는 컨테이너(FastAPI + onnxruntime + tokenizers, torch·transformers 없이). 게이트웨이 이미지는 이것들을 갖지 않는다.
   `POST /v1/detect {texts: [{id, role, text}], tasks: ["pii_ner"]}` → `{results: [{id, pii_ner: [{start, end, label, kind, score}]}], ms}`,
   `GET /health` → 모델 저장소·리비전·라이선스·ONNX SHA-256. 원문을 저장·기록하지 않는다(접근 로그 끔, 오류 본문에 요청 내용 없음). 본문 2MiB·텍스트 1,024개 상한(413·400).
   글자 합 131,072·토큰 합 16,384를 넘으면 추론 전에 413 `too_many_tokens`. 추론은 한 번에 하나(ONNX가 이미 코어를 다 쓴다 — 나머지는 줄을 선다), 종료 유예 25초.
   위치는 원문 코드 포인트. 짝 없는 서로게이트는 텍스트에서 U+FFFD로 바꿔 보고(한 글자 대 한 글자) id에 있으면 400. 토크나이저 앞에 NFC와 결합 부호 빼기를 넣는다 —
   풀어 쓴 한글(NFD)과 이름 뒤 결합 부호가 낱말째 [UNK]가 되던 것을 막고, 구간 끝은 뒤따르는 자모·부호까지 늘린다. WordPiece가 100자 넘는 띄어쓰기 없는 덩어리를 [UNK]로
   만들지 않게 위치를 지킨 채 100자씩 자른다(상한을 풀면 덩어리 길이의 제곱 시간 — 2만 자에 273초). 18단계가 같은 사이드카에 `tasks: ["injection"]`을 더한다.
2. **모델 고정** `detect/models.json` — HF 저장소·커밋 SHA 리비전·파일별 SHA-256·라벨 → 제품 종류(person·address·org)·디코딩·창. `fetch.py`가 받아 해시를 맞추고,
   `NER`은 열 때 다시 재서 다르면 기동하지 않는다. 이미지는 빌드 때 받는다(실행 중 네트워크 불필요). 후보마다 제작자가 배포한 ONNX를 쓴다(제작자 INT8이 있으면 그것).
   - 디코딩(`decode.py`)은 모델을 만든 쪽이 적은 방식을 따른다: BIOES인 veil은 제약 비터비(veil.py), 카드가 argmax를 보여 주는 BIO 모델은 argmax.
     창은 모델이 학습한 길이(기본 512, newmean 256·64)를 겹쳐 밀고 겹친 구간 가운데에서 나눈다. 뒷손질은 모든 모델에 같다 — 공백·조사 떼기(veil.py 규칙, Apache-2.0)와
     공백 하나 이내 주소 조각 잇기(시·도를 LOCATION, 도로를 STREET_ADDRESS로 나눠 다는 모델도 주소 하나로).
3. **합성 셋** `eval/ner/synth.jsonl` — 200문장(`make_synth.py`, 시드 고정·표준 라이브러리만, 바이트 고정): 템플릿 35 × 5 + 음성 25, 정답 person 230·address 90·org 90.
   구간 규약은 제품이 가려야 하는 범위다 — 이름은 호칭·조사 제외, 주소는 시·도(또는 시·군·구)부터 상세(층·동·호)까지 한 구간, 시·도·역 이름이 홀로 나오면 주소가 아님,
   부서·팀은 직장이 아님. 조사는 앞 글자를 읽은 소리를 따른다(숫자는 한자어로). 모델 라벨은 제품 대응(`kinds`)으로 옮겨 채점한다.
4. **공개셋** `eval/ner/kdpii_test.jsonl` — KDPII test(실제 사람이 쓴 한국어 대화, Fei·Kang et al., IEEE Access 2024, CC BY 4.0)를 `1T/veil-pii-ko-stress`(CC BY 4.0)가
   train과의 완전 중복을 빼고 문자 위치로 옮긴 `leakage/kdpii_test_dedup.jsonl`(리비전 `1a3106d8`, 4,799행)에서 PERSON·ADDRESS·ORGANIZATION 구간만 person·address·org로 남긴 것
   (`build_kdpii.py`, SHA-256 고정, 출처·바꾼 것은 `eval/ner/SOURCES.md`). 이 셋의 규약은 우리와 다르다 — 도시·역·가게 같은 장소 이름도 주소(KDPII LC_PLACE), 별명·성만 쓴
   호칭도 이름, 학과·동아리·군부대도 직장이다. 나라 이름은 대개 달지 않는다(LCP_COUNTRY는 대응 없음 — 그래도 홀로 선 나라 이름 49개 중 20개는 주소로 달려 있다), 사람과
   이어지지 않은 기관 이름도 달지 않기도 한다. 주소는 구성 요소마다 따로 단다(성남시·분당구·야탑로 846-2가 세 구간). 그래서 이 셋은 주소 잇기를 끄고, 모델 라벨을 그 규약으로 옮기는
   대응(`kinds_kdpii` — 장소 라벨은 주소, 부서 라벨은 직장)으로 채점한다. 원본은 Zenodo 10968609(연세대 김한샘 연구실·TSCIENTIFIC)다.
   veil과 FrameByFrame은 KDPII train으로 학습했다(같은 분포의 이점) — 표에 적는다.
5. **F1 게이트**: `eval/ner/score.py`의 exact(시작·끝·종류 일치, CoNLL) micro F1(person + address + org)이 **합성 셋과 KDPII 각각 0.85 이상**. 합성 셋은 제품 규약,
   KDPII는 실제 대화다 — 하나만 넘는 모델은 깨끗한 템플릿에서만 되거나 우리 규약과 어긋난다. overlap F1·글자 재현율(종류 무관 덮은 글자 = 상류로 새지 않은 비율)은 참고로 낸다.
6. **지연 게이트(사전 등록)**: `detect/bench.py` — 사이드카를 띄워 HTTP로 한 건씩(동시성 1, keep-alive) 보낸 왕복 = 게이트웨이가 더할 지연. 버킷 32·64·128·256·510토큰
   (510 = 특수 토큰 둘을 더해 창 하나 512), 버킷마다 예열 10 + 측정 100, 입력은 한국어 업무 문장 열에서 정확히 N토큰으로 자른 20개를 돌려 쓴다.
   측정 기계는 GitHub-hosted `ubuntu-24.04` 러너(4 vCPU, x86) — CI `detect` 워크플로가 `detect/`·`eval/ner/`(와 그것이 읽는 파일)를 바꾸는 푸시마다(손으로도) 재고
   작업 요약·`::notice` 주석에 CPU 이름과 함께 남긴다.
   ONNX 스레드 4와 2를 재고 나은 쪽을 그 모델의 배포 설정으로 본다. **게이트: 모든 버킷의 p95 ≤ 40ms** — '512토큰 이하'를 길이 범위로 읽는다(§3).
7. **판정**: 같은 모델·같은 설정이 F1 두 셋과 x86 지연을 모두 넘어야 채택한다. 넘으면 §2-8을 구현하는 단계를 새로 연다(PLAN에 단계로 올린다). 못 넘으면 수치를 §6에 적고
   NER을 v1.0에서 뺀다 — 게이트웨이는 사이드카를 부르지 않고(`GATEWAY_DETECT_URL` 없음), 사이드카는 18단계의 바탕이자 다음 후보를 같은 자로 재는 도구로 남는다.
8. (채택 시의 게이트웨이 연결 — 이 결정에서는 구현하지 않는다) `GATEWAY_DETECT_URL`·타임아웃 50ms, 기본 detect(감사만) → 정책에서 mask. 이름 대체값은 성·이름 사전,
   주소는 시·도 유지. 응답 복원은 발급한 대체값 문자열 찾기(정규식으로는 되찾을 수 없다), 스트림 보류도 같은 문자열의 앞부분. 사이드카 장애 시 detect는 통과, mask는 설정
   (fail-open·fail-closed). 결정적 대체값(D-111)이 그대로 성립하려면 같은 텍스트에 같은 구간이 나와야 한다 — 같은 모델·같은 입력이면 같다.

### 3. 버린 대안

- **'512토큰 이하'를 실제 길이 분포의 p95로 읽기**: 짧은 질문이 대부분인 셋이면 base 모델도 넘는다(128토큰까지는 M2에서 40ms 안팎). 그러나 게이트웨이가 NER에 줄 입력은
  요청의 모든 역할(시스템·도구 결과·이전 답) 텍스트다(D-112) — 다중 턴과 RAG 문서는 512토큰을 쉽게 넘는다. 길이 범위로 읽어야 타임아웃 50ms 설계와 맞는다.
- **합성 셋 하나로 판정**: 우리 템플릿은 쉽고(제작자들도 템플릿 + 규칙 생성 값으로 학습했다), 실제 대화의 별명·성 호칭·장소를 재지 못한다.
- **KDPII를 우리 규약으로 다시 라벨링**: 원 데이터의 LC_PLACE와 LC_ADDRESS가 veil의 대응에서 합쳐져 있어 나눌 수 없고, 사람이 다시 다는 것은 이 단계 밖이다.
- **1.4B MoE privacy-filter 계열**(openai/privacy-filter·BCCard·FrameByFrame 1.4B): 토큰당 활성 계산은 Horizon(임베딩 밖 42M)과 비슷하지만 가중치 1.6GB를 추론마다 훑는다.
  openai 원본은 ORG 라벨이 없고 카드가 한국어를 적게 학습했다고 적는다. FrameByFrame 1.4B는 카드의 KDPII 이름 F1 0.683.
- **변환 최적화로 base 모델 살리기**: veil fp32를 내보내 동적 INT8(MatMulInteger)·BERT 그래프 융합까지 재 봤다(§6) — 510토큰에서 1.15배라 게이트를 바꾸지 못한다.
- **자체 학습·증류**: PLAN 범위 밖(기존 모델을 재서 고른다). §6 조건부 트리거로 남긴다.
- **마지막 사용자 메시지만 NER**: 이력·도구 결과의 이름이 그대로 나가고, 같은 이름이 턴마다 다르게 가려져 이력 바이트가 바뀐다(D-111).

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| N1 | 합성 셋이 생성기와 바이트까지 같고, 스키마·구간 규약·조사 규칙을 지킨다 | `tests/test_d125_ner.py` |
| N2 | 점수 정의(exact·overlap·글자 재현율, 예측 빠진 id) | `tests/test_d125_ner.py` |
| N3 | KDPII 셋의 SHA-256·행 수·종류별 수가 결정과 같다 | `tests/test_d125_ner.py` |
| N4 | 디코더: 비터비가 규칙 안 최적(전수 대조)·창이 [0, n)을 한 번씩·조사·주소 잇기 | `detect/tests` (CI detect) |
| N5 | 사이드카 계약: 결과 순서·위치, 400·413 무반향, 512토큰 넘는 입력의 창 경계 이름, 해시 불일치 기동 거부, /health 해시 | `detect/tests` (CI detect) |
| N6 | 고정값(리비전·SHA-256·의존성·이미지·CI 단계) | `tests/test_d125_ner.py` |
| N7 | 게이트 수치(F1 두 셋, 지연 버킷 M2·x86)가 §6에 있다 | 이 결정 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy`(detect 포함) | |

PLAN 완료 기준의 '사이드카 꺼짐·켜짐 두 구성에서 전체 테스트, 장애 시 동작'은 채택했을 때(§2-8)의 것이다 — 미달이면 게이트웨이가 사이드카를 부르지 않으므로 '꺼짐' 한 구성뿐이다.

### 5. 한계

- 합성 셋은 우리 시각의 템플릿이다. KDPII는 대화체(평균 26자)라 512토큰 창이 한 번도 안 넘친다 — 긴 문서는 `detect/tests`의 창 경계 시험과 지연 버킷만 본다.
- 지연은 러너의 CPU(AMD EPYC·Intel Xeon, VNNI 유무)에 따라 다르다 — bench가 CPU 이름을 함께 적는다. 동시성 1이다(동시 요청은 같은 코어를 나눠 쓴다).
- 후보는 2026-11-01 HF에 있던 것이다. 몇은 만든 지 며칠 된 1인·소규모 저장소다(§6 표의 날짜·내려받기 수).
- KDPII와 합성 셋의 규약 차이(§2-4)는 대응(`kinds_kdpii`)과 주소 잇기 끄기로 다 메워지지 않는다 — 우리 규약으로 학습한 모델은 KDPII에서 불리하고, KDPII로 학습한 veil은 유리하다.
  그래서 두 셋 각각 0.85를 요구한다. 대응을 바꿔 쟀어도 atonlee의 판정은 같다(§6).
- 사이드카는 인증이 없고(같은 파드·내부망만), 한 요청이 시작되면 끊어도 끝까지 돈다(상한 안에서 — M2 veil 최악 약 6초). 토크나이저 앞 정규화(NFC·결합 부호 빼기)는
  다른 문자 체계의 결합 모음도 뺀다(한국어·영어 모델이라 손해가 없다고 보았다).

### 6. 결과 (2026-11-01)

- **판정: 미달 — 이름·주소·직장 NER은 v1.0에 넣지 않는다.** F1 두 셋을 넘는 모델(veil)은 510토큰 지연이 게이트의 5배이고, M2에서 지연이 게이트 언저리인 모델(atonlee —
  510토큰 p95 36.7·39.4·40.3ms, 세 번 잼)은 실제 대화(KDPII) F1이 0.490이다. 게이트웨이 동작은 바뀌지 않았다(사이드카를 부르지 않는다). x86 러너 숫자는 이 커밋을 푸시한 뒤 `detect` 워크플로가 처음 잰다 — 4 vCPU 러너는 M2보다 느려
  veil의 판정은 바뀔 수 없고 atonlee는 F1에서 이미 떨어졌으므로 판정을 기다리지 않는다. 다음 세션이 그 숫자를 아래 표의 'x86' 칸에 옮긴다.
- **조사한 후보**(측정 대상 여덟 — 나머지 37은 라이선스·한국어·라벨·가중치 형식에서 빠졌다):

  | 모델 | 크기(임베딩 밖) | 라이선스·학습 데이터 | 이번에 |
  |---|---|---|---|
  | 1T/veil-pii-ko-lite @a8343030 | KoELECTRA-base 110M(85M, 12×768) | Apache-2.0 · BCCard openpii(CC BY)·KDPII train(CC BY)·자체 합성 | 측정 |
  | atonlee/koelectra-ko-pii-ner @1e75c01e | KoELECTRA-small 14M(9.5M, 12×256) | Apache-2.0 · BCCard openpii·townboy 합성(CC BY) | 측정 |
  | newmean-ai/pii-large @e3ae973f · pii-small @0aab1a96 | mMiniLM 증류 24M(10.7M, 6×384) · 9.6M(7.1M, 4×384) | Apache-2.0 · Claude로 만든 합성 54개 언어 | 측정(q4 ONNX, 창 256) |
  | Horizon-Labs/pii-redactor-small @a20835db | mmBERT-small 141M(42M, 22×384) | Apache-2.0 · ai4privacy openpii·Nemotron-PII(CC BY) | 측정 |
  | FrameByFrame/korean-pii-e5-base | XLM-R base 278M(85M, 12×768) | MIT · KDPII·KLUE(CC BY-SA)·비공개 생성 문서 | 재지 않음 — veil과 같은 계산 급, 직장 라벨 없음 |
  | openai/privacy-filter · BCCard/MoAI-Privacy-Filter-INT8 | 1.4B MoE(8층, 전문가 128개 중 4) | Apache-2.0 | 재지 않음 — 가중치 1.6GB를 추론마다, openai 원본은 직장 라벨 없음 |

- **측정**(F1은 exact micro, 지연은 HTTP p95 ms — 버킷 32·64·128·256·510토큰, Apple M2·스레드 4 / 스레드 2는 510만. veil·atonlee는 리뷰 수정 뒤의 최종 코드로 다시 쟀다 —
  토큰 상한 세기·NFC 정규화가 더해져 atonlee 510토큰이 36.7 → 40.3ms. 나머지 셋의 지연은 수정 전 코드):

  | 모델 | 합성 F1 (이름·주소·직장) | KDPII F1 (이름·주소·직장) | M2 p95 32·64·128·256·510 | 스레드 2의 510 | x86 |
  |---|---|---|---|---|---|
  | veil-ko-lite-int8(비터비) | **0.963** (0.996·0.963·0.879) | **0.895** (0.899·0.878·0.900) | 12.0·21.3·38.4·82.3·**213.9** | 337.9 | 15.3·29.8·42.2·85.6·**201.5** (스레드 2: 206.4) |
  | atonlee-small-int8(argmax) | **0.895** (0.935·1.000·0.674) | 0.490 (0.556·0.504·0.425) | 2.5·6.7·7.9·15.7·**40.3** | 55.2 | 3.0·4.3·7.2·15.0·**34.8** (스레드 2: 47.1) |
  | newmean-pii-large-q4 | 0.865 (0.941·0.907·0.595) | 0.260 | 4.8·8.1·14.4·54.6·79.9 | — | — |
  | newmean-pii-small-q4 | 0.779 | 0.208 | 4.9·10.4·14.4·45.8·58.9 | — | — |
  | horizon-small-int8 | 0.647 (직장 0) | 0.259 | 15.0·27.9·46.9·89.6·236.7 | — | — |

  - veil의 KDPII 종류별 재현율(0.912·0.899·0.887)은 제작자 카드의 표와 같고, F1(0.899·0.878·0.900)은 제작자 평가 JSON(중복을 빼기 전 4,891행 — 0.897·0.878·0.900)과
    한 구간 이내다(이름 예측 282 대 281·직장 453 대 455, 주소 같음) — 우리 디코더(비터비·조사 떼기)가 제작자 것을 재현한다.
  - atonlee의 KDPII exact 정밀도 0.445·재현율 0.545(겹침 0.567·0.693) — 이름을 488개 내놓았다(정답 274). 일상 대화의 낱말·호칭을 이름으로 잡는다.
    합성 데이터로만 학습한 작은 모델의 한계로 보인다(실제 대화를 학습한 veil은 같은 셋에서 0.895). 다른 채점으로도 0.85에 못 미친다 — 제품 대응(장소·부서 라벨 버림) 0.407,
    장소만 뺀 대응 0.436, 비터비 디코딩 0.530.
  - 겹침 F1·글자 재현율(종류 무관 덮은 글자): veil 합성 0.967·0.970, KDPII 0.926·0.958 / atonlee 합성 0.963·0.934, KDPII 0.624·0.776 — atonlee의 KDPII 글자 재현율은
    KDPII 대응(장소 → 주소, 부서 → 직장) 기준이고, 제품이 실제로 가릴 대응으로는 0.561이다(veil은 두 대응이 같다).
- **변환·디코딩 실험**(M2, 추론만, 스레드 4, 512위치): veil fp32 내보내기 p50 320ms · 제작자 INT8(MatMulNBits, 가중치만) 173ms · 동적 INT8(MatMulInteger) 151ms ·
  BERT 융합 fp32 328ms — 어떤 변형도 4배 차이를 메우지 못한다. atonlee의 제작자 INT8은 이미 동적 INT8이고, 융합 뒤 다시 양자화해도 31ms로 같다.
  atonlee 510토큰 요청 한 번의 비용: 토큰화 0.5 · ONNX 31.0 · 비터비 4.3(argmax 0.02) · 뒷손질 0.4 · HTTP·JSON 약 2ms. 카드가 argmax를 보여 주므로 argmax로 쟀다
  (비터비면 합성 F1 0.899). ONNX 스레드는 4가 2보다 빠르다(M2 8코어).
- **테스트**: `tests/test_d125_ner.py` 6(N1 셋·N2·N3·N6 — 두 셋의 SHA-256, 잰 두 모델의 리비전·ONNX 해시, 의존성 버전을 고정), `detect/tests` 12(D1 둘·D2·D2b·D3·M1~M7).
  전체 `pytest` 773(이 단계 전 767)·`ruff`·`mypy`(gateway·detect).
- **리뷰 + 반박 검증**(울트라코드 워크플로, 에이전트 32 — 검토 4: 디코더·서비스·측정 타당성·CI와 문서, 지적마다 검증 1~2): 지적 28건 → 22건 확인(검증이 심각도를 낮춘 것 포함),
  6건은 검증 시점에 이미 고쳐져 있어 반박. 모두 반영했다 — 같은 위치를 나눠 가진 SentencePiece 조각의 겹친 구간(newmean·Horizon F1 0.854 → 0.865 등, 판정 불변),
  풀어 쓴 한글(NFD)·결합 부호에서 모든 후보가 NER을 놓침(NFC·부호 빼기, 구간 끝 늘리기), WordPiece 100자 덩어리 [UNK](상한을 풀면 제곱 시간이라 위치를 지켜 자름),
  요청 비용 상한(글자·토큰·동시성 1·종료 유예), 짝 없는 서로게이트 500, 깊은 JSON·끊김 500, 상한 넘은 본문을 끝까지 읽기, 해시와 로드 사이의 틈(바이트를 한 번 읽어 재고 연다),
  '호칭을 뗀 뒤 공백', stride ≥ 창 크기 검증, 고정값 테스트 강화, KDPII 규약 서술·veil 재현 서술·글자 재현율의 대응·CI 경로 필터·문서의 수와 명령.
- **x86**(2026-11-02, CI `detect` 워크플로 run의 주석 — AMD EPYC 9V45, 4 vCPU, `af88c24`): 표의 'x86' 칸. 지연은 M2와 비슷하다(veil 510토큰 201.5ms, 스레드 4가 2보다 빠르다).
  x86의 F1은 INT8 커널이 달라 소수 셋째 자리가 다르다 — veil 합성 0.960·KDPII 0.896, atonlee 0.897·0.489. **판정 그대로**: atonlee는 x86에서 지연 게이트를 넘지만(34.8ms) KDPII F1이 0.489다.
  이로써 완료 기준 N7을 채웠다.
- **x86 두 번째 러너**(2026-11-10, CI `detect` run의 주석 — 커밋 `c87db8d`, Intel Xeon Platinum 8370C 2.80GHz·4 vCPU, 2026-11-10 세션이 옮김): veil 510토큰 HTTP p95 **361.0ms**(스레드 2 — 스레드 4는 368.2),
  32·64·128·256토큰 p95 26.5·45.5·82.8·174.8ms(스레드 2), atonlee 510토큰 73.4ms(스레드 4). F1은 같다(veil 0.960·0.896, atonlee 0.897·0.489). **같은 4 vCPU라도 러너 CPU에 따라 1.8배 다르다**(AMD EPYC 9V45 201.5ms) —
  문서의 '약 200ms'를 '약 200~370ms(CPU에 따라)'로 고쳤다(2026-11-10). 용량 계획은 실제 노드에서 `python -m detect.bench --dir models`로 잰다.
- **x86 세 번째 러너**(2026-11-10, CI `detect` run의 주석 — 커밋 `30700da`, AMD EPYC 9V74 80-Core·4 vCPU, 같은 날 세션이 옮김): veil 510토큰 HTTP p95 **320.4ms**(스레드 2 — 스레드 4는 321.2),
  32·64·128·256토큰 p95 20.8·37.9·72.6·151.3ms(스레드 2), atonlee 510토큰 51.5ms(스레드 2). F1은 같다. 같은 AMD EPYC라도 9V45(201.5ms)와 1.6배 다르다 — 문서의 '약 200~370ms' 안이라 문서는 그대로다.
- **이후(2026-11-02 사용자 결정)**: 지연을 받아들이고 이름·주소 가림을 기본 꺼짐·정책에서 켜는 기능으로 넣기로 했다 — 결정 표 7번을 바꾸고 PLAN 17-1단계(D-126)로 한다.
  이 결정의 판정(미달)은 '+40ms 기본 켜짐' 게이트에 대한 것이고 그대로 둔다.
- **못 한 것·남은 것**: 없음(x86 숫자는 위에 옮겼다). FrameByFrame e5-base·1.4B MoE 둘은 재지 않았다(위 표의 근거). 게이트웨이 연결(§2-8)은 채택 때의 것이라 만들지 않았다.
  PLAN 조건부 표에 트리거를 더했다 — KoELECTRA-small급 크기로 KDPII F1 0.85를 넘는 공개 모델이 나오거나, 고객이 GPU 사이드카를 둘 수 있거나, 증류(veil → small)를 하기로 하면
  같은 `evaluate`·`bench`로 다시 잰다.

## D-126. 이름·주소 가림 — 사이드카 NER을 정책에서 켜는 PII 종류로 (2026-11-02, PLAN 17-1단계)

### 1. 근거

- D-125의 판정은 '기본 켜짐·+40ms' 게이트에 대한 미달이었다. 2026-11-02 사용자 결정("이름 주소 가림으로 진행하자"): 지연을 받아들이고 **기본 꺼짐·정책에서 켜는 기능**으로 넣는다.
  결정 표 7번을 그렇게 바꿨다 — F1은 두 셋 각각 0.85 이상(게이트), 지연은 게이트가 아니라 측정해 문서에 적는 비용이다.
- 모델은 F1 두 셋을 넘은 유일한 후보 `veil-ko-lite-int8`(합성 0.963·KDPII 0.895, x86 4 vCPU 510토큰 HTTP p95 201.5ms — D-125 §6). 사이드카(`detect/`)·평가셋·측정 도구는 D-125 그대로 쓴다.
- 왜 종류(kind)로 넣는가: 운영자 손잡이가 이미 있다 — `pii_kinds`·`pii_detect_kinds`는 정책마다 다르고, 감사·지표·대시보드가 종류 이름으로 센다. 이름·주소·직장을 종류 셋으로
  더하면 켜기·끄기·감사만·정책별 차등이 새 설정 없이 그대로 된다. 가짜 값·복원·스트림 보류·결정적 대체값(D-111)도 같은 볼트를 지난다.
- 정규식 종류와 다른 점 둘이 설계를 가른다: (1) 응답의 대체값을 정규식으로 되찾을 수 없다 — 발급한 문자열을 찾는다. (2) 탐지가 외부 프로세스라 실패·지연이 있다 — 실패 동작과
  캐시가 필요하다. 매 턴 다시 오는 이력은 같은 텍스트라 캐시에서 나오고(결정적 대체값과 맞물려 이력 바이트가 같다), 새 메시지만 사이드카로 간다.

### 2. 결정

1. **종류**: `person`(이름)·`address`(주소)·`org`(직장). 설정이 받는 이름 `ALL_KINDS`는 정규식 12 + 이 셋 = 15. **기본 `GATEWAY_PII_KINDS`는 정규식 12종 그대로(= NER 꺼짐)**.
   정책 `pii_kinds`(또는 환경변수)에 `person,address`를 더하면 켜진다. 감사만 기본값 `DETECT_ONLY`에 `org`를 더한다 — 회사 이름을 가짜로 바꾸면 '삼성전자 주가' 같은 질문의 답이
   망가진다. `pii_detect_kinds`에서 빼면 가린다.
2. **환경변수 셋**(게이트웨이 전체 — 사이드카는 하나다): `GATEWAY_DETECT_URL`(사이드카 주소, 비면 NER 없음), `GATEWAY_DETECT_TIMEOUT`(초, 기본 10 — 한 요청의 NER 전체 기한),
   `GATEWAY_DETECT_FAIL`(`closed`|`open`, 기본 `closed`). **기동 거부**: `pii_mode`가 `off`가 아닌 어느 정책이든 NER 종류를 켰는데 `GATEWAY_DETECT_URL`이 비면 뜨지 않는다
   (문구 `no_detect_url`). 사이드카의 /health를 기동 때 확인하지는 않는다(§3) — 사이드카가 없으면 요청 때 아래 4의 실패 동작이다.
3. **클라이언트** `gateway/detect_client.py` — `DetectClient(url, timeout)`: httpx AsyncClient(검사기 `prepare`에서 열고 `aclose`에서 닫는다), 캐시는 **텍스트의 SHA-256 → 구간 목록**
   LRU 4,096개(정책 검사기마다 — 원문은 캐시에도 없다). 캐시에 없는 텍스트만 한 요청에 묶되 요청당 글자 합 12,000 이하(사이드카 상한 토큰 16,384·글자 131,072 안 — WordPiece는
   글자당 토큰 1개를 넘지 않는다). 12,000자보다 긴 텍스트는 **12,000자 창을 256자 겹쳐** 자르고, 창마다 가장자리 128자(첫 창의 앞·마지막 창의 뒤는 빼고)에서 시작하는 구간은 버린다 —
   구간 하나가 두 창에서 두 번 나오지 않고, 128자보다 짧은 구간은 어느 한 창에 통째로 든다. 위치는 원래 텍스트로 옮긴다. 응답은 모양·범위를 검사한다(길이·id·start<end·범위·종류) —
   어긋나면 실패다. 실패는 `DetectUnavailable(사유)` 하나다: `timeout`(전체 기한)·`connect`·`http_<상태>`·`bad_response`. 요청은 순서대로 하나씩 보낸다(사이드카가 한 번에 하나만 돌린다).
4. **`PIIDetector.inspect`**: 정규식 탐지 뒤, 켠 NER 종류가 있으면 같은 텍스트(가리는 역할의 것)를 사이드카에 보내 구간을 더한다. **정규식 탐지와 겹치는 NER 구간은 버린다**(형식
   식별자는 정규식이 정확하다). `address`는 숫자가 든 토큰(번지·건물 번호·동·호·층)이 있을 때만 가리고 시·도·구·역·나라 이름뿐이면 감사만(`unmasked`) — '서울 날씨'를 가리면 질문이
   바뀐다. `org`는 감사만 목록에 따른다. NER 구간도 탐지 상한(`GATEWAY_MAX_FINDINGS`)에 센다. 감사 메타 `ner_ms`(사이드카에 쓴 시간, 캐시만이면 0에 가깝다)·`ner_error`(실패 사유).
   **실패 동작**: detect 정책이거나 켠 NER 종류가 모두 감사만이면 늘 통과하고 `ner_error`만 남긴다. mask 정책에서 가리는 NER 종류가 있으면 `GATEWAY_DETECT_FAIL`을 따른다 —
   `closed`: 상류에 보내지 않고 503 `detect_unavailable`(`retry-after: 1`, 그 API의 오류 형식), `open`: 정규식 종류만 가리고 보낸다(`ner_error`). 정규식 종류의 가림은 어느 경우에도
   그대로다.
5. **대체값**(`surrogate.py`): `person` — 한글이면 성(빈도 가중 사전) + 이름 음절, 길이는 원문과 같되 최소 3자, **마지막 음절의 받침 부류(없음·ㄹ·그 밖)를 원문과 맞춘다**(은/는·이/가·
   으로/로가 가짜 이름에도, 복원한 원문에도 맞는다). 라틴 글자면 영문 이름(토큰 수 유지, 마지막 토큰은 성), 그 밖(별명·한자 등)은 한글 3자. `address` — 앞쪽 시·도·시·군·구 토큰
   (…시·도·군·구·…특별자치시·…자치도)은 그대로, 도로(…로·…길)·법정동(…동·읍·면·리)·아파트·건물 이름은 사전에서, 그 밖의 한글 토큰은 같은 길이의 음절로, **숫자는 자릿수를 지키고
   마지막 자리는 원문 그대로**(읽는 소리의 받침이 같아 조사가 맞는다). `org` — 알려진 꼬리(은행·병원·학교·대학교·공사·공단·증권·보험·의원·치과·법인·`(주)`·주식회사·Inc.·Ltd.·Corp.)는
   남기고 줄기를 사전·음절로 바꾼다. 세 종류 모두 결정적이다(D-111 — 같은 키·같은 원문은 같은 대체값).
6. **볼트**(`vault.py`): 이 세 종류의 복원 키는 공백을 뺀 소문자 문자열이다(`norm_key`). 세션마다 발급한 문자열 대체값으로 정규식을 만들어(공백은 `\s+`, 긴 것부터, 이름은 앞이 한글 음절이
   아닐 때만, 대소문자 무시) `_hits`가 정규식 탐지와 함께 쓴다 — 복원·residual·suspect·스트림 복원이 그대로 돈다. 정규식 종류의 대체값과 겹치면 정규식 종류가 우선이다.
   `hold`는 꼬리를 **공백을 뺀 채로도** 접두사 집합과 비교한다(주소 대체값 '서울특별시 강'이 조각 끝에 걸린다). `token_for(..., avoid=텍스트)` — NER 종류의 대체값이 요청 텍스트
   어딘가에 이미 있는 글자열이면(놓친 실제 이름) 다음 시도로 만든다(정규식 종류는 하지 않는다 — 탐지한 값끼리의 충돌은 `taken`이 이미 막고, 텍스트 전체 검색은 건수 × 크기다).
7. **감사·지표·대시보드·문서**: 종류 `person`·`address`·`org`가 `pii`·`unmasked`·`gateway_pii_masked_total{kind}`에 그대로 들어간다. 대시보드 `KIND`에 이름·주소·직장, `REASON`에
   `detect_unavailable`, `metrics.REJECTED`에 `detect_unavailable`(503, 상류 없음), operations 결과 표·api-compat 오류 표·README 종류 표(가림·감사만·'막지 못하는 것' 고침)·
   configuration(환경변수 셋)·CHANGELOG·설명서 HTML·PDF. `/__gateway/info`에 `detect`(사이드카 주소, 없으면 null).
8. **배포 견본**: compose에 `detect` 서비스(빌드 `detect/Dockerfile` — 빌드 때 모델 143MB를 받는다, `healthcheck`는 이미지의 것), 게이트웨이는 `GATEWAY_DETECT_URL=http://detect:8081`에
   `depends_on: condition: service_healthy`, 체험 정책은 정규식 12 + `person,address`. k8s는 **같은 파드의 두 번째 컨테이너**(`ghcr.io/hongjinkong/llm-security-gateway-detect:0.1.0`,
   `127.0.0.1:8081`, readinessProbe `/health` — 파드는 두 컨테이너가 다 준비돼야 Ready다, 메모리 요청 512Mi·상한 1Gi, CPU 요청 1). CI의 compose 문법·kustomize 렌더·스키마 검사 그대로.
9. **응답 방향에는 NER을 돌리지 않는다**: 복원은 발급한 문자열 찾기로 충분하고, 응답에 새로 나온 이름을 세는 것은 요청마다 사이드카 왕복을 하나 더 더한다. `pii_new`는 정규식 종류만이다.
10. **지연 측정(이 결정의 §6)**: 실제 veil 사이드카 + 스텁 상류 앞에서 게이트웨이 경유 왕복을 M2에서 잰다 — 짧은 새 턴(약 30토큰), 둘째 턴(이력은 캐시·새 메시지만), 510토큰 새 텍스트.
   x86 숫자는 D-125 §6의 사이드카 단독 값(510토큰 201.5ms)에 게이트웨이 몫(수 ms)을 더한 것으로 읽는다.

### 3. 버린 대안

- **새 모드 손잡이**(`GATEWAY_NER=mask|detect|off`): 종류 목록 하나로 같은 일을 하고, 정책마다 다르게 켤 수 있으며, 감사만(org)도 기존 규칙이다. 손잡이가 둘이면 조합의 뜻을 문서로 설명해야 한다.
- **기동 때 사이드카 /health 확인 → 거부**: 같은 파드의 두 컨테이너는 기동 순서가 없어 게이트웨이가 크래시 루프를 돈다. 대신 사이드카 컨테이너에 readinessProbe(파드 Ready 조건)와
  요청 때 503(closed)·통과(open)로 한다. 주소 오타는 첫 요청의 503 `detect_unavailable`(감사 `ner_error: connect`)로 드러난다.
- **응답에도 NER을 돌려 복원·새 이름 세기**: 왕복이 두 배이고, 복원은 발급한 문자열 찾기가 결정적이고 싸다. 응답 마스킹은 '하지 않는 것'이다.
- **토큰 대체값(`[PERSON_1]`)**: D-107 B의 이유 그대로 — 모델이 가려진 것을 눈치채고 조사가 어긋나며 도구 인자에 그대로 쓴다.
- **이름 대체값을 원문 길이 그대로**: 2자(이름만)도 성 + 두 음절 3자로 만든다 — 모델이 성을 떼어 부르는 쪽이 자연스럽고, 길이가 바뀌어도 복원은 문자열 찾기라 문제없다.
- **마지막 사용자 메시지만 NER**: D-125 §3 — 이력·도구 결과의 이름이 그대로 나가고, 같은 이름이 턴마다 다르게 가려진다. 캐시가 이력 비용을 없앤다.
- **게이트웨이 전체 캐시 하나**: 정책마다 검사기가 따로고 정책 수가 적다 — 검사기마다 두는 쪽이 단순하다(같은 텍스트면 구간이 같으므로 공유해도 맞다. 정책이 많아지면 옮긴다).
- **창 경계를 공백에 맞춰 자르기**: 256자 겹침 + 128자 가장자리 규칙이면 128자보다 짧은 구간은 어느 창에 통째로 든다 — 주소도 50자 안이다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| H1 | 종류·설정: `ALL_KINDS` 15, 기본 `pii_kinds` 12(꺼짐), `DETECT_ONLY`에 `org`, 환경변수 셋 읽음, NER 종류를 켜고 URL이 없으면 기동 거부(ko·en 문구), `GATEWAY_DETECT_FAIL` 틀린 값 거부 | `tests/test_d126_ner_mask.py` |
| H2 | 가림: 시험용 사이드카 앞에서 이름·주소가 상류에 가짜 값으로 가고(원문 없음) 비스트리밍 응답에서 복원된다 — 세 API | 같은 파일 |
| H3 | 스트림: 3자 조각 스트림에서 이름·주소(공백 포함) 대체값이 조각 경계에 걸려도 복원된다(Chat·Messages) | 같은 파일 |
| H4 | 둘째 턴: 이력의 user 메시지 바이트가 첫 턴과 같고, 사이드카에는 새 텍스트만 간다(캐시 적중 — 호출 수) | 같은 파일 |
| H5 | 대체값 규칙: 이름의 받침 부류·길이·글자 체계(한글·라틴·그 밖), 주소의 머리 토큰 유지·숫자 자릿수·마지막 자리, org 꼬리 유지, 결정적(같은 키·원문) | 같은 파일 |
| H6 | 겹침·규칙: 정규식 탐지와 겹치는 NER 구간은 버림, 시·도만인 주소는 감사만, 숫자 든 주소는 가림, org는 기본 감사만·빼면 가림 | 같은 파일 |
| H7 | 실패 동작: 사이드카 500·시간 초과·연결 거부 × closed(503 `detect_unavailable`, 상류 없음, retry-after)·open(200, `ner_error`, 정규식 종류는 가림) · detect 정책은 늘 통과 | 같은 파일 |
| H8 | 긴 텍스트: 12,000자를 넘는 텍스트의 창 경계 양쪽 이름이 각각 한 번씩 올바른 위치에서 가려지고 요청이 두 번 간다 · 탐지 상한에 NER이 센다 | 같은 파일 |
| H9 | 볼트: 문자열 대체값 복원(공백 변형·`\s+`), 이름 앞 한글 음절이면 복원하지 않음, 정규식 종류 우선, `hold` 공백 뺀 비교, `avoid` | 같은 파일 |
| H10 | 감사·대시보드·문서 동기화: `REJECTED`·CODE_STATUS·대시보드 라벨 사전·operations 표·configuration 환경변수 표(README.en 포함)·k8s·compose 이름 | 기존 D-121·D-124 테스트(갱신) |
| H11 | 배포 견본: `docker compose config -q`, `kubectl kustomize` 렌더 + kubernetes-validate `--strict` 통과 | CI docker 작업·세션 |
| H12 | 지연 수치(실제 veil 사이드카 + 스텁 상류, M2): 짧은 새 턴·캐시된 둘째 턴·510토큰이 §6에 있다 | 이 결정 |
| — | 전체 `pytest -q`(사이드카 꺼짐 = 기존 테스트 그대로)·`ruff check .`·`mypy` 통과 | |

### 5. 한계

- 정확도는 모델의 것이다 — 합성 셋 F1 0.963·실제 대화 0.895(D-125): **놓침 약 10%·잘못 가림 약 10%**. 놓친 이름·주소는 그대로 나가고, 잘못 가린 보통 명사는 가짜 이름으로 바뀌어 답이
  어색해질 수 있다(감사 `findings`의 위치로 사후에 본다 — 원문은 남지 않는다).
- **부분 인용은 복원되지 않는다**: 모델이 성만 부르거나("김 고객님"), 주소의 일부만 되풀이하면 대체값 문자열이 통째로 없어 복원되지 않고, 의심 잔여(조각 규칙은 전화·카드·이메일)에도
  잡히지 않는다. 이름만 쓴 호칭도 같다.
- 요청마다 사이드카 왕복이 더해진다(캐시에 없는 텍스트만) — x86 4 vCPU에서 510토큰 약 200ms, 긴 문서는 12,000자마다 요청 하나(창 24개쯤 = 수 초). 사이드카는 한 번에 하나만 돌리므로
  동시 요청은 줄을 선다 — 처리량은 1/지연이다. 전체 기한(10초) 안에 못 끝나면 closed는 503이다. 긴 문서가 많은 정책은 `detect`나 `open`, 또는 사이드카 수를 늘린다(파드 수).
- 응답에 새로 나온 이름은 세지 않는다(`pii_new`는 정규식 종류).
- `avoid`(대체값이 요청에 이미 있는 글자열인지)는 64KB를 넘는 요청에서는 보지 않는다 — 그 요청에서는 놓친 실제 이름과 대체값이 겹칠 수 있다(드물다).
- 라틴 글자 대체값은 ASCII 대소문자만 무시하고 되찾는다(터키어 ı·İ 같은 변형은 다른 글자다). 한글 이름 대체값은 뒤따르는 조사를 포함해 어떤 한글이 와도 되찾는다 — '김민준수'처럼 다른 이름의 앞부분이
  대체값과 같으면 그 부분만 되돌아간다(대체값이 실제 텍스트에 이미 있으면 `avoid`가 피하지만, 응답에서 모델이 새로 쓴 이름은 피할 수 없다).
- `avoid`와 충돌 카운터(D-111 ponytail)로 대체값이 턴마다 달라질 수 있는 드문 경우가 있다 — 그 값만 이력 바이트가 바뀐다.
- 사람이 아닌 이름(제품·캐릭터·역사 인물)을 모델이 이름으로 잡으면 가린다. 주소 규칙은 '숫자가 든 토큰'이라 '강남역 2번 출구'도 가린다.
- 사이드카는 인증이 없다(같은 파드·내부망). 게이트웨이는 사이드카의 모델이 무엇인지 확인하지 않는다 — /health의 리비전·해시는 운영자가 본다.
- 라틴 이름은 영문 이름 사전으로, 그 밖의 글자 체계(한자·가나)는 한글 3자로 바꾼다 — 모델에게 다른 사람처럼 보이지만 글자 체계가 바뀐다.

### 6. 결과 (2026-11-02)

- **H1~H12 통과.** `tests/test_d126_ner_mask.py` 62개(시험용 사이드카 `tests/stub_detect.py` 앞의 HTTP 경로 + 가짜 클라이언트의 검사기 단위 + 리뷰 뒤 더한 20개), 기존 D-121·D-124 동기화 테스트 갱신
  (환경변수 25개·종류 15·거절 코드 13·줄 키 20). 전체 `pytest` 836(이 단계 전 773)·`ruff`·`mypy`(gateway 35 파일) 통과. 사이드카 꺼짐(기본) 구성은 기존 테스트가 그대로 지킨다 — 기본 `pii_kinds`가 정규식 12종이라 검사기는 사이드카를 만들지도 부르지도 않는다(H1).
- **만든 것**: `gateway/detect_client.py`(창·묶음·캐시·검증·실패 사유), `PIIDetector`의 `_with_ner`·`_ner_findings`(정규식 우선·숫자 없는 주소 감사만·org 감사만·상한 포함·`ner_ms`·`ner_error`·실패 동작),
  `surrogate.person/address/org`와 `final_class`, 볼트의 `_ner_pattern`·`_hits` 합류·`norm_key`(공백 제거·소문자)·`hold`(공백으로 시작하는 꼬리는 건너뛰고 공백 뺀 꼬리로 비교)·`token_for(avoid=)`,
  설정 셋(`GATEWAY_DETECT_URL`·`_TIMEOUT`·`_FAIL`)과 `ner_policies`(기동 거부 `no_detect_url` ko·en), `relay`의 503 `retry-after`, `metrics.REJECTED`·대시보드 `KIND`·`REASON`, `/__gateway/info`의 `detect`,
  compose `detect` 서비스(`service_healthy` 대기)·k8s 둘째 컨테이너(readinessProbe·512Mi/1Gi·CPU 1)·`gateway.toml`의 `[policies.names]`, 문서(configuration '이름·주소 가림' 절·operations '탐지 사이드카' 절·
  api-compat 503·README 두 언어의 종류 표와 '막지 못하는 것'·CHANGELOG·detect/README)·설명서 HTML·PDF(22쪽), `scripts/ner_latency.py`.
- **배포 견본 검사(H11)**: `docker compose config -q`, `kubectl kustomize` 렌더(컨테이너 `detect` 포함), kubernetes-validate 1.37 `--strict` 통과. `compose up --build`는 이 세션에서 Docker 데몬이 꺼져 있어 돌리지 않았다(PLAN 사용자 할 일).
- **지연(H12) — 실제 veil 사이드카(`detect.app`, 스레드 4) + 스텁 상류 + 게이트웨이, 모두 M2 한 대에서, `scripts/ner_latency.py --runs 100`** (왕복 = 클라이언트가 본 HTTP 왕복, 스텁 상류 평균 1.5ms 포함):

  | 장면 | n | 왕복 p50 · p95 (ms) | 감사 gateway_ms p50 · p95 | ner_ms p50 · p95 | 가린 이름·주소 |
  |---|---|---|---|---|---|
  | 짧은 새 턴(이름·주소 한 문장, 회차마다 다른 글) — 켜지 않은 정책 | 100 | 2.2 · 3.0 | 0.4 · 0.6 | — | 0 |
  | 같은 글 — 켠 정책(사이드카 왕복 하나) | 100 | 13.3 · 15.9 | 11.2 · 13.3 | 9.6 · 11.2 | 200/200 |
  | 둘째 턴(턴 1 user 메시지는 캐시, 턴 1의 답은 새 글 + 새 질문) | 100 | 13.4 · 16.0 | 11.3 · 13.4 | 10.6 · 12.4 | 400/400 |
  | 셋째 턴(이력과 되풀이되는 짧은 질문이 모두 캐시) | 100 | 2.6 · 3.6 | 0.7 · 1.0 | 0.0 · 0.0 | 400/400 |
  | 510토큰 새 텍스트(detect/bench.py와 같은 길이, 회차마다 다른 글) | 55 | 187.2 · 223.5 | 184.6 · 220.0 | 167.4 · 198.9 | 1,475 |

  읽는 법: 켠 정책의 비용은 사이드카 왕복(`ner_ms`) 그대로다 — 짧은 문장 약 +11ms, 510토큰 창 하나 약 +185ms(사이드카 단독 측정 D-125 §6의 M2 214ms·x86 201.5ms와 같은 급), 캐시에 있는 이력은 1ms 안쪽.
  합성 이름·주소(`eval/ner/make_synth.py` 사전)는 모두 가려졌다(정확도는 D-125 §6의 F1이 기준이다 — 이 표는 지연 측정이지 정확도 측정이 아니다).
  x86 4 vCPU에서는 D-125 §6의 사이드카 단독 값(32·64·128·256·510토큰 15·30·42·86·201.5ms)에 게이트웨이 몫 1~2ms를 더해 읽는다.
- **리뷰 + 반박 검증**(울트라코드 워크플로, 에이전트 24 — 검토 4관점: 클라이언트·검사기 / 볼트·복원·스트림·대체값 / 설정·기동·관측 / 배포·문서·테스트, medium 이상 지적마다 회의적 검증 2):
  지적 25건 → medium 이상 10건은 **검증 2/2 모두 재현(반박 0)**, low 15건은 미검증. 전부 반영했다 —
  ① **high** 문자열 대체값 정규식이 대안마다 `(?<![가-힣])` + IGNORECASE라 발급 수에 비례해 이벤트 루프를 멈췄다(5,000건: 컴파일 3.3초, 4KB 복원 0.25초 — 명단 1,000명으로도 0.7초, 모두 루프 위).
  단언을 무리마다 한 번으로 묶고 IGNORECASE 대신 ASCII 글자만 `[Aa]`로 쓰게 바꿨다(5,000건 발급 뒤 1,000개 든 5KB 복원 + residual·suspect가 0.1초 안 — 회귀 테스트). residual·suspect는 `leftovers`로 한 번만 훑는다.
  ② **medium** closed 503 줄에 `ner_error`·`ner_ms`가 남지 않았다 → `ApiError.meta`로 거절한 검사기의 메타를 relay가 한 단계짜리 체인 결과로 감사 줄에 남긴다(`action: reject`).
  ③ **medium** open·detect에서는 사이드카가 죽어도 200이라 장애 신호가 감사 줄 속 `ner_error`뿐이었다 → 지표 `gateway_detect_errors_total{reason}`, stats `detect_errors`, 최근 줄 `ner_error`(ROW_KEYS 20), 대시보드 문장.
  ④ **medium** 붙여 쓴 주소 토큰(`테헤란로123`·`역삼1동`·`삼성아파트101동`·`수성로275번길91`)과 `SK하이닉스`류 혼합 줄기에서 실제 도로·건물·회사 이름이 가짜 값에 남았다 → 토큰을 한글·숫자·그 밖 덩어리로 나눠 각각 바꾼다
  (단위 낱말 동·호·층·번길은 둔다, 괄호는 보존). ⑤ **medium** 사전의 `한빛로`·`미르재단` 등이 실존 이름이었다 → 두 낱말을 붙인 조어 사전으로. ⑥ **medium** 라틴 이름 대체값이 낱말 속(`dilemma`의 `emma`)에서도 복원됐다 →
  라틴·숫자로 시작·끝나는 대체값은 앞뒤가 영숫자가 아닐 때만. IGNORECASE가 터키어 ı·İ를 ASCII i와 겹쳐 `norm_key`와 어긋나 KeyError 500이 날 수 있던 것은 ASCII 대소문자만 무시하고 사전에 없는 키는 버리는 것으로.
  ⑦ **medium** `hold`가 숫자로 시작하되 글자가 섞인 꼬리(`101동 12`)를 보류하지 않아 숫자로 시작하는 주소 대체값이 스트림 조각 경계에서 복원되지 않았다 → 숫자 가지에서 못 맞추면 문자열 가지로 내려온다.
  ⑧ **medium** `GATEWAY_DETECT_TIMEOUT` 0·음수·nan과 경로·쿼리가 붙은 `GATEWAY_DETECT_URL`을 받아들여 요청마다 timeout·404가 됐다 → 기동 거부(`positive`·`detect_url` 문구). ⑨ **medium** `avoid`가 요청 크기 × 새 대체값 수라
  큰 요청에서 수 초가 될 수 있었다 → 64KB 넘는 요청은 보지 않는다(AVOID_CHARS, ponytail 주석), 대소문자 무관 비교. ⑩ **medium** 문서의 '유휴 300MiB'·'창 하나 ≈ 0.2초'가 실측과 달랐다 → 사이드카 물리 점유 기동 직후 약 590MiB·
  요청 뒤 약 620MiB(k8s 요청 768Mi), 창 하나(12,000자)는 글자 종류에 따라 1.1~5.7초(한글 낱말 1.1초, 숫자 2.8초, 구두점 섞인 영문·한자 5.5초 — 기본 기한 10초는 한글 문서 약 9만 자, 숫자·코드 문서 약 2만 자)로 고쳤다.
  low 15건: README 재현율 열의 합성 F1을 실제 대화 재현율 + F1로, configuration 예시의 `allowed_models`가 `names` 정책으로 넘어가던 순서, k8s·toml 주석(사이드카를 빼면 `[policies.names]`도 함께 — 쓰는 클라이언트가 없어도
  기동 거부), 공백·서식 문자뿐인 NER 구간 버림, 설명서의 '0.2초' 문장 둘, 검증자가 메운 테스트 빈자리(설정 파일로 켠 정책·Responses 스트림·도구 인자 속 이름·open 스트림·같은 이름 둘·1,024개 묶음·LRU 밀어내기) 등.
  반영하지 않은 것: '정책마다 DetectClient·캐시가 따로다'(정책 수가 적어 둔다 — §3), '사이드카에 인증이 없다'(§5 한계, 같은 파드·내부망).
- **못 한 것·남은 것**: `compose up --build`(Docker 데몬 꺼짐 — 사용자 할 일), 실제 공급자 앞에서 이름·주소 가림의 2턴 확인은 하지 않았다(D-114의 결정적 대체값 검증이 같은 볼트 경로를 지나고, 이번 단계는 유료 호출을 등록하지 않았다 —
  디자인 파트너 PoC(22단계)에서 실제 대화로 본다). 사이드카 메모리(M2, 위 측정 뒤 물리 점유 422MiB·최대 602MiB — `vmmap -summary`)로 k8s 요청 512Mi·상한 1Gi를 잠정으로 두었다.

## D-127. 인젝션 분류기(사이드카 `injection` 작업, 관측) + 가드레일 웹훅 검사기 (2026-11-03, PLAN 18단계)

### 1. 근거

- 인젝션 탐지는 정규식 룰 둘(R1·R2)뿐이다 — dev 재현율 8.7%(한국어 5.9%)·오탐률 2.7%, recall@FPR 1% 미달(D-123 §6). 연구 단계의 2·3차 기각(D-052 유사도, D-054 gemma3:4b Judge)은
  특정 구성·8GB VRAM의 결과이고 인코더 분류기는 시험하지 않았다(부록 A). 결정 표 6번: 관측 + 외부 가드레일 웹훅, 자체 모델 학습은 하지 않는다, 기본 후보 protectai v2.
- 후보 다시 보기(2026-11-03, HF API — 리비전·라이선스·파일): ① `protectai/deberta-v3-base-prompt-injection-v2` @90c9989b(Apache-2.0, 영어 전용, 제작자 ONNX fp32 738MB, 프로젝트 보관 상태)
  ② `Horizon-Labs/prompt-injection-guard-small` @5ed691c2(Apache-2.0, mmBERT-small, 학습 언어에 한국어 합성, 제작자 ONNX int8 268MB) ③ `…-guard-base` @8c321b08(mmBERT-base, int8 641MB)
  ④ `meta-llama/Llama-Prompt-Guard-2-86M` @a8ded8e6(mDeBERTa-base, Llama 4 Community, 수동 승인 게이트, safetensors만 — ONNX 없음, 평가 언어 8개에 한국어 없음)
  ⑤ `…-22M` @11614a15(DeBERTa-xsmall, 영어 어휘). wolf-defender(학습 데이터 라이선스 불명확, 독·영)·KLUE roBERTa 한국어 모델(라이선스 불명)은 17단계 조사대로 뺀다.
- **학습 데이터 오염**(카드 기준): Horizon은 `deepset/prompt-injections` train·`Lakera/gandalf_ignore_instructions`·jackhhao·llmail 1단계로 학습했다 — 우리 셋의 deepset·gandalf 행과,
  deepset 문항을 한국어로 옮긴 JHC56 행(D-123 §2-1)이 학습 분포와 겹친다. protectai v2는 이름을 밝힌 셋 밖에 MIT 8·라이선스 없음 6개를 쓰고(어느 것인지 모른다), PG2는 학습 셋을 밝히지 않는다.

### 2. 결정

1. **사이드카 `injection` 작업**(`detect/classify.py`) — 텍스트 하나 → 점수(0~1, 양성 클래스 softmax). tokenizers + ONNX Runtime(NER과 같은 고정·해시 규칙 — `models.json`의
   리비전·파일 SHA-256, 열 때 다시 잰다). 긴 텍스트는 **512토큰 창(특수 토큰 둘 포함)을 128토큰 겹쳐** 밀고 점수는 창들의 최댓값(문서 끝에 심은 지시도 본다).
   토크나이저 앞에는 NFC만 더한다(풀어 쓴 한글을 모은다 — 표준 동치라 뜻이 같다). 그 밖의 정규화는 모델이 배포한 토크나이저 그대로다(D-125 §2-2와 같은 원칙 — 만든 쪽의 방식으로 잰다).
   - `POST /v1/detect`의 `tasks`에 `injection` → 결과마다 `"injection": 점수`. `POST /v1/guard`(아래 웹훅 계약 구현) → `{"verdict", "score"}` — 점수는 텍스트·창의 최댓값,
     `verdict`는 점수 ≥ 문턱이면 `block`. 문턱은 `DETECT_GUARD_THRESHOLD`(없으면 `models.json`의 그 모델 `threshold` = §2-5의 dev 운영 문턱).
   - 환경변수: `DETECT_INJECTION_MODEL`(이름, 비면 이 작업 없음), `DETECT_MODEL`(NER — 비면 NER 없음, 가드레일만 쓰는 사이드카). 요청 상한(본문 2MiB·텍스트 1,024·글자 131,072·
     토큰 16,384 — 모델마다 그 토크나이저로 센다)과 한 번에 한 추론은 NER과 같다(두 작업이 같은 코어를 나눠 쓴다).
   - 점수 캐시: 텍스트 SHA-256 → 점수 LRU 4,096(원문 없음). 에이전트 루프는 이번 턴의 도구 결과를 단계마다 다시 보내므로 사이드카가 같은 텍스트를 다시 재지 않는다.
2. **가드레일 웹훅 검사기**(`gateway/detectors/guard.py`) — 계약: `POST GATEWAY_GUARD_URL {"texts": [{"role": "user"|"tool", "text"}]}` → 200 `{"verdict": "allow"|"block", "score": 0~1}`
   (그 밖의 키는 무시). 보내는 텍스트는 **이번 턴의 user·tool 텍스트**(룰의 차단 범위와 같다, D-118)이고, 검사기는 **체인의 마지막(PII 뒤)** — 웹훅은 공급자가 받을 텍스트(가짜 값)만 본다.
   외부 서비스여도 원문 개인정보가 새지 않는다. 텍스트가 없으면 부르지 않는다. (§6 리뷰로 고침: 웹훅은 공급자와 같은 텍스트를 볼 뿐이다 — 정책이 가리는 종류만 가짜 값이고
   감사만·켜지 않은 종류와 detect·off 정책의 텍스트는 원문이다. 이번 턴의 첨부 문서도 보내고, 메시지마다 하나로 잇는다.)
   - `GATEWAY_GUARD`(`off`|`observe`|`block`, 기본 `off`, 정책 키 `guard`), `GATEWAY_GUARD_URL`(`http(s)://호스트[:포트][/경로]`, 쿼리·조각 없이), `GATEWAY_GUARD_TIMEOUT`(초, 기본 5 —
     한 요청 전체 기한), `GATEWAY_GUARD_FAIL`(`open`|`closed`, 기본 `open`). 기동 거부: `guard`가 `off`가 아닌 정책이 있는데 URL이 비면(`no_guard_url`).
   - `observe`(검사기 `injection_guard`): 막지 않는다 — 감사 줄의 검사기 항목에 `guard_verdict`·`guard_score`, `block` 판정이면 `would_block: true`(결과 `observed`, 사유 `injection_guard`).
     `block`(검사기 `injection_guard_block`): `block` 판정이면 룰 차단과 같은 200 차단 응답(사유는 감사에만).
   - 실패(`guard_error`: `timeout`·`connect`·`http_<상태>`·`bad_response`)는 observe·open이면 판정 없이 통과하고, block + closed면 503 `guard_unavailable`(`retry-after: 1`, 상류 없음).
     지표 `gateway_guard_errors_total{reason}` — observe·open에서는 이것만이 장애 신호다. 인젝션 적중 지표 `gateway_injection_hits_total{mode}`에 가드레일 판정도 센다.
   - 사이드카를 웹훅으로 쓰는 예제: 같은 파드면 `GATEWAY_GUARD_URL=http://127.0.0.1:8081/v1/guard`. 배포 견본(compose·k8s)은 observe로 켠다.
3. **평가**(`detect/evaluate_injection.py`) — 분류기를 `eval/injection`에 돌려 `score.py`의 표(언어·유형별 재현율·오탐률, recall@FPR 1%·0.5%, 언어별 recall@FPR)를 낸다.
   다중 턴 항목의 점수는 턴들의 최댓값. 원문은 출력하지 않는다. **깨끗한 부분집합** = dev에서 출처 `deepset`·`JHC56`·`gandalf`를 뺀 것(Horizon 학습 셋과 그 번역 — 알려진 오염, §1).
   비교는 깨끗한 부분집합과 전체를 함께 낸다. protectai·PG2의 밝히지 않은 학습 셋 오염은 뺄 수 없다(§5).
4. **양성대조**(D-054 §6 재사용, `--control`) — 채택 모델의 dev 운영 문턱(§2-5)을 넘은 dev 공격(기저)마다 D-054의 조작 문구 6종(직접 지시·역할 재지정·출력 복사 유도·권한 사칭·
   울타리 탈출·규칙 재정의 — 연구 단계 `scripts/judge_control.py`의 `PAYLOADS` 문장 그대로)을 씌운 조작본을 재고, **문턱 밑으로 떨어진 비율(뒤집힘)**을 문구마다 센다.
5. **사전 등록 게이트**(이 결정을 적은 뒤에 처음 잰다 — 이 세션은 아직 어느 후보도 우리 셋에 돌리지 않았다):
   - **G1 채택**: 라이선스가 Apache-2.0·MIT이고 게이트 없이 받을 수 있는 후보(①②③) 가운데 **dev 깨끗한 부분집합의 한국어 recall@FPR≤1%**가 가장 높은 것을 사이드카 기본 분류기로 한다.
     2%p 이내로 비기면 M2 510토큰 HTTP p95가 낮은 쪽. PG2(④⑤)는 비교만 한다 — 이미지를 만들 때 사용자마다 Meta 승인과 토큰이 필요하고 Llama 4 라이선스 의무("Built with Llama" 표시)가 붙는다.
     운영 문턱(`threshold`) = 채택 모델의 dev 전체(모든 언어) 정상셋에서 오탐률 1%를 넘지 않는 가장 낮은 문턱(score.py `at_fpr`).
   - **G2 한국어 기준**: 채택 모델의 **홀드아웃 깨끗한 부분집합 한국어 recall@FPR≤1% ≥ 0.50**. 미달이면 PLAN 조건부 표의 '자체 파인튜닝' 트리거가 발동한 것으로 적는다
     (결정 표 6번 — 자체 학습은 하지 않는다 — 은 그대로이고 실행은 사용자 결정이다).
   - **G3 양성대조**: 문구마다 뒤집힘 ≤ 5%. 넘으면 그 모델로 block을 권하지 않는다(문서에 '관측 전용'으로 적는다).
   - **G4 지연**: 게이트가 아니라 비용으로 적는다(결정 표 7번이 NER에서 바꾼 것과 같다) — 버킷 32·64·128·256·510토큰 HTTP p50·p95, M2(모든 후보)와 x86 CI(채택 모델, `detect` 워크플로).
   - **홀드아웃은 채택을 dev로 정한 뒤 한 번** 연다(측정한 후보 모두를 같은 실행에서) — 결과를 보고 채택·문턱을 바꾸지 않는다(D-123 §2-3).
6. **배포**: 사이드카 이미지가 두 모델을 다 갖는다(`ARG MODEL`·`ARG INJECTION_MODEL`, 빌드 때 받아 해시를 맞춘다). compose·k8s 견본은 `GATEWAY_GUARD=observe`와
   `GATEWAY_GUARD_URL=…/v1/guard`. 사이드카 메모리 요청·상한은 두 모델을 올린 실측으로 고친다. 감사·지표·대시보드·문서(configuration·operations·api-compat·README 둘·detect/README·CHANGELOG·설명서)를 함께 고친다.

### 3. 버린 대안

- **분류기 전용 검사기 + 별도 웹훅 검사기 둘**: 사이드카가 웹훅 계약(`/v1/guard`)을 구현하면 게이트웨이 검사기는 하나다. 운영자는 같은 손잡이로 자기 가드레일과 우리 분류기를 바꿔 낀다.
- **체인 앞(PII 전)에서 웹훅 부르기**: 외부 웹훅이 원문 개인정보를 받는다 — 이 제품이 막으려는 유출이다. 분류에 가짜 값은 거의 영향이 없다(같은 모양).
- **관측 모드를 상류 호출과 동시에(지연 0)**: 감사 줄을 쓰기 전에 끝나지 않은 작업을 기다리거나 버려야 하고 차단·거절·예외 경로마다 정리가 필요하다. 순서대로 부르고 비용(캐시 밖 텍스트만)을 잰다 —
  ponytail: 관측 지연이 문제가 되면 상류 호출과 겹친다.
- **이력 전체를 웹훅에**: 이력은 그 턴이었을 때 이미 판정됐다. 웹훅 계약이 요청 하나에 판정 하나라 이력만 따로 가릴 수 없다(이력 가림은 룰의 `injection_rule_turn`).
- **웹훅 인증 헤더**(`GATEWAY_GUARD_KEY`): 외부 가드레일은 계약이 달라 어차피 어댑터가 필요하고, 어댑터는 같은 클러스터에서 공급자 키를 든다. 고객이 요구하면 더한다.
- **분류기마다 우리 정규화(NFKC·제로폭 제거)를 앞에**: 모델이 배포한 토크나이저의 정규화와 겹치거나 어긋난다(Horizon은 자체 정규화기를 토크나이저에 넣었다). 난독화 공격은 셋의 `encoding` 유형으로 그대로 잰다.
- **자체 파인튜닝·증류**: 결정 표 6번. G2 미달이면 트리거로만 적는다.
- **문턱을 한국어 정상셋으로**: 한 배포가 여러 언어를 받는다 — 전체 정상셋으로 정하고 언어별 오탐률을 함께 적는다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| I1 | 분류기: 창이 [0, n)을 덮고 점수 = 창 최댓값(긴 텍스트 끝의 지시), 특수 토큰은 토크나이저 규칙에서, 해시 불일치 거부, /health에 두 작업 | `detect/tests` (CI detect) |
| I2 | 사이드카 계약: `tasks: ["injection"]` 결과·순서, `/v1/guard` 판정·문턱·상한 413·400 무반향, 캐시(같은 텍스트 두 번째는 모델을 부르지 않음), 꺼진 작업은 400 | `detect/tests` |
| I3 | 평가: 깨끗한 부분집합·다중 턴 최댓값·원문 비출력, 양성대조가 D-054 문구 6종을 그대로 쓴다 | `tests/test_d127_guard.py`(점수 함수는 가짜 분류기로) |
| I4 | 관측: 웹훅이 block이라 해도 막지 않고(차단 0) 감사 줄에 판정·점수·`would_block`, 결과 `observed`/`injection_guard` | 같은 파일 |
| I5 | 차단: block 판정이면 200 차단 응답(세 API·스트림), 상류 호출 없음, 사유는 응답에 없음 | 같은 파일 |
| I6 | 웹훅이 받는 텍스트: 이번 턴의 user·tool만, PII는 가짜 값(원문 없음), 텍스트가 없으면 부르지 않음 | 같은 파일 |
| I7 | 실패: 시간 초과·500·연결 거부·잘못된 응답 × observe(통과·`guard_error`)·block+open(통과)·block+closed(503 `guard_unavailable`·retry-after·상류 없음), 지표 | 같은 파일 |
| I8 | 설정: 환경변수 넷·정책 키 `guard`·틀린 값 거부·URL 없이 켜면 기동 거부(ko·en)·체인 순서(PII 뒤) | 같은 파일 |
| I9 | 대시보드·문서 동기화: REJECTED·CODE_STATUS·라벨 사전·operations 표·환경변수 표·설정 키 표·row 키 | 기존 D-121·D-124 테스트(갱신) |
| I10 | 게이트 수치(G1~G4)·홀드아웃 한 번·양성대조가 §6에 있다 | 이 결정 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy`(gateway·detect) 통과 | |

### 5. 한계

- 평가셋의 라벨 잡음·LLM 합성 출처는 D-123 §5 그대로다. 밝히지 않은 학습 셋(protectai·PG2)의 오염은 뺄 수 없다 — 깨끗한 부분집합도 그 둘에는 '알려진 오염만 뺀' 숫자다.
- 분류기는 텍스트를 따로 본다 — 맥락상 정당한 지시(사용자가 정말 메일 전달을 원함)와 구분하지 못한다. 가드레일은 한 겹이고, 적응형 공격자는 어떤 분류기든 피해 갈 수 있다.
- 웹훅은 이번 턴만 본다 — block으로 막힌 질문을 클라이언트가 다음 턴 이력에 다시 넣으면 그 이력은 웹훅이 다시 보지 않는다(룰의 이력 가림은 룰 어휘에 걸린 것만).
- 관측도 요청 경로에서 기다린다 — 캐시 밖 텍스트만큼 지연이 더해진다(§6 수치). 사이드카는 한 요청에 캐시 밖 글을 새 글부터 비용 상한(`DETECT_INJECTION_MAX_TOKENS` 2,048)까지만 재고
  나머지는 `unscored`로 알린다(block은 막고 observe는 기록) — 혼자서 상한을 넘는 긴 글(한글 약 3,000자 이상)은 끝내 재지 않는다. (§6 재검증으로 고침 — 처음에는 토큰 16,384까지·넘으면 413이었다)
- 웹훅에 인증이 없다(같은 파드·내부망). 응답 크기 상한도 두지 않는다(운영자가 정한 주소다).
- 다중 턴 공격의 재현율은 대화 단위(턴들의 최댓값)이고 오탐률은 글 단위다 — 다중 턴 정상 대화가 셋에 없다. 긴 문서는 창이 많아 오탐이 는다(점수는 창들의 최댓값). (§6 리뷰로 더함)

### 6. 결과 (2026-11-03)

- **판정**: **G1** — `horizon-guard-base-int8`을 채택했다(dev 깨끗한 부분집합 한국어 recall@FPR≤1% **76.3%**, small 56.9%·protectai 11.7%. PG2는 비교만 — 86M 21.4%·22M 1.0%).
  운영 문턱은 dev 전체 정상셋 오탐 1% 문턱 **0.9357725303620347**(오탐 28/2,862, `models.json`). **G2** — 사전 등록 정의로 **통과**: 봉인 홀드아웃 깨끗한 부분집합 한국어 recall@FPR≤1%
  294/394 = **74.6%**(≥ 0.50). **G3** — **미달**: '출력 복사 유도'(공격 뒤에 가짜 판정 JSON)가 잡힌 dev 공격 1,501건 중 133건 = **8.9%**를 문턱 밑으로 떨어뜨렸다(기준 5%) — 등록대로
  **이 모델로 block을 권하지 않는다**(관측 전용). **G4** — 비용: M2 510토큰(창 하나) HTTP p50 0.56~0.59초·p95 0.65~0.80초, 32토큰 32~37·39~43ms(두 번 잼). x86은 푸시 뒤 CI.
- **G2를 운영 문턱으로 읽으면**(리뷰 지적 — 홀드아웃을 연 뒤라 판정은 바꾸지 않고 함께 적는다): 사전 등록 정의는 언어마다 그 언어(그 부분집합)의 정상셋으로 문턱을 다시 고른다
  (깨끗한 한국어 문턱 0.81). 실제로 내보낸 문턱 0.9358에서 홀드아웃 한국어 재현율은 **61.7%**(269/436, 깨끗한 부분집합 64.2%)이고 한국어 정상 오탐은 **1.7%**(8/470, 깨끗한 0.9%)다.
  전체 한국어 정상셋으로 오탐 1%를 맞추면 46.1%(201/436)로 0.50 밑이다. 깨끗한 부분집합은 오염 출처와 함께 가장 어려운 한국어 정상(JHC56 — deepset 번역, base 오탐의 대부분)도 뺀다 —
  그래서 깨끗한 숫자가 높다(리뷰가 이를 '오염이 아니다'라고 지적했고 반박 검증에서는 등록 정의대로라 반박됐다). 자체 파인튜닝 트리거는 등록대로 **발동하지 않은 것**으로 적되 경계에 있다 —
  PLAN 사용자 할 일에 판단 항목으로 남긴다. 문서의 머리 숫자는 운영 문턱의 홀드아웃 값(61.7%·1.7%)을 쓴다.
- **후보**(dev 5,492 · 홀드아웃 1,379, recall@FPR≤1%는 그 집합의 정상셋으로 문턱을 고른 값, 지연은 M2 스레드 4 HTTP p95 ms):

  | 모델 | dev 전체 | dev 한국어 | dev 깨끗한 한국어 | 홀드아웃 깨끗한 한국어 | 0.5에서 오탐 | p95 32·128·510토큰 |
  |---|---|---|---|---|---|---|
  | **horizon-guard-base-int8**(mmBERT-base 641MB) | 57.1% | 56.0% | **76.3%** | **74.6%** | 3.7% | 39~43·139~228·646~804 |
  | horizon-guard-small-int8(mmBERT-small 268MB) | 52.7% | 46.1% | 56.9% | 63.2% | 2.6% | 19.2·74.5·307.2 |
  | protectai-v2(DeBERTa-v3-base fp32 738MB) | 17.3% | 14.4% | 11.7% | 8.9% | 28.8% | 44.2·155.7·716.9 |
  | pg2-86m(mDeBERTa, 내보낸 fp32 1.1GB) | 16.5% | 23.8% | 21.4% | 17.3% | 0.9% | 52.6·121.2·724.4 |
  | pg2-22m(DeBERTa-xsmall, 내보낸 fp32 284MB) | 11.4% | 0.8% | 1.0% | 0.5% | 1.5% | 11.9·47.6·237.7 |

  룰 기준선(dev)은 재현율 8.7%(한국어 5.9%)·오탐 2.7%였다(D-123). base의 스레드 2는 510토큰 p95 968.9ms — 스레드 4가 낫다. 내보낸 PG2 ONNX는 torch 2.15.0으로 만들었고
  torch와의 양성 확률 차 1e-4 안을 확인했다(`detect/export.py`).
- **운영 문턱(0.9358)의 base** — dev: 재현율 1,501/2,630 = 57.1%·오탐 28/2,862 = 1.0%(한국어 57.0%·1.0%, 영어 50.6%·1.1%). 유형별 재현율(dev): 한국어 직접 59.3%·간접(문서 속) 95.7%·역할 위조 53.8%·
  난독화 43.0%, 영어 직접 68.1%·**간접(도구 결과 — BIPIA·InjecAgent) 22.7%**·다중 턴 51.6%. 오탐: 한국어 일반 1.1%·하드 네거티브 0.9%, 영어 하드 네거티브 2.1%.
  홀드아웃(한 번): 재현율 450/730 = 61.6%·오탐 9/649 = 1.4% — 한국어 61.7%(직접 65.0%·간접 100%·난독화 52.2%)·오탐 1.7%, 영어 55.1%(간접 28.0%)·오탐 0.9%.
- **양성대조**(D-054 문구 6종 그대로 — `tests/test_d127_guard.py`가 바이트 해시를 고정, dev·문턱 0.9358, 기저 1,501 = 한국어 908·영어 399·그 밖 194):
  직접 지시 0(0.0%) · 역할 재지정 27(1.8%) · **출력 복사 유도 133(8.9% — 한국어 103/908 = 11.3%)** · 권한 사칭 18(1.2%) · 울타리 탈출 22(1.5%) · 규칙 재정의 43(2.9%).
  인코더 분류기는 지시를 따르지 않지만, D-054에서 LLM 판사를 3/3 뚫은 바로 그 문구(미리 채운 판정 JSON)가 여기서도 가장 세다 — 문턱 근처의 공격이 'benign'·'정상 질문' 같은 낱말에 끌려 내려간다.
- **메모리**(M2 물리 점유, `vmmap`): NER만 0.6GiB · 분류기(base)만 기동 직후 1.5GiB(여는 동안 최대 2.4GiB) · 둘 다 1.8GiB(최대 2.6GiB) · small만 0.7~1.2GiB. 그래서 이미지는 분류기 파일을
  갖되 **기본으로 싣지 않는다**(`DETECT_INJECTION_MODEL` 빈 값) — 켜면 k8s 사이드카를 요청 2Gi·상한 3Gi로(견본 주석).
- **만든 것**: 사이드카 `detect/classify.py`(창 최댓값·NFC·특수 토큰 처리)·`app.py`의 `injection` 작업과 `POST /v1/guard`(점수 캐시, 작업마다 따로 선 줄, 상한을 모두 센 뒤 추론, 캐시 밖만 세는 상한
  `DETECT_INJECTION_MAX_TOKENS` 2,048, 끊긴 요청 건너뛰기, 문턱 범위 검사)·`fetch.py`(승인 저장소 토큰은 리다이렉트로 옮기지 않음, 쓰지 않는 파일은 해시만)·`export.py`·`evaluate_injection.py`·
  `bench.py`(작업 injection)·`models.json` 다섯 항목. 게이트웨이 `gateway/detectors/guard.py`(메시지마다 잇기·이번 턴의 첨부 문서 포함·입력 거절이면 block에서 막음)·설정 넷과 정책 키 `guard`·
  기동 거부 `no_guard_url`·URL 검증(포트·호스트·사용자 정보)·거절 줄에 앞 검사기 기록·지표 `gateway_guard_errors_total`·`gateway_guard_verdicts_total`·대시보드 문장(실패는 '그대로' 줄에도 꼬리로).
  배포 견본은 켜는 방법만(기본 꺼짐), CI `detect`는 채택 모델의 dev 점수·지연과 **이미지를 띄워 두 작업·/v1/guard·메모리**를 본다.
- **테스트**: `tests/test_d127_guard.py` 50(I3~I8 + 리뷰·재검증 뒤), `detect/tests` 23(이 단계 전 12 — C1~C11), D-121·D-124·D-125 동기화 테스트 갱신. 전체 `pytest` 887(이 단계 전 836)·`ruff`·`mypy`.
- **리뷰 + 반박 검증**(울트라코드 워크플로, 에이전트 19 — 검토 4: 사이드카·게이트웨이·평가 방법·테스트와 배포, medium 이상 지적마다 회의적 검증 1): 지적 42건 → medium 이상 15건 중 **14건 재현**, 1건 반박
  (깨끗한 부분집합의 JHC56 — 등록 정의대로라 반박, 위 'G2를 운영 문턱으로'에 함께 적었다), low 27건은 미검증. 고친 것 —
  ① **high** 사이드카가 캐시된 텍스트까지 글자 상한에 세어, 이번 턴이 131,072자를 넘으면 그 턴의 나머지 단계가 모두 413(판정 없이 통과 또는 503)이 됐다 → 캐시 밖만 센다.
  ② **high** 글 속의 '<eos>'·'[SEP]'가 진짜 특수 토큰으로 모델에 가 점수를 낮출 수 있었다 → BPE는 `encode_special_tokens`, Unigram은 그 위치의 글이 특수 토큰 글자면 뺀다(평가셋에 그런 글은 0건 — 숫자 불변).
  ③ **medium** 파트 1,025개로 쪼갠 메시지(사이드카 상한 1,024 → 400)나 상한을 넘는 글(413)로 block+open의 판정을 피할 수 있었다 → 메시지마다 잇고, block에서 입력 거절(400·413·422)이면 막는다.
  ④ **medium** 상한 안의 긴 요청 하나가 추론 줄을 게이트웨이 기한 너머까지 잡고, 가드레일 관측이 같은 줄의 이름·주소 가림(fail closed)을 503으로 밀어낼 수 있었다 → 작업마다 줄을 따로,
  분류기 한 요청 상한을 기한 안(창 다섯)으로, 기다리는 동안 끊긴 요청은 돌리지 않는다. 견본은 기본 꺼짐으로(이미지도 분류기를 싣지 않는다).
  ⑤ **medium** `GATEWAY_GUARD_URL`·`GATEWAY_DETECT_URL`의 틀린 포트(문자·범위 밖)가 기동을 지나 요청마다 500이었다 → 기동 거부(사용자 정보·빈 호스트도).
  ⑥ **medium** 문서가 '웹훅에는 원문 개인정보가 가지 않는다'고 했다 — 감사만 종류·켜지 않은 종류는 원문이다 → 문서·주석을 고치고 테스트로 고정.
  ⑦ **medium** 대시보드가 '그대로'·'기록만(감사만 종류)' 줄에서 가드레일·NER 실패를 숨겼다 → 모든 줄에 꼬리, node로 문장 테스트.
  ⑧ **low**(검증이 낮춤) 분류기를 여는 동안 쓰지 않는 파일까지 메모리에 올렸다 → 필요한 파일만 바이트로. 그 밖 low에서 반영: 내보내기는 확인 뒤 제 이름으로, 문턱·상한 범위 검사,
  모델 task 확인, 400자리 정수 점수의 OverflowError(500) → `bad_response`, 웹훅 연결 keep-alive 4초(사이드카 클라이언트도), 거절된 요청 감사 줄의 앞 검사기 기록, 판정 지표,
  Anthropic 첨부 문서를 웹훅에, 세 API의 이번 턴 텍스트 테스트, D-054 문구 바이트 고정, `--holdout`·`--control` 함께 거부, 요약의 동작점, bench의 40ms 게이트는 NER만.
  반영하지 않은 것: 양성대조가 마지막 턴에만 씌우고 기저에 학습된 행이 섞여 통과 쪽으로 기운다(그래도 미달이라 결론이 같다), 다중 턴의 재현율은 대화 단위·오탐은 글 단위(§5에 더함).
- **계획과 다른 점**: 배포 견본은 `observe`로 켜지 않고 켜는 방법만 적었다(메모리 +1.2GiB·G3 미달 — 리뷰 ④), 이미지는 분류기 파일을 갖되 기본으로 싣지 않는다, 웹훅이 이번 턴의 첨부 문서도 받고
  메시지마다 하나로 잇는다, block에서 입력 거절은 막는다(`GATEWAY_GUARD_FAIL`과 무관), 분류기 한 요청 상한 `DETECT_INJECTION_MAX_TOKENS`(2,048)를 더했다, 사이드카 작업마다 줄을 따로 선다,
  PG2는 `detect/export.py`로 ONNX를 만들어 같은 코드로 쟀다.
- **못 한 것·남은 것**: x86 지연·F1과 이미지 실제 기동(두 모델, 메모리)은 푸시 뒤 CI `detect` 워크플로가 잰다 — 다음 세션이 주석에서 옮긴다. Docker 데몬이 꺼져 있어 로컬 이미지 빌드·`compose up`은 하지 않았다.
  protectai·PG2의 밝히지 않은 학습 셋 오염은 뺄 수 없다. 실제 트래픽의 오탐은 관측 기간(22단계 PoC)에 `gateway_guard_verdicts_total`로 본다.
- **x86(CI `detect` 워크플로, 커밋 `4c03c2c`, 2026-11-03 — 2026-11-10 세션이 check-runs 주석에서 옮김)**: 작업 다섯(test 3.12·3.14·docker·image·detect) 모두 성공. 러너 AMD EPYC 9V74·4 vCPU.
  `horizon-guard-base-int8` HTTP p50 / p95 ms — 스레드 4: 32토큰 45.5 / 49.2 · 64토큰 81.8 / 83.7 · 128토큰 151.4 / 153.0 · 256토큰 306.4 / 311.5 · 510토큰(창 하나) 657.8 / **670.5**; 스레드 2: 46.4 / 47.1 · 81.8 / 82.6 · 154.8 / 156.3 · 311.9 / 315.9 · 665.0 / 670.3
  (스레드 2와 4가 같다 — M2의 p50 0.56~0.59초와 같은 자릿수). 점수는 M2와 같다: dev 깨끗한 부분집합 한국어 recall@FPR 1% **1,039/1,361 = 76.3%**, dev 전체 정상 오탐 1% 문턱 **0.93577**(M2 0.9358)에서 1,501/2,630·오탐 28/2,862, 한국어만 문턱이면 892/1,592 = 56.0%.
  이미지 실제 기동: NER + 분류기를 함께 실은 사이드카 메모리 **1.854GiB**(상한 3GiB, OOM 없음), `/health` 두 작업·`/v1/guard` block 응답 확인.
  2026-11-10 CI(커밋 `c87db8d`, Intel Xeon Platinum 8370C 러너): 510토큰 p95 601.2 / 652.7ms(스레드 4 / 2), 점수 같음(76.3%·문턱 0.93577), 이미지 메모리 1.871GiB — 같은 자릿수다.
  2026-11-10 CI(커밋 `30700da`, AMD EPYC 9V74 러너): 510토큰 p95 669.9 / 704.6ms(스레드 2 / 4), 점수 같음(1,039/1,361·문턱 0.93577), 이미지 메모리 1.891GiB.
- **재검증**(울트라코드 워크플로, 에이전트 15 — 고친 뒤 5관점: 사이드카·게이트웨이 수정 재현, 문서 숫자, 배포·CI, 우회 찾기, medium 이상 반박 검증 1): 지적 34건 → medium 이상 10건 중 **9건 재현**,
  1건 반박(이미 고친 system 메시지 전송), low 24건. 고친 것 — 상한을 넘었다고 요청 전체를 413으로 거절하면 그 글이 캐시에 들지 못해 **턴의 나머지 단계가 계속 413**이었다 → 새 글부터 비용 상한까지 재고 캐시,
  못 잰 수는 `/v1/guard` 응답의 `unscored`(block이면 막음, observe는 `guard_unscored`·지표 reason `unscored`), 비용은 창마다 (창 길이 + 특수 토큰 + 고정 16)이라 짧은 글 1,024개가 토큰 상한 안에서
  11초를 쓰던 것도 묶인다. Anthropic `document`(내용 원본·title·context)·`search_result`·`tool_result` 안의 문서는 **PII 가림도 하지 않고 원문 그대로** 나가고 가드레일도 못 봤다 → 어댑터에서 읽는다
  (Responses의 셸·패치·사용자 정의 도구 출력은 스트리밍 복원 경로까지 봐야 해 이번에는 api-compat '보지 않는다'에 적었다). 빈 user 메시지를 덧붙이면 판정할 글이 이력으로 밀려났다 → 이번 턴은 글이 든
  마지막 user 메시지부터. 마지막 user 뒤에 놓인 system·developer 메시지가 웹훅으로 갔다 → user 메시지 안의 문서만. 전각 '［SEP］'가 DeBERTa에서 특수 토큰이 됐다 → [UNK] 밖의 특수 토큰 id는 모두 뺀다.
  깊게 중첩된 JSON(요청·웹훅 응답)이 500이었다 → 400·`bad_response`. 같은 호스트 리다이렉트에서 토큰이 빠져 승인 저장소가 401일 수 있었다 → 같은 호스트에만 옮긴다. 문턱 없는 모델은 기동 거부,
  k8s `gateway.toml`의 `guard` 줄이 환경변수를 덮었다 → 주석으로, CI 이미지 확인은 스왑 없이 3GiB·OOM 확인·메모리 주석, 문서 숫자·표현(견본 기본 꺼짐, 오탐 1%의 뜻, 비용 상한, 지표 표) 정리.
  남긴 것: 혼자서 상한을 넘는 긴 글은 판정하지 않는다(상한·기한을 함께 올리면 잰다), Responses 셸·패치·사용자 정의 도구 출력은 가리지도 판정하지도 않는다(api-compat에 적음).
  테스트는 게이트웨이 가드레일 50·사이드카 23, 전체 `pytest` 887로 늘었다.
- **이후(2026-11-03 사용자 결정)**: "관측전용으로 안하고 자체튜닝으로 가자" — 이 분류기를 관측 전용으로 두지 않고 한국어 데이터로 이어 학습해 차단에 쓸 수 있게 한다. 결정 표 6번을 바꾸고 PLAN 18-1단계(D-128)로 한다. 이 결정의 판정(G3 미달 → 관측 전용 권고)은 지금 모델에 대한 것이고 그대로 둔다.

## D-128. 인젝션 분류기 한국어 자체 파인튜닝 — 학습 데이터·학습·게이트 사전 등록 (2026-11-04, PLAN 18-1단계)

### 1. 근거

- D-127 §6: 채택 분류기 `horizon-guard-base-int8`은 운영 문턱(0.9358)에서 봉인 홀드아웃 한국어 공격 61.7%를 잡고 한국어 정상 1.7%를 잘못 의심하며, D-054 양성대조 '출력 복사 유도'에 8.9%가 뒤집혀(기준 5%)
  관측 전용이 됐다. 사용자 결정(2026-11-03) "관측전용으로 안하고 자체튜닝으로 가자" — 결정 표 6번을 '공개 분류기를 한국어 데이터로 이어 학습한다'로 바꿨다. 처음부터 학습(사전학습)은 하지 않는다.
- 기준 모델 카드·학습 로그(2026-11-04 HF에서 확인, `Horizon-Labs/prompt-injection-guard-base` @8c321b08): mmBERT-base, 약 28만 행(양성 43%)으로 2 epoch, max_len 1,024, AdamW lr 3e-5(small 5e-5)·
  cosine·warmup 6%·wd 0.01·bf16, v2.2는 교사 증류(가중 0.5). 한국어는 합성 30개 언어 중 하나라 적다. 배포한 INT8은 **Gather(임베딩)만** 양자화한 것이다(`onnx/quantization_check.json`: MatMul까지 INT8이면
  fp32와 판정 일치율 0.96 → 'gather_only' 0.9975 채택). 학습·내보내기 코드(`code/train/`)가 Apache-2.0으로 공개돼 같은 방식으로 내보낼 수 있다.
- 한국어 공격의 새 공개 출처 조사(HF API 검색 질의 약 30개, 2026-11-04): 상업 이용·변형이 되는 **새** 한국어 공격 셋은 없다 — `Necent/llm-jailbreak-prompt-injection-dataset`(MIT, 승인 게이트, 1M+ 다국어
  번역·원출처 불명), `prismdata/guardrail-ko-11class-dataset`(GPL-3.0), `MarkrAI/ko-jailbreak`(D-123 제외 사유 그대로), XL-SafetyBench(유해 요청 — 인젝션 아님), `Gyr0ghost/promptwall-injection-dataset`(MIT, 500행 중
  한국어 공격 4). 평가셋이 표본만 쓴 출처의 남은 행: guardrail4agent S3 약 940·S5 약 270(한국어, LLM 합성)·safe 약 2,180, service_query_gating 약 3,200(정상), KoreanGuardrail 벤치마크 5,555행(씨앗 505가 전부
  dev·홀드아웃에 있다 — 그룹 규칙상 학습 쪽 씨앗의 변형만 쓸 수 있다). 다양한 한국어 직접·난독화 공격은 dev에만 있다 → PLAN 18-1의 '모자라면' 조항대로 **dev를 그룹째 나눈다**.
- 학습 환경: 맥북 M2 8GB(이 세션 시작 때 압축 메모리 3.4GiB 사용 중). 사용자가 학원 PC 사양을 주지 않았다 — 맥북에서 돌아가는 설정으로 시작하고 base 학습 명령은 다른 기계용으로 준다(PLAN 사용자 할 일).

### 2. 결정

1. **학습 데이터** `eval/injection/train/`(`build.py`·`train.jsonl`·`val.jsonl`·`SOURCES.md`·`benign_ko_train.jsonl`) — 평가셋 빌더의 받기·정규화·변형 함수를 그대로 쓴다. 난수 없음.
   - **평가 그룹·학습 그룹**: dev의 그룹마다 SHA-256(`"d128\x1f" + group`) 첫 바이트 < 128이면 **dev-train**(학습), 아니면 **dev-eval**(문턱·모델 고르기). 홀드아웃은 그대로 봉인(두 번째 개봉은 §2-4).
     학습 그룹 = dev-train 그룹 ∪ 공개 셋의 새 그룹. 평가 그룹 = dev-eval 그룹 ∪ 홀드아웃 그룹. **학습 행은 평가 그룹과 그룹을 공유하지 않고, 정규화 문장(공백 접기)이 평가셋(dev 전체·홀드아웃)의 어느 행과도
     같지 않다**(다중 턴은 턴마다). 테스트가 지킨다(T1).
   - 출처(표는 §6에 행수와 함께): dev-train 전부(모든 언어·라벨, 다중 턴은 뺀다 — 턴마다 라벨이 없다) · guardrail4agent S3·S5·safe의 남은 행 · service_query_gating 남은 행(표본) · KoreanGuardrail 벤치마크 중
     dev-train 씨앗의 변형(공격·**정상 난독화** — 정상 씨앗의 난독화 행은 평가셋이 쓰지 않았다) · gandalf 남은 행 표본 · 기준 모델이 학습한 영어 공개 셋 표본(`neuralchemy/Prompt-injection-dataset` core train Apache-2.0,
     `S-Labs/prompt-injection-dataset` train MIT, `yanismiraoui/prompt_injections` Apache-2.0 — 원래 실력을 지키는 되풀이 데이터) · promptwall(MIT) · 에이전트가 쓴 한국어 정상·하드 네거티브(`benign_ko_train.jsonl`,
     D-123 규칙 — 정상 문장만 쓴다). 라이선스 표·고지는 `eval/injection/train/SOURCES.md`.
   - **결정적 변형**: 공격(direct·indirect·role_spoof)의 절반(id 해시)에 변형 하나 — 평가셋의 `transform` 5종(synonym·spacing·fullwidth·zero_width·base64)에 **jamo**(음절을 호환 자모로 분해)·**chosung**(초성만)을 더한 7종,
     한국어가 아니면 jamo·chosung 대신 zero_width. 정상의 1/8에도 spacing·fullwidth·zero_width·jamo 가운데 하나를 씌운다(난독화 자체가 공격 신호가 되지 않게). 이미 난독화된 행(encoding)은 다시 씌우지 않는다.
   - **판정 조작 꼬리** 12종(한국어 6·영어 6, 앞에 붙는 꼴 2 포함 — 가짜 분류 JSON·'검토 완료·승인'·'교육용 예문'·'필터 끄기'·상태줄·티켓 메모): 공격의 1/4에 씌워 label 1, 정상의 1/12에 씌워 label 0.
     **D-054의 6문구는 학습·검증에 없다**(T2) — 그 문구는 양성대조(G3)로만 남긴다.
   - **학습용 검증 분할**: 학습 그룹의 SHA-256(`"val\x1f" + group`) 첫 바이트 < 26(약 10%)이면 `val.jsonl`. epoch 선택에만 쓴다.
   - 지키는 것: 공격을 LLM으로 만들거나 번역하지 않는다(에이전트는 정상 문장만), 외부 공급자에 보내지 않는다, 원문을 출력하지 않는다(요약은 개수), 데이터 파일 합계 8MB 이하.
2. **학습** `detect/train.py`(가상환경 `.venv-train`, `detect/requirements-train.txt`에 정확히 고정 — torch 2.15.0·transformers 5.22.1·onnxruntime 1.31.1·onnx·onnxscript·safetensors·tokenizers 0.23.3·numpy 2.5.4).
   - 기준 모델 파일은 `models.json`의 `horizon-guard-base-src`(`model.safetensors` SHA-256 d0c0f899f118…)·`horizon-guard-small-src`(a23196c117ba…) — `python -m detect.fetch`로 받아 해시를 맞춘다(제작자 SHA256SUMS와 같다).
   - **기본 설정(사전 등록)**: 시드 20261104 · AdamW(β 0.9/0.98, eps 1e-6, wd 0.01 — bias·norm 제외) · cosine + warmup 6% · grad clip 1.0 · 학습률 base 2e-5·small 3e-5 · 유효 배치 32(장치에 맞춰 배치 × 누적) ·
     길이 512(맥북은 256) · 3 epoch · **토큰 임베딩 동결**(base 197M — 어휘 지식 보존·메모리 절반; GPU에서는 `--train-embeddings`로 풀 수 있다) · 손실 교차 엔트로피. epoch마다 val의 recall@FPR≤1%(동률이면 AUC)로
     가장 좋은 epoch의 가중치를 남긴다. 장치 자동(cuda는 bf16 autocast, mps·cpu는 fp32; MPS는 `reference_compile` 끔).
   - 결과물: safetensors + 토크나이저 → ONNX(opset 17, `dynamo=False`, 제작자 `export_onnx.py`와 같은 입력·출력 이름) → INT8(**Gather만**, 제작자와 같은 설정; fp32와 양성 확률 차·판정 일치율을 잰다) →
     `manifest.json`(학습 설정·데이터 SHA-256·코드 커밋·결과 파일 SHA-256)·모델 카드 `README.md`. 명령 하나: `python -m detect.train --base horizon-guard-base-src --out models/<이름>`.
   - 재현 기준: 같은 명령·시드·데이터·장치면 같은 점수(부동소수 차 안), 다른 장치면 dev-eval 재현율·오탐률 ±1%p 안을 재현으로 본다.
3. **평가** `detect/evaluate_injection.py --exclude-train`(`models.json`에 `trained`가 있는 모델은 자동): dev에서 학습·검증 그룹을 빼고(**dev-eval**) 잰다. **운영 문턱 = dev-eval 전체 언어 정상셋 오탐 1%**(D-127과 같은 정의,
   셋만 dev-eval). 양성대조는 dev-eval 공격 중 문턱을 넘은 것에 D-054 6문구. dev-eval 표(언어·유형·출처별)와 '학습에 전혀 안 쓴 출처만' 숫자(ctf-satml24 다중 턴 등)를 함께 낸다. 깨끗한 부분집합(D-127)은 이제 뜻이 약하다 —
   우리도 그 출처의 dev-train 절반으로 학습한다 — 참고로만 낸다.
   - **모델 고르기(홀드아웃 전)**: 학습한 후보(base·small, 설정 변형) 가운데 dev-eval 운영 문턱의 **한국어 재현율**이 가장 높은 것. 2%p 이내면 작은 쪽(지연·메모리). D-127 채택 모델(학습 전)도 같은 dev-eval로 다시 재서 비교한다.
4. **게이트(사전 등록 — 운영 문턱, 봉인 홀드아웃을 이 결정에서 한 번 연다 = 전체 두 번째 개봉, 측정한 후보 모두 같은 실행)**:
   ① 홀드아웃 한국어 재현율 ≥ 75% ② 홀드아웃 한국어 정상 오탐 ≤ 1.5% ③ 홀드아웃 영어 재현율 ≥ 52.1%(D-127 base 55.1% − 3%p) ④ D-054 6문구 각각 뒤집힘 ≤ 5%(dev-eval 기저).
   넷 다 넘으면 채택 — 사이드카 기본 분류기를 새 모델로, 문서의 '관측 전용'을 '차단에 써도 된다(관측 기간 뒤)'로. 하나라도 못 넘으면 수치를 적고 관측 전용 유지, 다음 손잡이(데이터·크기·길이)를 적는다.
   결과를 보고 문턱·후보를 바꾸지 않는다(D-123 §2-3). 게이트가 아닌 보고: 전체 한국어 정상셋으로 오탐 1%를 맞춘 재현율, 유형·출처별 표, M2 지연(`detect.bench`)·메모리.
5. **배포**: 모델 파일은 사용자의 HF 저장소에(사용자 몫 — 쓰기 토큰). 올리기 전에는 `models.json` 항목에 `"published": false`를 두고 `revision`은 비워 둔다 — 이미지 `ARG INJECTION_MODEL`·CI·사이드카 테스트의 채택 이름은
   **올라간 뒤(리비전·해시 확인 뒤)** 바꾼다(그 전에는 D-127 모델이 기본). 라이선스: 기준 모델 Apache-2.0(NOTICE 계승)과 학습 데이터 출처 고지(CC BY 4.0·MIT·Apache-2.0·BSD)를 모델 카드와 train/SOURCES.md에.
6. **학습 환경**: 맥북에서 small(141M)부터, base는 임베딩 동결 + 작은 배치(누적)로 시도 — 스왑이 심하면 멈추고 학원 PC(NVIDIA 8GB+)·클라우드 GPU용 명령을 준다. 어느 쪽이든 같은 스크립트·시드.

### 3. 버린 대안

- **한국어 공격을 LLM으로 만들거나 영어 공격을 번역**: PLAN·D-123 금지 — 측정 대상과 같은 편향을 심는다. 공격은 공개 셋 + 결정적 변형 + 꼬리만.
- **행 단위 dev 분할**: 같은 원문의 말투·변형이 학습과 평가에 갈린다 — 그룹째.
- **dev 전부로 학습**: 문턱을 고를 셋이 없어진다(홀드아웃으로 고르면 게이트가 무의미).
- **평가셋을 다시 만들어 train·dev·holdout 3분할**: dev·홀드아웃 해시가 바뀌고 D-123·D-127 숫자와의 비교가 끊긴다. 홀드아웃은 그대로 두고 dev만 나눈다.
- **전체 가중치 학습(임베딩 포함)**: 메모리 약 2배(Adam 상태 3.2GB 더)·256k 어휘의 희소 갱신으로 한국어 밖 토큰 분포가 흔들린다. GPU에서 선택지로만 둔다.
- **LoRA·어댑터**: 새 의존성(peft)과 병합 단계, ONNX 내보내기 경로가 늘어난다. 임베딩 동결 전체 미세조정이 더 단순하고 메모리도 맞는다.
- **전부 INT8 양자화(MatMul 포함)**: 제작자 측정 판정 일치율 0.96 — 운영 문턱 근처 점수가 흔들린다. 임베딩만(제작자와 같은 설정, D-127이 잰 지연과 같은 프로파일).
- **증류(kakao kanana-safeguard 2.1b 교사)**: 교사 추론 비용·라이선스(비상업 조항 확인 필요)·'처음부터'에 가깝다 — 조건부로 남긴다.
- **승인 게이트 셋(Necent) 쓰기**: 사용자가 약관에 동의해야 받고 원출처·번역 품질이 불명 — 이번에는 빼고 §6에 후보로 적는다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| T1 | 학습·검증 그룹 ∩ (dev-eval ∪ 홀드아웃) 그룹 = ∅, 정규화 문장 겹침 0(다중 턴은 턴마다) | `tests/test_d128_train.py` |
| T2 | D-054 6문구가 학습·검증 텍스트에 없다, 꼬리 12종이 D-054 문구와 다르다 | 같은 파일 |
| T3 | 스키마(E1 규칙)·`train.jsonl`·`val.jsonl` SHA-256 고정·한국어 공격 1,000 이상·정상 중 하드 네거티브 20% 이상·합계 8MB 이하 | 같은 파일 |
| T4 | `evaluate_injection --exclude-train`이 dev에서 학습·검증 그룹을 뺀다(가짜 분류기), `trained` 모델은 자동 | 같은 파일 |
| T5 | 변형 jamo·chosung·꼬리가 결정적이고 빈 결과·같은 꼴을 버린다, 정상 꼬리는 label 0 | 같은 파일 |
| T6 | `models.json` 기준 모델 항목의 리비전·SHA-256이 제작자 SHA256SUMS와 같다, 학습 산출 항목(있으면)은 `trained`·`threshold`·파일 해시 | 같은 파일(갱신: `test_d127_guard.py` r9) |
| T7 | 학습 스크립트: 아주 작은 데이터·epoch 1로 끝까지(저장·ONNX·INT8·manifest) — torch가 있는 환경에서만(없으면 skip) | `detect/tests` |
| T8 | 게이트 수치 G①~④·홀드아웃 2회차·학습 설정·데이터 SHA-256이 §6에 | 이 결정 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy`(gateway·detect) 통과 | |

### 5. 한계

- 공개 한국어 공격은 LLM 합성 출처(guardrail4agent·KoreanGuardrail 절반)가 많고, dev-train과 홀드아웃이 같은 출처 분포다 — 홀드아웃 숫자는 '같은 종류의 공격'에 대한 것이다. 실제 트래픽의 새 꼴은 관측 기간에 본다.
- dev-eval이 절반이라 운영 문턱의 허용 오탐이 14건 안팎(정상 약 1,430) — 문턱의 분산이 D-127보다 크다. 홀드아웃 게이트 ②(470건 중 7건)도 거칠다.
- 변형·꼬리는 우리가 아는 꼴만이다. 적응형 공격자는 다른 꼴을 쓴다 — 가드레일은 한 겹이다(D-127 §5 그대로).
- 맥북 학습은 길이 256 — 긴 문서 끝의 간접 지시는 사이드카 창(512)의 뒷부분을 학습하지 않는다(GPU에서는 512).
- 홀드아웃은 이 결정으로 두 번 열렸다 — 다음 분류기 변경에는 새 홀드아웃(또는 새로 받은 공개 셋)이 필요하다.
- 에이전트가 쓴 정상 문장은 우리 시각의 문장이다(D-123 §5).

### 6. 결과 (2026-11-04)

- **판정 — 넷 다 통과, 채택**(`injection-ko-small-int8`: mmBERT-small을 Horizon guard small에서 이어 학습, INT8 268MB(255.97MiB), 운영 문턱 **0.9833213367983539**): 봉인 홀드아웃(두 번째 개봉, 기준 모델과 같은 실행)에서
  **G① 한국어 재현율 425/436 = 97.5%**(≥ 75%, 기준 모델 61.7%) · **G② 한국어 정상 오탐 7/470 = 1.49%**(≤ 1.5% — **경계**, 기준 모델 1.70%; dev-eval은 0.4%) · **G③ 영어 재현율 213/227 = 93.8%**(≥ 52.1%, 기준 모델 55.1%) ·
  **G④ D-054 6문구 뒤집힘(dev-eval 기저 1,199)**: 직접 지시 0 · 역할 재지정 0 · 출력 복사 유도 2(0.2%) · 권한 사칭 8(0.7%) · 울타리 탈출 0 · 규칙 재정의 1(0.1%) — 모두 ≤ 5%(기준 모델은 8.9%).
  등록대로 사이드카 기본 분류기를 이 모델로 바꾸고 문서의 '관측 전용'을 '차단에 써도 된다(관측 기간 뒤)'로 고친다 — **단 기본값 교체는 사용자가 HF 저장소에 올려 `revision`을 채운 뒤**(§2-5, 지금은 `published: false`·이미지·CI·사이드카 테스트는 D-127 모델 그대로).
  base(308M)는 이 기계에서 학습하지 못했다(아래 '학습 환경') — 학원 PC·GPU에서 같은 명령으로 돌려 비교하는 것은 남은 일이다(small이 게이트를 넘었으므로 base는 '더 나은가'의 문제다).
- **주의(게이트 밖)**: 홀드아웃 **영어** 정상 오탐 6/114 = 5.3%(NotInject 4/75 — 트리거 단어가 든 영어 정상, 기준 모델 0.9%), 전체 정상 오탐 15/649 = 2.3%(dev-eval에서 고른 1% 문턱이 홀드아웃에선 2.3% — 기준 모델도 1.4%였다).
  영어 트리거 문장이 많은 트래픽이면 문턱을 올리거나(`DETECT_GUARD_THRESHOLD`) 관측 기간을 두고 본다. 점수가 1 근처에 몰린다(문턱 0.9833, 0.5% 문턱은 0.99998) — INT8 차이(최대 0.012)가 문턱 근처 몇 건을 바꿀 수 있다.

- **학습 데이터**(`eval/injection/train/`, 빌드 2026-11-04): dev 5,492행을 그룹 해시로 나눠 학습 쪽 2,634행·dev-eval 2,858행(공격 1,369 — 한국어 865·영어 374·그 밖 130, 정상 1,489 — 한국어 1,126·영어 232·그 밖 131).
  학습 쪽에서 빠진 dev 행은 다중 턴 42·같은 문장 8뿐이다. 공개 셋의 남은 행은 평가셋과 겹친 것(guardrail4agent 350·gandalf 121·S-Labs 1·promptwall 1)을 뺐다.
  **학습 13,932행 = train 12,467 + val 1,465(4.56MiB)** — 공격 8,499(한국어 3,484)·정상 5,433(한국어 3,594, 하드 네거티브 37%), 변형 3,775·꼬리 1,708. 출처별(변형·꼬리 포함): guardrail4agent 2,363/949, S-Labs 1,064/738,
  neuralchemy 1,229/600, KoreanGuardrail 1,058/524, promptwall 728/76, yanismiraoui 537/0, gandalf 418/0, service_query_gating 0/613, JHC56 144/368, korean_guardrail_test 205/124, agent_ko 0/324, **agent_ko_train 0/646**(에이전트 4가 쓴 600줄 중
  검증자 둘이 56줄을 뺌 — 보안 관점 1('이전 안내는 잊고'가 직접 지시로 읽힘)·품질 관점 55(목록 밖 트리거 어휘만 든 hard_negative·어색한 혼용) → 543행 + 변형·꼬리), 그 밖 영어 셋(BIPIA·PurpleLlama·InjecAgent·NotInject·deepset·drakkeng·corpus).
  `train.jsonl` SHA-256 **fdcb36ab5f9eecc4938fd7e34ad9bb06f33f87d8fd684f5011f4590d5a6b12b4** · `val.jsonl` **c24c58105a3ab4c233cb0556b889f6cdf95c7dc3d650c78a32e431075d796bed**(테스트 T3가 지킨다).
- **학습 환경(맥북 M2 8GB)**: 세션 시작 때 다른 앱이 이미 압축 메모리 3.4GiB를 쓰고 있었고, small을 MPS로 올리자(배치 16×2, 다음에 8×4) 스왑이 8.9GB까지 차서 10분 동안 한 걸음도 나가지 못했다(두 번, 강제 종료).
  MPS 메모리는 고정(wired)이라 다른 앱을 밀어낸다 — **CPU(fp32, 스레드 4)로 돌렸다**(`--device cpu`). `detect/train.py`의 연기 시험(48행·1 epoch·CPU, `detect/tests` T7)은 25초에 끝났고 INT8(Gather)은 fp32와 양성 확률 차 최대 0.0034·0.5 판정 일치 1.0이었다.
  base(308M)는 이 기계에서 돌리지 않았다 — 학원 PC·GPU 명령은 PLAN 사용자 할 일에.
- **small 첫 실행(같은 설정, 누적 흘려보내기 수정 전 코드 — 재현성 참고)**: CPU 20분(1,170 step, 약 1초/step), val recall@FPR≤1% epoch 1·2·3 = 95.4%·96.1%·96.4%(AUC 0.997~0.998), INT8(Gather) fp32 대비 양성 확률 차 최대 0.028·0.5 판정 일치 1.0.
  dev-eval 전체 정상 오탐 1% 문턱 **0.99715**(점수가 1 근처에 몰린다)에서 한국어 재현율 **704/865 = 81.4%**(기준선 55.0%)·한국어 정상 오탐 8/1,126 = 0.7%, 영어 325/374 = 86.9%·오탐 3/232 = 1.3%, 그 밖 117/130·3/131.
  유형별(0.5 동작점) 한국어 직접 87.2%·간접 100%·역할 위조 70.6%·난독화 87.4%, 영어 간접(도구 결과) 84.8%(기준 모델 dev 22.7%). **D-054 양성대조(기저 1,146)**: 직접 지시 0·역할 재지정 0·출력 복사 유도 10(0.9%)·권한 사칭 7(0.6%)·울타리 탈출 0·규칙 재정의 4(0.3%) — 모두 5% 아래.
  이 모델은 채택 후보가 아니다(커밋 전 코드) — 최종 실행은 아래.
- **최종 실행**(`python -m detect.train --base horizon-guard-small-src --out models/injection-ko-small-int8 --max-len 256 --batch 8 --accum 4 --device cpu`, 그 밖은 기본 — 시드 20261104·lr 3e-5·3 epoch·임베딩 동결·wd 0.01·warmup 6%):
  CPU 25분(1,170 step), val recall@FPR≤1% epoch 1·2·3 = 95.4%·95.7%·96.1%(AUC 0.997, 한국어 94.9→95.4%) → epoch 3 저장. 첫 실행과 epoch 1이 같은 값(95.4%)이고 epoch 3은 96.4 대 96.1%·dev-eval 한국어 81.4 대 85.9% — 같은 설정의 두 실행 차가 이 정도다. 다만 두 실행은 코드가 달랐다(누적 흘려보내기 수정) — **§2-2의 재현 기준(같은 명령·시드·데이터·장치면 같은 점수, 다른 장치면 ±1%p)은 같은 코드 재실행으로 확인하지 못했다**(아래 '못 한 것').
  INT8(Gather) fp32 대비 양성 확률 차 최대 0.0124·평균 0.00015·0.5 판정 일치 1.0(검증 200문장). 파일 SHA-256: `onnx/model_quantized.onnx` **7d87c2ea04987bfd2ff27115548828c58c3cc725eb598b831a703a19aae9b888**, `model.safetensors` 1928d6a02fee…, `tokenizer.json` d1a272a3b438…(원본과의 차이는 학습 때 건 자르기 길이 1024 → 256뿐이었다 — 2026-11-10에 기준 모델 파일 47834a7dbbb0…으로 되돌렸다. 사이드카는 자르기를 끄고 쓰므로 점수는 같다), `config.json` 877ae4f8cd2b… — `models.json`·`manifest.json`에 전부.
- **dev-eval(2,858행, 운영 문턱 0.9833 = dev-eval 전체 언어 정상 오탐 1% — 14/1,489)**: 재현율 1,199/1,369 = 87.6%, 한국어 **743/865 = 85.9%**·정상 오탐 4/1,126 = 0.4%, 영어 336/374 = 89.8%·오탐 6/232 = 2.6%, 그 밖 120/130·4/131.
  유형별 한국어: 직접 84.2%·간접(문서 속) 100%·역할 위조 64.7%(11/17)·난독화 86.1% / 영어: 직접 94.2%·간접(도구 결과) **84.1%**(기준 모델 dev 22.7%)·다중 턴 85.0%. 0.5 동작점이면 한국어 89.6%·오탐 0.9%, 영어 92.2%·오탐 6.0%.
  출처별(dev-eval): KoreanGuardrail 94.1%·korean_guardrail_test 90.4%·guardrail4agent 99.4%·**JHC56 66.0%**(deepset 한국어 말투 — 가장 어렵다, 정상 오탐 0/424)·corpus 61.5%·corpus_xform 73.1%·BIPIA 82.3%·InjecAgent 78.3%·PurpleLlama 88.4%·deepset 87.6%·drakkeng 100%(정상 오탐 7/66 = 10.6%)·gandalf 100%·ctf 85.0%,
  정상 오탐 NotInject 2/120·agent_ko 0/309·service_query_gating 0/108·all100 1/35. **학습에 전혀 안 쓴 출처**(ctf-satml24 다중 턴만): 17/20 = 85.0%. 깨끗한 부분집합(D-127 정의)은 한국어 92.7%(직접) — 참고.
- **홀드아웃(1,379행, 두 번째 개봉 — D-127이 첫 번째)**, 운영 문턱 그대로:

  | 모델(문턱) | 한국어 재현율 | 한국어 정상 오탐 | 영어 재현율 | 영어 정상 오탐 | 전체 재현율 | 전체 오탐 |
  |---|---|---|---|---|---|---|
  | **injection-ko-small-int8**(0.9833) | **425/436 = 97.5%** | 7/470 = 1.5% | **213/227 = 93.8%** | 6/114 = 5.3% | 705/730 = 96.6% | 15/649 = 2.3% |
  | horizon-guard-base-int8(0.9358, D-127 채택) | 269/436 = 61.7% | 8/470 = 1.7% | 125/227 = 55.1% | 1/114 = 0.9% | 450/730 = 61.6% | 9/649 = 1.4% |

  유형별(새 모델 / 기준 모델): 한국어 직접 96.7 / 65.0%, 간접 100 / 100%, 역할 위조 100(9/9) / 55.6%, 난독화 97.8 / 52.2%; 영어 직접 97.0 / 68.0%, 간접(도구 결과) 87.8 / 28.0%, 난독화 100 / 86.7%, 다중 턴 93.3 / 53.3%.
  출처별(새 모델): KoreanGuardrail 189/190·JHC56 41/42·korean_guardrail_test 62/67·corpus_xform 58/62·guardrail4agent 77/77·BIPIA 39/47·InjecAgent 11/13·PurpleLlama 46/48·deepset 55/56·drakkeng 59/59·gandalf 40/40·ctf 14/15; 정상 오탐 NotInject 4/75·drakkeng 2/25·deepset 2/76·agent_ko 2/138·all100 2/12·JHC56 1/126·KoreanGuardrail 1/39·korean_guardrail_test 1/54·guardrail4agent 0/40·service_query_gating 0/64.
  홀드아웃 숫자가 dev-eval보다 높다(97.5 대 85.9%). 출처 구성(한국어 공격 중 KoreanGuardrail·guardrail4agent가 홀드아웃 57.6%·dev-eval 52.0%)은 그 11.6%p 가운데 **약 1.6%p만** 설명한다 — dev-eval의 출처별 재현율을 홀드아웃 구성에 곱하면 약 87.5%다.
  나머지는 같은 출처 안의 차이다: 어려운 출처(JHC56·corpus)가 홀드아웃에는 원문 그룹 20개(JHC56 6·corpus 14, 전체 217그룹)뿐이고 dev-eval은 47개(21·26, 전체 430그룹)라, 홀드아웃 숫자의 실효 표본은 행 수(436)보다 작다. 두 숫자를 같은 무게로 적는다(2026-11-10 리뷰로 고침 — 처음에는 출처 구성 때문이라고 적었다).
  홀드아웃 자체 정상셋으로 1%를 맞추면(게이트 아님): 전체 624/730 = 85.5%(문턱 0.99988), 한국어 395/436 = 90.6%(0.99843), 영어 191/227 = 84.1%(0.99993).
- **지연·메모리(M2, `detect.bench`, HTTP p50 / p95 ms)**: `injection-ko-small-int8` 스레드 4 — 32토큰 14.3 / **17.8**, 64토큰 24.1 / 30.1, 128토큰 45.3 / **47.4**, 256토큰 90.8 / 94.4, 510토큰(창 하나) 200.5 / **216.7**; 스레드 2 — 23.5 / 32.4 · 41.1 / 45.1 · 78.9 / 113.3 · 155.9 / 167.0 · 332.9 / 376.6.
  D-127의 base(641MB)는 스레드 4 p95 39~43 · 139~228 · 646~804ms였다 — 같은 창에서 약 3배 빠르다. 메모리는 따로 재지 않았다 — 구조·크기가 D-127의 small-int8(268MB → 분류기만 M2 물리 0.7~1.2GiB)과 같다. x86은 기본값 교체 뒤 CI `detect`가 잰다.
- **만든 것**: `eval/injection/train/build.py`(dev 그룹 절반 분할·공개 셋 남은 행·KoreanGuardrail 정상 난독화·되풀이 데이터 neuralchemy/S-Labs/yanismiraoui/promptwall·변형 7종·꼬리 12종·그룹 검증 분할, 캐시 받기 22초)·`split.py`(분할 규칙만 — httpx 없이)·
  `SOURCES.md`·`benign_ko_train.jsonl`(에이전트 4 + 검증자 8의 울트라코드 워크플로, 600 → 543) · `detect/train.py`(fit → 가장 좋은 epoch 저장 → ONNX opset 17 eager → INT8 Gather만 → quant_check → manifest.json·README.md 카드) · `detect/requirements-train.txt` ·
  `detect/evaluate_injection.py --exclude-train`(`trained` 모델은 자동, `excluded` 수를 요약에) · `models.json`에 `horizon-guard-base-src`·`-small-src`(제작자 SHA256SUMS와 같은 safetensors 핀)와 `injection-ko-small-int8`(`trained`·`published: false`·`revision ""`·threshold) ·
  문서(detect/README '이어 학습', CHANGELOG, PLAN 사용자 할 일의 학원 PC 명령).
- **테스트**: `tests/test_d128_train.py` T1~T6(그룹·문장 비겹침, D-054 문구 부재·꼬리 차이, 스키마·해시·수, dev-eval 제외, 변형·꼬리 결정성, 핀), `detect/tests` T7(학습 스크립트 끝까지 — torch 있을 때만), `test_d127_guard` r9·`test_d125_ner` N6 갱신. 전체 `pytest` **893**(이 단계 전 887)·`ruff`·`mypy` 통과.
- **계획과 다른 점**: base가 아니라 **small을 학습·채택**했다(맥북 메모리 — base는 학원 PC 몫으로 남김, small이 네 게이트를 넘어 채택 자체는 등록대로다). 한국어 공격의 새 공개 출처가 없어 **dev를 그룹째 절반으로 나눠** 학습 쪽을 썼다(PLAN의 '모자라면' 조항) —
  dev-eval은 2,858행으로 줄었고 dev-eval 숫자와 홀드아웃 숫자를 함께 적는다. 학습은 MPS가 아니라 CPU(길이 256). 학습 코드를 한 번 고쳐(epoch 끝의 남은 누적을 흘려보냄) 다시 학습했다 — 첫 실행은 참고로만. `--exclude-train`은 학습 쪽 그룹 전체를 뺀다(파일에 든 그룹만이 아니라).
- **리뷰 + 반박 검증(2026-11-10, 울트라코드 워크플로 — 에이전트 9: 검토 6관점 → medium 이상을 3묶음으로 반박 검증. D-129·D-130과 함께 돌렸다)**: 지적 78건 — medium 이상 25건 **전부 재현(반박 0)**,
  검증자가 다시 매긴 심각도는 high 1·medium 15·low 9, 검증하지 않은 low 53. 이 결정 몫(데이터 누수·학습 스크립트·평가·테스트/문서 4관점)에서 반영한 것:
  ① **HF에 올릴 폴더에 기준 모델의 LICENSE·NOTICE가 없었다**(카드는 'NOTICE를 계승한다'고 적었다) → `models.json`의 Horizon 네 항목에 두 파일을 해시와 함께 더했고, `train.py`가 결과 폴더에 복사하며 NOTICE에 '이어 학습으로 바꿨다'를 덧붙인다. 이미 만든 폴더도 고쳤다.
  ② **manifest·카드의 '코드 커밋'이 학습 코드가 없는 f60d5c7**이었다(커밋 전 작업 트리에서 학습) → manifest에 `dirty`와 학습을 정하는 스크립트 넷의 SHA-256을 남긴다. 이미 만든 산출물에는 '학습 코드·데이터는 7456056에 처음 커밋됐다, 학습 시점 파일과 같은지는 기록이 없다'를 사실대로 적었다.
  ③ **T2가 '출력 복사 유도' 문구에는 실패할 수 없었다**(포맷 전 템플릿의 `{{ }}`로 찾았다 — D-127에서 G3를 떨어뜨린 바로 그 문구) → 평가가 실제로 붙이는 글자로 찾는다. 다시 찾아 6문구 모두 0건.
  ④ 문서: 홀드아웃이 높은 이유(위 — 출처 구성은 1.6%p뿐), README 머리 문장(문턱은 dev-eval에서 고른 값 — 홀드아웃 오탐 2.3%, 1%로 맞추면 90.6·84.1%), '이어 학습 전 61.7%·8.9%'는 guard-base의 숫자(small의 학습 전 홀드아웃 값은 재지 않았다),
  '영어 트리거 문장 5.3%'의 분모는 영어 정상 전체, 255MB는 MiB(268MB), 설명서의 두 모델 서술(배포판에 든 것은 공개 모델·기록용), PLAN이 예고한 **홀드아웃 세 번째 개봉을 지움**(base는 dev-eval·양성대조로만 비교), 재현 기준을 결과를 본 뒤 좁혀 적은 문구를 지움.
  ⑤ low에서 반영: 올릴 `tokenizer.json`에 학습 길이 256이 박혀 있었다(→ 기준 모델 파일 그대로), `train_log.json`의 홈 폴더 절대 경로, Windows에서 manifest 키가 역슬래시가 되고 데이터 줄 끝이 바뀌던 것(`.gitattributes`), `--device cuda:0`·모르는 `--base`를 받던 것,
  손실 NaN·저장 없는 epoch·INT8 불일치에도 완성된 산출물처럼 남던 것, 양자화 확인 표본이 앞 200행(공격 88%)이던 것, T7이 누적·남은 누적 경로를 지나지 않던 것, T5가 꼬리·공격 변형 가지를 타지 않던 것, T6이 채택 모델의 문턱·해시를 고정하지 않던 것,
  `fetch`가 올리지 않은 모델에 빈 리비전 주소로 요청하던 것, 운영 문서의 '이미지에 들어 있다'(이어 학습 모델은 없다 — 마운트 방법을 적음), PLAN의 `hf repo create`(고정한 CLI에 없다)·비공개 저장소 안내, `SOURCES.md`의 NOTICE 전문·CC-BY 파생 행 표시.
  산출물 폴더를 고친 뒤 `onnx/model_quantized.onnx`·`model.safetensors`·`config.json` 해시는 그대로다(게이트 수치의 모델이 그대로다). `tests/test_d128_train.py` 8개·`detect/tests` T7(학습용 가상환경에서 통과).
- **못 한 것·남은 것**: base(308M) 이어 학습과 small 대 base 비교(학원 PC — PLAN 사용자 할 일의 명령, 결과 폴더를 가져오면 다음 세션이 **dev-eval·양성대조로** 잰다 — 홀드아웃은 다시 열지 않는다).
  **리뷰가 짚었지만 고칠 수 없어 한계로 남긴 것**: 재현 기준 미확인(같은 코드 재실행 1회가 필요하다 — 학원 PC에서 가능. 두 실행 차가 4.5%p라 §2-3의 '2%p 이내면 작은 쪽' 규칙으로 base와 small을 가르기 어렵다 — 시드 둘 이상이나 AUC로 본다),
  게이트 ②는 1건 차이 통과다(7/470, 허용 7.05건 — Wilson 95% 구간 약 0.7~3.0%로 기준 모델 8/470과 겹친다), 게이트 ④의 대조는 독립이 아니다(D-054 6문구 중 셋은 학습 꼬리와 같은 수법이고 문구만 다르다),
  기준 모델의 양성대조 8.9%는 dev 전체 기저(1,501건)라 새 모델의 dev-eval 기저(1,199건)와 다르다(§2-3이 말한 dev-eval 재측정을 하지 않았다), 변형을 씌운 정상 문장의 평가 행이 없다(난독화가 공격 신호가 되지 않았는지 재는 숫자가 없다),
  같은 틀에서 나온 형제 문장은 그룹이 달라 학습과 평가에 함께 있을 수 있다(그룹·정규화 문장의 완전 겹침만 0이다), T4는 `main()`의 배선을 소스 문자열로만 본다, T7은 torch가 있는 환경에서만 돈다(CI는 건너뛴다),
  §2-1 문구와 코드의 차이 둘(비한국어는 synonym도 zero_width로 돌린다, '평가셋과 비겹침'은 dev 전체가 아니라 dev-eval ∪ 홀드아웃 기준이다 — 학습에 dev의 학습 쪽이 그대로 들어 있다). HF 업로드(사용자)·`revision` 채우기·기본값 교체(Dockerfile `ARG INJECTION_MODEL`·CI `detect.yml`·`detect/tests` INJECTION·compose/k8s 주석)와
  그 뒤 x86 지연·이미지 메모리(CI). 홀드아웃은 두 번 열렸다 — 다음 분류기 변경은 새 홀드아웃이 필요하다. 영어 정상 오탐(홀드아웃 5.3%)은 관측 기간에 실제 트래픽으로 본다.
- **기준선(dev-eval, 학습 전 — 같은 자로 다시 잼)**: `horizon-guard-base-int8`은 운영 문턱 0.9358에서 한국어 재현율 **476/865 = 55.0%**(dev 전체는 57.0%)·한국어 정상 오탐 10/1,126 = 0.9%, 영어 189/374 = 50.5%,
  전체 오탐 11/1,489 = 0.7%. dev-eval 정상 오탐 1% 문턱(0.9088)으로 다시 고르면 782/1,369 = 57.1%. `horizon-guard-small-int8`(문턱 0.8163)은 한국어 392/865 = 45.3%·영어 209/374 = 55.9%.
  dev-eval은 dev보다 어렵다 — 쉬운 변형(corpus_xform·KoreanGuardrail 난독화) 가족이 학습 쪽에 많이 갔다.

## D-129. 보안 백서 + 법적 위치 메모(변호사 검토 전 초안) + PoC 키트 (2026-11-04, PLAN 19단계)

### 1. 근거

- 22단계 디자인 파트너 PoC에는 세 가지가 먼저 필요하다: 보안 담당자가 읽을 **백서**(데이터 흐름·저장하지 않는 것·키 취급·위협 모델·한계), 법무가 읽을 **법적 위치 메모**, 고객 샘플로 숫자를 뽑는 **PoC 리포트 도구**.
- 사실은 이미 README·`docs/operations.md`·`docs/configuration.md`·`docs/api-compat.md`·`SECURITY.md`·DECISIONS에 흩어져 있다 — 백서는 그것을 한 흐름으로 묶고 숫자는 측정한 결정만 인용한다.
- 부록 A 규제 행: 제28조의2 특례는 서비스 운영에 적용되지 않고, 매핑을 영속화하면 제28조의4 의무가 붙는다(반박 검증 안 함). 결정 표 8번: 대체값 키는 법률 검토 전까지 PIPA '추가정보'로 취급한다.

### 2. 결정

1. **`docs/security-whitepaper.md`**(한국어, 마크다운 — PDF·영어판은 만들지 않는다): ① 무엇을 하고 무엇이 아닌지 ② 데이터 흐름(클라이언트 → 인증 → 검사 체인(인젹션 룰 → PII → 가드레일 웹훅) → 상류, 응답·스트림 복원)
   ③ 저장하지 않는 것(요청 단위 메모리 볼트, 감사 줄의 크기·지문·개수만, 접근 로그 없음, URL은 키 이름만) ④ 대체값과 키(HMAC 결정적 대체값, 키 등급·보관·회전, 추가정보로 취급) ⑤ 위협 모델(자산·행위자·신뢰 경계·대응·범위 밖)
   ⑥ 탐지 범위와 숫자(종류 12 + 켜는 3, 인젹션 룰·분류기 — D-115·D-117·D-123·D-126·D-127·D-128의 측정값, 결정 번호 병기) ⑦ 배포 보안(비root·읽기 전용·경로·헤더 허용 목록·Secret) ⑧ 감사·관측 ⑨ 한계와 제보.
   새 주장은 쓰지 않는다 — 문장마다 근거가 되는 문서·결정이 있어야 한다.
2. **`docs/legal-position.md`**(2쪽 이내 — 9,000자 이하, 머리에 **'변호사 검토 전 초안 — 법적 자문이 아니다'**): 개인정보 보호법(2023-09-15 시행 개정 기준, 조문 번호는 변호사가 확인) ① 제2조 제1호의2 가명처리 정의와의 관계 — 같은 모양의 대체값은 가명처리의 한 꼴이되
   복원 매핑이 요청 동안 메모리에만 있고 고객 시스템에 남지 않는다 ② 제28조의2(통계·연구·공익적 기록보존 목적의 가명정보 특례)가 **서비스 운영에 적용되지 않는 이유** — 고객의 처리 목적은 업무 수행이고 원래 처리 근거(동의·계약 이행 등)가 그대로 필요하다,
   이 제품은 '동의 없이 처리할 근거'가 아니라 **처리위탁(제26조)·국외이전(제28조의8) 상황에서 최소 처리(제3조·제16조)와 안전성 확보조치(제29조)를 구현하는 기술적 조치**다 ③ 제28조의4 추가정보 — 대체값 키·볼트가 추가정보에 해당할 수 있으므로 분리 보관·접근 통제 — 우리 구현(요청 단위 메모리, 키는 Secret, 감사 줄에 없음)과 운영자가 할 일
   ④ 변호사 확인 항목 표(질문·우리 가정·근거). 결론을 단정하지 않는다("~로 볼 여지가 있다", "확인 필요").
3. **`scripts/poc_report.py`**: 고객 샘플 JSONL(`{"text": ...}` 한 줄 하나, 선택 `id`) → 마크다운 리포트(표준 출력 또는 `--out`). 게이트웨이를 띄우지 않고 프로세스 안에서 `gateway.detectors.patterns.find_all`(정규식 12종)과 `TokenVault`(대체값 발급·복원)를 그대로 쓴다 — 설치 직후 PoC 전에 돈다.
   표: ① 종류별 탐지 수(가림 / 감사만, 샘플 수·샘플당 평균) ② **오탐 후보** = 가리는 탐지의 값 **모양**(숫자→`#`, 영문→`x`, 한글→`ㅇ`, 그 밖 그대로)을 종류별로 빈도순 20개 — 검토자가 모양으로 오탐을 가려낸다(원문·가짜 값은 리포트에 없다) ③ **복원률** = 가짜 값으로 바꾼 텍스트를 그대로 되돌렸을 때 복원된 수 / 발급 수와 잔여(`residual`) —
   모델이 가짜 값을 그대로 돌려줄 때의 상한 ④ **지연** = 샘플마다 탐지+가림+복원 시간 p50·p95·최대(ms, 프로세스 안; 게이트웨이 경유 숫자는 D-122 인용) ⑤ 입력 요약(샘플 수·바이트·길이 분포). 옵션 `--kinds`(종류 제한)·`--detect-kinds`(감사만 종류)·`--out`·`--limit`. 이름·주소(NER)는 사이드카가 필요해 다루지 않는다(리포트에 그렇게 적는다).
4. 금지: 리포트·문서에 실제 개인정보·원문 발췌 없음(테스트가 합성 샘플의 원문 부재를 확인한다). 두 문서는 README(두 언어)에서 링크한다.

### 3. 버린 대안

- **영어 백서·PDF**: 디자인 파트너가 국내 기업이다(결정 표 5번). 수요가 생기면 번역한다. 설명서 PDF는 비전문가용이라 따로 있다.
- **poc_report가 게이트웨이를 띄워 HTTP로 재기**: 설치·키·상류 스텁이 필요해 PoC 전 '샘플만 주세요' 단계에 못 쓴다. 프로세스 안 숫자(탐지·복원·처리 시간)와 D-122 지연을 나눠 적는다.
- **오탐 후보를 LLM이 판정**: 고객 원문을 외부 공급자에 보낼 수 없다(공통 규칙). 모양 표로 사람이 본다.
- **법률 메모에서 결론 단정**: 변호사 검토 전이다 — 확인 항목으로 남긴다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| P1 | 두 문서가 있고 README 두 언어가 링크한다, 법률 메모는 9,000자 이하이고 '변호사 검토 전 초안' 표시가 머리에 있다, 두 문서에 합성 아닌 개인정보 꼴(주민번호·전화·이메일 정규식)이 없다 | `tests/test_d129_poc.py` |
| P2 | `poc_report.py`가 합성 샘플(`eval/pii/corpus.jsonl` 표본)로 리포트를 만들고, 리포트에 샘플 원문·발급한 가짜 값이 없다 | 같은 파일 |
| P3 | 리포트의 종류별 탐지 수 = `find_all`로 직접 센 수, 복원률 분모 = 발급 수, 빈 입력·`text` 없는 줄은 건너뛰고 수를 적는다 | 같은 파일 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 | |

### 5. 한계

- 법률 메모는 법적 자문이 아니고 변호사 검토 전이다(사용자 몫). 조문 번호·해석은 개정에 따라 바뀐다.
- 백서 숫자는 측정 시점(결정 번호)의 값이다 — 모델·룰을 바꾸면 결정과 함께 고친다.
- poc_report는 정규식 종류만 본다(이름·주소는 사이드카) — 실제 게이트웨이 경유 지연·스트리밍 복원은 재지 않는다.

### 6. 결과 (2026-11-04)

- **만든 것**: `docs/security-whitepaper.md`(9절, 14,072바이트 — 모든 숫자에 결정 번호), `docs/legal-position.md`(8,270바이트 ≤ 9,000자, 머리에 '변호사 검토 전 초안 — 법적 자문이 아니다', 쟁점 5 + 변호사 확인 항목 6 + 쓰는 말/쓰지 않는 말),
  `scripts/poc_report.py`(프로세스 안 `find_all` + `TokenVault` — 종류별 가림/감사만 수, 값 모양 빈도 20, 복원률·잔여·원문 일치, 처리 시간 p50·p95·최대, `--kinds`·`--detect-kinds`·`--limit`·`--out`), README 두 언어의 6절 링크, `tests/test_d129_poc.py` P1~P3.
- **합성 코퍼스로 돌린 리포트**(`eval/pii/corpus.jsonl` 2,400건, 0.5초): 발급 787·복원 787(100%)·잔여 0·원문 일치 2,400/2,400, 처리 시간 p50 0.02ms·p95 0.11ms·최대 0.6ms. 종류별 가림/감사만 — rrn 102/5·frn 103/7·passport 80/44·driver 100/0·card 102/136·phone 100/0·email 100/0·secret 100/0,
  감사만 종류 account 0/142·brn 0/100·crn 0/89·ipv4 0/111(코퍼스의 약한 꼴·감사만 종류가 그대로 감사만으로 잡힌다 — D-116·D-117). `hard.jsonl` 40건: 발급 19·복원 19·일치 40/40. 리포트에 원문·가짜 값이 없음을 P2가 300건 표본으로 확인했다.
- **계획과 다른 점**: 리포트의 지연은 게이트웨이 경유가 아니라 프로세스 안 처리 시간이고 경유 지연은 D-122를 인용한다(§3). '오탐 후보'는 LLM 판정이 아니라 값의 모양 표다. 영어판·PDF는 만들지 않았다.
- **못 한 것(사용자 몫)**: 변호사 검토 1회, 외부 1인 백서 리뷰 — PLAN 사용자 할 일. 백서 숫자는 D-128 기본값 교체(HF 업로드 뒤)·20단계 릴리스 서명이 끝나면 그 자리만 고친다.
- **리뷰 + 반박 검증(2026-11-10, D-128 §6의 워크플로)**: 이 결정 몫 medium 이상 10건 전부 재현 — 그중 **high 1: 백서 4·9절이 '가짜 값은 실제 할당 대역을 피한다(전화는 실제 번호 대역이 아닌 꼴, 카드는 시험용 BIN) — 다른 실제 사람의 식별자가 아니다'라고 적었는데 코드·D-113과 반대였다**
  (검증자 실행: 가짜 전화 2,000/2,000이 `010-dddd-dddd`, 예약 대역은 이메일뿐). 등록한 '새 주장은 쓰지 않는다'(§2-1)를 어긴 문장이었다 → '실제 값과 겹칠 수 있다, 복원에 실패하면 제3자의 번호를 받을 수 있다'로 고쳤다.
  그 밖에 고친 것: 볼트 상한(오래된 것을 비우는 게 아니라 새 요청을 503으로 거절), 키 회전(복원을 깨지 않는다 — 가짜 값이 바뀔 뿐), 웹훅이 받는 텍스트('원문 PII 없이'가 아니라 정책이 가리는 종류만 가짜 값), 사이드카로 가는 가리기 전 텍스트와 결과 캐시,
  감사 줄에 남는 것(탐지 위치·길이·확신도, 룰이 붙잡은 어휘 — **§2-1 ③에 등록한 '크기·지문·개수만'이라는 문구 자체가 부정확했다**), 9절 한계(보지 않는 자리·요청 간 연결·가짜 값에 남는 원문 일부)와 주민번호 검증식 문장,
  사이드카 '외부 노출 없이'(포트 8081은 파드 IP로 닿는다 → `deploy/k8s/networkpolicy.yaml` 견본), 메모의 제28조의4(기록은 제3항, 특례 처리에만 걸리는 조항이라 직접 적용 여부는 확인 필요)와 단정 둘('개인정보를 보관하지 않으므로'·'수탁자가 되지 않는다') → 확인 항목 8개,
  `poc_report`의 모양이 원 글자 등을 그대로 내던 것(허용한 글자만 그대로, 줄바꿈은 `␤`). low 8건도 반영(절 참조 6절 → 9절, SDK 점검은 스텁 상류, HTTPS는 강제가 아님, stderr 예외 로그, 고유식별정보 조문·제3조 제7항, 리포트의 BOM·깨진 줄·`--detect-kinds` 검증·숫자의 뜻, P2 표본이 3종뿐이던 것).

## D-130. 릴리스 공정 — 태그 → 이미지(GHCR)·SBOM·cosign 서명·취약점 스캔, dependabot, 비밀 검사 (2026-11-04, PLAN 20단계)

### 1. 근거

- 릴리스가 없다(부록 A '저장소' 행). 디자인 파트너가 설치할 이미지는 **누가 어떻게 만들었는지 검증할 수 있어야** 한다(백서 7절이 '20단계에서 더한다'고 적었다).
- 저장소에는 합성 키(Anthropic·GitHub·AWS·JWT·PEM·Google 꼴 — `eval/pii/`, 테스트의 가짜 키, 학습 데이터의 base64 변형)가 있어 비밀 검사기를 그대로 켜면 걸린다(D-115 보강: GitHub push protection은 실제 형식만 막는다).
- 의존성은 정확히 고정한다(pyproject·detect/requirements*) — 올릴 때 근거를 남기려면 올릴 것이 있다는 알림(dependabot)이 필요하다.

### 2. 결정

1. **`.github/workflows/release.yml`** — 태그 `v*` 푸시에 돈다(권한: `contents: write`·`packages: write`·`id-token: write`, 그 밖은 읽기). 단계: ① **태그 = `pyproject.toml` 버전**이고 CHANGELOG에 `## <버전> — ` 절이 있는지 확인(아니면 실패) ② buildx·GHCR 로그인(`GITHUB_TOKEN`)
   ③ 이미지 둘 빌드·푸시 — `ghcr.io/<owner>/llm-security-gateway:<태그>`·`:latest`(게이트웨이), `…/llm-security-gateway-detect:<태그>`·`:latest`(탐지 사이드카, 빌드 때 모델을 받는다) ④ **취약점 스캔**(Trivy, 이미지 다이제스트 대상): 고칠 수 있는(`ignore-unfixed`) HIGH·CRITICAL이 하나라도 있으면 실패
   ⑤ **SBOM**(syft, SPDX JSON) 이미지마다 ⑥ **cosign keyless 서명**(GitHub OIDC)과 SBOM 증명(`cosign attest --type spdxjson`) ⑦ GitHub 릴리스 생성(`gh release create`) — CHANGELOG의 그 버전 절 + 이미지 다이제스트 + 검증 명령, SBOM 파일 첨부.
   액션은 전부 **커밋 SHA로 고정**(옆에 태그 주석, ci.yml과 같은 규칙). 릴리스 생성은 서드파티 액션 없이 러너의 `gh`로.
2. **`.github/dependabot.yml`**: pip(`/`·`/detect`)·github-actions·docker(`/gateway`·`/detect`) 주마다. PR은 제안이다 — 받아들일 때 DECISIONS에 근거를 적는 규칙은 그대로.
3. **비밀 검사**: `ci.yml`에 `secrets` 작업(gitleaks-action, 푸시·PR 범위) + `.gitleaks.toml`로 합성 키 경로(`eval/`·`tests/`·`detect/tests/`·`gateway/data/`)만 허용 목록 — 제품 코드·설정·문서·배포 견본은 검사한다.
4. **버전 올림**: `pyproject.toml` 0.1.0 → **0.2.0**(1단계 이후 모든 결정이 미출시였다), `gateway/version.py`가 같은 값, CHANGELOG '미출시' 절을 `## 0.2.0 — 2026-11-04`로(릴리스는 사용자가 `v0.2.0` 태그를 푸시할 때). 테스트가 셋을 맞춘다.
5. **문서**: 운영 문서 '업그레이드'에 이미지 주소·서명 검증(`cosign verify`)·SBOM 위치, README 실행 절에 이미지 주소. 백서 7절의 '20단계에서 더한다'를 고친다.

### 3. 버린 대안

- **키 보관형 서명(cosign 키 쌍)**: 키 관리가 늘고 유출되면 끝이다. keyless(OIDC·Rekor 투명 로그)는 저장소·워크플로 신원으로 검증한다.
- **SBOM을 저장소에 커밋**: 이미지마다 다르고 수백 KB다 — 릴리스 자산과 증명으로.
- **취약점 스캔을 고칠 수 없는 것까지 실패로**: 베이스 이미지의 미수정 CVE가 릴리스를 영영 막는다. 고칠 수 있는 HIGH·CRITICAL만 게이트, 전체 표는 로그에.
- **gitleaks 전체 히스토리 스캔**: 연구 단계 히스토리(결과 파일)를 매번 훑는다. 푸시 범위만 — 히스토리 정리는 조건부 표의 '새 히스토리 저장소'.
- **릴리스 PR 봇(release-please 등)**: 버전은 결정과 함께 사람이 올린다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| R1 | 워크플로·dependabot·gitleaks 설정이 YAML/TOML로 파싱되고, 모든 `uses:`가 40자 SHA + 태그 주석이다(ci·detect·release) | `tests/test_d130_release.py` |
| R2 | release.yml: 태그 `v*` 트리거, 권한 셋, 버전 확인 단계, 이미지 둘, Trivy(HIGH·CRITICAL·exit 1), SBOM, cosign sign·attest, `gh release create` | 같은 파일 |
| R3 | `pyproject` 버전 = `gateway/version.py` = CHANGELOG 첫 절 = 0.2.0, dependabot 생태계 셋, gitleaks 허용 경로가 합성 키 경로를 덮는다(실제로 `eval/pii/corpus.jsonl`의 키 꼴 수 > 0) | 같은 파일 |
| R4 | 사용자가 `v0.2.0` 태그를 푸시한 뒤 릴리스 성공(이미지 둘·SBOM·서명·스캔) | 사용자 할 일 → 다음 세션이 확인 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 | |

### 5. 한계

- 워크플로는 로컬에서 돌려 볼 수 없다 — 문법·구조 테스트와 첫 태그 푸시로 확인한다. 실패하면 로그 마지막 줄을 다음 세션에.
- Trivy 게이트는 '고칠 수 있는' HIGH·CRITICAL만이다. 미수정 CVE는 로그로 본다.
- gitleaks는 푸시 범위만 본다 — 과거 히스토리는 검사하지 않는다.
- detect 이미지는 빌드 때 모델 약 800MB를 받는다 — 릴리스가 몇 분 더 걸린다. 기본 분류기 교체(D-128 업로드 뒤)는 이미지 내용을 바꾸므로 그때 다시 릴리스한다(0.2.1 등).

### 6. 결과 (2026-11-10)

- **만든 것**: `.github/workflows/release.yml` — 태그 `v*`에 작업 둘. **build**(읽기 권한만): ① `scripts/release_notes.py`로 태그 = `pyproject.toml` = CHANGELOG 절 확인(어긋나면 빌드 전에 실패) ② 이미지 둘 빌드(러너의 docker, 라벨 source·revision·version)
  ③ Trivy 목록(HIGH·CRITICAL 전부 — 막지 않음) → 게이트(`ignore-unfixed`·`exit-code 1`) ④ SBOM(syft, SPDX JSON) ⑤ `docker save` → 아티팩트. **publish**(`contents`·`packages`·`id-token` 쓰기): ⑥ 받은 이미지 파일을 `docker load` → GHCR에 버전 태그 푸시 → 다이제스트
  ⑦ `cosign sign`·`cosign attest --type spdxjson`(keyless) ⑧ `latest` 푸시 ⑨ `gh release create --verify-tag`(노트 + SBOM 둘). 처음에는 작업 하나였다 — 아래 리뷰로 나눴다.
  `scripts/release_notes.py`(버전 확인 + CHANGELOG 절 + 다이제스트 + 검증 명령), `.github/dependabot.yml`(pip `/`·`/detect`, github-actions, docker `/gateway`·`/detect`, 주마다), `ci.yml`의 `secrets` 작업(gitleaks-action, gitleaks 8.24.3 — 푸시·PR 범위, 손으로 돌릴 때는 건너뜀),
  `.gitleaks.toml`, 버전 **0.2.0**(pyproject·CHANGELOG `## 0.2.0 — 2026-11-10`·k8s 견본 이미지 태그·README 둘·설명서), dev 의존성 `pyyaml==6.0.3`(테스트가 워크플로를 YAML로 읽는다),
  문서(운영 '업그레이드'·'배포', README 둘, 백서 위협 표·7절, CHANGELOG에 D-129·D-130 항목, 설명서 진행 표·PDF 22쪽).
- **고정한 액션**(2026-11-10 GitHub API `/repos/<repo>/commits/<tag>`로 태그와 SHA를 대조, 입력 이름은 그 SHA의 action 정의에서 읽음): actions/checkout v7.0.1 · aquasecurity/trivy-action v0.36.0(Trivy v0.70.0) · anchore/sbom-action v0.24.3 ·
  sigstore/cosign-installer v4.1.2(cosign v3.0.6) · gitleaks/gitleaks-action v3.0.0. cosign-installer는 v4.1.3이 2026-11-04에 나왔다 — 엿새 된 판이라 올리지 않았다(dependabot이 제안한다).
- **테스트**: `tests/test_d130_release.py` 9개 — R1(파싱, 모든 `uses:`가 40자 SHA + 태그 주석이고 줄로 센 수 = 파싱한 수, 워크플로 기본 권한은 읽기, `run` 안에 표현식 없음) · R2(트리거·권한 셋·단계 순서 확인 < 빌드 < 스캔 둘 < 푸시 < SBOM 둘 < 서명 < 릴리스,
  스캔 설정, 서명·증명이 다이제스트를 가리킴, 올리는 이름 = k8s 견본의 이름, `secrets` 작업) · R3(버전 넷의 일치, dependabot 생태계 셋과 폴더, gitleaks 허용 경로가 합성 키 경로만 덮음, 릴리스 노트의 버전 불일치·빈 절·앞부분만 같은 버전 거절과 검증 명령).
  전체 `pytest` **905**(이 단계 전 896)·`ruff`·`mypy` 통과(리뷰 반영 뒤 이 파일은 10개).
- **리뷰 + 반박 검증(2026-11-10, D-128 §6의 워크플로 — 릴리스·CI 관점 1)**: medium 이상 3건 전부 재현 → 반영. ① **스캐너(Trivy·Syft — 실행 때 바이너리를 내려받는다)가 푸시·서명·릴리스 권한을 쥔 같은 작업에서 돌았다**: 그쪽이 변조되면 이 워크플로의 신원으로 서명할 수 있다
  → 작업을 build(읽기)와 publish(쓰기·OIDC — 서드파티는 cosign 설치뿐)로 나누고 이미지는 파일로 넘긴다(다시 빌드하지 않는다). 액션 둘 추가: actions/upload-artifact v7.0.2 · download-artifact v8.0.2(SHA를 태그와 대조).
  ② 푸시 뒤 단계가 실패하면 `<버전>`·`latest`가 서명 없이 남았다 → SBOM을 푸시 앞으로, `latest`는 서명·증명 뒤에만 옮긴다(실패하면 publish만 다시 돌린다 — 같은 이미지 파일). ③ '미수정 취약점은 로그의 표로 본다'고 적었지만 `ignore-unfixed`가 표에서도 뺐다 → 막지 않는 목록 단계를 게이트 앞에 뒀다.
  다른 관점의 지적으로: 공개로 올리는 사이드카 이미지에 내장 모델의 LICENSE·NOTICE가 없었다 → `/licenses/`(저장소 LICENSE + `detect/THIRD_PARTY_NOTICES.md`)와 Horizon 모델의 LICENSE·NOTICE(`models.json`에 해시와 함께).
  low 6건 중 반영: 태그 `v-h`가 버전 확인을 지나치던 것(`--` 뒤에 넘긴다), 내부 레지스트리 복사 안내(`cosign copy`는 사용 중단 — 서명은 함께 옮겨지지 않을 수 있다), `secrets` 작업 주석(푸시에서는 머지 커밋 쪽을 건너뛴다), 태그 둘을 함께 밀 때의 `latest` 경합(`concurrency`).
  한계로 남긴 것: gitleaks 허용 경로 `tests/` 전체는 넓다(테스트에 붙여 넣은 실제 키를 놓친다 — 걸리는 파일만 고르려면 gitleaks를 돌려 봐야 하는데 이번 세션은 바이너리 실행이 막혔다. 실제 공급자 키 꼴은 GitHub push protection이 막는다),
  예전 계열의 패치 태그도 `latest`를 옮긴다(지금은 계열이 하나다), SBOM 증명의 크기가 공개 Rekor 상한 안인지 재 보지 못했다(넘으면 증명 단계가 실패한다 — 그때는 로그를 본다).
- **두 번째 리뷰 + 반박 검증(2026-11-10, 에이전트 4 — 위에서 다시 짠 워크플로를 한 번 더)**: medium 이상 2건 모두 재현 → 반영. ① **high — publish가 아티팩트를 체크아웃한 작업 폴더 위에 풀고 그 폴더의 `scripts/release_notes.py`를 실행했다**:
  build에서 도는 스캐너가 변조되면 아티팩트에 그 스크립트를 끼워 넣어 쓰기·OIDC 권한을 쥔 publish에서 코드를 돌릴 수 있었다(작업을 나눈 뜻이 무너진다) → 받은 파일은 `$RUNNER_TEMP` 아래에 푼다.
  ② 스캐너가 `docker save` 앞에서 같은 docker 데몬으로 돌았다(이미지를 바꿔치기해도 publish가 그대로 서명) → **작업을 셋으로**: build(서드파티 코드 없음 — 빌드·`docker save`·SHA-256을 **작업 출력**으로) → scan(Trivy·Syft, 읽기 권한뿐) → publish(`sha256sum -c`로 build의 그 파일인지 확인한 뒤에만 load·푸시·서명).
  low 5건도 반영: trivy-action `cache: "false"`(Actions 캐시의 바이너리·DB를 쓰지 않는다 — 캐시는 main의 다른 워크플로가 채울 수 있다), 다이제스트를 `RepoDigests`의 0번이 아니라 레지스트리 이름으로 고름(containerd 이미지 저장소 대비),
  아티팩트 보존 1일 → 7일, `concurrency`에 `queue: max`(기본값은 대기 실행을 하나만 남겨 태그 셋이면 가운데가 취소된다 — GitHub 문서로 확인), 테스트가 게이트 무력화(`continue-on-error`·`if`)·저장하는 이미지 이름·체크아웃 자격 증명·publish의 run 단계 수를 고정.
  남은 한계: SBOM은 scan(스캐너)이 만든 파일이라 스캐너가 변조되면 SBOM 내용은 보장하지 않는다(이미지 자체는 해시로 지킨다). 이 세 작업 구조도 로컬에서 돌려 보지 못했다 — 첫 태그 푸시가 확인이다.

- **계획(§2)과 다른 점**: ① **스캔을 푸시 앞에** 둔다 — §2는 푸시한 다이제스트를 스캔했다. 그러면 스캔에 걸린 이미지가 이미 `latest`로 올라가 있다. 러너의 docker에 빌드 → 스캔 → 통과해야 푸시(스캔한 그 이미지를 파일로 넘겨 민다).
  ② buildx·login·build-push·metadata 액션을 쓰지 않고 러너의 `docker build`·`docker login`·`docker push` — 쓰기 권한을 쥔 작업(publish)에 들이는 서드파티 액션은 cosign 설치 하나다(스캔·SBOM은 읽기 권한뿐인 build에서 돈다).
  ③ 이미지 태그는 `v`를 뗀 버전(`0.2.0` — k8s 견본과 같다), linux/amd64만. ④ gitleaks 허용 경로는 `eval/`·`tests/` 둘과 `detect/models.json`의 SHA-256(규칙 허용 목록)뿐 — §2의 `detect/tests/`·`gateway/data/`에는 걸릴 값이 없어 넣지 않았다(좁을수록 낫다).
  ⑤ CHANGELOG 절 날짜는 등록일(11-04)이 아니라 만든 날(11-10). ⑥ 버전 확인과 노트는 워크플로 안 셸이 아니라 `scripts/release_notes.py` — pytest가 같은 코드를 돌린다. ⑦ 백서 5절 표도 고쳤다.
- **못 한 것**: **R4**(실제 릴리스 — 사용자가 `v0.2.0` 태그를 푸시, PLAN 사용자 할 일). Docker 데몬이 꺼져 있어 로컬 이미지 빌드·Trivy 스캔을 해 보지 못했다 — 베이스 다이제스트가 2026-10-30 것이라 그새 고칠 수 있는 HIGH가 생겼으면 첫 릴리스가 스캔에서 멈춘다
  (그러면 두 Dockerfile의 베이스 다이제스트를 올리고 다시 태그한다 — 게이트가 뜻대로 도는 것이다). gitleaks 바이너리는 이번 세션에서 돌리지 못했다(외부 바이너리 실행이 권한 분류기에 막힘) — 설정은 11-04 세션이 8.24.3으로 맞춘 그대로이고,
  이번에는 허용 목록 밖 추적 파일을 파이썬으로 근사 검사했다(공급자 키 꼴 0건, 일반 비밀 꼴 후보는 `detect/models.json`의 SHA-256 17개뿐 — 규칙 허용 목록이 덮는다). 첫 푸시의 `secrets` 작업이 실제 확인이다. GHCR 패키지 공개 설정은 사용자 몫.

## D-131. 공개 데모 — 데모 웹의 공개 모드(스텁 고정·본문 상한·레이트리밋·방문자 분리), 데모 이미지, Fly.io 견본 (2026-11-10, PLAN 21단계)

### 1. 근거

- 데모 웹(`web/app.py`, D-104)은 한 사람이 자기 노트북에서 쓰는 도구다. 그대로 공개하면:
  (가) `WEB_ON_TARGET`·`.env`로 실제 공급자에 붙는다 — 공개 자유 입력이 외부 공급자로 나간다(PLAN 21단계가 금지), (나) `/api/chat`이 본문 크기를 보지 않는다, (다) 요청 수 제한이 없다,
  (라) 스텁의 수신 기록(`/__stub/received`)이 포트당 하나라 **동시에 쓰는 방문자가 서로의 문장을 '상류가 받은 것'으로 본다**, 그 기록은 지워지지 않고 쌓인다('없음' 팔은 원문 그대로),
  (마) 감사 로그 파일이 끝없이 자라고 요청마다 통째로 읽는다.
- **재현(구현 전, 2026-11-10)**: 지금 코드에 서로 다른 문장 12건을 동시에 보내면 24팔 중 **19팔이 남의 문장**을 보였다. 30만 바이트 본문은 다 읽은 뒤에야 400(메시지 길이)이다.

### 2. 결정

1. `WEB_PUBLIC=1`(기본 꺼짐 — 로컬 동작은 그대로)이면:
   - **상류는 두 팔 모두 스텁 고정** — `WEB_ON_TARGET`·`WEB_ON_MODEL`을 무시하고 `.env`를 읽지 않는다(공급자 키가 프로세스에 들어오지 않는다).
   - **본문 상한 4,096바이트**(`/api/chat` — Content-Length와 실제로 읽은 양 둘 다) → 413.
   - **레이트리밋**: 방문자별 분당 `WEB_RATE_PER_MINUTE`(기본 20) + 전체 분당 `WEB_RATE_TOTAL_PER_MINUTE`(기본 300) → 429 + `Retry-After`. 게이트웨이의 `RateLimiter`를 그대로 쓴다.
     방문자 주소는 `WEB_CLIENT_IP_HEADER`(Fly.io는 `Fly-Client-IP`)가 설정돼 있으면 그 헤더, 아니면 소켓 주소 — `X-Forwarded-For`는 클라이언트가 채울 수 있어 쓰지 않는다. 전체 상한은 헤더 위조와 무관하게 걸린다.
   - **방문자 분리**: 한 번에 한 요청만 두 팔을 지난다(전역 잠금). 잠금 안에서 스텁 수신 기록을 읽고 **지운다**(스텁에 `DELETE /__stub/received`), 스트리밍 결과는 잠금 안에서 다 모은 뒤 잠금 밖에서 흘려보낸다
     (느린 클라이언트가 잠금을 쥐지 못한다). 대기를 포함한 요청 기한 15초 → 503.
   - **감사 로그**: 끝 64KiB만 읽고, 1MiB를 넘으면 잠금 안에서 비운다. 위치는 지금처럼 임시 폴더.
   - 화면에 '공개 데모 — 실제 개인정보를 넣지 마세요, 가짜 AI(스텁)만 답합니다' 한 줄(`/api/info`의 `public`).
2. **데모 이미지** `web/Dockerfile`(베이스 다이제스트는 게이트웨이와 같다, 비root, `WEB_PUBLIC=1` 고정, 포트 8090) + `web/Dockerfile.dockerignore`.
   `free_port`·`serve`를 pytest 없는 모듈(`tests/procs.py`)로 옮겨 이미지에 pytest를 넣지 않는다(`tests.conftest`는 다시 내보낸다 — 기존 import 그대로).
3. **배포 견본** `deploy/demo/fly.toml`(Fly.io — 요청이 없으면 0대로 줄고 요청에 켜진다, 512MB, 동시 요청 상한). Render 견본은 두지 않는다(하나면 된다).
4. **문서**: README 두 언어에 '공개 데모' 문단(빌드·배포 명령, 끄는 법). 상단 링크는 사용자가 배포해 주소가 생긴 뒤.

### 3. 버린 대안

- **방문자마다 스텁·게이트웨이 한 벌**: 프로세스가 방문자 수만큼 는다. 데모에 과하다.
- **요청 ID로 스텁 수신 기록 찾기**: 스텁(테스트 도구)의 기록 구조를 바꿔야 하고, 지우는 시점도 따로 정해야 한다. 잠금이 더 작다(한계: 한 번에 한 요청 — 스텁이라 수 ms).
- **`X-Forwarded-For`로 방문자 구분**: 클라이언트가 값을 채워 한도를 피한다.
- **공개 모드를 기본으로**: 로컬 데모(실제 공급자 모드, D-104)가 깨진다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| P1 | 공개 모드는 `WEB_ON_TARGET`이 있어도 두 팔 모두 스텁(`/api/info`의 `real` false·`public` true), 인젝션 장면이 켜져 있다 | `tests/test_d131_public_demo.py` |
| P2 | 본문 4,097바이트 → 413(Content-Length가 없거나 작게 적힌 경우 포함), 4,096바이트는 통과 | 같은 파일 |
| P3 | 방문자 한도 초과 → 429·`Retry-After`, 헤더 값이 다르면 따로 센다, 전체 한도는 헤더와 무관 | 같은 파일 |
| P4 | 동시 요청이 각자 자기 문장만 본다(잠금을 빼면 실패함을 되돌려 확인), 요청 뒤 스텁 수신 기록이 비어 있다 | 같은 파일 |
| P5 | 감사 로그가 상한을 넘지 않고(작은 상한으로 시험) 그 뒤 요청의 감사 줄도 보인다 | 같은 파일 |
| P6 | 로컬 모드(기본)는 그대로 — `tests/test_web.py` 통과 | 기존 테스트 |
| P7 | `web/Dockerfile`·`fly.toml` 구조(베이스 다이제스트 = 게이트웨이, 비root, `WEB_PUBLIC=1`, `internal_port` = `EXPOSE`) | 같은 파일 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 | |

### 5. 한계

- 전역 잠금이라 한 번에 한 요청이다 — 방문자가 몰리면 줄을 서고 15초 뒤 503.
- 레이트리밋·잠금은 프로세스 하나 기준이다(머신을 늘리면 머신별).
- 이미지 빌드·실행은 Docker 데몬이 켜져 있어야 확인한다. 실제 배포와 남용 감시는 사용자 몫이다(PLAN 21단계).
- 방문자가 넣은 글은 '없음' 팔의 스텁 메모리에 요청이 끝날 때까지 있다(끝나면 지운다). 디스크에는 쓰지 않는다(감사 줄에는 원문이 없다).

### 6. 결과 (2026-11-10)

- **만든 것**: `web/app.py`의 공개 모드(`WEB_PUBLIC=1` — `_public`·`_limit`·`_body`·`_forget`·`_public_chat`, `/api/info`의 `public`), 감사 줄 읽기를 로그 끝 64KiB로(두 모드 공통 — 통째로 읽던 것),
  `tests/procs.py`(`free_port`·`serve`를 옮김 — `tests.conftest`가 다시 내보낸다), 스텁의 `DELETE /__stub/received`, `web/Dockerfile`(게이트웨이와 같은 베이스 다이제스트·비root·`WEB_PUBLIC=1`·접근 로그 끔·포트 8090)과
  `web/Dockerfile.dockerignore`(전부 빼고 쓰는 것만 — `.env`·`models`·`eval`이 문맥에 없다), `deploy/demo/fly.toml`(0대로 줄었다 요청에 켜짐·512MB·`WEB_CLIENT_IP_HEADER = "Fly-Client-IP"`), 화면의 공개 데모 안내 한 줄, README 두 언어 문단.
- **재현 → 고친 뒤**: 서로 다른 문장 12건 동시 요청에서 남의 문장을 본 팔 19/24 → **0/24**(절반은 스트리밍). 요청이 끝나면 두 스텁의 수신 기록이 비어 있다.
- **테스트**: `tests/test_d131_public_demo.py` 9개 — P1(실제 공급자 설정·키를 넣어도 두 팔 모두 스텁, `arm_target`) · P2(4,096 통과·4,097은 413, Content-Length 없는 chunked도 413, 깊게 중첩된 JSON·깨진 UTF-8은 400)
  · P3(방문자별 한도와 `Retry-After`, info도 같은 한도, 전체 한도는 방문자 헤더와 무관, 헤더를 정하지 않으면 소켓 주소 — `X-Forwarded-For`는 보지 않음) · P4(동시 12건 분리, 수신 기록 삭제, 기한 503과 잠금 해제)
  · P5(로그 상한 — 30건 동안 상한을 넘지 않고 비운 뒤의 감사 줄도 읽힘) · P7(이미지·문맥 허용 목록·fly.toml 구조, 이미지가 싣는 모듈이 pytest 없이 import됨). P6은 기존 `tests/test_web.py` 6개 그대로 통과.
  **되돌리기 확인 8/8**(잠금·수신 기록 삭제·스텁 고정·읽은 양 상한·방문자 한도·`X-Forwarded-For` 신뢰·로그 비우기·기한을 하나씩 빼면 해당 테스트가 실패). 전체 `pytest` **914**(이 단계 전 905)·`ruff`·`mypy` 통과.
- **계획(§2·§4)과 다른 점**: P2의 'Content-Length가 작게 적힌 경우'는 서버가 적힌 만큼만 읽으므로 넘칠 수 없다 — 대신 Content-Length 없는 chunked 본문을 시험했다. 한도는 `/api/info`에도 건다(게이트웨이 둘을 부르는 경로다).
  로그 상한은 `WEB_LOG_MAX_BYTES`로 바꿀 수 있다(시험이 작은 값으로 돈다). 같은 프로세스 시험은 Starlette TestClient 대신 스레드 uvicorn(`conftest.start` — TestClient는 사용 중단 경고를 낸다).
- **못 한 것**: Docker 데몬이 꺼져 있어 **이미지 빌드·실행을 확인하지 못했다**(완료 기준의 '로컬 docker run' — PLAN 사용자 할 일에 명령). 실제 배포·README 상단 링크(주소가 생긴 뒤)·남용 감시는 사용자 몫.
  flyctl은 설치돼 있지 않아 명령을 돌려 보지 못했다 — `fly deploy [작업 폴더] --config --dockerfile --ignorefile --ha`와 fly.toml의 키, `Fly-Client-IP`(Fly Proxy가 본 방문자 주소)는 2026-11-10 Fly 공식 문서에서 확인한 것이다.
- **리뷰 + 반박 검증(2026-11-10, 에이전트 4 — D-132와 함께)**: 이 결정 몫 medium 이상 3건 모두 재현(검증자 심각도 medium 1·low 2) + low 4건 → 반영.
  ① **공개 모드에서 장면 6('너무 큰 본문', 6,043바이트)이 웹 층의 413에 먼저 걸려 깨졌다**(상한이 게이트웨이 팔과 같은 4,096이었다) → 웹 층 상한을 **8,192**로(§2의 4,096과 다르다 — 게이트웨이 팔의 상한은 4,096 그대로라 처리되는 본문은 여전히 4,096 이하다). 장면 여섯이 모두 두 팔의 결과를 내는지 테스트.
  ② 본문 읽기가 기한 밖이었다(60바이트를 17초에 걸쳐 보내도 200) → 본문 5초 기한(408). ③ 방문자 키: IPv6는 /64로 묶고, 같은 헤더가 둘이면 마지막 값, 주소가 아닌 값은 64자로 자름. 프록시 뒤에서 `WEB_CLIENT_IP_HEADER`를 정하지 않으면 한 통이 된다는 것을 README·기동 경고에 적었다
  (지적은 전체 한도를 먼저 세라고 했지만 그대로 뒀다 — 먼저 세면 한 방문자가 거절되는 요청만으로 전체 한도를 채운다).
  low: 기한(503)으로 끝난 요청의 글이 스텁에 남을 수 있었다(정리가 기한 안에서 돌았고, 끊긴 상류 호출이 뒤늦게 닿는다) → 잠금 대기와 실행에 기한을 따로 걸고 정리는 기한 밖 + 요청 시작 때도 한 번, 스텁의 경로 기록(`HITS`)도 지움,
  `/docs`·`/redoc`·`/openapi.json`이 열려 있었다(끔), 짝 없는 서로게이트 한 글자로 500(400으로), 헬스체크가 자식 프로세스를 보지 않았다(`/api/info`로), 화면이 거절 사유를 한 칸에만 보였다.
  `tests/test_d131_public_demo.py` 11개, **되돌리기 확인 8/8**(고친 판 기준 — 잠금·정리·본문 기한·문서 경로·웹 층 상한·IPv6 묶기·서로게이트·스텁 고정). 기한은 이제 대기 15초 + 실행 15초다(§2의 '대기를 포함한 15초'와 다르다).

## D-132. 22단계 준비 — v1.0 기준의 자(감사 로그 판정 도구), 가격·계약 초안 (2026-11-10, PLAN 22단계)

### 1. 근거

- 22단계의 첫 항목(디자인 파트너 1곳)은 사용자 몫이고 아직 없다. 세션이 미리 할 수 있는 것은 둘이다 — 파트너에게 내밀 **가격·계약 초안**(결정 표 9번), 그리고 PoC 2주가 끝났을 때 **v1.0 기준을 재는 자**.
- v1.0 기준('의심 잔여 0.1% 미만, 5xx 0.1% 미만')은 분모·분자가 정해져 있지 않다. 데이터를 본 뒤에 정하면 유리한 쪽으로 정하게 된다 — 지금 적는다(사전 등록).
- 오탐 예외 규칙(`allow_patterns`)은 **만들지 않는다** — PLAN은 'PoC에서 나온 오탐'을 처리하라고 했다. 실제 오탐의 모양(값 정규식인지, 종류별인지, 필드 경로인지)을 모르고 만들면 추측이다.
  PoC 리포트(`scripts/poc_report.py`)의 오탐 후보 표가 나온 뒤에 결정한다.

### 2. 결정

1. **v1.0 기준의 정의**(감사 로그 JSONL로 잰다 — 연속 14일 이상, mask로 돈 구간):
   - **G1 의심 잔여**: 가짜 값을 발급한 요청(`pii_issued` > 0) 가운데 `pii_suspect` > 0인 요청의 비율 **< 0.1%**.
   - **G2 5xx**: 전체 요청 가운데 **게이트웨이 몫 5xx**(`status` ≥ 500이고 결과가 `upstream_error`가 아닌 줄 — 게이트웨이 예외, 포화 503 `upstream_busy`, 사이드카·가드레일 503 포함) 비율 **< 0.1%**.
     상류 장애(`upstream_error` — 공급자 5xx·연결 실패)는 게이트웨이가 고칠 수 없으므로 따로 세어 보인다(게이트 밖).
   - 분모가 1,000건 미만이면 **판정 불가**(0.1%를 말할 수 없다), 기간이 14일 미만이면 **기간 부족**. 둘 다 통과여야 v1.0.
   - 결과 분류는 게이트웨이의 `gateway.metrics.outcome`을 그대로 쓴다(대시보드·지표와 같은 코드).
   - **정의 보완(2026-11-10 리뷰 — PoC 데이터가 생기기 전이다)**: 'mask로 돈 구간'은 감사 줄에 가림 검사기(`pii_mask`)가 처음 나온 시각부터다 — 그 앞(관측 구간)은 기간에도 분모에도 넣지 않는다. '연속'은 그 구간에 줄이 없는 날(UTC)이 하루도 없는 것이다.
     G2의 분자에 **스트림 도중의 게이트웨이 실패**(머리 200이 나간 뒤라 `status` 200 + 오류로 남는다 — 결과 `failed`)를 더하고, 클라이언트가 끊은 요청(`ClientDisconnect`·`CancelledError`)은 뺀다. 같은 요청 ID가 되풀이되면 한 번만 센다.
2. **`scripts/poc_gate.py`**: 감사 로그 파일들(또는 표준 입력) → 기간·요청 수·G1·G2·상류 장애 수·판정을 마크다운으로. 통과면 종료 코드 0, 아니면 1. 원문은 감사 로그에 없고 이 도구도 값을 내지 않는다.
3. **`docs/pricing.md`**('초안' 표시): 결정 표 9번 그대로 — 코드는 전부 Apache-2.0, 유료는 배포 단위 연간 지원 계약, 좌석·토큰 과금 없음, 금액은 추정 구간. 디자인 파트너 조건·PoC 진행 순서·v1.0 기준·계약 체크리스트·사용자가 정할 것.
   README 두 언어에 링크.

### 3. 버린 대안

- **`allow_patterns`를 지금 구현**: 위 §1. 가림을 끄는 규칙은 보안 기능을 약하게 하는 손잡이라 근거(실제 오탐) 없이 넣지 않는다.
- **G1을 발급 건수 기준(의심 건수/발급 건수)**: 한 요청이 값 수백 개를 발급하면 희석된다. 사용자가 겪는 단위는 요청이다.
- **G2에 상류 5xx 포함**: 공급자 장애가 제품 판정을 좌우한다.
- **가격을 좌석·토큰 기준으로**: 결정 표 9번이 뺐다(자체 호스팅이라 셀 수도 없다).

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| Q1 | G1·G2의 경계(0.1% 바로 아래 통과·딱 0.1% 미달), 분모 1,000 미만은 판정 불가, 14일 미만은 기간 부족, 상류 장애는 G2에 안 들어감, 깨진 줄은 세어 보이고 건너뜀 | `tests/test_d132_poc_gate.py` |
| Q2 | 실제 게이트웨이가 쓴 감사 로그(스텁 상류)로 도구가 돌고 종료 코드가 판정과 같다 | 같은 파일 |
| Q3 | `docs/pricing.md`: '초안' 표시, 상대 링크 유효, 결정 표 9번의 원칙(Apache-2.0·배포 단위·좌석·토큰 과금 없음) | 같은 파일 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 | |

### 5. 한계

- 기준은 요청 수 기준이다 — 트래픽이 적은 파트너는 2주에 1,000건이 안 될 수 있다(그러면 기간을 늘린다).
- `pii_suspect`는 '가짜 값이나 그 조각이 응답에 남은' 신호다 — 모델이 가짜 값을 풀어 쓴 경우(다른 표기)는 잡지 못한다(D-113 한계 그대로).
- 가격 문서의 금액은 추정이다. 계약 조항은 변호사 검토 대상이다.

### 6. 결과 (2026-11-10)

- **만든 것**: `scripts/poc_gate.py`(감사 로그 → 기간·요청 수·G1·G2·상류 장애·판정, 종료 코드 0/1, 인자가 없으면 사용법과 2) · `docs/pricing.md`(초안 — 원칙 넷, 커뮤니티/지원 계약 구성표, 디자인 파트너 조건, v1.0 기준과 재는 명령,
  계약 체크리스트, 사용자가 정할 것) · README 두 언어 링크.
- **테스트**: `tests/test_d132_poc_gate.py` 6개 — Q1(1/2,000 = 0.05% 통과·2/2,000 = 0.1% 미달, 분모 999는 판정 불가, 발급 요청이 500뿐이면 G1만 판정 불가, 13.9일은 기간 부족, 포화 503·게이트웨이 예외는 세고
  상류 연결 실패·전달한 상류 500·스트림 안 공급자 오류·429는 세지 않음, 감사 줄이 아닌 줄은 건너뛰고 수를 보임) · Q2(실제 마스킹 게이트웨이 + 스텁 상류가 쓴 로그로 CLI — 3건은 판정 불가·종료 코드 1·값이 출력에 없음, 1,200건 15일은 통과·0)
  · Q3(가격 문서의 초안 표시·원칙 문구·링크, README 링크). **되돌리기 확인 6/6**(미만 → 이하, 분모 하한 제거, 상류 장애를 5xx로, 기간 확인 제거, G1 분모를 전체 요청으로, 깨진 줄을 요청으로). 전체 `pytest` 920(이 결정 전 914)·`ruff`·`mypy` 통과.
- **계획과 다른 점**: `allow_patterns`는 만들지 않았다(§1 — PoC의 실제 오탐이 나온 뒤). v1.0 기준의 '5xx'를 게이트웨이 몫으로 좁혔다(상류 장애 제외 — §3).
- **못 한 것(사용자 몫)**: 디자인 파트너 1곳, PoC(하루 설치 → 2주 observe → mask), 금액·파트너 조건·계약 주체 결정, 계약 조항의 변호사 검토 — PLAN 사용자 할 일.
- **리뷰 + 반박 검증(2026-11-10, 에이전트 4)**: 이 결정 몫 medium 이상 2건 모두 재현 → 반영(§2에 '정의 보완'으로 적었다 — 데이터를 보기 전이다). ① **도구가 기간·분모를 mask 구간으로 좁히지 않았다**: 관측 2주 + mask 1시간 로그가 '통과'(종료 코드 0)였고,
  하루치 1,000줄 + 13일 공백 + 60줄도 통과였다(§2가 '연속 14일, mask로 돈 구간'이라고 적었는데 처음~끝 시각 차이만 봤다) → `pii_mask`가 처음 나온 줄부터만 세고 빈 날이 있으면 기간 부족.
  ② 스트림 도중의 게이트웨이 실패(`status` 200 + 오류)가 G2에 잡히지 않았다 — §2의 문구('status ≥ 500')를 글자대로 구현한 것이라 정의의 구멍이었다 → 분자에 더함(클라이언트 끊김 제외).
  low: 같은 파일을 두 번 주면 분모가 두 배가 돼 '판정 불가'가 '통과'로 바뀌던 것(요청 ID 중복 제거), 시각이 ISO가 아니거나 시간대가 없는 줄 하나에 traceback으로 죽던 것, 표준 입력의 깨진 바이트. 파일 순서는 상관없다(시각으로 정렬).
  `tests/test_d132_poc_gate.py` 7개, **되돌리기 확인 6/6**(고친 판 기준 — mask 구간 무시·빈 날 무시·스트림 실패 무시·끊긴 요청 포함·중복 허용·미만 → 이하).

## D-133. 실 공급자 확인 2 — OpenAI·Gemini·Claude 모델 앞의 가림·복원(라우터 경유) 사전 등록 (2026-11-10, PLAN 20-1단계)

### 1. 근거

- 실제 공급자 앞에서 확인한 것은 Claude Messages 2턴 하나뿐이다(D-114). **OpenAI Chat Completions·Responses와 Gemini 모델은 스텁 상류로만** 확인했다(SDK 점검 D-121) — 실제 모델이 가짜 값을 그대로 되풀이하는지, 도구 인자에 옮겨 적는지는 모른다.
- 사용자가 여러 공급자를 한 키로 부르는 라우터(MonoRouter, `monogpt.kr`)의 크레딧을 써도 된다고 했다(2026-11-10 "API 쓸 데 있으면 다 써도 돼"). 공개 안내(콘솔 화면의 스크립트, 2026-11-10 확인)로 본 경로:
  OpenAI 호환 `https://monogpt.kr/api/monorouter/v1/{chat/completions,responses,models,credits}`(`Authorization: Bearer mr_universal_…` — 모델 이름으로 공급자를 고른다),
  Anthropic 호환 `https://monogpt.kr/api/monorouter/v1/anthropic/v1/messages`(`x-api-key: mr_anthropic_…`). 게이트웨이의 상류 주소는 경로가 붙어도 된다(`TARGET_URL` — 받은 경로를 뒤에 붙인다).
- 유료 호출이므로 기준을 먼저 적는다(공통 규칙 7). 키는 아직 없다 — 사용자가 `.env`에 넣는다.

### 2. 결정

1. **`scripts/check_real_providers.py`**: 게이트웨이(현재 트리, `GATEWAY_PII=mask`·인젝션 관측)를 라우터 앞에 띄우고, API × 모델 조합마다 네 가지를 **3번씩** 보낸다.
   - **E** 되풀이(비스트리밍): "아래 연락처를 고치지 말고 그대로 다시 적어 주세요" + 합성 전화·메일. **S** 같은 요청을 스트리밍으로. **T** 도구 호출을 강제해(`save_contact(phone, email)`) 인자를 본다. **M** 2턴 — E의 답을 이력에 붙이고 "메일 주소만 한 번 더".
   - 조합(기본 — 라우터의 `/v1/models`에 없는 모델은 건너뛰고 기록한다): chat `gpt-5.4-mini`·`gemini-3.5-flash`·`claude-haiku-4.5`, responses `gpt-5.4-mini`, messages `claude-haiku-4.5`(Anthropic용 키가 있을 때만).
2. **보내는 것**: 정상 업무 문장과 합성 값(전화 `010-2345-6789`, 예약 도메인 메일)뿐이다. 공격 문장·실제 개인정보를 보내지 않는다(공통 규칙 8). 보내기 전에 스크립트가 문장의 탐지 결과가 전화·메일 하나씩인지 확인한다.
3. **성공 기준**(조합마다):
   - **P1** 200이 아닌 응답 0건 — 가림이 요청을 망가뜨리지 않는다(게이트웨이 5xx, 상류의 형식 거절 4xx 모두 미달).
   - **P2** 모든 요청의 감사 줄에 `pii_issued` ≥ 2 — 전화와 메일이 가짜 값으로 나갔다.
   - **P3** 답(또는 도구 인자)에 **가짜 값이 남은 요청 0건**(`pii_suspect` = 0).
   - **P4** 모델이 값을 되풀이한 요청(E·S·M)과 인자에 옮긴 요청(T) 가운데 **원래 값이 온전히 돌아온 비율 ≥ 2/3**. 모델이 값을 아예 적지 않은 요청은 '되풀이 안 함'으로 따로 세고 분모에서 뺀다 — 분모가 0이면 그 검사는 '판정 불가'.
   - 넷 다 넘은 조합은 '통과', 하나라도 미달이면 '미달'(무엇이 미달인지 적는다). 전체 판정은 조합별 표다 — 한 조합의 미달이 다른 조합을 미달로 만들지 않는다.
4. **비용 상한**: 요청 최대 90건(5조합 × (E 3 + S 3 + T 3 + M 3×2)), 요청당 출력 512토큰 이하 → 출력 약 4.6만 토큰 이하. 넘으려 하면 멈춘다. 라우터 잔액(`/v1/credits`)을 앞뒤로 읽어 숫자만 적는다(읽히면).
5. **기록**: `docs/verification/real_providers_router.jsonl`·`.md` — 요청마다 상태·판정·감사 줄의 개수·토큰 사용량. **답 본문·키는 남기지 않는다.**
6. **순서**: 이 등록이 커밋된 뒤, 키가 `.env`(`MONOROUTER_KEY`, 선택 `MONOROUTER_ANTHROPIC_KEY`)에 있을 때만 실행한다. 그 전에는 `--stub`(스텁 상류, 비용 0)로 배선만 본다.

### 3. 버린 대안

- **SDK 점검 스크립트(`check_openai_sdk.py` 등)를 그대로 실 공급자에**: 인젝션 차단 항목이 있어 설정이 어긋나면 공격 문장이 밖으로 나간다.
- **인젝션 평가·공격 문장 생성에 쓰기**: 공통 규칙 8과 D-128의 '공격 문장을 LLM으로 만들지 않는다'에 어긋난다.
- **공급자 직접 키로**: 키가 없다. 라우터 경유의 차이는 한계에 적는다.
- **반복 수를 늘리기**: 질문은 '되는가'이지 비율의 정밀 측정이 아니다. 미달이 나오면 그 조합만 다시 본다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| V1 | `--stub`으로 세 API × 네 검사가 끝까지 돌고 모두 통과로 판정한다(배선·파싱·판정 코드) | `tests/test_d133_real_providers.py` |
| V2 | 판정 함수의 경계 — 가짜 값이 남으면 미달, 되풀이 안 함은 분모에서 빠짐, 200이 아니면 미달, 2/3 경계 | 같은 파일 |
| V3 | 실제 실행 결과를 §6에(조합별 통과·미달, 비용) | 등록 커밋 뒤 — 다음 세션 |
| — | 전체 `pytest -q`·`ruff check .`·`mypy` 통과 | |

### 5. 한계

- **라우터 경유다** — 공급자 직결과 다를 수 있다(프롬프트 캐시·thinking 서명·오류 형식·모델 이름). '실제 모델이 가짜 값을 어떻게 다루는가'는 보지만 '공급자 API와의 완전한 호환'은 아니다.
- 라우터는 요청을 기록할 수 있다(콘솔에 콘텐츠 로깅 설정이 있다) — 합성 값만 보내는 이유다.
- 3회 반복은 작은 표본이다. 모델 판과 라우터의 라우팅은 실행 시점의 것이다.
- Gemini 고유 API(`generateContent`)는 게이트웨이가 지원하지 않는다 — OpenAI 호환 경로로 부른 Gemini 모델만 본다.

### 6. 결과 (2026-11-10)

- **실행**: 등록 커밋 `c87db8d`(푸시됨) 뒤, 그 커밋의 게이트웨이 코드(지문 `6e2881c16420` — `gateway/`는 등록 뒤 바뀌지 않았다)로 `scripts/check_real_providers.py`를 **기본값 그대로 한 번** 돌렸다(2026-11-10 02:14 UTC).
  조합 다섯이 모두 라우터의 모델 목록에 있어 건너뛴 것이 없고, 요청 **60건**(상한 90 — M은 E의 답을 이력으로 쓰므로 한 건씩), 입력 8,454·출력 4,428토큰(감사 줄 `usage` 합), 라우터 `used_credits` 0 → 1,074(라우터 단위 그대로).
  이 실행 밖의 유료 호출은 없다. 기록: `docs/verification/real_providers_router.{md,jsonl}`(상태·판정·감사 줄 개수·토큰만 — 답 본문·키 없음).
- **판정 — 다섯 조합 모두 통과**:

  | API | 모델 | P1 200만 | P2 가림 | P3 가짜 값 0 | P4 복원 E·S·T·M |
  |---|---|---|---|---|---|
  | chat | `gpt-5.4-mini` | ○ | ○ | ○ | 3/3·3/3·3/3·3/3 |
  | chat | `gemini-3.5-flash` | ○ | ○ | ○ | 3/3·3/3·3/3·3/3 |
  | chat | `claude-haiku-4.5` | ○ | ○ | ○ | 3/3·3/3·3/3·3/3 |
  | responses | `gpt-5.4-mini` | ○ | ○ | ○ | 3/3·3/3·3/3·3/3 |
  | messages | `claude-haiku-4.5` | ○ | ○ | ○ | 3/3·3/3·3/3·3/3 |

- **무엇을 봤나**: 60건 모두 200, 감사 줄의 `pii_issued` 2(전화·메일이 가짜 값으로 나갔다), `pii_suspect` 0. E·S·T 45건은 `pii_restored` 2 — 모델이 가짜 값을 그대로 되풀이했고(스트리밍 포함),
  도구 인자(Chat `tool_calls`·Responses `function_call`·Messages `tool_use`)에 옮겨 적은 가짜 값도 게이트웨이가 되돌렸다. M 15건은 `pii_issued` 2·`pii_restored` 1 — 이력의 assistant 턴(복원된 원래 값)이
  사용자 턴과 같은 가짜 값으로 다시 가려져 나갔고(결정적 대체값 — 둘째 턴의 고유 값이 둘 그대로) 메일 하나가 돌아왔다. '되풀이 안 함'·'일부만'은 0건이라 P4의 분모는 모두 3이다. 같은 조합의 세 번은 답 길이까지 같았다.
- **눈에 띈 것**: `gemini-3.5-flash`는 요청당 출력 140~427토큰으로 다른 모델(8~64)보다 많다 — 답 글은 같은 길이라 사고 토큰으로 보인다(512 상한에 닿은 요청은 없다). Claude의 도구 호출(T)은 입력 750토큰이다(Chat·Messages 같다 — 공급자 쪽 도구 정의 비용).
  프롬프트 캐시 읽기는 0이다(짧은 요청 — 이 실행이 보는 것이 아니다).
- **한계**(§5에 더해): Chat 경로의 Claude·Gemini는 라우터가 공급자 형식으로 바꿔 보낸 것이다 — 공급자 API 직결·thinking 서명·프롬프트 캐시는 이 실행이 보지 않는다(Claude 직결의 서명·캐시는 D-114).
  모델이 값의 모양을 바꿔 적는 답(하이픈 빼기 등)은 이번에 나오지 않아 시험되지 않았다 — 그런 답은 D-113의 의심 잔여(`pii_suspect`)로 세는 경로이고 스텁 테스트로만 봤다. 3회·한 시점·한 라우터의 결과다.
- **문서**: 백서 6절·`docs/api-compat.md` '상류'·README 두 언어·설명서(HTML·PDF)·CHANGELOG 0.2.0에 '라우터 경유 다섯 조합 통과'를 적었다.

## D-134. 의존성 올림 첫 묶음(dependabot #4~#13) — uvicorn·python-dotenv·ruff·액션 둘은 올리고 FastAPI 0.162·transformers는 보류 (2026-11-10, PLAN 20단계 뒤 — 사용자 할 일 'dependabot')

### 1. 근거

- dependabot(D-130)이 첫 실행(2026-11-10, `c87db8d` 푸시 직후)에서 PR 10개를 열었다. 세션이 GitHub API로 제목·바뀐 파일·릴리스 노트를 읽었다(사용자 할 일의 'PR 제목을 알려 주면'을 대신했다). 보안 공지(CVE·GHSA)를 단 PR은 없다 — 모두 기능·수정 판이다.
  #4 actions/setup-python 7.0.0 → 7.1.0(ci·detect) · #5 sigstore/cosign-installer 4.1.2 → 4.1.3(release — 기본 Cosign v3.1.4) · #6·#12 uvicorn 0.52.0 → 0.54.0 · #7·#11 fastapi 0.141.1 → 0.162.0 ·
  #8 python-dotenv 1.2.2 → 1.2.4 · #9·#13 transformers 5.22.1 → 5.22.2(`detect/requirements-train.txt`) · #10 ruff 0.17.3 → 0.17.4.
- **FastAPI 0.162.0을 설치해 확인한 것**(세션의 별도 venv, Python 3.14):
  ① 새 필수 의존성 `opentelemetry-api`(1.45.2)를 `import fastapi`만으로 읽는다. 환경변수 `OTEL_PROPAGATORS`가 설치되지 않은 전파기를 가리키면(예: `b3` — 메시·Zipkin 쪽 클러스터 전체 설정)
  `ValueError: Propagator b3 not found`로 **프로세스가 뜨지 못한다**(재현). 0.141.1은 OTel을 읽지 않아 영향이 없다.
  ② 내장 텔레메트리(`fastapi/telemetry`)가 기본으로 켜져 있다(tracing·metrics·logs). 프로세스에 전역 OTel 공급자가 있으면 요청마다 span에 `url.path`·`url.query`를 남긴다(민감 키 몇 개만 `REDACTED`, 나머지 값은 그대로) —
  게이트웨이는 쿼리 값을 일부러 남기지 않는다(D-109 B9: 접근 로그를 끈 이유). `FASTAPI_OTEL_AUTO_CONFIGURE=true`면 OTLP 내보내기를 스스로 붙인다.
  ③ 깨지는 변경 둘(폼의 bool 기본값, 쿼리·헤더 파라미터 모델의 extra)은 우리 코드가 쓰지 않는다 — 게이트웨이·사이드카·데모 웹은 `Request`·`Response`류만 쓴다.
  ④ 0.141.1의 Starlette 조건은 `starlette>=0.46.0`(상한 없음)이라, FastAPI를 묶어도 HTTP 층(Starlette) 수정은 이미지를 새로 빌드할 때 들어온다(오늘 풀면 1.10.0).
- **uvicorn 0.53**: 기본 `FORWARDED_ALLOW_IPS`가 `127.0.0.1,::1`이 됐다(#3119 — 설치본 `uvicorn/config.py`로 확인). 문서 넷(README 두 언어·configuration·Dockerfile 주석)이 '기본 127.0.0.1'이라고 적는다.
  HTTP/2(zttp)·zuvloop은 켜야 쓰는 기능이라 해당 없다. 그 밖에 `Connection: close` 토큰 목록 처리 수정.
- **transformers**는 학습 환경(`detect/requirements-train.txt`)에만 있다 — D-128 모델(5.22.1로 학습)과 학원 PC의 base 학습이 같은 환경이어야 같은 자로 비교된다(D-128 §6).

### 2. 결정

1. **올린다**: uvicorn 0.54.0(`pyproject.toml`·`detect/requirements.txt` — 게이트웨이와 사이드카가 같은 판), python-dotenv 1.2.4, ruff 0.17.4,
   actions/setup-python v7.1.0(`6d4fd22b…`), sigstore/cosign-installer v4.1.3(`756fe2d2…`). 액션은 GitHub API로 태그가 가리키는 커밋을 읽어 PR의 SHA와 대조했다(둘 다 같음).
2. **FastAPI는 0.141.1에 둔다**(#7·#11 보류). 다시 볼 때(PLAN 조건부 표): FastAPI 보안 공지가 나오거나 필요한 기능이 생기면 — 생성자 셋(게이트웨이·사이드카·데모 웹)에서 내장 텔레메트리를 끄고
   (`telemetry={"tracing": False, "metrics": False, "logs": False, "auto_configure": False}`), ①(`OTEL_PROPAGATORS` 기동 실패)을 문서와 시험에 넣은 뒤 올린다.
3. **transformers는 5.22.1에 둔다**(#9·#13 보류). 학습 환경을 바꾸려면 새 결정으로 한다(새 판으로 다시 학습하면 홀드아웃이 아니라 dev-eval·양성대조로 비교 — D-128 §2-4).
4. 문서의 `FORWARDED_ALLOW_IPS` 기본값을 `127.0.0.1,::1`(루프백뿐)로 고친다.
5. 받아들인 PR(#4·#5·#6·#8·#10·#12)은 이 커밋이 푸시되면 dependabot이 스스로 닫는다. 보류한 PR(#7·#9·#11·#13)은 사용자가 닫는다 — 닫은 판은 다시 열지 않고, 더 새 판이 나오면 새 PR이 온다(그때 이 기준으로 다시 본다).

### 3. 버린 대안

- **PR을 그대로 머지**: 사이드카 고정 목록 테스트(`tests/test_d125_ner.py`)·문서의 기본값이 어긋나고, FastAPI ①의 기동 실패 위험을 들인다.
- **FastAPI 0.162 + 생성자에서 텔레메트리 끄기**: ②만 막는다 — ①은 import 때라 생성자 인자가 닿기 전이다.
- **dependabot `ignore`로 FastAPI를 막기**: 보안 업데이트까지 가릴 수 있다. 판마다 PR을 보고 닫는 편이 낫다.
- **텔레메트리가 들어가기 전 마지막 FastAPI 판으로**: 그 판을 찾느라 판마다 설치·시험해야 하고 얻는 것(쓰지 않는 기능)이 없다.

### 4. 완료 기준

| # | 기준 | 어디서 |
|---|---|---|
| U1 | 새 판 환경(별도 venv — fastapi 0.141.1·uvicorn 0.54.0·python-dotenv 1.2.4·ruff 0.17.4, 전이 의존성은 오늘 풀린 판: starlette 1.10.0·pydantic 2.14.3·uvloop 0.23.0)에서 전체 `pytest`·`ruff check .`·`mypy` | 세션 |
| U2 | 사이드카 고정 목록이 `pyproject.toml`과 같은 uvicorn | `tests/test_d125_ner.py`(목록을 고친다) |
| U3 | 워크플로의 액션이 여전히 커밋 SHA + 태그 주석 | `tests/test_d130_release.py` R1(그대로) |
| U4 | 개발 환경 `.venv`를 새 고정 값으로 맞춘 뒤 전체 `pytest`·`ruff`·`mypy`, `pip check` | 세션 |

### 5. 한계

- FastAPI를 묶어 두는 동안 FastAPI 자체의 수정은 받지 못한다(Starlette 수정은 받는다).
- 전이 의존성(starlette·pydantic·uvloop 등)은 고정하지 않는다 — 이미지 빌드 때 풀리는 판이 바뀐다. 잠금 파일은 이 결정 밖이다.
- 이미지에서 uvicorn 0.54의 실제 기동은 CI(`docker`·`detect`의 이미지 작업)가 본다 — 세션은 Docker가 꺼져 있다. 사이드카 테스트는 uvicorn을 띄우지 않는다.

### 6. 결과 (2026-11-10)

- **U1**: 별도 venv(Python 3.14.7 — fastapi 0.141.1·uvicorn 0.54.0·python-dotenv 1.2.4·ruff 0.17.4, 전이 의존성 starlette 1.10.0·pydantic 2.14.3·uvloop 0.23.0)에서 전체 `pytest` 926 통과·2 실패 —
  실패 둘은 프로젝트를 설치하지 않아 버전이 `0+unknown`이던 테스트였고 설치 뒤 2/2 통과. `ruff` 통과. `mypy`도 설치 뒤 통과(설치 전에는 `detect/`가 import하는 `eval/`을 소스로 보고 `eval/pii/score.py`에서 3건 — 설치한 환경·CI와 조건이 다르다).
- **U2·U3**: `tests/test_d125_ner.py`(고정 목록)·`tests/test_d130_release.py`(SHA + 태그 주석) 통과. 액션: setup-python v7.1.0 = `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0`,
  cosign-installer v4.1.3 = `756fe2d284c7292c4e9b62c8a28f1e5629c59532`(둘 다 태그가 커밋을 바로 가리킨다 — PR의 SHA와 같다).
- **U4**: `.venv`를 새 고정 값으로 맞추고(편집 설치 메타데이터 갱신, `pip check` 통과) 전체 `pytest` **928(+1 건너뜀)**·`ruff`·`mypy` 통과. `.venv-detect`의 uvicorn도 0.54.0 — 사이드카 테스트 23(+1 건너뜀) 통과(uvicorn을 띄우지 않는 테스트다).
- **문서**: `FORWARDED_ALLOW_IPS` 기본값 네 곳. 같은 날 CI(`c87db8d`)의 `detect`가 Intel Xeon 8370C 러너에서 veil 510토큰 p95 361ms를 쟀다 — AMD EPYC 러너(201.5ms)의 1.8배라
  문서 일곱 곳(README 두 언어·configuration·operations·백서·사이드카 README·설명서)과 PLAN 결정 표 7번의 '약 200ms'를 '약 200~370ms(CPU에 따라)'로 고쳤다(숫자는 D-125 §6). 설명서 PDF 22쪽 그대로, 바뀐 쪽 10·17·18·19.
- **계획과 다른 점**: 없음. **못 한 것**: 이미지에서 uvicorn 0.54 기동(CI 몫 — Docker 꺼짐), 보류 PR 닫기(사용자 — #7·#9·#11·#13).
- **푸시 뒤 CI**(2026-11-10, 세션이 `gh api`로 확인): `30700da`의 `ci` 네 작업(test 3.12·3.14·docker·secrets)과 `detect` 두 작업(image·detect) 모두 성공 —
  사이드카 이미지는 uvicorn 0.54로 실제로 떴고(`image` 작업의 `/health` 두 작업·`/v1/guard`), 게이트웨이 이미지는 빌드까지(`docker` 작업 — 게이트웨이의 uvicorn 0.54는 테스트가 스레드로 띄운다).
  받아들인 PR 여섯(#4·#5·#6·#8·#10·#12)은 푸시 2분 뒤 dependabot이 스스로 닫았다. 보류 넷은 열려 있고, #7·#11(FastAPI)은 새 main에 다시 맞춰져 `ci`가 실패한다(예상대로 — 고정 목록 테스트).
