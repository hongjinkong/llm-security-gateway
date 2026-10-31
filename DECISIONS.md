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
