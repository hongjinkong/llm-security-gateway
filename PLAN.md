# 상용화 실행 계획

이 파일이 계획의 원본이다. Claude Code에서 `/next-step`을 치면(또는 부록 B의 프롬프트를 붙여 넣으면) 아래 '진행 상황'에서 체크 안 된 첫 단계부터 이어서 진행한다.

- 출발점: 커밋 `34c16fb`(D-107 서비스 전환).
- 근거: 2026-10-30 상용화 검토. 리뷰 7영역 결함 91건, 코드 결함 28건 반박 검증(반박 0건), 핵심 4건 직접 재현. 요약은 부록 A.
- 목표 모양: 자체 호스팅 한국 PII 가명화 프록시. 파는 것은 '인젝션 차단'이 아니라 '밖으로 나가는 한국 개인정보를 같은 모양의 가짜 값으로 바꾸고 돌려받는, 증빙 가능한 프록시'다. Python·FastAPI는 유지한다.

## 진행 상황

**A. 정리와 긴급 수정**
- [x] 1. 제품 저장소로 정리 — 연구 산출물은 태그로, LICENSE·pyproject·CI
- [x] 2. 보안 경계 — 경로·헤더 허용 목록, 관리 엔드포인트, 컨테이너
- [x] 3. 가용성 — 볼트 제곱 시간, 탐지 상한, 스레드 오프로드, 상류 풀, 보류 상한

**B. 마스킹 재설계**
- [x] 4. 결정적 대체값 + 7단계 실측 사전 등록
- [x] 5. 마스킹 범위를 모든 역할로 + thinking 서명 보존
- [x] 6. 응답 필드별 복원 + 복원 가시화 + 안전한 가짜 값
- [x] 7. 실 공급자 2턴 확인(Claude, 비용 상한 $1)

**C. 한국 식별자**
- [x] 8. PII 평가 코퍼스 + CI 오탐 게이트(기준선)
- [x] 9. 정규화 + 오탐 축소
- [x] 10. 한국 식별자 확장

**D. 설정·운영**
- [x] 11. 설정 객체화 + 인프로세스 테스트 + mypy
- [x] 12. 설정 파일 + 상류 라우팅 + 클라이언트 정책
- [x] 13. 감사·관측·문구 카탈로그
- [x] 14. 배포 패키지 + 제품 문서
- [x] 15. 부하·안정성

**E. 탐지 모델**
- [x] 16. 한국어 평가셋 v1 + 기준선
- [ ] 16-1. 운영 대시보드(읽기 전용) — 시험 중 요청마다 무엇을 가리고·막고·거절했는지 보기
- [ ] 17. 탐지 사이드카 + 한국어 PII NER(채택 게이트)
- [ ] 18. 인젝션 분류기(관측) + 가드레일 웹훅

**F. 출시**
- [ ] 19. 보안 백서 + 법적 위치 메모 + PoC 키트
- [ ] 20. 릴리스 공정
- [ ] 21. 공개 데모(선택)
- [ ] 22. 디자인 파트너 PoC + 가격 + v1.0

## 진행 기록

단계를 끝내거나 중간에 멈출 때마다 한 줄씩 붙인다.

| 날짜 | 단계 | 결정 | 결과 | 다음에 이어갈 곳 |
|---|---|---|---|---|
| 2026-10-30 | — | — | 계획 작성 | 1단계 처음부터 |
| 2026-10-30 | 1 | D-108 | pytest 379(3.14·3.12)·ruff 통과, 추적 3.2MB, `research-final` 태그(로컬). 제품 테스트는 계획 추정 410이 아니라 379개 | 2단계 |
| 2026-10-30 | 2 | D-109 | B1~B8·pytest 386(3.14·3.12)·ruff·SDK 8/8·6/6 통과. 공유 httpx 쿠키 저장소 누수를 찾아 고침. 계획과 다른 점: 인증이 켜져 있으면 상류 키가 없어도 클라이언트 인증 헤더를 넘기지 않음 | 3단계 |
| 2026-10-30 | 3 | D-110 | V1~V7·pytest 397·ruff 통과. 전화 5,000개 0.19초, 168자 키·PEM 스트림 복원, 풀 503·볼트 503·응답 502 | 4단계 |
| 2026-10-30 | 4 | D-111 | R1~R5·pytest 410·ruff 통과. HMAC 시드 결정적 대체값, 키 없으면 mask 기동 실패. 7단계 실측을 D-111 §6에 사전 등록(커밋 전 — 7단계는 이 커밋 뒤) | 5단계 |
| 2026-10-30 | 5 | D-112 | M1~M4·pytest 425·ruff 통과. system·tool·문서까지 마스킹, thinking·reasoning 무변경(JSON 문자열 단위 복원) | 6단계 |
| 2026-10-30 | 6 | D-113 | F1~F5·pytest 437·ruff 통과. 인자 텍스트 복원+안쪽 이스케이프, x-gateway-pii·pii_suspect, 예약 이메일 도메인. 스트림 PEM 보류 결함 2건 수정 | **7단계 — D-111 사전 등록이 커밋된 뒤에만**(사용자 커밋 대기) |
| 2026-10-30 | 1·2 보강 | D-108·D-109 | 1~6단계 커밋 `4c1731c` 뒤, Docker를 켜고 로컬 이미지 빌드·컨테이너 확인 통과. uvicorn 접근 로그의 쿼리 값 누출을 찾아 `--no-access-log`로 고침(B9) | 7단계 처음부터(사전 등록 D-111 §6이 `4c1731c`에 있다) |
| 2026-10-30 | 7 | D-114 | 사전 등록(D-111 §6) 그대로 실행, 성공 기준 충족. `claude-haiku-5-5` 2턴 대화 팔마다 5개: 새 코드 둘째 턴 400 0/5·캐시 읽기 5/5·복원 5/5, 옛 코드 5/5가 서명 400(prefix 불일치), 비용 $0.013. 턴 1은 10건 모두 `max_tokens`(1024)에서 잘려 턴 1 답의 복원은 시험되지 않음. pytest 438·ruff 통과 | 8단계 |
| 2026-10-30 | 8 | D-115 | E1~E4·pytest 442·ruff 통과. 합성 코퍼스(양성 500·음성 1,000·어려운 사례 27) 기준선: 재현율 rrn·card·email·secret 100, phone 96(070 놓침), 오탐 card 117(IMEI 100/100)·rrn 6(국내 바코드·13자리 송장)·전체 123/1000. 게이트는 목표 또는 기준선. 계획과 다른 점: 카드의 Luhn 실패 군은 두지 않음(정답을 정할 수 없다), 10단계에 070 추가 | 9단계 |
| 2026-10-30 | 9 | D-116 | N1~N8·pytest 473·ruff 통과, 데모·Anthropic SDK 재통과. 코퍼스 오탐 123 → 3(0.3%), 재현율 496 → 494(rrn 98 — 문맥 없는 약한 13자리는 감사만, 검증식 통과 55/55), 어려운 사례 양성 8 → 14/17. 계획과 다른 점: 발급사 목록에 Discover·Diners·국내 전용 9, rrn 재현율 목표는 검증식 통과 값에 | 10단계 |
| 2026-10-30 | 8 보강 | D-115 | 커밋 `0daf559` 푸시가 GitHub push protection에 막힘 — 코퍼스의 합성 Slack 토큰 8건이 실제 형식. 생성기가 6자 묶음으로 다시 잘라 8줄만 바뀜, 점수·게이트 그대로. 그 커밋은 원격에 없으므로 고친 파일로 amend한 뒤 푸시 | 10단계 |
| 2026-10-30 | 10 | D-117 | K1~K9·pytest 586·ruff 통과, 데모·Anthropic SDK 재통과, 코퍼스·점수 3.12=3.14. 새 종류 frn·passport·driver(가림)·brn·crn·account·ipv4(기본 감사만, `GATEWAY_PII_DETECT_KINDS`)와 070. 코퍼스 양성 1,200·음성 1,200(앞 1,500줄 그대로): 오탐 3(0.2%), phone 96 → 100, 문맥에 달린 passport 80·crn 89·account 64. 1MiB 0.19초(N8 글). 계획과 다른 점: 사업자·법인·IPv4도 기본 감사만, 구분자 없는 꼴·지역명 면허는 넣지 않음(탐지는 모양만 — 문맥으로만 찾으면 응답의 대체값을 못 되찾는다) | 11단계 |
| 2026-10-30 | 11 | D-118 | C1~C6·pytest 599·ruff·mypy 통과, 데모·Anthropic SDK 재통과. `Settings.from_env`·`create_app`, main 660 → 260줄(settings·relay·audit로 나눔), `.env` 자동 로드 제거, `GATEWAY_INJECTION_SCOPE`·`GATEWAY_CHAT_UPSTREAM_PATH`·`GATEWAY_DETECTORS` 환경변수 제거, CI에 mypy. 테스트 69초 → 18초. 계획과 다른 점: ASGITransport 대신 스레드 uvicorn(스트리밍 그대로·테스트 호출부 무변경), 저수준 검사기 목록은 `Settings.detectors`로만 | 12단계 |
| 2026-10-30 | 12 | D-119 | G1~G7·pytest 623·ruff·mypy 통과. `GATEWAY_CONFIG`(TOML): 클라이언트별 정책(인젝션·PII·허용 모델 403), API별 상류(`key_env`), 해시 키(`keygen --hash`), info·감사 줄의 `config`·`policy`. `scripts/check_sdks.py`로 OpenAI SDK 8/8·Anthropic SDK 6/6이 한 게이트웨이에서 함께 통과(상류 분리 확인). 계획과 다른 점: 상류 표 이름은 어댑터(chat·responses·messages), 파일의 상류는 `key_env` 없이는 키를 달지 않음 | 13단계 |
| 2026-10-30 | 13 | D-120 | O1~O5·pytest 639·ruff·mypy 통과, 두 SDK(한 게이트웨이)·데모 재통과. 감사 줄 `model`·`usage`(세 API × 스트리밍, Chat 스트림은 include_usage 주입·조각 숨김), `pii_new`·`gateway_pii_new_total`(출력 방향 관측), 상류 헤더 `x-gateway-request-id`, 문구 카탈로그 `GATEWAY_LANG=ko|en`. 계획과 다른 점: client·api·config는 이미 있었음, API 오류 본문은 영어 그대로 | 14단계 |
| 2026-10-31 | 14 | D-121 | S1~S4·pytest 658(3.14·3.12)·ruff·mypy 통과. compose(게이트웨이 읽기 전용 + 스텁 파일 마운트)에 OpenAI SDK 8/8·Anthropic SDK 6/6, k8s kustomize 렌더가 kubernetes-validate `--strict`(1.37·1.28) 통과, 견본 설정이 읽기 전용·uid 10001 컨테이너에서 기동. 문서 configuration·operations·api-compat·SECURITY·README.en, 동기화 테스트(변이 7/7). 1MiB 요청 동시 50건 최대 256MiB·23.5초(워커 1). 계획과 다른 점: kustomize 생성기(설정·키 변경 = 롤링 재시작), 클라이언트 키는 해시로 ConfigMap, 빈 `key_env` 값도 기동 실패, 실제 클러스터는 미확인(컨텍스트 없음) | 15단계 |
| 2026-10-31 | 15 | D-122 | L1~L5·pytest 670(3.14·3.12)·ruff·mypy 통과. 동시 100(스트림 50 + 비스트리밍 50) 60초: 13,367건·오류 0·모두 실제 마스킹, 게이트웨이 경유 지연이 스텁 직접과 같음(비스트리밍 p95 362 vs 352ms), 감사 gateway_ms p95 18.5ms. 30분 soak(연결 80으로 대기 경로까지): 323,416건·판정 10/10·RSS −2.4%. 찾아 고친 것: httpcore 1.0.9 공유 풀 결함(처리량 1/4 — 연결 하나짜리 클라이언트를 빌려 쓰는 `UpstreamPool`), 클라이언트 끊김 때 세션·감사 줄 누수(anyio 취소 → 막고 정리), 다차원 리뷰+반박 검증 35건 전부 수정(회귀 테스트 되돌리기 7/7). 계획과 다른 점: 지표 둘(정책별 세션·빌려 간 연결), k8s `UVICORN_TIMEOUT_KEEP_ALIVE=75`, 종료 유예 35초 | 16단계(D-123 결정 적음, 빌드 워크플로 진행 중) |
| 2026-10-31 | 16 | D-123 | E1~E5·pytest 678(3.14·3.12)·ruff·mypy 통과. 평가셋 v1 6,871행(dev 5,492·봉인 홀드아웃 1,379 — SHA-256 결정·테스트에 고정), 한국어 공격 2,028·정상 2,608, 하드 네거티브 29%. 룰 기준선(dev) 재현율 8.7%(한국어 5.9%)·오탐률 2.7%(일반 정상 0%·하드 네거티브 9.2%), recall@FPR 1% 미달. 데이터셋 조사(에이전트 36, 라이선스·리비전 확인)·한국어 정상 문장 작성·검증(에이전트 23)·리뷰+반박 검증(에이전트 74, 31건 수정 — 홀드아웃 가족 누수 12%·in-the-wild 번역 포함 등). 계획과 다른 점: 공개 한국어 정상셋을 함께 씀, ko-jailbreak·jackhhao 뺌, 한국어 다중 턴 없음, datasets-server 출처는 받은 날짜+저장소 고정 | 17단계 |
| 2026-10-31 | — | — | 계획 변경: 16-1단계 추가(사용자 요청). 설명서 화면 C를 제품 안 읽기 전용 대시보드(`/__gateway/dashboard`·`/__gateway/stats`, 관리 키)로 만든다 — 요청마다 결과·사유가 보이는 최근 요청 표, 시험 트래픽 `scripts/traffic.py`(16장면, 스스로 대조, `--shot` 스크린샷). 선행 수정으로 FastAPI 기본 문서 경로(`/docs`·`/redoc`·`/openapi.json` 무인증 200, 재현)를 없앤다. 설계는 독립 설계 3개 → 종합 → 코드 대조·실행 가능성 검토 2개(지적 22건 반영). 16단계 커밋에 든 설명서 PDF(docs/overview)의 화면 C·7장도 이 단계에서 실제 화면으로 고친다. 17~22 번호는 그대로 | 16-1단계 |

