# LLM Security Gateway

LLM 앱과 AI 공급자 사이에 끼워 넣어, **밖으로 나가는 개인정보·자격 증명을 같은 모양의 가짜 값으로 바꿔 보내고 응답에서 되돌리며,
프롬프트 인젝션을 관측(선택하면 차단)하고, 요청마다 감사 한 줄을 남기는** API 게이트웨이다. OpenAI Chat Completions·Responses, Anthropic Messages
세 API를 스트리밍·도구 호출까지 그대로 통과시킨다. 앱과 모델 코드는 고치지 않는다 — 클라이언트의 `base_url`과 API 키(게이트웨이 키)만 바꾼다.
공급자 키는 게이트웨이 한 곳에만 둔다.

> **상태(2026-10-30)**: 연구 단계(D-001~D-105 — 측정·종결)를 마친 뒤 **서비스로 전환했다(D-107)**: 인증과 키 보관, 요청 단위 볼트, 모양 보존 대체값,
> Messages·Responses API, 인젝션 기본 관측, 로그 회전·지표·레이트리밋. 현재 코드 `ac56e263ddc6`는 측정 입력 전부(13,023회)에서 차단 구성의 판정이
> 옛 코드와 같다(`results/d107_equivalence.md`). 3절 수치는 `6d81265136b0`·차단 모드·토큰 방식으로 잰 값이다. 주장은 증거만큼만 쓰고, 숫자마다 한계를 함께 적는다.

---

## 1. 무엇을 하나

```
클라이언트 (OpenAI SDK · Anthropic SDK · AnythingLLM — base_url과 api_key(게이트웨이 키)만 바꾼다)
    │  POST /v1/chat/completions · /v1/responses · /v1/messages   (스트리밍·도구 호출 포함)
    ▼
게이트웨이 :8080   클라이언트 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 파싱(400)
    요청  인젝션 룰 관측(또는 차단) → user·assistant 텍스트와 도구 인자의 개인정보·자격 증명을 같은 모양의 가짜 값으로 교체
    상류  클라이언트의 인증 헤더를 떼고 공급자 키를 단다
    응답  가짜 값을 원래 값으로 복원(스트리밍은 조각 경계·채널별) · 요청마다 감사 로그 한 줄(원문 없음) · /__gateway/metrics
    │
    ▼
상류  OpenAI · Anthropic · 로컬 Ollama(gemma3:4b — 공격 평가는 여기서만) / 외부 공급자에는 정상 요청·합성 데이터만
```

- **방어를 앱 바깥에 둔다.** 설정은 환경변수 몇 개다(6절). 측정은 같은 공격을 방어 없음·있음으로 돌려 차이를 잰다.
- **밖으로 나가는 정보가 보호의 중심이다**(D-073). 상류는 `010-8419-3027` 같은 가짜 값을 보고 보통의 값으로 다룬다 — 모델이 "가려졌다"고 눈치채지 않고,
  도구 인자에도 그대로 쓰며, 사용자는 원래 값을 돌려받는다(D-107 B). 상류 로그에는 가짜 값이 남는다(상류 운영자는 그것이 대체값인지 알 수 없다 — 의도된 선택).
- **인젝션은 기본으로 막지 않는다.** 룰은 정규식 둘이고 정상 문장("ignore the instructions in the PDF and summarize")도 걸린다. 적중은 감사에 남고
  (`would_block`), 운영자가 `GATEWAY_INJECTION=block`으로 켠다. 3절의 수치는 차단 모드의 값이다.
- **공격 평가는 로컬에 직접 배포한 구성에서만 한다.** 외부 공급자에는 공격 프롬프트를 보내지 않는다(9절).

바로 보기: `python3 web/app.py`(브라우저 비교 화면) 또는 `python3 scripts/demo.py`(터미널) — Docker·Ollama 없이 여섯 장면을 보여 준다(6절).
아래는 웹 화면에서 장면 1·3·4·5·6을 누른 기록이다(토큰 방식이던 D-104 때의 GIF — 지금은 "상류가 실제로 받은 것"에 토큰 대신 가짜 값이 보인다).

