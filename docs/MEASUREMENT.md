# 측정 재현 절차

> 이 문서의 목적은 **명령을 기억에 의존하지 않는 것**이다.
> 베이스라인 3종(dan·promptinject·encoding)은 실제 실행 명령이 어디에도
> 기록되지 않은 채 결과만 남았다. SCOPE 7절 "단일 명령으로 전체 평가 재현"을
> 만족하려면 여기서부터는 모든 실행이 `scripts/run_garak.sh`를 거쳐야 한다.

## 0. 실행 환경

측정은 **학원 GPU PC에서만** 한다(D-025). 맥북은 코딩·단위테스트 전용이다.

장시간 실행 전 반드시:

```powershell
powercfg /change standby-timeout-ac 0
```

절전에 들어가면 WSL과 컨테이너가 통째로 죽어 Exit255가 난다(D-027, encoding 1차 실패 원인).

## 1. 준비

```bash
cd <저장소>
bash eval/preflight.sh                      # 타겟 기동 + Ollama 모델 상주 확인
docker compose build gateway                # 게이트웨이 이미지 빌드
GATEWAY_DETECTORS= docker compose up -d      # 검사기 없이 기동
curl -s localhost:8080/__gateway/health      # {"status":"ok", ...} 확인
```

`garak-runner` 이미지가 없으면:

```bash
docker build -t garak-runner garak/
```

## 2. 한 번의 측정

```bash
bash scripts/run_garak.sh <target|gateway> <프로브> <생성횟수> <이름>
```

두 설정 파일은 **uri 한 줄만 다르다**. 나머지(요청 템플릿, 응답 필드, 타임아웃)는
동일하게 유지한다. 하나라도 바뀌면 EVAL 5.1에 따라 전체 재측정이다.

| | 설정 파일 | uri |
|---|---|---|
| 베이스라인 | `garak/anythingllm_rest.json` | `http://target-app:3001/...` |
| 게이트웨이 경유 | `garak/gateway_rest.json` | `http://gateway:8080/...` |

요청 템플릿에 `sessionId`를 넣지 않는다. 베이스라인이 그렇게 측정됐기 때문이다.
게이트웨이는 `sessionId`가 없으면 요청 단위로 마스킹 매핑을 격리하므로,
한 요청 안에서의 마스킹→복원은 정상 동작한다.

## 3. EVAL 5.2 증분 측정 순서

검사기 구성만 바꿔 같은 측정을 반복한다. **"다 만들고 한 번 측정"은 금지다.**

```bash
# (a) 방어 없음 — 게이트웨이는 지나가지만 검사기 0개. 프록시 오버헤드 자체를 잰다.
GATEWAY_DETECTORS= docker compose up -d gateway
bash scripts/run_garak.sh gateway <프로브> <횟수> gw_none_<프로브>

# (b) PII 탐지만
GATEWAY_DETECTORS=pii docker compose up -d gateway
bash scripts/run_garak.sh gateway <프로브> <횟수> gw_pii_<프로브>

# (c) PII 마스킹 + 복원
GATEWAY_DETECTORS=pii_mask docker compose up -d gateway
bash scripts/run_garak.sh gateway <프로브> <횟수> gw_piimask_<프로브>

# (d) 룰 기반 인젝션 탐지 추가 — 5단계. 순서는 D-037(인젝션 탐지가 마스킹보다 앞).
GATEWAY_DETECTORS=injection_rule,pii_mask docker compose up -d gateway
bash scripts/run_garak.sh gateway <프로브> <횟수> gw_rule_<프로브>

# (e) 2차 유사도 — 관측 전용으로 동행. 차단이 0이므로 ASR·FPR 기여도 0이다.
#     본표에 새 행을 만들지 않는다. 점수 분포만 부록으로 싣는다(D-052/D-053).
GATEWAY_DETECTORS=injection_rule,injection_similarity_observe,pii_mask docker compose up -d gateway
bash scripts/run_garak.sh gateway <프로브> <횟수> gw_ruleobs_<프로브>
```

각 구성 전에 반드시:

```bash
bash scripts/verify_gateway.sh injection_rule,pii_mask
```

```bash
bash scripts/verify_gateway.sh injection_rule,injection_similarity_observe,pii_mask
```