## 사용자 할 일

세션이 대신할 수 없는 일이다. 세션은 여기에 붙이고, 사용자는 끝나면 체크한다.

- [ ] (1단계 전, 선택) 결정 표를 훑어보고 바꿀 값이 있으면 표만 고친다.
- [ ] (언제든) 디자인 파트너 후보 1곳을 찾는다. 22단계의 전제다.
- [x] (1단계) `git push origin research-final` — 원격에 있음(2026-10-30 확인).
- [x] (7단계 전) 1~6단계를 커밋·푸시한다 — `4c1731c`, origin/main(2026-10-30 확인). D-111 §6 사전 등록이 커밋됐으므로 7단계를 할 수 있다.
- [x] (7단계 전) `.env`에 `ANTHROPIC_API_KEY`가 있는지 확인 — 2026-10-30 세션이 있음을 확인(값은 출력하지 않음).
- [ ] (1단계, 선택) 죽은 브랜치 `codex/*` 3개를 로컬·원격에서 삭제, GitHub 저장소 설명을 제품 설명으로 변경.
- [x] (9단계 뒤, 선택) OpenAI SDK 점검 — 2026-10-30 세션이 처리했다(PyPI가 열려 있었다). 점검용 venv의 `python`은 3.9라 `/tmp/sdkvenv/bin/python -m pip install openai`로 깔아야 한다(`bin/pip`은 3.14 쪽). 8/8 통과.
- [x] (14단계 전, 선택) Docker Desktop을 켜 두고 `kubectl`을 설치해 둔다 — 2026-10-31 확인: Docker 29.9.2 실행 중, kubectl v1.36.1 있음.
- [ ] (선택) Docker Desktop 설정 → Kubernetes → Enable Kubernetes(`docker-desktop` 컨텍스트가 생긴다). kubectl은 `--dry-run=client`에도 서버 탐색이 필요해 컨텍스트가 없으면 `--validate=false`로도 실패한다(2026-10-31 확인). 14단계(D-121)는 클러스터 없이 kustomize 렌더 + 스키마 검증으로 끝냈다 — 켜 두면 다음 세션이 `kubectl apply -k deploy/k8s --dry-run=server`와 실제 배포를 확인한다.
- [ ] (14단계 뒤) GitHub 저장소 Settings → Code security → **Private vulnerability reporting** 켜기 — `SECURITY.md`가 제보 경로로 가리킨다(켜기 전에는 그 링크가 열리지 않는다).

## 결정 표

기본값으로 바로 진행한다. 바꾸고 싶으면 그 단계를 시작하기 전에 이 표의 값만 고친다.

| # | 결정 | 기본값 | 쓰이는 단계 |
|---|---|---|---|
| 1 | 라이선스 | Apache-2.0 | 1 |
| 2 | 저장소 | 이 폴더를 그대로 제품 저장소로 쓴다. 연구는 `research-final` 태그로 보존한다. 메모리·원격·CI가 그대로 이어진다. 히스토리가 남아 클론 크기는 줄지 않는다(조건부 표 참고) | 1 |
| 3 | 배포 이름 | `llm-security-gateway`. import 이름은 `gateway` 그대로 | 1 |
| 4 | 복원 매핑 보관 | 요청 단위 메모리 + 대체값 키만. 원문은 어디에도 저장하지 않는다. `previous_response_id`·서버 저장 대화는 미지원 | 4, 14 |
| 5 | 대상 고객 | 외부 LLM API로 고객 데이터를 다루는 국내 B2B 개발팀(50~300명)·금융권 협력 핀테크. 자체 호스팅 | 14, 19, 22 |
| 6 | 인젝션 | 관측 + 외부 가드레일 웹훅. 자체 모델 학습은 하지 않는다. 분류기 기본 후보는 protectai/deberta-v3-base-prompt-injection-v2 | 18 |
| 7 | NER 게이트 | x86 CPU p95 +40ms 이하, F1 0.85 이상. 미달이면 v1.0에서 뺀다 | 17 |
| 8 | 대체값 키 | 환경변수(K8s Secret) 하나. 회전은 수동이고 문서화한다. 법률 검토 전까지 PIPA '추가정보'로 취급 | 4, 19 |
| 9 | 가격 | 코드는 전부 공개 라이선스. 유료는 배포 단위 연간 계약(지원 SLA·컴플라이언스 문서·설치와 PoC 지원), 연 수백만~2천만 원대(추정). 좌석·토큰 과금 없음 | 22 |
| 10 | 언어 | 한국어 기본, 영문 병행(`README.en.md`, `GATEWAY_LANG=en`) | 13, 14 |
| 11 | 커밋 | 세션은 커밋하지 않고 명령만 준다. 여러 단계를 이어서 했으면 커밋 하나에 결정 번호를 모두 적는다 | 전부 |
| 12 | 실 공급자 비용 | 단계마다 상한을 결정에 적는다(7단계 $1). 정상 요청·합성 PII만 | 7, 16 |
| 13 | 운영 대시보드 | 게이트웨이 안 읽기 전용 화면 `/__gateway/dashboard`. 데이터는 `/__gateway/stats`, 관리 키 Bearer로 연다 — 키는 탭의 sessionStorage에만 두고 URL·쿠키에는 두지 않는다. 숫자는 프로세스(파드) 하나의 누적 + 최근 요청 200건(원문·가짜 값·위치·IP 없음), 2초마다 갱신, 한국어 화면에 코드 이름 병기. 쓰기 동작·로그인·원문 보기는 없다. 여러 파드 합산·장기 보관은 Prometheus·감사 로그 몫 | 16-1 |

## 모든 단계 공통 규칙

1. 시작할 때 `git status`·`git log -1`로 상태를 보고, 진행 기록 마지막 줄에서 이어갈 곳을 찾는다.
2. 결정 먼저. `DECISIONS.md`에 다음 번호(1단계가 D-108)로 근거·결정·버린 대안·완료 기준(테스트 표)·한계를 적고 시작한다. 끝나면 결과 절에 한 것·수치·못 한 것을 채운다. 1단계 이후 옛 결정은 `git show research-final:DECISIONS.md`로 본다.
3. 완료 기준의 명령을 직접 돌려 통과시킨다. 단계 끝에는 전체 `pytest -q`가 초록이어야 한다(1단계 이후 `ruff check .`도).
4. 계획과 코드가 다르면 코드를 기준으로 판단하고, 이 파일을 고친 뒤 진행 기록에 한 줄 남긴다.
5. 세션은 커밋하지 않는다. 마지막 답에 `pytest -q`, `git add`, `git commit`, `git push`를 코드 블록 하나에 한 줄씩, 주석 없이 준다.
6. `git fetch`·`pull`·`push`는 실행하지 않는다(샌드박스에서 멈춘다). 설치·다운로드가 네트워크 때문에 막히면 사용자에게 `! 명령` 형식으로 준다.
7. 실 공급자(유료) 호출은 그 기준을 적은 결정이 커밋된 뒤에만 한다(사전 등록). 등록만 하고 아직 커밋 전이면 거기서 멈춘다.
8. 공격 프롬프트를 외부 공급자에 보내지 않는다. 실제 개인정보는 쓰지 않는다(합성만). 키·토큰을 출력하지 않는다.
9. 사용자 몫 항목은 하지 않고 '사용자 할 일'에 붙인다. 단계의 남은 일이 사용자 몫뿐이면 그 단계를 체크하고 다음 단계로 간다.
10. 한 단계를 끝내면 다음 단계로 이어간다. 멈추는 때는 셋이다. 사전 등록 커밋이나 사용자 몫을 기다릴 때, 사용량 한도가 가까울 때, 풀지 못한 실패가 있을 때. 멈출 때는 테스트가 초록인 지점에서 체크박스와 진행 기록에 이어갈 곳을 남긴다.

## 단계

### 1. 제품 저장소로 정리

목표: 작업 트리에는 제품만 남긴다. 연구 기록은 태그로 보존한다. 누구나 합법적으로 설치하고 CI가 품질을 지킨다.

할 일
- [x] 정리 직전 커밋에 주석 태그 `research-final`을 단다.
- [x] 트리에서 뺀다(태그에 남는다): `results/` `garak/` `target/` `docs/`(제품 README가 쓰는 `docs/demo.gif`만 남김) `eval/`(`eval/benign/all100.jsonl`만 남김) `SCOPE.md` `EVAL_CRITERIA.md` `DECISIONS.md` `docker-compose.yml` `requirements.txt` `.github/workflows/cpu-tests.yml` `gateway/.gitkeep`.
- [x] `scripts/`는 `check_openai_sdk.py` `check_anthropic_sdk.py` `demo.py`만 남긴다.
- [x] 연구 하네스 테스트 19개를 뺀다: test_canary test_canary_fn_scan test_canary_k test_ci_junit_check test_ci_readme_sync test_cluster_ci test_d090 test_d094 test_fpr_link_time test_fpr_report test_matched_baseline test_multiturn_run test_night_chain_oa test_openai_compose test_paired_arms test_rescore_blocking test_setup_target test_validate_encoding test_validate_oa_arm. 남는 제품 테스트 17개와 도우미(`conftest.py`·`stub_target.py`·`chain_app.py`)가 통과해야 한다.
- [x] 새 `DECISIONS.md`: 머리말 한 단락(D-001~D-107은 `research-final` 태그에 있다) + D-108(이 단계).
- [x] `LICENSE`: 결정 표 1번. Apache-2.0이면 원문을 그대로 복사한다. 오프라인 원문이 `.venv/lib/python3.14/site-packages/packaging-26.2.dist-info/licenses/LICENSE.APACHE`에 있다(첫 줄이 `Apache License`, `Version 2.0, January 2004`인지 확인).
- [x] `pyproject.toml`: 이름(결정 표 3번), 버전 0.1.0, `requires-python = ">=3.12"`, 의존성은 지금 `requirements-gateway.txt`의 고정 버전 4개 그대로, `dev` 추가 의존성(pytest·ruff), ruff·pytest 설정. `requirements-gateway.txt`는 지우고 Dockerfile은 `pip install .`으로.
- [x] `gateway/version.py`에 패키지 버전을 노출한다(`importlib.metadata`). 코드 지문은 그대로 둔다.
- [x] `CHANGELOG.md`(0.1.0), `.dockerignore`(.git·.venv·logs·tests·__pycache__ 등).
- [x] CI `.github/workflows/ci.yml`: Python 3.12·3.14에서 `pip install -e ".[dev]"` → `ruff check .` → `pytest -q`, 그리고 `docker build -f gateway/Dockerfile .`. 액션은 지금 워크플로의 SHA 고정을 그대로 쓴다.
- [x] ruff는 기본 규칙(E·F)부터 켠다. 걸리는 것은 고치거나 그 규칙만 좁힌다. 전체 서식 변경은 하지 않는다.
- [x] README를 제품 중심으로 줄인다: 무엇을 하나·막지 못하는 것·실행·설정·구조·라이선스. 연구 수치(3절)와 측정 장치(4절), 코드 지문 문구는 빼고 `research-final` 태그를 가리키는 한 줄을 둔다.
- [x] `.env.example`에서 연구용 변수(TARGET_API_KEY·WORKSPACE_SLUG·CANARY_*·ANYTHINGLLM_* 등)를 뺀다.
- [x] `PLAN.md`와 `.claude/commands/next-step.md`를 커밋 대상에 넣는다.

완료 기준
- `pytest -q` 전부 통과, `ruff check .` 통과
- `git ls-files -z | xargs -0 du -ch | tail -1`이 5MB 미만
- `git show research-final:DECISIONS.md | head -3`이 옛 결정 기록을 보여 준다
- Docker가 있으면 `docker build -f gateway/Dockerfile .` 성공(없으면 CI가 확인)

사용자 몫: `git push origin research-final`, (선택) 죽은 브랜치 `codex/*` 3개를 로컬·원격에서 삭제, (선택) GitHub 저장소 설명 변경.

근거: 추적 용량의 98%(약 1GB)가 `results/`다. LICENSE·pyproject가 없어 법적으로 쓸 수 없다. CI는 pytest 한 단계이고 `tests/test_ci_readme_sync.py`가 CI 확장을 실패로 만든다. 723개 테스트 중 제품 검증은 410개다.

### 2. 보안 경계

목표: 게이트웨이 키 하나로 운영자 공급자 계정 전체를 쓰는 길을 닫는다.