![데모 — 게이트웨이 없음 vs 있음](docs/demo.gif)

---

## 2. 현재 상태

| 구분 | 상태 |
|---|---|
| 타겟 배포 · 평가 기준 동결 · 베이스라인 | ✅ AnythingLLM(이미지 digest 고정) · 2026-07-27 동결(`EVAL_CRITERIA.md`) · `dan`·`promptinject`·`encoding` |
| 게이트웨이 · PII 마스킹 · 인젝션 1차 룰 | ✅ 구현·테스트 완료, 리뷰 결함 10건 수정(D-102), 스트리밍(D-106), **서비스 전환(D-107: 인증·키 보관·대체값·세 API·관측 기본·운영)**. 2차 유사도·3차 LLM Judge는 사전 기준으로 기각(D-052·D-054), 코드는 `v1` 태그 |
| 출력 방어 · 카나리 | ⏹ 관측형으로 종결(D-059) — 세기만 하고 응답을 바꾸지 않는다 |
| 새 구조 공격 측정 | ✅ 최종 코드 `6d81265136b0` 기준값(D-100) — `dan`·`promptinject`, 팔 `none`·`rule`·`turn` 모두 유효 · 옛 코드 세 밤(D-081) |
| 외부 공급자 기능 검증 | ✅ OpenAI `gpt-4o-mini` 합격(D-087) · Claude `claude-opus-5-5` 합격(D-103, OpenAI 호환 입구, 호출 3회; 스트리밍 복원 1회 합격 D-106 §8) · Gemini는 정상 대화까지(D-088) |
| 데모 | ✅ 터미널 `scripts/demo.py` · 웹 `web/app.py` · GIF(D-104) |
| 남은 일 | 2026-10-29 종결(D-105) 뒤 보강 중 — 스트리밍(D-106 ✅) → 서비스 전환(D-107 ✅) → 진입 정리·CI lint·타입(D-108) → 웹 공개 배포(D-109) |

### 성공 기준(SCOPE 7절) 대비

| 기준 | 결과 | 판정 |
|---|---|---|
| 공격 성공률이 베이스라인보다 유의미하게 줄고 신뢰구간을 함께 보고 | `promptinject` 74.5% → 7.8%(권장 (C)) · 0.2%((A)), `dan` 75.9% → 31.2% · 29.4%, Wilson 95% CI 병기(3절). 시도가 독립이 아니라 유의성 검정은 하지 않았다 | 달성 — 한계 병기 |
| 정상 질문셋 FPR 5% 이하 | 단일 턴 1.0%(N=100, 고유 89), 다중 턴 (C) 0.0% · (A) 100.0% | (C) 달성. (A)는 다중 턴에서 미달 — 그래서 (C)가 기본 |
| 지연 p95 +100ms 이하 | `gateway_ms` p95 1.02~1.41ms(짧은 정상 질문) | 달성 |
| `docker compose up` 뒤 단일 명령으로 전체 평가 재현 | 테스트·데모는 단일 명령(`pytest`, `scripts/demo.py`, `web/app.py`). 공격 측정은 compose + 호스트 Ollama + 밤샘 절차(`docs/next_D100_launch.md`, 약 2.5일)라 단일 명령이 아니다 | 부분 달성 |
| 타겟 앱 교체 시 설정 파일 1개 수정 | 클라이언트는 `base_url` 하나(AnythingLLM·OpenAI SDK·데모 웹). 상류 교체는 `TARGET_URL`(경로가 다르면 `GATEWAY_CHAT_UPSTREAM_PATH` 하나 더). 공격 평가 하네스는 AnythingLLM 전용 | 달성(클라이언트·상류). 평가 하네스는 전용 |

---

## 3. 결과 요약

