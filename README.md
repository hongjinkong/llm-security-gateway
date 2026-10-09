# LLM Security Gateway

> **진행 중인 프로젝트다.** 무엇이 끝났고 무엇을 아직 재지 않았는지 2절에 그대로 적었다.
> 주장은 증거만큼만 좁혀 쓰고 숫자마다 한계를 함께 싣는다. 상세 결과와 경위는 [`docs/RESULTS.md`](docs/RESULTS.md)에 있다.

---

## 1. 무엇을 하나

LLM 애플리케이션과 OpenAI 호환 AI 공급자 사이에 삽입되어, 외부 AI로 전송되는 개인정보·기밀정보를
우선 보호하고 프롬프트 인젝션도 차단하는 **API 보안 게이트웨이**다(`SCOPE.md` 1절).

```
클라이언트 (AnythingLLM · OpenAI SDK — base_url만 바꾼다)
    │  POST /v1/chat/completions   (OpenAI Chat Completions 형식)
    ▼
게이트웨이 :8080
    요청  인젝션 룰 검사(걸리면 상류를 부르지 않고 차단) → 개인정보·자격 증명을 토큰으로 마스킹
    응답  토큰을 원래 값으로 복원 · 요청마다 감사 로그 한 줄(본문 원문은 남기지 않는다)
    │
    ▼
상류  로컬 Ollama(gemma3:4b — 공격 평가) / 외부 공급자(정상 요청·합성 데이터로 기능 검증만)
```

- **방어를 앱 바깥에 둔다.** 클라이언트와 모델 코드는 고치지 않는다. 검사기 구성은 환경변수
  `GATEWAY_DETECTORS` 하나로 바뀌므로, 같은 공격셋을 방어 없음·있음으로 돌려 그 차이를 잰다.
- **밖으로 나가는 정보가 보호의 중심이다**(D-073). `user`·`assistant` 메시지의 개인정보와 형식이
  고정된 자격 증명을 상류에 보내기 전에 가리고, 응답에서 되돌린다.
- **공격 평가는 로컬에 직접 배포한 구성에서만 한다.** 외부 공급자에는 공격 프롬프트를 보내지 않는다(9절).
- **측정 전에는 효과를 주장하지 않는다.** 기준을 먼저 동결·등록하고 잰다(4절).

`/v1/chat/completions` 밖의 경로(AnythingLLM API)도 같은 검사기를 거쳐 중계한다 — 게이트웨이를 AnythingLLM 앞에 둔
옛 측정 구조(v1)의 입구다.

---

## 2. 현재 상태

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 타겟 앱 선정·로컬 배포 | ✅ AnythingLLM (이미지 digest 고정) |
| 2 | 평가 기준 확정·동결 | ✅ 2026-07-27 (`EVAL_CRITERIA.md`) |
| 3 | 베이스라인 측정 (방어 없음) | ✅ `dan`·`promptinject`·`encoding` |
| 4 | 게이트웨이 코어 + PII 레이어 | 🟡 구현·테스트 완료. 마스킹 효과는 `dan`으로 잴 수 없음을 확인(D-065). D-099 수정분은 측정 전 |
| 5 | 인젝션 탐지 (룰 → 유사도 → LLM Judge) | 🟡 1차 룰만 남김. 2·3차는 사전 기준으로 기각(D-052·D-054), 코드는 `v1` 태그 |
| 6 | 출력 방어 + 카나리 | ⏹ 관측형으로 종결(D-059) — 세기만 하고 응답을 바꾸지 않는다 |
| 7 | 결과 요약·데모 (대시보드 대체, D-099) | 🟡 이 README·`docs/RESULTS.md`·`scripts/demo.py`. 데모 GIF는 D-100 뒤 |
| 8 | Docker / CI / 문서화 | 🟡 부분 — compose 기동, CI(push마다 테스트), 데모 |

새 구조(OpenAI 형식 입구, D-081):

| 항목 | 상태 |
|---|---|
| B1 `/v1/chat/completions` 입구 | ✅ |
| B2 AnythingLLM → 게이트웨이 → Ollama | ✅ 세 밤 측정(D-081, 코드 `3e2d81e49e73`) — 3절 |
| B3 실제 공급자 기능 검증 (정상 요청·합성 PII만) | 🟡 OpenAI `gpt-4o-mini` 합격(D-087). Gemini는 정상 대화까지(D-088). Claude는 키가 없어 범위 밖 |
| 현재 코드 `6d81265136b0` 기준값 | ⬜ **D-100 등록, 미측정** — 세 팔(`none`·`rule`·`turn`), `dan` 조각 실행, 다중 턴 FPR. 착수 지시서 `docs/next_D100_launch.md` |