### (e)에 관하여 — `injection_similarity`는 쓰지 않는다

차단형 `injection_similarity`는 `GATEWAY_SIMILARITY_T`가 없으면 **기동 실패**한다(D-048).
T는 캘리브레이션 2회로도 갭이 열리지 않아 동결되지 못했다(D-052). 그래서 배선에 올라가는
이름은 `injection_similarity_observe` 하나뿐이며, `verify_gateway.sh`의 `활성 검사기` 줄이
그 사실을 매 측정마다 기록한다 — "관찰 모드였는지"를 사람이 기억할 필요가 없다.

`observe`는 코퍼스 59항목을 기동 시 임베딩하므로 **Ollama가 살아 있어야 뜬다.**
compose는 `GATEWAY_OLLAMA_URL`을 `host.docker.internal:11434`로 넘긴다. Ollama가 죽어
있으면 게이트웨이가 아예 뜨지 않는다 — 방어가 꺼진 채로 측정이 도는 것보다 낫다.

(a)가 중요하다. 게이트웨이를 끼우기만 해도 ASR이 변하는지 먼저 확인해야,
이후 변화를 방어 로직 탓으로 돌릴 수 있다. 단위테스트에서는 응답이 동일함을
확인했지만, 실제 모델은 비결정적이므로 측정으로도 확인한다.

## 3-1. 맥북 예행연습 (학원 PC 없이 배선을 확인한다)

측정 자체는 학원 PC 전용이지만, **배선이 맞는지는 맥북에서 미리 확인할 수 있다.**
가짜 타겟(`tests/stub_target.py`)을 쓰면 모델 없이 100문항을 전부 통과시켜
FPR 집계 경로와 감사 로그 필드를 검증할 수 있다.
2026-08-10에 5단계 차단 경로를 이 방법으로 처음 검증했다 — 그전까지 `blocked`는
한 번도 발생한 적이 없어 집계 코드가 실행된 적조차 없었다.

```bash
python3 -m uvicorn tests.stub_target:app --port 8000 --log-level error
```

```bash
GATEWAY_DETECTORS= TARGET_URL=http://127.0.0.1:8000 GATEWAY_LOG_PATH=/tmp/reh/audit_off.jsonl python3 -m uvicorn gateway.main:app --port 8080 --log-level error
```

```bash
BASE_URL=http://127.0.0.1:8080 WORKSPACE_SLUG=demo TARGET_API_KEY=k RUNS=1 SLEEP=0 python3 eval/fpr_run.py eval/benign/all100.jsonl /tmp/reh/fpr_off.jsonl
```

ON 구성은 `GATEWAY_DETECTORS=injection_rule,pii_mask`, 포트와 로그 경로만 바꿔 반복한다.
그다음 집계:

```bash
python3 scripts/fpr_report.py --off /tmp/reh/fpr_off.jsonl --on /tmp/reh/fpr_on.jsonl --audit-off /tmp/reh/audit_off.jsonl --audit-on /tmp/reh/audit_on.jsonl
```

확인할 것:

- `FPR = 1.0%` (차단 1건 = B-103). D-040의 설계 예측과 일치해야 한다
- `transformed=true : 13개` — 체인 순서를 바꿔도 PII 마스킹이 깨지지 않았다는 증거
- `차단을 일으킨 룰` 절에 `injection_rule/R2`
- `토큰 복원 감사` 절이 `residual_tokens 0`

**주의**: 가짜 타겟은 질문을 그대로 되돌려주므로 `all_facts_hit`은 전부 0이다.
예행연습으로 판단할 수 있는 것은 **배선과 집계 경로**뿐이고, FPR의 '부분 저하'
판정이나 지연 수치는 여기서 얻을 수 없다.

## 4. 세 지표를 함께 낸다

ASR만 있는 결과는 무효다(EVAL 1절).

**ASR** — garak 리포트에서:

```bash
python3 scripts/asr_summary.py garak/logs/garak_runs/<이름>.report.jsonl \
  | tee results/<이름>_summary.md
```

**FPR / 지연** — 정상 질문셋 100개 순차 실행에서 함께 얻는다(D-021):

```bash
python3 eval/validate_benign.py        # 게이트웨이를 향하도록 대상 주소 확인 필요
python3 eval/pii_report.py             # PII 탐지 재현율·오탐 (맥북에서도 가능)
```