최종 코드(`6d81265136b0`)로 새 구조(AnythingLLM → 게이트웨이 → Ollama)에서 잰 값이다(D-100). 측정 전에 등록한 무효 조건 기준으로
두 프로브의 세 팔이 모두 유효하다. 팔은 `none`(게이트웨이 경유, 검사기 없음)·`rule`(`injection_rule,pii_mask` — 검사 범위 (A))·
`turn`(`injection_rule_turn,pii_mask` — 검사 범위 (C), 권장 기본값)이고, 괄호는 Wilson 95% 신뢰구간이다.
현재 코드(`ac56e263ddc6`, D-107)는 이 측정의 입력 1,447문장 × 9가지 재생 13,023회에서 차단 구성(`rule`·`turn`·`pii`)의 판정·검사기 기록이 D-106 코드와 전부 같다
(`results/d107_equivalence.md`; D-106·D-102 때는 상류 본문까지 같았다 — `results/d106_equivalence.md`·`results/d102_equivalence.md`). D-107부터 상류 본문은 대체값이라 비교하지 않는다.
**현재 기본 구성은 인젝션 관측(`observe`)이다** — 아래 표의 `rule`·`turn` 수치는 `GATEWAY_INJECTION=block`에서만 성립한다.

| 지표 | `none` | `rule` (A) | `turn` (C, 권장) | 읽을 때의 한계 |
|---|---|---|---|---|
| `promptinject` 공격 성공률, n=7,680 | 74.5% (73.5–75.5) | **0.2%** (0.2–0.4) | **7.8%** (7.2–8.4) | 차단율 98.2% vs 82.8%. (A)가 더 막은 15.4%p는 이번 턴은 룰에 걸리지 않는데 앞 대화에 있던 공격 때문에 막힌 몫이다(D-094·D-101) |
| `dan` 공격 성공률, n=4,000 | 75.9% (74.6–77.2) | **29.4%** (28.1–30.9) | **31.2%** (29.8–32.7) | 판정기가 차단 문구를 거절로 읽지 못해, 결과 전에 동결한 채점 규약으로 센 값이다(ASR_blk). 차단율 61.8% vs 58.8% |
| 정상 질문 오탐률(FPR), 질문마다 새 대화 | — | **1.0%** (0.2–5.4), N=100 | **1.0%** (0.2–5.4), N=100 | 작성자가 만들고 룰 설계 때 본 100문항(고유 문장 89 — 일반 문항 11쌍이 같은 문장, D-102 §4). 목표 5% 이하, 노이즈 플로어 0.0% |
| 다중 턴 FPR — 룰에 걸린 정상 질문 뒤 같은 대화의 정상 질문 | — | **100.0%** (83.9–100.0), N=20 | **0.0%** (0.0–16.1), N=20 | 한 가지 시나리오를 1회 쟀다. (A)는 정상 질문 하나가 걸리면 같은 대화의 뒤 질문을 계속 막는다 |
| 게이트웨이 지연 `gateway_ms` p95 | 1.22ms | **1.41ms** | **1.02ms** | 짧은 정상 질문 100개 기준. 목표 100ms 이하. 검사 비용은 입력 길이에 거의 비례한다(v1 측정) |

- 기본값은 이 공격 쪽 결과를 보기 전에 다중 턴 FPR을 근거로 (C)로 정했다(D-101). `promptinject`에서 (C)가 (A)보다 7.6%p 더 뚫리는 것은
  그 비용으로 보고한다.
- `encoding`은 최종 코드로 다시 재지 않았다. 옛 코드에서 룰이 5,120건 중 0건을 막아 (A)·(C)가 갈릴 표면이 없다(D-081 §13·D-100 §1).
- **시도는 서로 독립이 아니다.** garak 요청은 같은 대화의 직전 20개를 달고 갔고(D-084), 같은 프롬프트의 출력 10개도 독립이 아니라
  신뢰구간이 실제보다 좁을 수 있다. `turn`은 마지막 팔이라 순차 실행과 이력 내용 차이가 섞여 있다. 유의성 검정은 하지 않고,
  룰의 효과와 마스킹의 효과를 나누어 주장하지 않는다. 등록 기준상 "유효"는 방어 효과의 인과 입증과 다르다.