---

## 3. 결과 요약

새 구조(D-081) 세 밤의 값이다. 측정 전에 등록한 무효 조건(E1~E7) 기준으로 세 밤 모두 유효하다.
**모두 D-099 이전 코드(`3e2d81e49e73`)로 쟀다. 새 코드(`6d81265136b0`)의 수치는 아직 없다(D-100 대기).**
팔은 `none`(게이트웨이 경유, 검사기 없음)과 `rule`(`injection_rule,pii_mask` — 검사 범위 (A))이고, 괄호는 Wilson 95% CI다.

| 지표 | 값 | 읽을 때의 한계 |
|---|---|---|
| `promptinject` 차단율 (`rule`) | **98.2%** (97.9–98.5), n=7,680 | 이력 전염 15.2%p가 들어 있다. 프롬프트만으로 막힌 몫은 82.8%다(D-094) |
| `promptinject` ASR `none` → `rule` | **72.2% → 0.3%** | 통과분의 ASR_pass는 16.1%(n=137). 두 팔이 달고 간 대화 이력이 다르다 |
| `dan` ASR_blk `none` → `rule` | **73.4% → 30.5%** | 부재 기반 판정기라 재채점 규약 적용값이다(`docs/SCORING_PROTOCOL.md`). 차단율 61.8% |
| `encoding` 차단 (`rule`) | **0 / 5,120** | 룰은 인코딩된 문구를 보지 못한다 — 사전 예측과 같다 |
| 단일 턴 FPR (정상셋 100문항) | **1.0~1.5%** (세 밤 관문), v1 1.0~2.0% | 작성자가 만들고 룰 설계 때 본 문항이다. 요청마다 새 세션인 단일 턴 조건이고, 다중 턴은 아직 안 쟀다(D-100) |
| `gateway_ms` p95 (정상셋) | **0.99~5.17ms** (목표 100ms 이하) | 짧은 정상 질문 기준이다. 검사기 비용은 입력 길이에 거의 비례한다(v1 측정) |

- **시도는 서로 독립이 아니다.** garak 요청은 공유 대화의 직전 20개를 달고 갔고(D-084) 그 내용이 팔마다 다르다.
  같은 프롬프트의 출력 10개도 독립이 아니라 CI가 실제보다 좁을 수 있다. 등록 기준상 유효는 순수 방어 효과의 인과 입증과 다르다.
- 차단율과 ASR 감소를 룰의 효과와 마스킹의 효과로 나누어 주장하지 않는다. 유의성 검정은 하지 않는다.
- 옛 구조(v1)의 결과와 경위 — 판정기가 차단을 읽지 못한 일(`dan`), 설명되지 않은 44%p(`promptinject`),
  기각된 2·3차 탐지기 — 는 [`docs/RESULTS.md`](docs/RESULTS.md) 3.1~3.8에 있다. 두 구조의 수치는 섞지 않는다.

---

## 4. 측정을 믿을 수 있게 만든 장치

- **기준 동결** — 평가 기준(`EVAL_CRITERIA.md`)을 방어 구현 전인 2026-07-27에 동결했다. 고치면 이전 측정이 전부 무효다.
- **사전 등록** — 측정마다 판정 규칙·무효 조건·예측을 실행 전에 `DECISIONS.md`에 적어 커밋한다.
  결과를 본 뒤 기준을 바꾸지 않았고, 그래서 2·3차 탐지기가 기각됐다.
- **무효 조건** — 공격 측정은 E1~E7, FPR은 F1~F5. 자료가 없거나 출처끼리 어긋나면 "통과"가 아니라 "무효"가 나온다(D-064).
- **판정기를 직접 만들지 않는다** — garak 표준 프로브와 내장 판정기를 쓴다. 판정기가 차단을 읽지 못하면
  판정기를 고치지 않고, 결과 전에 동결한 집계 규약으로 값을 옆에 놓는다(D-057).
- **변이 검사** — 테스트와 검증 도구에 결함을 일부러 넣어 잡히는지 센다(`scripts/mutate_*.py`).
  "전부 통과"는 하네스가 고장 나도 똑같이 나온다.
- **세 지표를 함께** — ASR·FPR·지연을 같은 구성에서 함께 보고하고, 분모와 신뢰구간을 붙인다.

---

## 5. 막지 못하는 것