할 일
- [x] 경로 허용 목록: `POST /v1/chat/completions` `POST /v1/responses` `POST /v1/messages` `GET /v1/models`만 받는다. 그 밖의 경로·메서드는 404이고 상류에 연결하지 않는다. `gateway/main.py`의 캐치올 라우트(`/{full_path:path}`)를 없앤다.
- [x] 어댑터 없는 옛 경로를 지운다: `detectors/pii.py`의 `doc is None` 분기와 그 도우미(`_session_spans`·`_outside`, 쓰는 곳이 없어지면 `normalized_text`), `detectors/injection.py`의 `user_text`·`USER_FIELDS`, `_relay`의 AnythingLLM 형식 차단 응답.
- [x] 카나리 검사기를 지운다: `detectors/canary.py`, `GATEWAY_CANARY_*`, health의 `canary_fp`, 관련 테스트. `detectors/noop.py`는 테스트만 쓰면 `tests/`로 옮긴다.
- [x] 상류 키는 허용 경로에만 붙는다(`gateway/auth.py`의 `upstream_headers`).
- [x] 요청 헤더 허용 목록: content-type·accept·user-agent·anthropic-version·anthropic-beta·openai-beta·idempotency-key. 상류 키 모드에서는 클라이언트의 인증 헤더와 openai-organization·openai-project를 떼고, 상류 키가 없는 통과 모드에서는 openai-organization·openai-project를 넘긴다. cookie·x-forwarded-*는 항상 뗀다.
- [x] 응답 헤더 허용 목록: content-type·cache-control·retry-after·retry-after-ms·x-should-retry. 게이트웨이 자신의 `x-gateway-*`는 그대로. 상류 request-id(x-request-id·request-id)는 클라이언트에 넘기지 않고 감사 줄 `upstream_request_id`에 적는다.
- [x] `GATEWAY_AUTH=off`인데 `GATEWAY_UPSTREAM_KEY`가 있으면 기동 실패.
- [x] `/__gateway/health`는 인증 없이 `{"status": "ok"}`만 준다. 상세(target·code·detectors)는 `/__gateway/info`로 옮기고, 그것과 `/__gateway/metrics`는 `GATEWAY_ADMIN_KEY` Bearer가 맞을 때만 응답한다(관리 키가 없으면 404).
- [x] `gateway/Dockerfile`: 비root `USER`, 베이스 이미지 다이제스트 고정(Docker Hub에서 조회), `HEALTHCHECK`, `--workers 1` 제거(uvicorn이 기본으로 읽는 `WEB_CONCURRENCY`로 조절), `--timeout-graceful-shutdown 25`, `--limit-concurrency`(스트림이 오래 열려 있으므로 넉넉히), 낡은 주석(garak·볼트 워커) 정리. 프록시 신뢰는 uvicorn의 `FORWARDED_ALLOW_IPS`로 한다고 문서에 적는다.

완료 기준
- `DELETE /v1/files/x`, `POST /v1/fine_tuning/jobs`, `GET /v1/organization/users` → 404이고 스텁 상류 수신 0건
- `GET /v1/models` → 스텁 상류가 상류 키를 받는다
- 상류 키 모드에서 클라이언트의 `Cookie`·`OpenAI-Organization`이 상류에 닿지 않고, 상류의 `openai-organization` 응답 헤더가 클라이언트에 닿지 않는다
- `GATEWAY_AUTH=off` + 상류 키 → 기동 실패(종료 코드가 0이 아님)
- 무인증 health는 status만, 관리 키 없는 metrics·info는 404
- 전체 pytest·ruff 통과

근거: 캐치올이 메서드 7개를 받고 경로와 무관하게 상류 키를 단다(검증자 재현: 파일 삭제·파인튜닝·조직 API가 상류 키로 도달). 헤더는 요청 3개·응답 4개만 뗀다(`main.py:217·220`). 무인증 health가 상류 주소·검사기 구성·8자리 카나리 지문을, metrics가 PII 처리량을 공개한다. 세 POST 경로 밖은 검사 없이 통과하고 multipart 본문이 깨진다.

### 3. 가용성

목표: 요청 한 건이 게이트웨이 전체를 멈추지 못하게 한다.

할 일
- [x] `gateway/vault.py`의 `token_for`: 새 값마다 `taken` 집합을 다시 만드는 것을, 세션에 집합을 두고 발급할 때 넣는 방식으로 바꾼다(O(1)).
- [x] 요청당 탐지 상한 `GATEWAY_MAX_FINDINGS`(기본 5000). 넘으면 상류로 보내지 않고 413(어댑터 오류 형식). 가리지 못한 값을 내보내지 않는다.
- [x] 순수 함수(`find_all`·`match_rules`)만, 검사할 텍스트가 16KB를 넘을 때 `asyncio.to_thread`로 돌린다. 볼트 조작은 이벤트 루프에 둔다.
- [x] 상류 클라이언트: `httpx.Timeout(connect=5, read=GATEWAY_TIMEOUT, write=30, pool=5)`, `httpx.Limits(max_connections=100)`, 풀 대기 초과는 503 + `retry-after: 1`.
- [x] 스트리밍 보류 상한 = 이 요청에서 발급한 가장 긴 대체값 길이(16KB 상한). 고정값 `MAX_HOLD = 128`을 없앤다. D-107 결정문이 원래 이렇게 정했다.
- [x] 볼트 TTL을 `GATEWAY_TIMEOUT`보다 길게 하고, 스트림의 모든 이벤트(ping·thinking 포함)에서 세션을 갱신한다. 용량을 넘으면 진행 중 세션을 축출하지 말고 503.
- [x] 비스트리밍 상류 응답 크기 상한 32MiB, 넘으면 502.

완료 기준
- 볼트 발급 1,000개 대비 4,000개 시간 비가 8 미만(지금 약 14배: 0.50s → 6.84s)
- 고유 전화 5,000개 본문이 1초 안에 끝나고, 5,001개면 413이며 스텁 상류 수신 0건
- 168자 `sk-proj-` 대체값이 스트리밍 조각 경계에 걸려도 복원된다
- `Limits(max_connections=1)`로 띄우고 동시에 두 요청을 보내면 하나는 503
- 전체 pytest·ruff 통과

근거: 직접 재현값, 고유 전화 1,000/2,000/4,000개 → 0.50/2.19/6.84s. 같은 입력의 `find_all`은 20,000건에 0.05s라 병목은 볼트다. 168자 대체값의 보류 길이는 0이었다. 상류 타임아웃 600초가 연결·풀 대기에도 걸린다. 워커가 하나라 이 동안 health도 응답하지 못한다.

### 4. 결정적 대체값 + 7단계 실측 사전 등록

목표: 같은 원문은 언제나 같은 가짜 값이 되게 해서, 둘째 턴부터 이력 바이트가 바뀌지 않게 한다. Anthropic thinking 서명·프롬프트 캐시와 양립한다.

할 일
- [x] `GATEWAY_SURROGATE_KEY`: PII mask 모드면 필수(없으면 기동 실패). `python -m gateway keygen` 출력을 그대로 써도 된다.
- [x] `gateway/surrogate.py`: 모듈 전역 `_rng`(`secrets.SystemRandom`) 대신 생성기마다 `rng`를 받는다. 시드 = HMAC-SHA256(대체값 키, 종류 + "\0" + `norm_key(종류, 값)`), `random.Random(시드)`. 모양 규칙(접두사·Luhn·생년월일)은 그대로.
- [x] 한 요청 안에서 두 원문이 같은 대체값을 받으면 카운터를 붙여 다시 만든다(지금 20회 루프 재사용). `# ponytail:` 주석으로 천장을 적는다. 그 값만 다른 턴과 바이트가 달라질 수 있다.
- [x] 결정의 한계 절: 같은 원문이 늘 같은 가명이 되므로 공급자 로그에서 요청 간 연결이 가능하다. 키 회전 절차와 회전 시 진행 중 대화의 이력 바이트가 바뀐다는 점을 적는다.
- [x] 7단계 실측을 같은 결정에 사전 등록한다: 모델, 대화 수, 두 팔(옛 코드·새 코드), 성공 기준, 비용 상한 $1. 이 단계의 커밋에 들어가야 7단계를 할 수 있다.

완료 기준
- 같은 키·같은 값 100회 → 같은 대체값, 다른 키 → 다른 대체값
- 한 요청 안에서 서로 다른 원문이 같은 대체값을 받지 않는다
- 모양 규칙 테스트가 그대로 통과
- 2턴 대화(스텁): 턴 1에 상류가 받은 user 메시지 바이트와 턴 2 이력 속 같은 메시지 바이트가 같다
- 전체 pytest·ruff 통과

근거: `surrogate.py:25`가 요청마다 난수를 쓴다. 현행 Claude 모델의 thinking 서명은 앞선 메시지 바이트에 묶이고, 어긋나면 기본 400이다. 프롬프트 캐시는 바이트 prefix 일치라 PII가 처음 나온 턴부터 매번 미스다. 둘 다 공급자 문서 근거이고 실 API로는 아직 재현하지 않았다(7단계).

### 5. 마스킹 범위를 모든 역할로 + thinking 서명 보존

목표: 에이전트·RAG 앱에서 도구 결과와 system 문서 속 값도 상류에 평문으로 나가지 않게 한다.

할 일
- [x] `gateway/openai_api.py`의 `PII_ROLES` 기본을 user·assistant·tool·system·developer로 넓히고, `GATEWAY_PII_ROLES`로 좁힐 수 있게 한다. D-073("답에 필요한 값을 훼손")을 뒤집는 근거를 결정에 적는다. 결정적 대체값이면 모델은 어디서나 같은 가짜 값을 보고 사용자는 원문을 돌려받는다.
- [x] 세 어댑터가 system·developer·tool(Chat `tool` 메시지, Anthropic `tool_result`, Responses `function_call_output`·`instructions`)을 TextRef로 내는지 확인하고 빠진 곳을 채운다.
- [x] Anthropic `thinking`·`redacted_thinking` 블록과 `signature`, Responses `reasoning` 항목은 요청 마스킹도 응답 복원도 하지 않는다. 비스트리밍이 thinking 텍스트를 복원하던 동작을 없앤다. thinking 요약에 가짜 값이 보일 수 있다는 점을 문서에 적는다.

완료 기준
- Chat `tool` 메시지·Anthropic `tool_result`·Responses `function_call_output`·system 속 합성 전화·이메일이 상류에 평문으로 가지 않는다(`tests/stub_target.py`의 `RAW_MARKERS` 판정)
- 에이전트 루프 2요청(스텁): 도구 결과 속 값이 가려지고 최종 답에서 원래 값으로 돌아온다
- thinking 블록 바이트가 요청·응답 양쪽에서 바뀌지 않는다
- `GATEWAY_PII_ROLES=user,assistant`면 옛 동작
- 전체 pytest·ruff 통과

근거: `openai_api.py:13`이 user·assistant만 가린다. 직접 재현에서 Chat `tool` 메시지 속 전화·이메일이 상류에 평문 그대로 갔다.

### 6. 응답 필드별 복원 + 복원 가시화 + 안전한 가짜 값

목표: 복원이 JSON을 깨뜨리지 않게 하고, 실패하면 보이게 한다.

할 일
- [x] 비스트리밍 응답을 파싱해 텍스트 필드 위에서 복원하고 한 번 직렬화한다(어댑터에 응답 텍스트 참조를 추가). 대상: Chat `choices[].message.content`·`tool_calls[].function.arguments`, Anthropic `content[].text`·`tool_use.input`의 문자열, Responses 출력 텍스트·`function_call.arguments`. thinking은 제외한다. arguments는 안쪽 JSON을 파싱해 문자열 값에서 복원한 뒤 다시 직렬화하고, 파싱에 실패하면 안쪽 이스케이프를 한 번 더 적용한다. JSON이 아닌 응답은 지금처럼.
- [x] 응답 헤더 `x-gateway-pii: issued=N restored=M`, 같은 값을 감사 줄에.
- [x] 의심 잔여 지표 `gateway_pii_suspect_total`: 응답에 남은 대체값(지금의 `residual`)과, 발급한 대체값의 식별 조각(전화·카드 끝 4자리, 이메일 로컬파트)이 복원 없이 나타난 경우를 센다. `issued>0 && restored==0`은 모델이 값을 되풀이하지 않는 정상 응답과 구별되지 않으므로 쓰지 않는다.
- [x] 이메일 대체값 도메인을 예약 도메인(`example.com`·`example.net`·`example.org`)으로 바꾼다. 전화는 공식 미할당 대역이 있는지 확인하고, 있으면 그 대역에서 뽑고 없으면 '복원 실패 시 제3자 번호' 위험을 문서에 적는다.

완료 기준
- 도구 인자에 PEM·개행 포함 값이 들어가도 복원 뒤 `json.loads(arguments)`가 성공하고 원문과 같다
- 응답 JSON에서 `<`가 붙은 대체값도 복원된다
- 이메일 대체값이 예약 도메인이다
- 헤더·감사·지표 값 테스트
- 전체 pytest·ruff 통과

근거: 비스트리밍 복원이 응답 JSON 텍스트 전체에 정규식 + 이스케이프 1단계(`detectors/pii.py:201`)라 문자열 안의 JSON이 깨진다. `residual`은 정확 일치만 세서 끝 4자리 언급·`+82` 국제화·TTL 만료를 0으로 보고한다. 가짜 이메일·전화가 실제 할당 대역에서 나온다.

### 7. 실 공급자 2턴 확인

전제: 4단계 결정(사전 등록)이 커밋돼 있다. `git log`로 확인하고, 아니면 멈춘다. 비용 상한 $1. 정상 요청·합성 PII만.

