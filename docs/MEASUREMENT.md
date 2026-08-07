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
```

(a)가 중요하다. 게이트웨이를 끼우기만 해도 ASR이 변하는지 먼저 확인해야,
이후 변화를 방어 로직 탓으로 돌릴 수 있다. 단위테스트에서는 응답이 동일함을
확인했지만, 실제 모델은 비결정적이므로 측정으로도 확인한다.

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