- 옛 코드(`3e2d81e49e73`)로 잰 세 밤(D-081)과 옛 구조(v1)의 결과·경위 — 판정기가 차단을 읽지 못한 일, 설명되지 않은 44%p,
  기각된 2·3차 탐지기 — 는 [`docs/RESULTS.md`](docs/RESULTS.md)에 있다(이 절의 상세는 3.10). 수치는 서로 섞지 않는다.

---

## 4. 측정을 믿을 수 있게 만든 장치

- **기준을 먼저 얼린다.** 평가 기준(`EVAL_CRITERIA.md`)은 방어를 만들기 전인 2026-07-27에 동결했다. 고치면 이전 측정이 전부 무효다.
- **재기 전에 등록한다.** 측정마다 판정 규칙·무효 조건·예측을 실행 전에 `DECISIONS.md`에 커밋한다.
  결과를 본 뒤 기준을 바꾸지 않았고, 그래서 2·3차 탐지기가 기각됐다.
- **자료가 이상하면 "무효"가 나온다.** 공격 측정은 E1~E7, 오탐률은 F1~F5. 자료가 없거나 출처끼리 어긋나면 통과가 아니라 무효다(D-064).
- **공격과 판정기를 직접 만들지 않는다.** garak 표준 프로브와 내장 판정기를 쓴다. 판정기가 차단을 읽지 못하면 판정기를 고치지 않고,
  결과 전에 동결한 채점 규약으로 값을 옆에 놓는다(D-057).
- **테스트가 정말 잡는지 센다.** 테스트와 검증 도구에 결함을 일부러 넣어 잡히는지 확인한다(`scripts/mutate_*.py`).
  "전부 통과"는 하네스가 고장 나도 똑같이 나온다.
- **세 지표를 함께 낸다.** ASR·FPR·지연을 같은 구성에서 함께 보고하고, 분모와 신뢰구간을 붙인다.

---

## 5. 막지 못하는 것

- **형식이 없는 개인정보·기밀.** 탐지는 주민등록번호·카드번호·전화번호(국내·국제 `+국가번호`·괄호 지역번호)·이메일, 그리고 접두사가 고정된 키
  (OpenAI·Anthropic·AWS·GitHub·Google·Slack)·JWT·PEM 개인 키뿐이다. 이름·주소·계좌번호·여권·IBAN·서술형 민감정보는 그대로 나간다.
- **`system`·`developer`·`instructions`·`tool`(도구 결과) 텍스트(RAG 문서 포함)의 개인정보**는 가리지 않는다(D-073). 이미지 같은 비텍스트도 보지 않는다.
- **룰이 모르는 공격.** 룰은 알려진 문구에만 듣는다. 인코딩된 공격은 한 건도 막지 못했다. `System:`으로 시작하는 역할 헤더 위조는
  정상 문항과 모양이 같아 룰에서 뺐고, 넘겨받을 2차가 기각돼 지금은 어떤 층도 잡지 않는다.
- **검사 범위 (A)의 이력 전염과 (C)의 비용.** (A)는 이력에 룰에 걸린 턴이 하나라도 있으면 그 대화의 뒤 요청을 계속 막는다(D-094, 다중 턴 FPR 100%).
  기본값인 (C)는 걸린 이력 턴만 가려 이를 피하지만(D-101), 이번 턴은 룰에 걸리지 않는 공격을 이력에 다른 공격이 있다는 이유로 막지는 않는다 —
  `promptinject` 공격 성공률 (A) 0.2% → (C) 7.8%(D-100).