할 일
- [x] `scripts/check_multiturn_claude.py`: 사전 등록한 수만큼 2턴 대화를 한다. system에 캐시 최소 길이 이상의 정상 업무 문서(합성)를 넣고 `cache_control`을 명시한다(최소 길이는 claude-api 스킬의 prompt-caching 문서에서 확인). 턴 1 user에 합성 전화·이메일, 턴 2는 게이트웨이가 돌려준 턴 1 응답(thinking 블록 포함)을 그대로 이력에 붙인다.
- [x] 모든 요청에 `anthropic-beta: thinking-binding-controls-2026-08-01`과 `thinking: {"type": "adaptive", "block_binding": {"prefix_mismatch_behavior": "error"}}`를 넣어 서명 검사를 명시적으로 켠다(계정 강제 여부와 무관). 모델은 `claude-haiku-5-5`($0.10/$0.50 per MTok), 안 되면 `claude-sonnet-5-5`.
- [x] 기록: 상태 코드, 오류 문구, 응답의 `input_transformations`, `usage.cache_read_input_tokens`, 복원 여부, 비용.
- [x] 옛 팔: `git worktree add`로 `research-final`을 따로 꺼내 다른 포트에 띄운다. 새 팔: 현재 코드.
- [x] 요약은 `docs/verification/multiturn_claude.md`에, 원자료는 같은 폴더의 jsonl로(키·원문 없음).

완료 기준(사전 등록과 같게)
- 옛 팔: 둘째 턴 400(prefix 불일치) 또는 캐시 읽기 0 중 하나 이상 재현. 재현되지 않으면 그대로 적는다
- 새 팔: 400 없음, 둘째 턴 `cache_read_input_tokens > 0`, 복원 100%
- 비용 $1 이하

사용자 몫: 샌드박스가 네트워크를 막으면 스크립트를 `!`로 실행한다. 키가 `.env`에 이미 있으면 그대로 쓴다.

### 8. PII 평가 코퍼스 + CI 오탐 게이트

목표: 탐지를 바꾸기 전에 지금 수치를 잰다. 이후 모든 PII 변경은 같은 자로 잰다.

할 일
- [x] `eval/pii/make_corpus.py`(시드 고정)로 합성 코퍼스를 만든다. 종류별 양성 100건(검증식 통과·실패 섞음, 문장 속 위치·구분자 다양), 숫자 밀도 높은 음성 1,000건(주문번호·송장·타임스탬프·Snowflake ID·IMEI·diff 줄·로그·버전·내선번호). 손으로 쓴 어려운 사례는 별도 파일.
- [x] `eval/pii/score.py`: 종류별 재현율·오탐률과 Wilson 95% 구간을 마크다운 표로.
- [x] 지금 5종의 기준선을 결정 결과 절에 적는다.
- [x] `tests/test_pii_corpus.py`: 오탐률 상한·재현율 하한을 넘으면 실패. 기준선이 목표(오탐 1% 이하, 체크섬 종류 재현율 99% 이상)에 못 미치면 게이트를 기준선 값에 두고 9단계에서 조인다.

완료 기준: 코퍼스·점수 스크립트·게이트 테스트가 CI에서 돈다. 기준선 표가 결정에 있다.

근거: 지금 FPR 1.0%는 HR 도메인 89문항 기준이다(Wilson 95% 0.2~5.4%). 13~19자리 숫자의 약 10%가 Luhn을 통과해 카드로 가려진다(검토 추정).

### 9. 정규화 + 오탐 축소

할 일
- [x] 정규화: NFKC(전각 숫자·문자), 제로폭·서식 문자(Unicode Cf) 제거, 숫자 구분자 변형(‐ – — · 등) 통일. 문자 단위로 정규화하면서 원문 인덱스 표를 만들어 대체값은 원문 위치에 넣는다. 인젝션 룰도 정규화된 텍스트를 본다.
- [x] 체크섬이 맞지 않는 주민번호 꼴: 하이픈 형식(`YYMMDD-NNNNNNN`)은 지금처럼 가리고, 하이픈 없는 13자리는 문맥어(주민·생년·등록번호 등) 창 안에서만 가린다. 밖이면 detect(감사만). 2020년 10월 이후 번호에는 체크섬이 없다는 점을 결정에 적는다.
- [x] 카드: 발급사 범위(IIN 4, 51–55, 2221–2720, 34·37, 35, 62와 국내 전용 대역은 확인 후)와 길이 규칙을 더한다. Luhn만 통과하고 범위 밖이면 문맥어 창 안에서만 가린다.
- [x] 8단계 게이트를 목표값으로 조인다.

완료 기준: 게이트 목표값 통과, 전각 숫자·제로폭이 섞인 전화·주민번호 탐지, 전체 통과.

근거: 정규화 층이 없어 전각·제로폭·구분자 변형이 두 탐지기를 우회한다. 약한 주민번호·Luhn 통과 숫자열을 문맥 없이 가려 업무 번호가 가짜 값으로 바뀐다.

### 10. 한국 식별자 확장

할 일
- [x] 새 종류와 대체값 생성기(모양·검증식 유지, 결정적 시드): 여권(구 M+8자리·신 M+3자리+영문 1자+4자리), 운전면허(지역 2-2-6-2), 사업자등록번호(3-2-5, 검증식), 법인등록번호(6-7, 검증식, 주민번호와 분리), 외국인등록번호(지금은 주민번호 성별 자리 5~8로 잡힘 → 별도 종류), 계좌번호(은행별 자릿수·하이픈 꼴 + 문맥어 창, 기본 detect), IPv4. 전화 패턴에 인터넷 전화 070(8단계 기준선에서 4/4 놓침).
- [x] 패턴·검증식은 Presidio의 KR 인식기(KR_RRN·KR_BRN·KR_FRN·KR_PASSPORT·KR_DRIVER_LICENSE, MIT)와 공개 검증식으로 대조하고 출처를 결정에 적는다.
- [x] 8단계 코퍼스에 새 종류의 양성·음성을 더하고 게이트를 통과시킨다.
- [x] README에 커버리지 표(종류·검증식·기본 모드·한계).

완료 기준: 종류별 게이트 통과, 1MiB `find_all` 시간 기록(지금 약 0.1초), 전체 통과.

근거: 법정 고유식별정보 4종 중 2종만 잡는다. Presidio가 KR 5종을 공식 지원한다(2026-10-30 확인). 지금 '한국형 PII'는 차별점이 아니라 따라가야 할 기준이다.

### 11. 설정 객체화 + 인프로세스 테스트 + mypy

할 일
- [x] `gateway/main.py`의 import 시점 전역 설정을 `Settings`(dataclass, 환경변수를 한 번 읽음)와 `create_app(settings)`로 바꾼다. 모듈의 `app = create_app(Settings.from_env())`는 uvicorn용으로 남긴다. `.env` 자동 로드는 없애고 uvicorn `--env-file`을 쓴다.
- [x] `main.py`(약 600줄)를 라우팅·중계·관리 엔드포인트로 나눈다. 파일 수는 최소로.
- [x] 테스트에 `httpx.ASGITransport` 인프로세스 픽스처를 더하고, 서브프로세스는 스트리밍·기동 실패처럼 꼭 필요한 테스트에만 쓴다. (D-118: ASGITransport 대신 스레드 uvicorn — 스트리밍이 실제 그대로이고 테스트 호출부가 바뀌지 않는다)
- [x] 낡은 설정을 지운다: `GATEWAY_INJECTION_SCOPE=all`(다중 턴 FPR 100%), `GATEWAY_CHAT_UPSTREAM_PATH`, 테스트만 쓰게 되면 `GATEWAY_DETECTORS`.
- [x] CI에 mypy(관대한 설정)를 더한다.

완료 기준: 전체 통과, 테스트 시간 전후 기록, mypy 통과.

근거: 설정이 import 시점 전역이라 테스트마다 uvicorn 서브프로세스를 띄우고, 키 회전마다 재시작이 필요하다.

### 12. 설정 파일 + 상류 라우팅 + 클라이언트 정책

할 일
- [x] `GATEWAY_CONFIG` 파일(TOML, 표준 라이브러리 `tomllib`): `[[clients]]` name·key_sha256·policy, `[policies.<이름>]` pii_mode·pii_kinds·pii_roles·injection·allowed_models, `[upstreams.<api>]` base_url·key_env·timeout. 환경변수만으로도 지금처럼 뜬다.
- [x] 클라이언트 키는 sha256으로 저장·비교한다(`keygen --hash`).
- [x] 어댑터별 상류: OpenAI(Chat·Responses)와 Anthropic(Messages)을 한 게이트웨이에서 동시에. `TARGET_URL`은 둘 다의 기본값으로 하위 호환.
- [x] `allowed_models` 밖의 모델은 403(어댑터 오류 형식).
- [x] 설정 버전(파일 sha256 앞 12자)을 info와 감사 줄에.

완료 기준: `scripts/check_openai_sdk.py`와 `scripts/check_anthropic_sdk.py`가 스텁 상류로 한 게이트웨이에서 함께 통과, 해시 키 인증 테스트, 모델 차단 테스트, 전체 통과.

사용자 몫: Anthropic SDK가 없으면 `python3 -m venv /tmp/sdkvenv && /tmp/sdkvenv/bin/pip install anthropic`.

근거: 클라이언트 키는 이름뿐이고 정책·허용 모델이 없다. 상류 URL·키가 각각 하나라 공급자마다 게이트웨이를 따로 띄워야 한다. 키를 평문으로 보관·비교한다.

### 13. 감사·관측·문구 카탈로그

할 일
- [x] 감사 줄에 client·api·model·usage(입력·출력·캐시 토큰)·config_version. 스트리밍 usage는 Anthropic `message_start`·`message_delta`에서 읽는다. OpenAI는 `stream_options.include_usage`를 넣어 받고, 클라이언트가 요청하지 않았으면 usage 전용 조각을 클라이언트 스트림에서 뺀다.
- [x] 출력 방향 관측: 복원 뒤 응답에서 우리가 발급하지 않은 PII·비밀 건수 `new_in_response`(감사·지표). 가리지는 않는다.
- [x] 사용자·운영자에게 가는 문구(차단 문구·REDACTED_TURN·설정 오류)를 카탈로그로 모은다. `GATEWAY_LANG=ko`(기본)·`en`.
- [x] 상류가 사내 서비스일 때를 위해 게이트웨이 요청 ID를 `x-gateway-request-id`로 상류에 넘긴다.

완료 기준: 스트리밍·비스트리밍 둘 다 usage가 감사 줄에 있다, 카탈로그 en·ko 테스트, 전체 통과.

근거: usage를 읽지 않아 비용·예산 집계가 불가능하다. 문구가 한국어로 하드코딩돼 있다. 출력 방향은 카나리로만 셌다.

### 14. 배포 패키지 + 제품 문서

할 일
- [x] `deploy/compose.yml`: 게이트웨이 + 스텁 상류(로컬 체험용).
- [x] `deploy/k8s/`: Deployment(레플리카 2, readiness=health, preStop sleep 5, terminationGracePeriodSeconds 30), Service, Secret(클라이언트·대체값·관리 키), ConfigMap(설정 파일), PodDisruptionBudget. Helm은 고객이 요구할 때. (D-121: kustomize 생성기 — 바꾸고 apply하면 롤링 재시작. 클라이언트 키는 해시로 ConfigMap, Secret은 대체값·관리·공급자 키)
- [x] `docs/configuration.md`(모든 환경변수·설정 키), `docs/operations.md`(배포·키 회전·로그 수집·지표·용량), `docs/api-compat.md`(지원과 미지원: `previous_response_id`, embeddings, files, audio, `count_tokens`, 서버 측 도구), `SECURITY.md`(취약점 제보 경로).
- [x] `README.en.md`.
- [x] 문서의 환경변수 목록이 코드와 같은지 확인하는 테스트.

완료 기준: Docker가 있으면 compose로 띄워 두 SDK 점검 통과, k8s YAML 검증(`kubectl apply --dry-run=client`가 되면), 문서 동기화 테스트 통과.
(D-121: kubectl 컨텍스트가 없어 `kubectl kustomize` 렌더 + kubernetes-validate `--strict` 스키마로 대신했다.)

### 15. 부하·안정성

할 일
- [x] `scripts/load.py`(httpx 비동기, 새 의존성 없음): 지연을 주입한 스텁 상류 앞에서 동시 50 스트림과 비스트리밍을 섞어 게이트웨이 지연 p50·p95·p99와 오류율을 잰다.
- [x] 30분 soak: RSS·열린 파일 수·볼트 세션 수가 안정적인지 본다.
- [x] 결과를 `docs/operations.md` 용량 표에 적는다.

완료 기준: 오류율 0, soak RSS 증가 10% 미만, 수치가 문서에 있다.

### 16. 한국어 평가셋 v1 + 기준선

목표: 인젝션 탐지를 어떤 방법으로 바꾸든 같은 자로 잰다. 한국어 수치가 생기기 전에는 차단 성능을 주장하지 않는다.

