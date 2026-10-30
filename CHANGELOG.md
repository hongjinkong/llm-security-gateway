# 변경 기록

## 미출시

- 실 공급자 2턴 확인(D-114): Claude(`claude-haiku-5-5`) 앞에서 둘째 턴이 thinking 서명 검사 400 없이 프롬프트 캐시를 읽었다 — 요청마다 난수였던 옛 코드는 5/5가 400
  (`docs/verification/multiturn_claude.md`, `scripts/check_multiturn_claude.py`)
- PII 평가 코퍼스와 CI 게이트(D-115): 합성 양성 500·음성 1,000·어려운 사례(`eval/pii/`), 종류별 재현율·오탐률과 Wilson 구간(`score.py`), `tests/test_pii_corpus.py`
- 정규화(D-116): 전각 숫자·문자·제로폭·서식 문자·대시 변형을 정규화해 탐지하고 원문 위치에 가짜 값을 넣는다(복원은 원문 그대로). 인젝션 룰도 정규화한 텍스트를 본다
- 오탐 축소(D-116): 구분자·문맥어 없는 약한 주민번호와 발급사 범위(국내 전용 9 포함) 밖 카드 꼴은 감사(`unmasked`)에만 남기고 가리지 않는다 —
  합성 업무 문장 오탐 12.3% → 0.3%

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