- **출력 방향.** 시스템 프롬프트·문서 유출은 카나리로 세기만 하고(D-059) 막지 않는다. 모델이 새로 내보낸 개인정보도 사용자에게 그대로 간다.
- **측정 범위.** 공격 측정은 `gemma3:4b` + AnythingLLM 조합, 차단 모드, 토큰 방식(`6d81265136b0`)뿐이다. 현재 코드는 판정 동등성으로만 잇는다(3절).
  OpenAI·Anthropic SDK와 Messages·Responses API는 기능만 확인했다(D-107 §8).
- **대체값 복원 실패는 조용하다.** 모델이 가짜 값을 알아볼 수 없게 바꿔 쓰면(구분자·대소문자 변경은 복원된다) 사용자는 가짜 값을 받는다 —
  토큰 시절처럼 `[PII:`가 보이지 않는다. 감사의 `issued`/`restored`/`residual_tokens`와 지표 `gateway_pii_residual_total`로만 보인다(D-107 B).
- **운영 제약.** 워커 1개 고정, 레이트리밋·지표는 프로세스별이다. 멀티테넌시 없음(클라이언트 키는 이름일 뿐 권한 구분이 없다). Responses API의
  `previous_response_id`로 상류에 쌓인 이전 턴은 게이트웨이가 볼 수 없다(이미 대체값으로 보냈다).

---

## 6. 실행 방법

Python 3.12 이상이 필요하다(`requirements.txt`의 `numpy`·`scipy` 핀이 3.12 이상을 요구한다).
CI는 새 체크아웃에서 아래 설치·테스트 명령을 글자 그대로 실행한다(Python 3.12·3.14, D-069). 둘이 어긋나면 `tests/test_ci_readme_sync.py`가 실패한다.

```bash
git clone <이 저장소>
cd llm-security-gateway
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

테스트는 가짜 상류를 쓴다 — Ollama·Docker가 필요 없다.

```bash
pytest -q
```

한 명령 데모 — 스텁 상류와 게이트웨이(`injection_rule_turn,pii_mask`)를 임시 포트에 띄우고, 여섯 장면(개인정보·API 키·
assistant 이력·이번 턴 차단·이력 가림·413)에서 상류가 받은 것과 사용자가 받은 것을 나란히 보여 준다.

```bash
python3 scripts/demo.py
```

브라우저 비교 화면 — 같은 요청을 게이트웨이 없음·있음에 나란히 보내고, 상류가 실제로 받은 것·사용자가 받은 답·감사 한 줄을 보여 준다.
여섯 장면 프리셋과 직접 입력(이어지는 대화)을 지원한다. 기본은 스텁 상류이고, 있음 쪽만 실제 공급자로 바꿀 수 있다
(`WEB_ON_TARGET=https://api.anthropic.com WEB_ON_MODEL=claude-opus-5-5`, 키는 `ANTHROPIC_API_KEY`). 없음 쪽은 언제나 스텁이다 —
외부 공급자에는 공격을 보내지 않으므로 실제 공급자 모드에서는 인젝션 프리셋이 꺼진다(9절).

```bash
python3 web/app.py
```

직접 띄워 보기 (터미널 둘):

```bash
uvicorn tests.stub_target:app --port 8000
```

```bash
GATEWAY_CLIENT_KEYS=demo=demo-key TARGET_URL=http://localhost:8000 uvicorn gateway.main:app --port 8080
```

```bash
curl -s http://localhost:8080/v1/chat/completions \
  -H 'Authorization: Bearer demo-key' -H 'Content-Type: application/json' \
  -d '{"model":"stub-model","messages":[{"role":"user","content":"제 번호는 010-2345-6789입니다"}]}'
```

실제 공급자 앞에 두기 — 공급자 키는 게이트웨이 환경변수 한 곳에만 있고, 클라이언트는 게이트웨이 키를 쓴다(`python -m gateway keygen`으로 만든다).