할 일
- [x] 공격셋: 공개 데이터셋(실행 시 탐색하고 라이선스 확인. 예: deepset/prompt-injections, jackhhao/jailbreak-classification, 한국어 공개셋) + `gateway/data/injection_corpus.jsonl` 59건 + 기존 표본을 결정적 스크립트로 변형한 것(동의어·띄어쓰기·전각·인코딩). LLM으로 새 공격을 만들지 않는다. 언어·유형(직접·간접·역할 위조·인코딩·다중 턴) 태그를 단다.
- [x] 정상셋 2,000건 이상: 여러 도메인(HR·고객 지원·개발·금융·의료·법률) 업무 문장, 하드 네거티브('지시사항 무시', '개발자 모드', 'DAN 프로젝트', '시스템 프롬프트 작성법' 등) 20% 이상. 세션이 직접 쓰거나 템플릿 조합 스크립트로 만들고, 기존 `eval/benign/all100.jsonl`을 포함한다.
- [x] 홀드아웃 20%를 봉인한다: 파일 sha256을 결정에 적고, 룰·임계값 조정에 쓰지 않는다.
- [x] `eval/injection/score.py`: recall@FPR 1%·0.5%, Wilson 구간, 언어·유형별 표. 판정기 인터페이스 하나로 룰·분류기·웹훅을 같은 자로 잰다.
- [x] 지금 룰(R1·R2)의 기준선을 결정과 README 한계 절에 적는다.

완료 기준: 셋 파일·해시·라이선스 표가 결정에 있다, 기준선 표, CI에 점수 스크립트 스모크 테스트.
(D-123: 공개셋 13개 + 한국어 업무 문장 717(에이전트 작성·검증). 홀드아웃은 같은 원문의 번역·합성·팀까지 한 그룹으로 나눈다. ko-jailbreak·jackhhao는 리뷰에서 뺐다.)

근거: 헤드라인 74.5%→0.2%는 garak 템플릿의 "ignore … instructions"를 R1이 문자 그대로 맞춘 결과다(동의어 하나로 14/14 미탐). 한국어 공격 탐지율은 측정된 적이 없다. 정상셋은 HR 89문항뿐이다.

### 16-1. 운영 대시보드(읽기 전용) — 시험 중 처리 결과 보기

목표: 설명서 화면 C를 제품 안에 넣는다. 시험·체험·PoC 중에 요청마다 다음을 브라우저 한 장에서 본다 — 무엇을 몇 개 가렸는지, 무엇을 어떤 룰로 막았는지, 무엇을 왜 거절했는지.
- 보기만 한다. 설정을 바꾸는 동작·로그인·원문 보기는 없다.
- 원문과 가짜 값은 화면에도 데이터에도 없다.
- 새 의존성·환경변수·컨테이너는 없다.

할 일
- [ ] D-124를 먼저 적는다.
  - 근거와 결정: 결정 표 13번과 아래 설계.
  - 버린 대안:
    - Grafana만 쓰기 — 체험·시험 환경에 없고, 요청별 처리는 못 본다.
    - 별도 서비스·컨테이너.
    - 감사 파일 읽기 — 이미지는 stdout으로 쓴다.
    - SSE·WebSocket — EventSource는 Authorization 헤더를 달지 못한다.
    - 이력 저장.
    - 쿠키 세션·Basic·URL 키.
    - 키를 JS 메모리에만 두기.
    - 프레임워크·차트 라이브러리·CDN.
    - 파드 합산.
    - 두 번째 링.
    - Playwright.
  - 완료 기준: W1~W10 표.
  - 한계:
    - 프로세스·파드마다 따로이고, 재시작하면 0이다.
    - 최근 200건만 남는다.
    - 화면은 한국어다(코드 이름 병기).
    - 관리 키가 있으면 화면 경로가 있다는 사실이 드러난다.
    - 관리 키로 최근 요청 요약까지 열린다.
    - traffic.py는 게이트웨이가 스스로 내는 rate_limited(429)·gateway_busy·upstream_busy(503)·내부 오류(500)·끊김을 만들지 않는다(상류 429 전달은 장면 15).
- [ ] 선행 수정 — 같은 출처 정리. `create_app`의 `FastAPI(...)`에 `docs_url=None, redoc_url=None, openapi_url=None`을 준다.
  - 지금 다음 경로가 인증 없이 200이다(2026-10-31 재현):
    - `/docs`·`/redoc`: cdn.jsdelivr.net 스크립트를 읽는 HTML.
    - `/openapi.json`: 관리 경로까지 나열한다.
    - `/docs/oauth2-redirect`.
  - D-109 허용 목록 위반이다. 관리 키를 담는 화면과 같은 출처에 제3자 스크립트가 남아서는 안 된다.
- [ ] 감사 `error` 빈칸 두 곳을 채운다(`gateway/main.py`).
  - 파싱 400(`api()`의 `except ApiError`): `request.state.upstream_error = exc.code`. 코드는 `invalid_json`·`invalid_messages`·`invalid_request`·`invalid_stream`.
  - 허용 목록 밖 404·405(`_http_error`): `"not_found"`.
  - 이제 게이트웨이가 낸 4xx·5xx 감사 줄에는 모두 사유 코드가 있다.
- [ ] `gateway/metrics.py`(+약 80줄). 원천은 지금처럼 `AuditLog(on_write=Metrics.observe)`의 감사 레코드 하나다.
  - `outcome(rec) -> (결과, 사유)`. 위에서부터 처음 맞는 것을 쓴다. 사유는 공백 없는 코드다.
    1. `blocked` → `blocked`, 사유 `blocked_by`.
    2. `error`가 `REJECTED` 안에 있으면 → `rejected`, 사유는 그 코드. `REJECTED`: unauthorized·rate_limited·request_too_large·too_many_findings·model_not_allowed·invalid_json·invalid_messages·invalid_request·invalid_stream·not_found·gateway_busy·upstream_busy.
    3. `error`가 `UPSTREAM_ERRORS` 안에 있으면 → `upstream_error`, 사유 `error`. 상태는 보지 않는다.
       - `UPSTREAM_ERRORS`: `httpx.RequestError` 하위 클래스 이름 전부(`{c.__name__ for c in vars(httpx).values() if isinstance(c, type) and issubclass(c, httpx.RequestError)}` — ConnectError·ReadTimeout·RemoteProtocolError 등)와 `response_too_large`.
       - 응답 전에 실패하면 502·504다. 스트림 도중 상류가 끊기거나 시간이 다 되면 이미 200을 보낸 뒤라 감사 줄이 `status 200, error "ReadTimeout"`이다(2026-10-31 재현: `GATEWAY_TIMEOUT=1`, 조각 사이 1.5초 스텁).
    4. 그 밖에 `error`가 있으면 → `failed`, 사유는 예외 이름. 내부 500, 클라이언트가 끊은 요청(200 + ClientDisconnect, CancelledError), 스트림 도중의 게이트웨이 예외가 여기에 든다.
    5. 상태 400 이상:
       - `upstream_ms`가 있으면 → `upstream_error`, 사유 `upstream_<상태>`(상류 응답을 그대로 전달).
       - 없으면 → `rejected`, 사유 `http_<상태>`.
    6. `transformed` → `masked`. 사유: 개인정보를 가렸으면 `pii_mask`, 이력 턴만 가렸으면 `masked_turns`.
    7. `injection_observe`의 `would_block`이면 → `observed`, 사유 `injection_observe`. 아니고 가리지 않은 탐지(detect 정책의 `pii`, `pii_mask`의 `unmasked`)가 있으면 → `observed`, 사유 `unmasked`.
    8. 나머지 → `passed`, 사유 `none`.
  - `row(rec)`: 고정 키 19개(`ROW_KEYS`).
    - ts, request_id, client, policy, api, status, outcome, reason, gateway_ms
    - model: 앞 64자.
    - upstream_ms: null이면 상류 응답을 받지 않았다(차단·거절·상류 연결 실패).
    - masked{종류: 수}: pii_mask의 `pii`.
    - unmasked{종류: 수}: detect 정책의 `pii` + pii_mask의 `unmasked`.
    - masked_turns
    - rules: 앞 5개, 각각 {rule, trigger, object}. trigger·object는 앞 40자.
    - issued·restored·suspect·new: 감사 줄의 `pii_*`.
    - 싣지 않는 것: ip·path·query_keys·req_sha256_12·findings(위치)·usage·upstream_request_id·config.
  - `Metrics`:
    - `masked`는 pii_mask만 센다. 새 `unmasked`를 둔다.
    - `outcomes`: Counter[(결과, 사유)].
    - `recent = deque(maxlen=RECENT)`. `RECENT = 200`, `appendleft`로 최신이 앞이다.
    - `started`(ISO, 밀리초까지 — 감사 줄의 `utcnow()`와 같은 형식)·`pid`. 이미지에서는 uvicorn이 PID 1이라 파드마다 pid가 같으므로 파드는 started로 가른다.
    - `observe`는 어떤 레코드에도 예외를 올리지 않는다. 몸통 전체(기존 카운터 포함)를 try/except로 감싸고, 실패하면 그 레코드의 남은 집계와 줄을 버린다. 감사 줄은 이미 써졌으므로 집계·화면 버그가 프록시 요청을 500으로 만들지 않는다.
      - 지금도 기존 카운터는 모양이 이상한 레코드에서 예외를 낸다(재현: `Metrics().observe({"detectors": [{"detector": "pii_mask", "pii": "phone"}]})` → AttributeError). `AuditLog.write`가 `on_write`를 try 없이 부르고, 미들웨어의 `audit.write`도 try 밖이라 그 요청이 500이 된다.
  - `snapshot(vault_sessions, upstream_in_use) -> dict`: 락 안에서 복사한다(아래 stats JSON). 평균은 횟수가 0이면 null이다. NaN이면 JSONResponse가 500을 낸다.
  - `render()`:
    - `gateway_outcomes_total{outcome,reason}`·`gateway_pii_unmasked_total{kind}`를 더한다.
    - `gateway_pii_masked_total`은 실제로 가린 것만 센다. 지금은 detect 정책의 찾은 수가 섞인다(CHANGELOG '바뀐 점').
  - `# ponytail:` 주석: 링은 하나다. 부하 중에는 차단·거절 줄도 몇 초 안에 밀려난다. 필요해지면 passed·masked가 아닌 줄만 담는 두 번째 링을 둔다.
- [ ] `gateway/main.py`(+약 40줄).
  - `GET /__gateway/dashboard`
    - 관리 키가 설정된 게이트웨이에만 있다. 아니면 404.
    - 인증 헤더 없이 정적 HTML을 준다. 데이터·키·버전은 없다. 주소창 이동으로는 Bearer 헤더를 실을 수 없기 때문이다.
    - 헤더:
      - `Content-Security-Policy: default-src 'none'; script-src 'sha256-…'; style-src 'sha256-…'; img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'`
      - `X-Content-Type-Options: nosniff`
      - `Referrer-Policy: no-referrer`
      - `Cache-Control: no-store`
    - 해시는 import 때 `Path(__file__).with_name("dashboard.html")`의 바이트에서 계산한다. `(script,) = re.findall(rb"<script>(.*?)</script>", html, re.S)`로 블록이 정확히 하나인지 확인한다(style도 같다). 블록 수가 다르거나 파일이 없으면 기동이 실패한다.
  - `GET /__gateway/stats`
    - `_is_admin`(Bearer + `hmac.compare_digest`)일 때만 준다.
    - 키 없음·틀린 키·`?key=`·Basic·관리 키 미설정은 404다.
    - `Cache-Control: no-store`, nosniff. CORS 헤더는 없다.
  - stats JSON 키:
    - `started`·`now`·`pid`·`max_connections`·`requests`
    - `status`{"200": n…}
    - `outcomes`: 7가지가 늘 있다.
    - `reasons`[{outcome, reason, count}]: 많은 순.
    - `masked`·`unmasked`{종류: n}
    - `injection`{observe, block}
    - `restored`·`residual`·`suspect`·`new`
    - `gateway_ms_avg`: (Σtotal_ms − Σupstream_ms) / 횟수. 감사 gateway_ms의 평균과 같다.
    - `upstream_ms_avg`
    - `vault_sessions`{정책: n}
    - `upstreams`{주소: 빌려 간 연결}
    - `recent`[줄…]: 최신이 먼저, 200건 이하.
    - 호스트 이름은 싣지 않는다. 스크린샷·화면 공유에 장비 이름이 남지 않게 하고, 프로세스는 started·pid로 가른다.
  - 지금 `metrics()` 안에 있는 세션·연결 계산을 `_gauges(request)`로 옮겨 metrics와 stats가 함께 쓴다.
  - `/__gateway/*`는 모두 GET이다. INTERNAL_PREFIX 아래라 폴링이 감사·지표·레이트리밋에 들어가지 않는다.
  - 머리 docstring에 D-124 한 줄(metrics.py도 같다).
  - `gateway/version.py`의 `code_fingerprint()`가 `.py`와 함께 `dashboard.html`도 해시한다. 지금은 `rglob("*.py")`만이라 화면을 고쳐도 info의 코드 지문이 그대로다.