- **형식이 없는 개인정보·기밀.** 탐지는 주민등록번호·카드번호·전화번호·이메일, 그리고 접두사가 고정된 키
  (OpenAI·Anthropic·AWS·GitHub·Google·Slack)·JWT·PEM 개인 키뿐이다. 이름·주소·계좌번호·서술형 민감정보,
  사내 문서·비밀번호 문장은 그대로 나간다.
- **`system`·`developer`·`tool` 메시지(RAG 문서 포함)의 개인정보는 가리지 않는다**(D-073). 이미지 같은 비텍스트도 보지 않는다.
- **역할 헤더 위조**(`System:`으로 시작하는 가짜 지시). 정상셋 경계 문항과 같은 모양이라 1차 룰에서 뺐고,
  넘겨받을 2차가 기각돼 지금은 어떤 층도 잡지 않는다.
- **룰은 알려진 문구에만 듣는다.** 인코딩된 공격은 한 건도 막지 못했다. 검사 범위 (A)는 이력에 걸린 턴이 하나라도
  있으면 그 대화의 뒤 요청을 계속 막는다(이력 전염, D-094). (C)는 걸린 이력 턴을 가려 이를 피하지만 기본값은 D-100 뒤 정한다.
- **출력 방향 방어 없음.** 시스템 프롬프트·문서 유출은 카나리로 세기만 하고(D-059) 막지 않는다. 모델이 응답에서
  새로 내보낸 개인정보도 사용자에게 그대로 간다.
- **단일 모델·단일 타겟.** 공격 측정은 `gemma3:4b` + AnythingLLM 조합뿐이다. 두 번째 클라이언트(OpenAI Python SDK)는
  기능만 확인했다(D-099 §8).
- **FPR은 조건부다.** 정상셋 100문항은 작성자가 만들었고 룰 설계 때 봤다. 단일 턴 조건의 값이다.
- **운영 제약.** 워커 1개(토큰 볼트가 프로세스 메모리에 있다), 스트리밍 미지원(`stream: true`는 400),
  사용자 인증·멀티테넌시 없음(`sessionId`는 신원이 아니다).

---

## 6. 실행 방법

Python 3.12 이상이 필요하다(`requirements.txt`의 `numpy`·`scipy` 핀이 3.12 이상을 요구한다).
CI는 새 체크아웃에서 아래 설치·테스트 명령을 글자 그대로 실행한다(Python 3.12·3.14,
`.github/workflows/cpu-tests.yml`, D-069). 둘이 어긋나면 `tests/test_ci_readme_sync.py`가 실패한다.

```bash
git clone <이 저장소>
cd llm-security-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

테스트는 가짜 상류를 쓴다 — Ollama·Docker가 필요 없다. CI가 push마다 돈다.

```bash
pytest -q
```

한 명령 데모. 스텁 상류와 게이트웨이(`injection_rule_turn,pii_mask`)를 임시 포트에 띄우고, 여섯 장면(개인정보·API 키·
assistant 이력·이번 턴 차단·이력 가림·413)에서 상류가 받은 것과 사용자가 받은 것을 나란히 보여 준다.

```bash
python3 scripts/demo.py
```

직접 띄워 보기 (터미널 둘):

```bash
uvicorn tests.stub_target:app --port 8000
```

```bash
GATEWAY_DETECTORS=injection_rule,pii_mask TARGET_URL=http://localhost:8000 uvicorn gateway.main:app --port 8080
```

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"stub-model","messages":[{"role":"user","content":"제 번호는 010-2345-6789입니다"}]}'
```

`GATEWAY_DETECTORS` 값에 따라 방어 구성이 바뀐다. 표에 없는 이름이면 게이트웨이가 기동하지 않는다.

| 값 | 동작 |
|---|---|
| (빈 값) | 검사기 없음 — 순수 프록시 |
| `pii` | 탐지만 하고 원문 그대로 전달 |
| `pii_mask` | `user`·`assistant` 메시지의 개인정보·자격 증명을 토큰으로 가려 전달하고 응답에서 복원 |
| `injection_rule` | 1차 룰 인젝션 차단, 검사 범위 (A) — 이력까지 `user`·`tool` 메시지 전체를 본다 |
| `injection_rule_turn` | 같은 룰, 검사 범위 (C) — 이번 턴이 걸리면 차단하고, 이력의 걸린 턴은 가린 채 통과시킨다(D-099) |
| `canary_observe` | 카나리 **관측 전용** — 응답을 바꾸지 않는다. 목록 맨 뒤 고정, `GATEWAY_CANARY_A/_B/_DOC`가 없거나 겹치면 기동하지 않는다(D-058-1) |