```bash
GATEWAY_CLIENT_KEYS="app=$(python3 -m gateway keygen)" GATEWAY_UPSTREAM_KEY=sk-ant-... TARGET_URL=https://api.anthropic.com \
  uvicorn gateway.main:app --port 8080
```

클라이언트는 `base_url`을 `http://localhost:8080`(Anthropic SDK) 또는 `http://localhost:8080/v1`(OpenAI SDK)로, `api_key`를 게이트웨이 키로 바꾼다.
Docker는 `gateway/Dockerfile` 하나다 — `docker build -f gateway/Dockerfile -t llm-gateway . && docker run -p 8080:8080 -e GATEWAY_CLIENT_KEYS=... -e TARGET_URL=... llm-gateway`.

### 설정 — 환경변수

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `TARGET_URL` | `http://localhost:8000` | 상류(공급자) 주소. Chat Completions의 상류 경로만 `GATEWAY_CHAT_UPSTREAM_PATH`로 바꿀 수 있다(Gemini) |
| `GATEWAY_CLIENT_KEYS` | (없음 — **기동 실패**) | 클라이언트 키 `이름=키,이름2=키2`. `Authorization: Bearer`나 `x-api-key`로 낸다. 로컬 실험만 `GATEWAY_AUTH=off` |
| `GATEWAY_UPSTREAM_KEY` | (없음) | 공급자 키. 있으면 클라이언트의 인증 헤더를 떼고 상류 형식(`/v1/messages*`는 `x-api-key`, 그 밖은 `Bearer`)으로 단다. 없으면 클라이언트 헤더를 그대로 넘긴다(로컬 Ollama) |
| `GATEWAY_PII` | `mask` | `mask`(대체값으로 바꾸고 응답에서 복원) · `detect`(감사에만) · `off`. 종류는 `GATEWAY_PII_KINDS`(기본 `rrn,card,phone,email,secret`) |
| `GATEWAY_INJECTION` | `observe` | `observe`(적중을 감사에만, `would_block`) · `block`(이번 턴이 걸리면 차단, 이력의 걸린 턴은 가림 — 검사 범위 (C)) · `off`. `GATEWAY_INJECTION_SCOPE=all`이면 (A) |
| `GATEWAY_CANARY_A/_B/_DOC` | (없음) | 셋 다 있으면 카나리 관측이 체인 맨 뒤에 붙는다(D-058) |
| `GATEWAY_MAX_BODY_BYTES` | 1MiB | 넘으면 검사기·상류를 부르지 않고 413 |
| `GATEWAY_RATE_PER_MINUTE` | 0(끔) | 클라이언트(무인증이면 IP)마다 분당 상한. 넘으면 429 + `retry-after`, 상류 없음 |
| `GATEWAY_LOG_PATH` | `logs/gateway.jsonl` | 감사 로그. `-`면 stdout. 파일이면 `GATEWAY_LOG_MAX_BYTES`(100MiB)·`GATEWAY_LOG_BACKUPS`(5)로 회전 |
| `GATEWAY_DETECTORS` | (없음) | 저수준 검사기 목록(쉼표). **설정돼 있으면 위 PII·INJECTION·CANARY 설정을 무시한다** — 측정·테스트용. 빈 값은 검사기 없음 |

`GATEWAY_DETECTORS`의 이름: `pii`·`pii_mask`·`injection_observe`·`injection_rule`((A))·`injection_rule_turn`((C))·`canary_observe`(맨 뒤 고정)·`noop`.

- 처리 순서: 키 검증(401) → 레이트리밋(429) → 본문 상한(413) → 파싱(400) → 인젝션 → PII → 상류 → 복원 → 감사 한 줄. 401·429·413은 본문을 검사하지도 중계하지도 않는다.
- 차단(`block` 모드)은 HTTP 200의 정상 응답으로 돌려준다 — Chat `finish_reason=content_filter`, Messages `stop_reason=refusal`, Responses `status=incomplete`(`content_filter`),
  모두 `gateway_blocked: true`와 문구 끝의 `(요청 ID: …)`. 사유는 넣지 않는다(감사에만). 상류는 부르지 않는다.