- [ ] `gateway/dashboard.html`(한 파일, 400줄 이내). 패키지 안에 있어 휠·이미지에 함께 실린다.
  - 파일 규칙:
    - 속성 없는 `<style>`·`<script>`를 하나씩 둔다.
    - 줄 끝은 LF만 쓴다. HTML 파서가 CRLF를 LF로 바꿔 해시가 어긋난다.
    - 외부 자원·프레임워크·CDN은 쓰지 않는다.
    - `<link rel="icon" href="data:,">`를 둔다. 파비콘 요청이 감사 404 줄을 만들지 않게 한다.
  - 그리는 규칙:
    - 값은 `createElement`·`textContent`·`replaceChildren`으로만 넣는다.
    - innerHTML·인라인 이벤트·`style=` 속성은 쓰지 않는다. 막대 너비는 CSSOM `el.style.width`나 `<meter>`로 정한다.
    - 한국어 문구에 코드 이름을 함께 적는다.
    - 색과 글자를 함께 쓴다. `th scope`를 쓰고, 다크 모드를 지원한다.
  1. 키 카드(키가 없을 때만)
     - password 칸(autocomplete=off)과 [열기].
     - 키는 `sessionStorage`에만 둔다. 탭을 닫으면 사라진다.
     - `fetch`는 `Authorization: Bearer` 헤더로만 보낸다(`cache: "no-store"`, `credentials: "omit"`). URL·쿠키·localStorage에는 두지 않는다.
     - 404를 받으면 키를 지우고 "키가 틀렸거나 이 게이트웨이에 관리 키가 없습니다"를 보인다.
     - 정적 문구 `<p id="nojs">`는 스크립트가 지운다.
  2. 머리 띠
     - info(처음 한 번 읽음): 버전·코드 지문·설정 버전·정책별 검사기.
     - "시작 HH:MM:SS 이후(pid N) — 다시 시작하면 0", 마지막 갱신 시각, 연결 상태.
     - [멈춤]·[잠금(키 지우기)].
     - started나 pid가 바뀌면 "다시 시작했거나 다른 프로세스 — 숫자가 0부터" 띠를 띄운다.
  3. 타일 8개. 제목은 설명서 화면 C의 8개를 그대로 쓰고, 보조 문구는 아래 괄호 안대로 한다(설명서의 예시 문구와 다르다). '지난 24시간' 대신 '시작 이후'라고 적는다.
     - 요청 수(분당 평균·지금 초당)
     - 가린 개인정보(상위 3종 비율, 기록만 n)
     - 복원 실패 의심(0이 아니면 경고색과 '확인 필요')
     - 응답에 새로 나온 개인정보
     - 수상한 지시 기록(기록만 n · 차단·이력 가림 m)
     - 게이트웨이 처리 시간(평균, AI 응답 시간 빼고)
     - 사용 중 AI 연결(가장 바쁜 상류 n / max_connections, 진행 중 대체값 세션)
     - 오류(5xx) 비율
  4. 처리 결과
     - 7가지 누적 건수: 가림 후 전달(masked)·그대로 전달(passed)·기록만(observed)·차단(blocked)·거절(rejected)·AI 회사 오류(upstream_error)·오류·끊김(failed — 내부 500과 클라이언트 끊김을 한 칸에 센다). 누르면 아래 표가 그 결과로 걸러진다.
     - 사유별 건수(코드 + 한국어 라벨).
  5. 종류별 가린 개수: 12종의 한국어 이름·막대·수(많은 순). 아래 한 줄에 '기록만'(가리지 않은) 종류별 수를 보인다.
  6. 최근 요청 — 어떻게 처리했나(최신이 위, 200줄)
     - 결과 필터, 찾기(요청 ID·클라이언트 앞부분), [멈춤].
     - 열: 시각(로컬) · 요청 ID · 클라이언트·정책 · API·모델 · 결과 배지 · 어떻게 처리했나 · 복원(복원/발급, 의심·새 값 배지) · HTTP · 게이트웨이 ms.
     - '어떻게 처리했나' 문장 예:
       - "전화번호 1 · 이메일 1을 가짜 값으로 바꿔 보냄 → 2개 되돌림 · 기록만: 계좌번호 1"
       - "인젝션 룰 R1 지시 무효화(ignore + instructions) — 이번 턴 차단, 상류 호출 없음"
       - "이력 1턴 가림(R1)"
       - "인젝션 룰 R1 적중 — 기록만(차단 꺼짐), 그대로 보냄"
       - "전화번호 1 찾음 — 이 정책은 가리지 않음(원래 값이 나감)"
       - "허용 안 된 모델(403 model_not_allowed) — 상류 호출 없음"
       - "AI 회사가 429를 줌 — 그대로 전달"
       - "AI 응답 시간 초과(504 ReadTimeout)"
       - "응답 도중 끊김(ClientDisconnect)"
     - '상류 호출 없음'은 결과가 blocked·rejected인 줄에 붙인다(이 줄들은 upstream_ms가 늘 null이다). 502 ConnectError처럼 연결을 시도하다 실패한 줄에는 붙이지 않는다.
     - 줄을 누르면 상세가 열린다. 그 줄의 JSON 전체(`<pre>`)와 "원문·가짜 값·위치·IP는 없다 — 전체 감사 줄은 감사 로그에서 이 요청 ID로 찾는다"를 보인다.
  7. 갱신과 바닥글
     - 응답을 받은 뒤 2초 지나 다시 읽는다. setTimeout을 이어 걸어 요청이 겹치지 않게 한다.
     - 탭이 숨거나 [멈춤]이면 쉰다.
     - 실패하면 '연결 끊김' 띠를 띄우고 5초 뒤 다시 시도한다.
     - 바닥글: 이 프로세스의 숫자다(여러 대면 각자 — 합산·보관은 Prometheus·감사 로그). 스트림은 끝나야 줄이 생긴다. 이 화면으로 설정을 바꿀 수 없다.
  - 라벨 사전. operations '대시보드' 절의 표와 같은 말을 쓴다.
    - 결과 7가지.
    - 종류 12가지(rrn 주민등록번호 … ipv4 IP 주소).
    - 룰: R1 지시 무효화, R2 역할 전환·제약 해제.
    - 사유:
      - unauthorized: 키 없음·틀림(401)
      - rate_limited: 분당 한도(429)
      - request_too_large: 본문 상한(413)
      - too_many_findings: 개인정보가 너무 많음(413, 가짜 값 발급 전)
      - model_not_allowed: 허용 안 된 모델(403)
      - invalid_*: 요청 형식 오류(400)
      - not_found: 허용 목록 밖 경로(404)
      - gateway_busy: 게이트웨이 바쁨(503)
      - upstream_busy: AI 연결 가득(503)
      - upstream_<상태>: AI 회사가 준 오류를 그대로 전달
      - 시간 초과 예외(ConnectTimeout·ReadTimeout·WriteTimeout·PoolTimeout): AI 응답 시간 초과(504, 상태가 200이면 스트림 도중)
      - 그 밖의 `UPSTREAM_ERRORS`(ConnectError·ReadError·RemoteProtocolError 등): AI 회사 연결 실패·끊김(502, 상태가 200이면 스트림 도중)
      - response_too_large: AI 응답이 너무 큼(502)
      - ClientDisconnect·CancelledError: 클라이언트가 끊음
      - 그 밖의 예외 이름: 게이트웨이 내부 오류(500, 상태가 200이면 스트림 도중). 예외 이름을 함께 보인다
      - injection_rule_turn: 이번 턴의 수상한 지시(그 밖의 blocked_by는 검사기 이름 그대로)
      - pii_mask: 개인정보를 가짜 값으로 바꿈
      - masked_turns: 이력의 수상한 턴을 가림
      - injection_observe: 수상한 지시 — 기록만
      - unmasked: 가리지 않는 개인정보 — 기록만
      - none: 해당 없음
- [ ] `scripts/traffic.py`(약 200줄). httpx와 stdlib만 쓰고, 개발 의존성이 필요하다. load.py처럼 `tests.conftest`의 `serve`·`free_port`와 `scripts/load.py`의 `SERVER_ARGS`를 쓴다.
  - 띄우기: 셸의 `GATEWAY_*`·`TARGET_*` 변수를 지우고, 스텁과 게이트웨이(127.0.0.1:`--port`, 기본 8070)를 서브프로세스로 띄운다.
  - 클라이언트 셋:
    - `app`: `GATEWAY_CLIENT_KEYS`로 넣는다. 기본 정책 = 제품 기본값(인젝션 기록만·PII 가림).
    - `strict`: 임시 `GATEWAY_CONFIG`에 둔다. `injection = "block"`, `allowed_models = ["stub-*"]`.
    - `audit`: 같은 파일에 둔다. `pii_mode = "detect"`.
    - 키 해시는 `gateway.settings.key_hash`로 만든다.
  - 환경:
    - `GATEWAY_ADMIN_KEY=traffic-admin`. 고정 체험값이라 출력해도 된다.
    - 대체값 키는 실행마다 새로 만든다.
    - `GATEWAY_MAX_BODY_BYTES=4096`, `GATEWAY_TIMEOUT=1`.
    - 감사 로그는 임시 파일.
  - 출력: 시작할 때 "대시보드 http://127.0.0.1:8070/__gateway/dashboard · 관리 키 traffic-admin"과 클라이언트 키 셋을 찍는다.
  - 돌리기:
    1. 아래 16장면을 보내며 장면마다 `[n] 장면 → HTTP · 요청 ID · 기대`를 찍는다.
    2. 회차가 끝나면 stats의 recent에서 요청 ID로 줄을 찾아 기대와 대조한다. "16/16 일치"를 찍고, 어긋나면 받은 줄을 보인다.
    3. 요청 수가 보낸 수 이상 늘었는지도 확인한다(돌리는 동안 출력된 클라이언트 키로 사용자가 보낸 요청도 같은 게이트웨이에 들어온다).
    4. 2초 쉬고 반복한다.
  - 플래그는 셋:
    - `--rounds N`: N회 뒤 끝난다. 하나라도 어긋나면 종료 코드 1. 기본 0은 Ctrl-C까지 돈다.
    - `--port P`
    - `--shot PNG`: W8.
  - 외부 공급자 옵션은 두지 않는다. 늘 자기 스텁으로만 보낸다.
- [ ] 기존 도구에 연결한다.
  - `scripts/load.py`: 기동 직후 "대시보드 … · 관리 키 load-admin" 한 줄.
  - `web/app.py`: "있음" 게이트웨이의 대시보드 주소와 관리 키 demo-admin 한 줄.
  - `deploy/compose.yml` 머리 주석: http://127.0.0.1:8080/__gateway/dashboard, 관리 키 local-admin-key.
  - `GATEWAY_ADMIN_KEY` 설명을 "info·metrics·stats·대시보드를 연다. 없으면 모두 404"로 고친다. 고칠 곳은 여섯이다: `Settings.admin_key` 주석, `.env.example`(13행), `deploy/k8s/secret.env.example`, docs/configuration.md, README 4절, README.en.
- [ ] 테스트.
  - `tests/test_d124_dashboard.py`: W1~W7·W10.
  - `tests/test_d109_boundary.py`의 test_b8 parametrize에 `/__gateway/stats`를 더한다. dashboard는 넣지 않는다 — 인증 헤더 없이 200이 정상이다.
- [ ] 세션이 직접 확인한다: W8 브라우저(스크린샷 `docs/dashboard.png`), W9 컨테이너·부하. 수치와 스크린샷 경로를 D-124 결과에 적는다.
- [ ] 문서를 고친다.
  - `docs/operations.md` — 지표 절 뒤에 새 절 '## 대시보드':
    - 여는 법:
      - compose.
      - k8s는 `kubectl port-forward pod/<파드> 8080:8080`으로 파드 하나씩 본다. Service 너머로 보면 폴링마다 파드가 바뀐다.
      - `scripts/traffic.py`.
    - 키를 넣는 법과 보관.
    - 타일의 뜻.
    - 결과·사유 코드 표: 코드 · 뜻 · HTTP · 상류 호출 여부.
    - 사용자가 받은 요청 ID(차단 문구·`x-gateway-request-id`)로 그 줄을 찾는 법.
    - 한계.
    - Ingress로 `/__gateway/*`를 열지 않는다. 원격으로 보면 TLS 뒤에 둔다.
  - `docs/operations.md` — 기존 절:
    - 지표 표: `gateway_outcomes_total`·`gateway_pii_unmasked_total`을 더하고 masked 뜻을 고친다.
    - 로그 표 `error`: 400 코드와 not_found를 더한다.
    - 키 회전 표 관리 키 행: 대시보드를 연 탭은 키를 다시 넣는다.
    - 장애 신호: "숫자가 튄다 → 여러 파드에 번갈아 붙는다".
  - `docs/api-compat.md` 경로 표:
    - dashboard·stats 행. stats 형식은 바뀔 수 있으니 수집은 metrics로 한다고 적는다.
    - "FastAPI 기본 문서 경로는 없다".
  - README·README.en:
    - 3절(실행)에 대시보드 한 줄과 스크린샷(`docs/dashboard.png`).
    - 5절 구조에 `gateway/dashboard.html`·`scripts/traffic.py`.
  - CHANGELOG 미출시:
    - 추가: 대시보드·stats·traffic.py·지표 둘.
    - 바뀐 점: `gateway_pii_masked_total`의 뜻, 감사 `error`가 400·404에도 붙는다.
    - 보안: FastAPI 기본 문서 경로 제거.