지연은 게이트웨이 감사 로그에서 뽑는다.

```bash
python3 - <<'PY'
import json, statistics as st
rows = [json.loads(l) for l in open("logs/gateway.jsonl")]
g = sorted(r["gateway_ms"] for r in rows)
def p(q): return g[int(len(g)*q)] if g else 0
print(f"n={len(g)}  p50={p(.50):.1f}ms  p95={p(.95):.1f}ms  p99={p(.99):.1f}ms")
PY
```

**`gateway_ms`가 SCOPE 7절 "p95 +100ms 이하"의 대상이다.** `total_ms`는
gemma3:4b 생성 시간이 지배해서 방어 비용 판단에 쓸 수 없다.

### 차단이 있는 구성(5단계~)의 지연 해석

차단된 요청은 타겟을 호출하지 않는다. 따라서 `upstream_ms`가 `None`이고
`total_ms`는 1ms대로 찍힌다. 이 값이 통계에 섞이면 **종단 지연이 실제보다
짧아 보인다.** 차단 비율이 높아질수록 왜곡이 커진다.

`gateway_ms`는 원래 게이트웨이 자체 처리 시간이므로 섞여도 의미가 유지된다.
`fpr_report.py`가 차단 건수를 감지하면 이 경고를 자동으로 출력한다.

## 5. 기록

측정 1회마다 남긴다.

- `results/`에 원본 `report.jsonl`과 요약 md를 함께 커밋 (EVAL 5.3)
- `DECISIONS.md`에 날짜·검사기 구성·프로브·생성횟수·결과·소요시간
- EVAL_CRITERIA 5.2 표의 해당 행

## 6. 베이스라인 실행 명령 (2026-08-07 확정)

`scripts/run_garak.sh`는 아래 실제 명령을 그대로 옮긴 것이다. 셸 히스토리에만
남아 있던 것을 여기에 고정했다. 앞으로는 이 스크립트가 단일 출처다.

```bash
# dan (2026-07-30, 리포트 9abe5583...) — 최종본에는 --parallel_requests 없음
docker run -d --name baseline_dan \
  --network llm-security-gateway_default \
  -e REST_API_KEY="$TARGET_API_KEY" \
  -v "$PWD/garak:/work" \
  -v "$PWD/garak/logs:/root/.local/share/garak" \
  garak-runner \
    --target_type rest -G /work/anythingllm_rest.json \
    --probes "$DAN_PROBES" --generations 10

# promptinject (2026-08-06) — --probes promptinject --generations 10
# encoding    (2026-08-07) — --probes encoding      --generations 3
```

주의할 점 세 가지:

1. **`-e REST_API_KEY=`** 가 맞다. garak RestGenerator가 설정 파일의 `$KEY` 자리에
   넣는 환경변수 이름이 `REST_API_KEY`다. 다른 이름으로 주면 인증 없이 나가 401이 난다.
2. **`-v "$PWD/garak/logs:/root/.local/share/garak"`** — `garak_runs/` 하위만
   마운트하면 `garak.log`가 남지 않는다.
3. **`--parallel_requests`는 쓰지 않는다.** 최종 3종 모두 순차였고
   (리포트 `parallel_requests: false`), D-024에서 8GB VRAM 병렬이 오히려 느렸다.

`-d`(detached)로 띄우는 이유: 몇 시간짜리 실행이라 터미널이 닫혀도 살아남아야 한다.
화면잠금(Win+L)은 괜찮지만 절전은 컨테이너를 통째로 죽인다(0절 참조).

### 남은 정리 — API 키 단일 출처

promptinject·encoding 실행은 `$REST_API_KEY`라는 셸 변수를 썼는데 `.env`에는 그 이름이
없다. 그래서 `baseline_dan` 컨테이너가 값 보관처가 되어 삭제 금지 상태였다.
dan 실행은 `.env`의 `$TARGET_API_KEY`를 썼으므로 두 값이 같은지 확인하면 정리된다.

```bash
docker inspect baseline_dan --format '{{range .Config.Env}}{{println .}}{{end}}' | grep REST_API_KEY
grep TARGET_API_KEY .env
```

같으면 `.env`가 단일 출처가 되고 컨테이너를 붙잡아둘 이유가 없어진다.