- 차단은 HTTP 200의 정상 completion(`finish_reason=content_filter`)으로 돌려준다. 상류는 부르지 않는다.
- 본문이 `GATEWAY_MAX_BODY_BYTES`(기본 1MiB)를 넘으면 검사기·상류를 부르지 않고 413을 돌려준다.
- `stream: true`는 OpenAI 오류 형식의 400으로 거부한다.
- 실행 중인 코드의 지문과 활성 검사기는 `curl -s localhost:8080/__gateway/health`로 본다.

다른 클라이언트로 붙여 보기 — 공식 OpenAI Python SDK를 `base_url`만 바꿔 붙이고 정상 대화·PII 마스킹과 복원·차단·
`stream` 거부·상류 401 중계를 확인한다. SDK는 프로젝트 의존성이 아니므로 별도 venv에 깔고 그 파이썬을 넘긴다.

```bash
python3 scripts/check_openai_sdk.py --sdk-python <openai가 깔린 파이썬>
```

Docker Compose(AnythingLLM + 게이트웨이)는 `cp .env.example .env`로 값을 채운 뒤 `docker compose up -d`로 띄운다.
새 구조(AnythingLLM → 게이트웨이 `/v1` → 호스트 Ollama)는 `.env.example` 끝의 선택 항목을 켠다.
측정 재현 절차는 `docs/MEASUREMENT.md`, 다음 측정 착수는 `docs/next_D100_launch.md`에 있다.

---

## 7. 저장소 구조

```
gateway/    프록시 본체 · OpenAI messages 파서 · 감사 로그 · 검사기 체인 · 토큰 볼트
  detectors/  base(인터페이스) noop pii injection canary
  data/       injection_corpus.jsonl (59항목, 룰 회귀 테스트·기록) · CORPUS.md
tests/      단위·통합 테스트 + 가짜 타겟
eval/       정상 질문셋 100문항 · FPR 실행기(단일·다중 턴) · 공격셋 오탐 스캐너
garak/      garak 러너 이미지 · REST generator 설정
scripts/    측정 실행 · 집계 · 지문 검증 · 밤샘 런 · 변이 검사 · 데모 · SDK 확인
docs/       RESULTS.md 상세 결과 · MEASUREMENT.md 측정 재현 · next_D100_launch.md 착수 지시서 · 설계 기록
results/    측정 산출물 원본 (요약만 남기고 버리지 않는다)
```

2차 유사도·3차 Judge의 코드와 그 테스트·스크립트는 `v1` 태그에 있다(D-099).

---

## 8. 문서

| 문서 | 내용 |
|---|---|
| `SCOPE.md` | 만드는 것 / 만들지 않는 것 / 절대 하지 않는 것 |
| `EVAL_CRITERIA.md` | 평가 기준 (동결됨) |
| `DECISIONS.md` | 모든 설계 결정의 날짜·근거·폐기 이력 (D-001 ~ D-100) |
| `docs/RESULTS.md` | 상세 결과 — README에서 옮긴 정량 결과(v1 3.1~3.8, 새 구조 3.9)·측정 장치·한계 |
| `docs/MEASUREMENT.md` | 측정 재현 절차 |
| `docs/next_D100_launch.md` | 다음 측정(D-100) 착수 지시서 |
| `docs/SCORING_PROTOCOL.md` | 차단형 방어 채점 규약 — 결과 전에 동결(D-057). garak 판정기는 고치지 않고 집계 규칙만 더한다 |
| `docs/CANARY_DESIGN.md` | 6단계 카나리 설계 — 동결(D-058) |
| `docs/JUDGE_DESIGN.md` | 3차 LLM Judge 설계 — 종결(D-054), 코드는 `v1` 태그 |
| `docs/RUNBOOK_GPU.md` | v1 `encoding` 무인 런 실행표(D-068) — 기록 |
| `gateway/data/CORPUS.md` | 2차 유사도 공격 코퍼스 59항목의 작성 기준 — 기록 |

---

## 9. 윤리 · 범위 제한

- 공격 테스트 대상은 **로컬에 직접 배포한 시스템으로 한정**한다. 타인이 운영하는
  실제 서비스를 대상으로 하는 테스트는 어떤 경우에도 하지 않는다.
- 모든 개인정보 테스트 데이터는 **합성 데이터**다. 실제 개인정보를 쓰지 않는다.
- 공격 프롬프트는 garak 표준 프로브이며, 이 저장소는 새로운 공격 기법을 만들거나
  공개하지 않는다.