- [ ] 설명서 `docs/overview/overview.html`을 고치고 PDF를 다시 만든다.
  - 고칠 곳:
    - 표지와 0장 '지금 상태': 16단계 + 16-1.
    - 0장 '무엇인가요?', 1장 '화면' 행과 상자, 7장 머리 문단: "제품에 든 화면은 시연용 비교 화면(B)과 운영 대시보드(C) 둘".
    - 7장 표의 운영 대시보드 행: 지금 '있음', 완성 때 '있음 — 서버 한 대의 숫자, 여러 대 합산·장기 보관은 회사 모니터링 도구'.
    - 7장 표의 웹 관리 콘솔 행: '없음 — 대시보드는 보기만'.
    - 화면 C:
      - 제목은 '제품에 들어 있음 — /__gateway/dashboard, 읽기 전용'.
      - 손 그림을 `<img src="../dashboard.png">`로 바꾼다.
      - 캡션은 '합성 시험 트래픽(scripts/traffic.py) 한 바퀴 뒤의 실제 화면'.
    - 8장 '읽는 법' 상자와 운영자 표의 '지표 보기'.
    - 10장 테스트 수.
    - 11장 표의 16-1 행과 v1.0 상자의 운영자 문장.
    - 용어 풀이 '지표'·'대시보드'.
  - PDF 만들기: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer --print-to-pdf=docs/overview/LLM보안게이트웨이_제품설명서.pdf "file://$PWD/docs/overview/overview.html"`. 만든 뒤 쪽을 열어 넘치는 곳이 없는지 본다.

traffic.py 장면. 값은 모두 합성이고 web/app.py·tests에 이미 있는 값과 표준 공격 문장 하나만 쓴다. 상류는 늘 자기 스텁이다.

| # | 장면 | 클라이언트 · 요청 | 대시보드에 보일 처리 |
|---|---|---|---|
| 1 | 개인정보 | app · chat, 전화+이메일 | masked — phone 1·email 1, restored 2 |
| 2 | 스트리밍 API 키 | app · responses `stub-stream`, 가짜 `sk-proj-` 키 | masked — secret 1(스트림이 끝난 뒤 한 줄) |
| 3 | 고유식별정보 + 감사만 | app · messages, 주민번호·카드·계좌 | masked — rrn·card, unmasked account |
| 4 | 정상 질문 | app · chat `stub-quiet` | passed |
| 5 | 수상한 지시(기록만) | app · chat, 공격 문장 | observed — R1, 상류 호출 있음 |
| 6 | 수상한 지시(차단) | strict · chat, 공격 문장 | blocked — injection_rule_turn·R1, 상류 호출 없음 |
| 7 | 이력 속 차단 문장 | strict · chat, [공격, 차단 답, 정상 질문] | masked — masked_turns 1 |
| 8 | 탐지만 하는 정책 | audit · chat, 전화 | observed — unmasked phone, new 1 이상 |
| 9 | 복원 실패 의심 | app · chat `stub-last4`, 전화 | masked — suspect 1 이상 |
| 10 | 허용 안 된 모델 | strict · chat `gpt-4o` | rejected — model_not_allowed(403) |
| 11 | 틀린 키 | — | rejected — unauthorized(401) |
| 12 | 본문 상한 | app · chat, '가'×2000 | rejected — request_too_large(413) |
| 13 | 형식 오류 | app · messages, 본문 `{` | rejected — invalid_json(400) |
| 14 | 허용 목록 밖 경로 | app · GET /v1/files | rejected — not_found(404). 경로가 인증보다 먼저 걸러져 줄의 client·policy·api는 null |
| 15 | AI 회사 오류 | app · chat `stub-429` | upstream_error — upstream_429(그대로 전달) |
| 16 | AI 응답 시간 초과 | app · chat `stub-slow`(2초 > 시간 제한 1초) | upstream_error — ReadTimeout(504) |

완료 기준
- W1 노출·인증
  - `/docs`·`/redoc`·`/openapi.json`·`/docs/oauth2-redirect`가 404다.
  - `/__gateway/stats`는 Bearer 관리 키에만 200 JSON이다.
  - 다음은 모두 404다: 키 없음, 틀린 키, `?key=<관리 키>`, `Authorization: Basic`, 관리 키 미설정 게이트웨이(키를 보내도).
  - stats 응답에 `Access-Control-Allow-Origin`이 없다.
  - router의 `/__gateway/*` 라우트는 모두 GET뿐이다.
- W2 화면 응답
  - 관리 키가 있는 게이트웨이의 `/__gateway/dashboard`는 인증 없이 200 `text/html`이고, 관리 키가 없으면 404다.
  - CSP에 위 지시어가 모두 있고 `'unsafe-inline'`·`'unsafe-eval'`이 없다.
  - script-src·style-src의 해시가 응답 본문의 유일한 `<script>`·`<style>`에서 테스트가 따로 계산한 sha256과 같다.
  - nosniff·no-referrer·no-store 헤더가 있다.
  - 본문에 다음이 없다: innerHTML, outerHTML, insertAdjacentHTML, document.write, eval, new Function, localStorage, document.cookie, `style=`, 인라인 `on…=`, `http://`, `https://`, 관리 키 값.
  - 본문에 `<link rel="icon" href="data:,">`와 `id="nojs"`가 있다.
  - 본문에 `\r`이 없다. CRLF면 브라우저는 LF로 바꾼 뒤 해시를 재므로 스크립트가 막힌다 — 서버와 테스트가 같은 바이트로 잰 해시 비교로는 잡히지 않는다.
- W3 분류
  - `outcome()` 표 테스트가 레코드 모양 하나씩으로 8규칙을 모두 지난다:
    - passed
    - masked: PII, 이력 턴
    - observed: injection_observe, detect 정책, unmasked만 있음
    - blocked
    - rejected: REJECTED 12코드, http_<상태>
    - upstream_error: 상류 401·429, 502 ConnectError, 504 ReadTimeout, 502 response_too_large, 200 + ReadTimeout(스트림 도중), 200 + RemoteProtocolError
    - failed: 500 예외, 200 + ClientDisconnect, 500 + CancelledError
  - 소스 검사: `gateway/`의 `upstream_error = "…"` 리터럴, `ApiError`·`ChatRequestError`가 내는 코드(기본값 `invalid_request`·`invalid_messages` 포함), `too_many_findings`가 모두 `REJECTED`나 `UPSTREAM_ERRORS`에 든다(`response_too_large`는 뒤쪽). 새 코드가 어디에도 들지 않으면 실패한다.
  - 실제 요청에서 파싱 400의 감사 `error`가 `invalid_json`, 경로 404의 감사 `error`가 `not_found`다.
- W4 개인정보
  - 합성 전화·이메일·키·주민번호와 공격 문장을 보낸 뒤 stats 본문에 다음이 하나도 없다: 보낸 원문, 스텁이 실제로 받은 가짜 값(`/__stub/received`에 `find_all`).
  - 줄의 키 집합이 `ROW_KEYS`와 정확히 같다.
  - 1,000자 model은 64자로, 1,000자 트리거·목적어는 40자로, 룰 10개는 5개로 잘린다. 이렇게 잘린 값과 12종을 모두 채운 masked·unmasked로 만든 최악의 줄 JSON(UTF-8, 한국어로 채움)이 2.5KB 이하다(계산값 약 2.1~2.3KB). 200줄이어도 0.5MB를 넘지 않는다.
- W5 링·격리
  - 205건을 넣으면 recent는 200건이고 최신이 먼저다.
  - dashboard·stats·info를 여러 번 불러도 카운터와 recent가 그대로다.
  - 모양이 이상한 레코드(detectors None, pii가 문자열, 필드 누락)에도 observe가 예외를 올리지 않는다. 기존 `tests/test_d107_ops.py`의 test_e2 둘(지표 = 감사 줄)이 그대로 통과한다.
- W6 같은 숫자
  - 같은 순간 stats의 requests·masked·unmasked·outcomes·injection·restored·suspect·new가 `/__gateway/metrics`의 값과 같다.
  - requests가 감사 줄 수와 같다.
- W7 시나리오
  - `python3 scripts/traffic.py --rounds 1 --port <빈 포트>`가 종료 코드 0으로 끝난다.
  - 16장면이 모두 기대와 일치하고, 결과 6가지(masked·passed·observed·blocked·rejected·upstream_error)가 나온다.
  - CI에서 돈다.
- W8 브라우저(세션이 직접, CI 밖)
  - `python3 scripts/traffic.py --rounds 1 --shot docs/dashboard.png`가 0으로 끝난다.
  - ① headless Chrome `--dump-dom`으로 실제 서버의 화면을 연다.
    - CSP 아래에서 스크립트가 돌아 `id="nojs"`가 사라지고, 키 카드(`id="key"`)가 있다.
    - 연 뒤에도 stats의 requests가 그대로다(파비콘 등 감사 줄이 생기지 않는다).
  - ② 마지막 stats·info를 넣은 `file://` 사본을 `--screenshot=<PNG> --window-size=1280,1600 --hide-scrollbars --virtual-time-budget=5000`으로 찍는다. 기본 창(800×600)이면 아래 표가 잘린다 — 16줄 표까지 한 장에, 설명서 A4 한 쪽에 들어가는 비율로 한다.
    - 사본에는 원래 `<script>` 앞에 fetch를 대체하고 키를 넣는 스크립트를 끼운다.
    - 응답 헤더와 같은 CSP를 `<meta http-equiv="Content-Security-Policy">`로 넣는다. script-src에 끼운 스크립트의 해시를 더하고, meta가 무시하는 frame-ancestors는 뺀다. ①은 키가 없는 상태라 그리기 경로를 지나지 않으므로, 데이터를 그리는 경로가 실제 CSP·Trusted Types 아래에서 도는지는 이 사본이 본다(2026-10-31 확인: file:// + meta CSP에서 해시가 맞는 스크립트는 돌고 innerHTML은 막힌다).
    - Chrome은 PATH의 google-chrome·chromium이나 macOS 경로에서 찾는다. 없으면 종료 코드 2다.
  - ③ 같은 사본을 `--dump-dom --virtual-time-budget=5000`으로도 열어, 16장면의 요청 ID마다 그 줄에 장면 표의 결과 배지와 '어떻게 처리했나' 핵심어(예: 장면 6 '차단'·'상류 호출 없음', 장면 10 'model_not_allowed', 장면 1 '가짜 값')가 있는지 traffic.py가 확인한다. 어긋나면 종료 코드 1.
  - 세션이 PNG를 열어 확인한다:
    - 타일 8개, 처리 결과, 종류별 막대가 보인다.
    - 차단·거절·가림·기록만 배지와 '어떻게 처리했나' 문장이 보인다.
    - 설명서 화면 C와 배치가 맞는다.
  - PNG는 600KB 이하다.
- W9 컨테이너·부하
  - `docker compose -f deploy/compose.yml up --build -d`로 띄운다.
    - `/__gateway/dashboard`가 같은 CSP로 200이다. HTML이 휠·이미지에 들어 있다는 뜻이다. 빠지면 pyproject에 포함 규칙을 더한다.
    - `local-admin-key`로 stats가 200이다.
    - compose 머리 주석의 curl 요청이 recent 맨 앞에 masked(phone 1)로 보인다.
    - 끝나면 `down`으로 정리한다.
  - `python3 scripts/load.py --duration 30 --no-baseline`
    - 판정이 모두 통과하고, 시작할 때 대시보드 주소를 찍는다.
    - 감사 gateway_ms(비스트리밍) p95가 D-122 값 18.5ms의 1.5배 이하다. 넘으면 원인을 찾는다.
- W10 문서·전체
  - api-compat의 `/__gateway/*` 경로 집합이 router의 것과 같다(테스트).
  - 다음이 갱신돼 있다: operations의 '대시보드' 절·지표 표·로그 표, 관리 키 설명 여섯 곳, README·README.en·CHANGELOG·compose 주석, 설명서 HTML·PDF.
  - 설명서에 '하나뿐'·'숫자만 제공'·'제품에 없음'·'제공하지 않음'·'지어낸 값'이 남지 않는다(grep 0건).
  - D-124 결과 절에 수치·스크린샷·못 한 것을 채운다.
  - 새 의존성·새 환경변수가 없다(test_s3의 22개 그대로).
  - 전체 `pytest -q`·`ruff check .`·`mypy`가 통과한다.

사용자 몫: 없다(커밋·푸시만). 이미지 빌드가 네트워크 때문에 막히면 `! docker compose -f deploy/compose.yml build`. 선택으로 브라우저에서 열어 배치 의견을 줄 수 있다 — 세션은 스크린샷으로 확인한다.

근거:
- 사용자 요청(2026-10-31): 설명서 화면 C 같은 운영 대시보드를 제품에 넣고, 시험할 때 어떻게 막았는지가 보여야 한다.
- 지금 처리 결과를 보는 길은 두 가지뿐이다: 관리 키로 여는 Prometheus 텍스트, 감사 JSONL(이미지에서는 stdout). 체험·시험 환경에는 Grafana가 없다.
- 화면 B(web/app.py)는 자기가 띄운 스택만 보여 준다. compose·k8s·PoC 설치에는 화면이 없다.
- 감사 레코드에는 원문이 없고, 지표도 이미 그 레코드에서 센다(`on_write`). 같은 훅에 결과 분류와 최근 줄만 더하면 된다.
- 17 앞에 두는 이유:
  - 사용자가 다음 계획으로 정했다.
  - 17·18은 모델 다운로드·라이선스 동의(사용자 몫)·x86 측정이 걸린 긴 단계이고, 이 단계와 무관하다.
  - 17·18이 더하는 검사기 결과는 같은 표에 근거로 붙는다(줄에 키 하나).
  - 22단계 2주 관측에서 운영자가 볼 화면이 된다.
- 17~22는 DECISIONS·커밋이 가리키므로 번호를 바꾸지 않고 16-1로 넣는다.
- 검토 중 FastAPI 기본 문서 경로가 인증 없이 200임을 재현했다(D-109 위반).

### 17. 탐지 사이드카 + 한국어 PII NER

할 일
- [ ] `detect/`: 별도 컨테이너(FastAPI + onnxruntime, 게이트웨이 이미지와 의존성 분리). `POST /v1/detect {texts: [{id, role, text}], tasks: ["pii_ner"]}` → 스팬, `GET /health`에 모델 해시.
- [ ] 후보 모델을 실행 시 확인한다(존재·라이선스·크기): KoELECTRA 계열 한국어 PII NER(검토에서 거론된 `1T/veil-pii-ko-lite` 등). INT8 ONNX로 변환한다.
- [ ] NER 평가셋: 합성 200문장(이름·주소·직장, 템플릿과 사전으로 생성해 정답 스팬 자동) + 공개셋(라이선스 확인).
- [ ] 게이트(결정 표 7번): x86 CPU에서 512토큰 이하 p95 +40ms 이하, F1 0.85 이상. 맥북은 arm이므로 지연은 CI 러너(x86)에서 잰다.
- [ ] 통과하면 게이트웨이에 `GATEWAY_DETECT_URL`, 타임아웃 50ms, 기본 detect(감사만) → 정책에서 mask. 이름·주소 대체값 생성기(성씨·이름 사전, 주소는 시·도 유지). 사이드카 장애 시 detect는 통과, mask는 설정에 따른다.
- [ ] 미달이면 수치를 결정에 적고 v1.0에서 뺀다.

완료 기준: 게이트 수치가 결정에 있다, 사이드카 꺼짐·켜짐 두 구성에서 전체 테스트 통과, 장애 시 동작 테스트.

사용자 몫: 게이트가 걸린 모델이면 Hugging Face에서 라이선스 동의, 다운로드가 막히면 `!`로 실행.

### 18. 인젝션 분류기(관측) + 가드레일 웹훅

할 일
- [ ] 같은 사이드카에 `tasks: ["injection"]`: 기본 후보 protectai/deberta-v3-base-prompt-injection-v2(실행 시 라이선스 재확인), 비교 후보 Llama Prompt Guard 2 86M(Llama 4 Community 라이선스, 게이트 승인 필요). 512토큰 청크.
- [ ] 16단계 평가셋으로 recall@FPR 1%를 잰다(홀드아웃은 마지막에 한 번). 관측 모드: 점수만 감사 줄에.
- [ ] 옛 D-054의 메타 인젝션 양성 대조(`git show research-final:DECISIONS.md`의 D-054 §6)를 분류기 게이트에 재사용한다.
- [ ] 가드레일 웹훅 검사기: `GATEWAY_GUARD_URL` → `POST {texts, role}` → `{verdict, score}`, 타임아웃과 fail-open/closed 설정, 사이드카를 웹훅으로 쓰는 예제.
- [ ] 한국어 recall이 기준에 못 미치면 조건부 '자체 파인튜닝' 트리거를 결정에 적는다.

완료 기준: 언어·유형별 수치 표, 관측 모드에서 차단 0과 점수 기록 테스트, 웹훅 타임아웃 테스트.

근거: 옛 2·3차 기각(D-052 유사도, D-054 gemma3:4b Judge)은 특정 구성과 8GB VRAM 환경의 결과이고, 인코더 분류기는 시험하지 않았다.

### 19. 보안 백서 + 법적 위치 메모 + PoC 키트

할 일
- [ ] `docs/security-whitepaper.md`: 데이터 흐름, 저장하지 않는 것(원문 무저장·요청 단위 메모리), 대체값 키를 추가정보로 다루는 법, 위협 모델, 한계.
- [ ] `docs/legal-position.md`(2쪽 이내, '변호사 검토 전 초안' 표시): PIPA 제2조 가명처리 정의와의 관계, 제28조의2 특례가 서비스 운영에 적용되지 않는 이유, 처리위탁·국외이전 때 최소화와 안전성 확보조치로서의 위치, 제28조의4 추가정보.
- [ ] `scripts/poc_report.py`: 고객 샘플(JSONL) → 종류별 탐지 수·오탐 후보·복원률·지연 p95 마크다운 리포트. 원문은 리포트에 넣지 않는다.

완료 기준: 문서 둘, poc_report가 합성 샘플로 리포트를 만드는 테스트.

사용자 몫: 변호사 검토 1회, 외부 1인 백서 리뷰.

### 20. 릴리스 공정

할 일
- [ ] `.github/workflows/release.yml`: 태그 `v*` → 이미지 빌드·GHCR 푸시·SBOM·서명(cosign 키리스)·취약점 스캔(HIGH 0이면 통과). 액션은 SHA로 고정한다.
- [ ] dependabot(pip·actions·docker).
- [ ] 비밀 검사기(gitleaks 등)를 CI에 넣으면 `eval/pii/`의 합성 키(Anthropic·GitHub·AWS·JWT·PEM·Google 꼴)가 걸린다 — 그 경로만 허용 목록에 둔다. GitHub push protection은 Slack·Anthropic·OpenAI·AWS 쌍·GitHub 토큰을 기본으로 막는다(2026-10-30 확인, D-115 보강).
- [ ] CHANGELOG 정리와 버전 올림.

완료 기준: 워크플로 문법 검사 통과, 사용자가 태그를 푸시한 뒤 릴리스 성공.

사용자 몫: 태그 push, GHCR 패키지 공개 설정.

### 21. 공개 데모(선택)

옛 D-109 계획이다. 공개 자유 입력을 외부 공급자로 보내지 않는다.

할 일
- [ ] `web/` 데모를 공개용으로: 상류는 스텁 고정, 본문 상한 4096, 레이트리밋, 로그는 임시 폴더.
- [ ] 데모용 Dockerfile과 배포 설정(Fly.io 또는 Render).

완료 기준: 로컬 docker run과 전체 통과, README 상단 링크.

사용자 몫: 계정·배포, 남용 징후가 보이면 끄기.

### 22. 디자인 파트너 PoC + 가격 + v1.0

할 일
- [ ] (사용자) 디자인 파트너 1곳: 하루 설치 → 2주 observe → mask 전환.
- [ ] PoC에서 나온 오탐을 정책별 예외 규칙(설정 파일 `allow_patterns`)으로 처리한다.
- [ ] 가격·계약 초안 `docs/pricing.md`(결정 표 9번).
- [ ] v1.0.0 기준: 2주 트래픽에서 의심 잔여 0.1% 미만, 5xx 0.1% 미만.

## 조건부

트리거가 생길 때만 단계로 올린다.

| 트리거 | 할 일 |
|---|---|
| 고객이 `previous_response_id`·서버 저장 대화의 복원을 요구 | 봉투 암호화 역매핑(TTL·KMS·접근·파기 로그) 또는 FF1 형식 보존 암호화 |
| 한 클러스터를 고객 둘 이상이 공유 | Redis 레이트리밋·지표 |
| 금융권 고객이 출력 단계 대책을 요구 | 응답 DLP(마스킹) |
| 분류기의 한국어 recall@FPR 1%가 기준 미달 | mDeBERTa 자체 파인튜닝 |
| SaaS 고객 3곳 이상 | 관리 API·콘솔 |
| 고객이 여러 파드를 합친 대시보드나 기간 그래프를 요구 | Grafana 대시보드 JSON 견본(같은 지표 이름 — `gateway_outcomes_total`·`gateway_pii_masked_total` 등). 게이트웨이 안에서 합산·저장은 하지 않는다 |
| 운영자 화면과 지표 수집기의 키를 나눠 달라는 요구 | 대시보드 전용 읽기 키(관리 키와 분리) |
| 공개 출시 직전 클론 크기가 문제 | 새 히스토리 저장소 |
| 목표 부하에서 게이트웨이 p95 > 50ms | 언어·런타임 교체 검토 |
| embeddings·files 요구 | 결정적 대체값으로 경로 추가 |

## 하지 않는 것

자체 인젝션 모델 학습(측정은 한다) · 설정을 바꾸는 관리 콘솔·SSO·RBAC(16-1 운영 대시보드는 읽기 전용이라 예외 — 쓰기 동작·로그인·원문 보기 없음) · SaaS 호스팅 · 금융·공공 직판(파트너 경유만) · 영속 볼트 · Redis · 응답 마스킹 · 서킷브레이커·재시도·폴백 · OTel · 연구 ASR 수치 영업 · 다국어 PII.

## 부록 A. 검증된 결함 요약 (2026-10-30, 커밋 34c16fb)

'직접'은 메인 세션 재현, '검증자'는 반박 전담 검증자의 재현, '미검증'은 검증 상한으로 재현하지 않은 것이다. 위치의 연구 파일은 1단계 이후 `research-final` 태그에 있다.

| 영역 | 결함 | 위치 | 확인 | 단계 |
|---|---|---|---|---|
| 보안 | 캐치올이 모든 경로·메서드에 운영자 상류 키를 붙인다 | main.py:377, auth.py:75 | 검증자 | 2 |
| 보안 | AUTH=off + 상류 키 = 무인증 중계 | main.py:90 | 검증자 | 2 |
| 보안 | 요청·응답 헤더가 거의 그대로 통과 | main.py:217·220 | 검증자 | 2 |
| 보안 | 무인증 시 X-Forwarded-For로 레이트리밋 우회·감사 ip 위조 | main.py:387 | 검증자 | 2 |
| 보안 | 세 POST 경로 밖은 검사 없이 통과, multipart 본문 깨짐 | main.py:405, pii.py:154 | 검증자 | 2 |
| 보안 | 무인증 health·metrics가 내부 정보 공개 | main.py:345·351 | 미검증 | 2 |
| 보안 | root 실행·태그 미고정·HEALTHCHECK·.dockerignore 없음 | gateway/Dockerfile | 미검증 | 1·2 |
| 가용성 | 볼트 발급이 고유 값 수의 제곱 시간 | vault.py:92 | 직접 | 3 |
| 가용성 | CPU 검사가 이벤트 루프 위, 워커 1 고정의 근거 소멸 | chain.py:97, Dockerfile:14 | 검증자 | 3 |
| 가용성 | 상류 600초 타임아웃이 연결·풀까지, 기본 풀 100 | main.py:175 | 검증자 | 3 |
| 마스킹 | 128자 넘는 대체값이 스트리밍에서 복원되지 않음 | vault.py:33 | 직접 | 3 |
| 마스킹 | 볼트 TTL 600초·용량 2,000 고정 | vault.py:63 | 미검증 | 3 |
| 마스킹 | 요청마다 난수 대체값 → thinking 서명·캐시 깨짐 | surrogate.py:25 | 검증자(기제), 실 API 미재현 | 4·7 |
| 마스킹 | tool·system 역할을 가리지 않음 | openai_api.py:13 | 직접 | 5 |
| 마스킹 | 비스트리밍이 thinking 텍스트까지 복원 | api/anthropic.py | 미검증 | 5 |
| 마스킹 | 도구 인자 복원 이스케이프가 한 단계 모자람 | pii.py:201 | 미검증 | 6 |
| 마스킹 | residual이 실제 복원 실패 대부분을 0으로 보고 | vault.py:137 | 검증자 | 6 |
| 마스킹 | 가짜 값이 실제 할당 대역에서 나옴 | surrogate.py:68 | 미검증 | 6 |
| 탐지 | 인젝션이 정규식 2개, 어휘 밖은 전부 통과 | injection.py:86 | 검증자 | 16·18 |
| 탐지 | 헤드라인 ASR이 garak 템플릿 문구 매칭 | docs/RESULTS.md:567 | 검증자 | 1 |
| 탐지 | 한국어 공격 탐지율 측정 0회 | tests/test_injection.py:266 | 검증자 | 16 |
| 탐지 | PII가 법정 고유식별정보 4종 중 2종 | patterns.py:24 | 검증자 | 10 |
| 탐지 | 약한 주민번호·Luhn 통과 숫자열 오탐 | pii.py:155 | 검증자 | 9 |
| 탐지 | 정규화 층 없음 | patterns.py | 미검증 | 9 |
| 탐지 | 2·3차 기각은 특정 구성의 결과, 인코더 분류기 미시험 | DECISIONS.md D-052·D-054 | 미검증(판단) | 18 |
| 탐지 | 정상셋 100문항(HR 단일 도메인, 고유 89) | eval/benign/all100.jsonl | 미검증 | 16 |
| 탐지 | 출력 방향은 세기만 함 | detectors/canary.py | 미검증 | 13 |
| 구조 | 멀티테넌시·정책·usage 집계 없음 | auth.py:63 | 검증자 | 12·13 |
| 구조 | 상류 URL·키가 하나 | main.py:61 | 검증자 | 12 |
| 구조 | 설정이 import 시점 전역 | main.py:57 | 미검증 | 11 |
| 저장소 | LICENSE·pyproject·릴리스 없음 | — | 직접 | 1·20 |
| 저장소 | 추적 용량의 98%가 results/ | results/ | 검증자 | 1 |
| 저장소 | CI가 pytest 한 단계, 자체 테스트가 확장을 막음 | tests/test_ci_readme_sync.py:158 | 검증자 | 1 |
| 시장 | Presidio가 KR 5종 공식 지원 | — | 직접 | 10 |
| 시장 | '모양 보존 대체값+복원'은 Kong·Private AI·Azure·Skyflow·LiteLLM이 이미 제공 | — | 반박 검증 안 함 | 22 |
| 규제 | 제28조의2 특례는 서비스 운영에 적용되지 않음, 매핑을 영속화하면 제28조의4 의무 | — | 반박 검증 안 함 | 19 |

## 부록 B. 실행 프롬프트

`/next-step`과 같은 내용이다. 명령이 안 보이면 이것을 붙여 넣는다.

```
/Users/hongjinkong/Desktop/project/llm-security-gateway/PLAN.md를 읽고 '결정 표'와 '모든 단계 공통 규칙'대로, '진행 상황'에서 체크 안 된 첫 단계부터 이어서 진행해줘. 되묻지 말고, 멈출 때는 진행 기록과 사용자 할 일을 갱신한 뒤 커밋 명령을 줘.
```