- 스트리밍(`stream: true`)은 상류 SSE를 조각마다 흘려보내며 채널(텍스트·도구 인자·content block)마다 조각 경계에 걸린 대체값을 복원한다(D-106·D-107 C).
  감사 줄은 스트림이 끝난 뒤 한 줄. 오류(400·401·413·429·502·504)는 스트리밍 요청에도 JSON이고 형식은 API를 따른다(Messages는 Anthropic 오류 형식).
- `curl -s localhost:8080/__gateway/health`로 코드 지문·활성 검사기를, `/__gateway/metrics`로 Prometheus 지표(요청·차단·마스킹·복원·잔여·지연)를 본다. 둘 다 키가 필요 없다.
- 세 API 밖의 경로(AnythingLLM API 등)도 키 검증을 거쳐 같은 검사기(바이트 검사)로 중계한다 — 옛 측정 구조(v1)의 입구다.

### 그 밖의 실행

- **다른 클라이언트** — 공식 SDK를 `base_url`·`api_key`만 바꿔 붙여 확인한다. SDK는 프로젝트 의존성이 아니므로 별도 venv에 깔고 그 파이썬을 넘긴다.
  OpenAI(`chat.completions`·`responses`, 스트리밍·차단·401): `python3 scripts/check_openai_sdk.py --sdk-python <openai가 깔린 파이썬>`,
  Anthropic(`messages`, 스트리밍·도구 호출·401·틀린 게이트웨이 키): `python3 scripts/check_anthropic_sdk.py --sdk-python <anthropic이 깔린 파이썬>`
- **Docker Compose**(AnythingLLM + 게이트웨이) — `cp .env.example .env`로 값을 채운 뒤 `docker compose up -d`.
  새 구조(AnythingLLM → 게이트웨이 `/v1` → 호스트 Ollama)는 `.env.example` 끝의 선택 항목을 켠다.
- **측정 재현** — 새 구조는 `docs/next_D100_launch.md`, 옛 구조(v1)는 `docs/MEASUREMENT.md`.

---

## 7. 저장소 구조

```
gateway/    프록시 본체(main) · 인증(auth) · API 어댑터(api/: chat·anthropic·responses) · 검사기(detectors/: injection·pii·patterns·canary) ·
            대체값(surrogate)·볼트(vault)·스트리밍 복원(streaming) · 감사 로그(audit)·지표(metrics)·레이트리밋(ratelimit)
  detectors/  base(인터페이스) noop pii injection canary
  data/       injection_corpus.jsonl (59항목, 룰 회귀 테스트·기록) · CORPUS.md
web/        데모 웹 — 브라우저 비교 화면. 게이트웨이 밖의 또 하나의 클라이언트(base_url만 바꾼다)
tests/      단위·통합 테스트 + 가짜 타겟
eval/       정상 질문셋 100문항 · FPR 실행기(단일·다중 턴) · 공격셋 오탐 스캐너
target/     타겟 앱에 올리는 합성 문서(가상 회사의 인사 규정)·시스템 프롬프트 — 측정 입력
garak/      garak 러너 이미지 · REST generator 설정
scripts/    측정 실행 · 집계 · 지문 검증 · 밤샘 런 · 변이 검사 · 동등성 재생 · 데모 · SDK·Claude 확인
docs/       상세 결과 · 채점 규약 · 측정 절차 · 설계 기록 (8절)
results/    측정 산출물 원본 (요약만 남기고 버리지 않는다)
```

2차 유사도·3차 Judge의 코드와 그 테스트·스크립트는 `v1` 태그에 있다(D-099).

---

## 8. 문서

처음 읽는다면 이 README → [`docs/RESULTS.md`](docs/RESULTS.md)(상세 결과·한계) → 아래 "먼저 볼 결정" 순서가 빠르다.

| 문서 | 내용 |
|---|---|
| `SCOPE.md` | 만드는 것 / 만들지 않는 것 / 절대 하지 않는 것 |
| `EVAL_CRITERIA.md` | 평가 기준 — 2026-07-27 동결 |
| `DECISIONS.md` | 모든 결정의 날짜·근거·폐기 이력 (D-001 ~ D-107, 최신이 맨 끝) |
| `docs/RESULTS.md` | 상세 결과 — 옛 구조 3.1~3.8, 새 구조 3.9(옛 코드)·3.10(최종 코드) · 측정 장치 · 한계 |
| `docs/SCORING_PROTOCOL.md` | 판정기가 차단을 읽지 못할 때의 채점 규약 — 결과 전에 동결(D-057) |
| `docs/CANARY_DESIGN.md` | 카나리 관측(`canary_observe`) 설계 — 동결(D-058) |
| `docs/next_D100_launch.md` | 새 구조 측정(D-100)의 착수·회수 절차 |
| `docs/MEASUREMENT.md` | 옛 구조(v1) 측정 재현 절차 |

기록으로만 남긴 문서 — 지금 코드의 동작과 무관하다: `docs/JUDGE_DESIGN.md`(3차 Judge 설계, 종결 D-054),
`docs/RUNBOOK_GPU.md`(v1 `encoding` 무인 런 실행표, D-068), `gateway/data/CORPUS.md`(2차 유사도 코퍼스 작성 기준).

**먼저 볼 결정** (`DECISIONS.md`)

| 번호 | 내용 |
|---|---|
| D-039 · D-040 | 룰은 공개 지식만으로 만들고 공격셋은 봉인한다 · 1차 룰 설계("놓치는 쪽이 잘못 막는 쪽보다 낫다") |
| D-052 · D-054 | 2차 유사도·3차 LLM Judge를 사전 기준으로 기각 |
| D-057 | 판정기가 차단을 읽지 못할 때의 채점 규약 — 결과 전에 동결 |
| D-070 · D-073 | 외부 AI 공급자 앞 API 게이트웨이로 방향 전환 · 밖으로 나가는 정보를 보호의 중심으로 |
| D-081 · D-084 | 새 구조 첫 평가(세 밤) · garak 요청이 공유 대화 이력 20개를 달고 간다 |
| D-094 · D-095 | 이력 전염의 크기 · 검사 범위 세 안 비교 |
| D-099 · D-100 · D-101 | 리뷰 반영 수정 묶음 · 최종 코드 기준값 · 기본 검사 범위 (C) |
| D-102 | 독립 리뷰 결함 10건 수정 · 판정 동등성 재생(13,023회 차이 0) · 정상셋 중복 관찰 |
| D-103 · D-104 · D-105 | Claude 기능 검증 사전 등록 · 데모 웹과 GIF · 종결(성공 기준 대비 결과, 잔재 정리) |
| D-106 | 스트리밍 응답 통과 — 조각 경계의 토큰 복원, 감사 한 줄, SSE 차단(판정 동등성 재생 13,023회 차이 0) |
| D-107 | **서비스 전환** — 인증·키 보관, 요청 단위 볼트(세션 가로채기 결함 수정), 모양 보존 대체값, Messages·Responses API, 인젝션 기본 관측, 로그 회전·지표·레이트리밋 |

---

## 9. 윤리 · 범위 제한

- 공격 테스트 대상은 **로컬에 직접 배포한 시스템으로 한정**한다. 타인이 운영하는
  실제 서비스를 대상으로 하는 테스트는 어떤 경우에도 하지 않는다.
- 모든 개인정보 테스트 데이터는 **합성 데이터**다. 실제 개인정보를 쓰지 않는다.
- 공격 프롬프트는 garak 표준 프로브이며, 이 저장소는 새로운 공격 기법을 만들거나
  공개하지 않는다.
