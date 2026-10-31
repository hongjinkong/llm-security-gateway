# 운영

배포·키 회전·로그·지표·대시보드·용량. 설정 항목은 [설정](configuration.md), 경로·오류 형식은 [API 호환 범위](api-compat.md)에 있다.

## 배포

**이미지** — `docker build -f gateway/Dockerfile -t llm-security-gateway .`
베이스는 다이제스트로 고정한 `python:3.12-slim`, 비root(uid 10001)로 돈다. 포트 8080. 감사 로그(JSONL)는 stdout, 기동·오류 로그는 stderr다.
uvicorn 접근 로그는 꺼 두었다 — 쿼리 문자열을 값까지 찍어 감사 로그가 일부러 빼는 값을 남긴다. 동시 연결 1,000을 넘으면 uvicorn이 503을 준다.
루트 파일 시스템을 읽기 전용으로 둬도 된다(쓰는 파일이 없다 — 감사 로그를 파일로 쓸 때만 쓰기 가능한 볼륨이 필요하다).

**로컬 체험** — [`deploy/compose.yml`](../deploy/compose.yml): 게이트웨이 + 스텁 상류. 외부 공급자로는 아무것도 나가지 않는다. 키가 고정값이라 운영에 쓰지 않는다.

```bash
docker compose -f deploy/compose.yml up --build
```

`http://127.0.0.1:8080`이 게이트웨이(클라이언트 키 `test-key`, 관리 키 `local-admin-key`), `http://127.0.0.1:8000/__stub/received`가 상류가 실제로 받은 본문이다.
포트가 겹치면 `HOST_PORT=18080 STUB_HOST_PORT=18000`, 인젝션 차단을 보려면 `GATEWAY_INJECTION=block`을 앞에 붙인다.
공식 SDK 점검: `python3 scripts/check_openai_sdk.py --sdk-python <openai가 깔린 파이썬> --gateway http://127.0.0.1:8080`(차단 항목이 있어 `GATEWAY_INJECTION=block`으로 띄운다),
`scripts/check_anthropic_sdk.py`도 같다.

### Kubernetes

[`deploy/k8s/`](../deploy/k8s/)는 kustomize 디렉터리다(`kubectl apply -k`, kubectl에 들어 있다).

| 파일 | 내용 |
|---|---|
| `gateway.yaml` | Deployment(레플리카 2) · Service(ClusterIP 8080) · PodDisruptionBudget(`minAvailable: 1`) |
| `gateway.toml` | 설정 파일 → ConfigMap. 클라이언트 키 해시·정책·상류 |
| `secret.env.example` | → `secret.env`(커밋하지 않는다) → Secret. 대체값 키·관리 키·공급자 키 |
| `kustomization.yaml` | 위 둘로 ConfigMap·Secret을 만든다. 이름에 내용 해시가 붙어 바꾸고 apply하면 롤링 재시작된다 |

1. 이미지 — `gateway.yaml`의 `image`는 릴리스가 올리는 GHCR 주소다. 릴리스 전이거나 사내 레지스트리를 쓰면 직접 빌드해 올리고 그 주소로 바꾼다.
2. 비밀 — `cp deploy/k8s/secret.env.example deploy/k8s/secret.env` 뒤 채운다. 대체값 키·관리 키는 `python -m gateway keygen`(패키지가 없으면 `docker run --rm <이미지> python -m gateway keygen`).
   쓰지 않는 공급자는 `gateway.toml`에서 그 상류 표를 지운다 — `key_env`가 가리키는 값이 비면 기동하지 않는다.
3. 클라이언트 — `python -m gateway keygen --hash`의 첫 줄(키)은 클라이언트에게 주고, 둘째 줄을 `gateway.toml`의 `[[clients]]`에 넣는다. 클라이언트가 없으면 기동하지 않는다.
4. `kubectl apply -k deploy/k8s -n <네임스페이스>` → `kubectl rollout status deployment/llm-security-gateway -n <네임스페이스>`.
5. 확인 — `kubectl port-forward -n <네임스페이스> svc/llm-security-gateway 8080:8080` 뒤 `curl localhost:8080/__gateway/health`, 관리 키로 `/__gateway/info`(버전·설정 버전·상류).

파드는 Pod Security `restricted`를 만족한다(비root·읽기 전용 루트·권한 상승 없음·capabilities 없음·seccomp RuntimeDefault, 서비스 계정 토큰 없음).
레플리카는 노드에 나눠 놓으려 하고(soft), readiness는 `/__gateway/health`다. 워커는 파드당 1이다 — 지표·레이트리밋·대체값 세션 상한이 프로세스 단위라 파드 수로 늘린다.

**밖으로 열기.** 게이트웨이는 평문 HTTP다. 클라이언트 키와 가리기 전 원문이 이 구간을 지나므로 TLS는 인그레스나 서비스 메시에서 끝내고 Service를 그대로 밖에 내지 않는다.
인그레스 뒤에서 감사 줄의 `ip`를 실제 클라이언트 주소로 남기려면 `FORWARDED_ALLOW_IPS`에 인그레스 주소를 준다. 게이트웨이에서 나가는 연결은 공급자 HTTPS(443)뿐이다.
k8s 견본은 쉬는 연결을 75초 붙잡는다(`UVICORN_TIMEOUT_KEEP_ALIVE`, uvicorn 기본 5초) — 인그레스·LB의 유휴 시간(보통 60초)보다 짧으면 LB가 게이트웨이가 막 닫은 연결로
요청을 보내 502가 난다. 인그레스의 유휴 시간을 바꿨으면 이 값을 그보다 길게 둔다.

**종료.** preStop `sleep 5`(Service 엔드포인트에서 빠질 시간) 뒤 SIGTERM, uvicorn이 진행 중인 요청·스트림을 25초까지 기다린다 — `terminationGracePeriodSeconds: 30`.
25초보다 오래 남은 스트림은 끊기고, 비스트리밍 요청은 감사 줄에 500 `CancelledError`로 남는다(대시보드 '처리 중 취소됨'). 설정·키를 바꾸면 재시작해야 적용된다(다시 읽기는 없다) — kustomize 견본은 apply가 롤링 재시작을 만든다.

## 키 회전

| 키 | 있는 곳 | 바꾸는 법 |
|---|---|---|
| 클라이언트 키 | `gateway.toml` `[[clients]]`(해시) 또는 `GATEWAY_CLIENT_KEYS` | 새 키를 **같은 이름으로 한 줄 더** 넣고 apply → 클라이언트를 새 키로 → 옛 줄을 지우고 apply. 끊김이 없다 |
| 관리 키 | `GATEWAY_ADMIN_KEY` | 바꾸고 apply, 지표 수집기의 토큰도 바꾼다(롤링 동안 옛 키 파드는 새 토큰에 404). 대시보드를 연 탭은 404를 받아 키를 지우므로 새 키를 다시 넣는다 |
| 공급자 키 | `key_env`가 가리키는 변수(`OPENAI_API_KEY` 등) 또는 `GATEWAY_UPSTREAM_KEY` | 공급자에서 새 키를 받아 넣고 apply → 옛 키 폐기 |
| 대체값 키 | `GATEWAY_SURROGATE_KEY` | 아래 |

**대체값 키.** 같은 원문을 같은 가짜 값으로 만드는 키다. 바꾸면 진행 중인 대화는 다음 턴에 이력 속 가짜 값이 달라진다.

- 그 턴은 프롬프트 캐시 미스다.
- Anthropic extended thinking을 쓰는 대화는 그 턴이 **400**(`Invalid signature in thinking block … bound to a different conversation`)으로 거절된다 — 이력의 thinking 블록이
  바뀐 앞 내용과 맞지 않는다. 새 대화로 시작해야 한다. 실제 Claude API에서 확인한 동작이다(가짜 값이 요청마다 달랐던 옛 코드가 2턴 대화 5개 모두 거절됐다 — DECISIONS D-114).
- 롤링 배포 동안 옛 키 파드와 새 키 파드가 섞이면, 한 대화의 턴이 서로 다른 파드로 갈 때 같은 일이 생긴다.

절차: 트래픽이 적을 때 한 번에 바꾼다(`secret.env`를 고치고 `kubectl apply -k`). 섞이는 시간은 롤링이 끝날 때까지다. 롤링이 끝나면 옛 Secret을 지운다 —
kustomize는 이름에 해시가 붙은 옛 Secret·ConfigMap을 지우지 않아 옛 키가 클러스터에 남는다
(`kubectl get secret,configmap -n <네임스페이스> -l app.kubernetes.io/name=llm-security-gateway`로 보고, Deployment가 가리키지 않는 것을 `kubectl delete`). 섞임을 아예 없애려면 그동안만 Deployment `strategy`를
`Recreate`로 둔다(모든 파드가 내려갔다 올라오는 동안 끊긴다). 정해진 주기는 없다 — 키가 샜을 때, 담당자가 바뀔 때, 공급자 로그에서 같은 원문끼리 이어지는 것(같은 키 아래 같은 원문은
늘 같은 가짜 값)을 끊고 싶을 때 바꾼다. 키와 가짜 값이 함께 있으면 전화번호처럼 공간이 작은 값은 전수 대입으로 되짚을 수 있으므로, 키는 공급자 키와 같은 등급으로 보관하고
(가능하면 외부 비밀 관리자) 접근 기록을 남긴다 — 법률 검토 전까지 개인정보 보호법의 '추가정보'로 다룬다.

같은 효과(진행 중인 대화의 가짜 값이 바뀜)가 나는 변경: 가릴 종류·역할 바꾸기(`pii_kinds`·`pii_detect_kinds`·`pii_roles`), 탐지 규칙이나 가짜 값 생성이 바뀐 버전으로 올리기(CHANGELOG에 적는다),
이미지의 파이썬 메이저 버전 교체(가짜 값을 만드는 난수 생성기). 이것들도 대체값 키처럼 한 번에 바꾼다.

## 로그

- **감사 로그** — 요청 1건 = JSON 한 줄. 이미지는 stdout, 그 밖은 `GATEWAY_LOG_PATH` 파일(100MiB × 5 회전). 스트리밍은 스트림이 끝난 뒤 한 줄이다.
  **원문은 없다** — 본문은 크기와 SHA-256 앞 12자, 쿼리는 키 이름만 남는다. 탐지는 종류별 건수와 앞 100건의 위치(시작·끝·길이)·확신도,
  인젝션 룰은 발동한 어휘(우리 사전의 단어)가 남는다 — 값 자체는 남지 않는다. 게이트웨이 자체 경로(`/__gateway/*`)는 남기지 않는다.
- **기동·오류 로그** — stderr(uvicorn). 기동 거부는 무엇을 고칠지 문장으로 남긴다(`GATEWAY_LANG`).
- k8s에서는 노드의 로그 수집기(Fluent Bit·Vector 등)가 컨테이너 stdout을 모은다. stdout의 모든 줄이 JSON이다.
- 감사 줄에 원문은 없지만 클라이언트 이름·IP·모델·사용량이 있다 — 보존 기간은 사내 로그 정책을 따른다.

| 필드 | 뜻 |
|---|---|
| `ts` `request_id` | UTC 시각, 요청 ID(응답 헤더·상류 헤더 `x-gateway-request-id`와 같다) |
| `method` `path` `query_keys` `query_bytes` `status` `error` | 요청·결과. `error`는 게이트웨이가 정한 사유(`unauthorized`·`model_not_allowed`·`upstream_busy`·파싱 400의 `invalid_json`·`invalid_messages`·`invalid_request`·`invalid_stream`·허용 목록 밖 404의 `not_found`…)나 예외 타입 이름. 게이트웨이가 낸 4xx·5xx 줄에는 모두 있다 — 코드는 [대시보드](#대시보드)의 표 |
| `total_ms` `upstream_ms` `gateway_ms` `chain_ms` | 지연 — 전체·상류·게이트웨이 몫·검사기 |
| `req_bytes` `req_sha256_12` `res_bytes` | 크기와 본문 지문 |
| `client` `policy` `ip` `api` `model` `config` | 클라이언트 이름·정책·주소·API(`chat`·`responses`·`messages`·`models`)·요청 모델·설정 파일 버전 |
| `usage` | `{input, output, cache_read, cache_write}` 토큰 — 상류가 준 것(스트리밍 포함). 비용 집계는 이것 × 모델 단가 |
| `upstream_request_id` | 상류가 준 요청 ID(공급자 문의용) |
| `blocked` `blocked_by` `transformed` | 차단 여부·차단한 검사기·본문을 바꿨는지 |
| `pii_issued` `pii_restored` `pii_suspect` `pii_new` | 가짜 값 발급·복원 수, 의심 잔여(복원 실패 신호), 응답에 새로 나온 PII |
| `detectors` `response_detectors` | 검사기별 결과(종류별 건수, 감사만 종류 `unmasked`, 인젝션 룰 적중 `would_block`) |

## 지표

`GET /__gateway/metrics`(Prometheus 텍스트), `Authorization: Bearer <GATEWAY_ADMIN_KEY>` — 관리 키가 없으면 404다. 감사 레코드에서 세므로 감사 줄과 어긋나지 않는다.
값은 프로세스 메모리의 카운터라 **파드(워커)마다 따로이고 재시작하면 0**이다 — 파드마다 긁고 `sum(rate(…))`로 본다.

| 지표 | 뜻 |
|---|---|
| `gateway_requests_total{api,status,blocked}` | 요청 수 |
| `gateway_outcomes_total{outcome,reason}` | 처리 결과 7가지와 사유 — 코드는 [대시보드](#대시보드)의 표 |
| `gateway_injection_hits_total{mode}` | 인젝션 룰 적중(observe는 `would_block`) |
| `gateway_pii_masked_total{kind}` | 실제로 가린 것(`pii_mask`, 종류별). detect 정책의 찾은 수와 감사만 종류는 세지 않는다 |
| `gateway_pii_unmasked_total{kind}` | 찾았지만 가리지 않은 것(종류별) — detect 정책의 찾은 수 + 감사만 종류(`unmasked`) |
| `gateway_pii_restored_total` · `gateway_pii_residual_total` · `gateway_pii_suspect_total` | 복원 수 · 복원 뒤 남은 가짜 값 · 의심 잔여(남은 가짜 값 + 가짜 값의 끝 4자리·로컬파트만 나타난 경우) |
| `gateway_pii_new_total` | 응답에 새로 나온 PII·비밀(가리지 않는다) |
| `gateway_upstream_ms_sum`·`_count`, `gateway_total_ms_sum`·`_count` | 지연 합·횟수 — 평균은 `rate(_sum) / rate(_count)` |
| `gateway_vault_sessions{policy}` | 진행 중인 대체값 세션 수(게이지, 정책마다). 2,000에 닿은 정책은 503 `gateway_busy` |
| `gateway_upstream_connections_in_use{upstream}` | 빌려 간 상류 연결 수(게이지, 상류 주소마다 — 주소가 같아도 `timeout`이 다르면 풀이 따로라 가장 바쁜 풀의 값). `GATEWAY_MAX_CONNECTIONS`에 닿으면 새 요청이 기다리다 503 `upstream_busy` |

```yaml
# Prometheus — 파드를 직접 긁는다. 관리 키는 파일로 준다.
scrape_configs:
  - job_name: llm-security-gateway
    metrics_path: /__gateway/metrics
    authorization:
      credentials_file: /etc/prometheus/secrets/gateway-admin-key
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_name]
        regex: llm-security-gateway
        action: keep
      - source_labels: [__meta_kubernetes_pod_container_port_name]
        regex: http
        action: keep
```

볼 것: `gateway_pii_suspect_total`·`gateway_pii_residual_total`이 늘면 복원이 실패하고 있다(사용자가 가짜 값을 받는다 — 가짜 휴대전화 번호는 실제로 쓰이는 번호일 수 있다).
5xx 비율(`gateway_requests_total{status=~"5.."}`), 503(`upstream_busy`면 상류 지연·풀 크기, `gateway_busy`면 파드 수), `gateway_pii_new_total`(모델이 새 개인정보를 낸다),
`gateway_upstream_connections_in_use`가 `GATEWAY_MAX_CONNECTIONS`에 붙어 있으면 곧 `upstream_busy`다.

## 대시보드

`GET /__gateway/dashboard` — 요청마다 무엇을 가리고 막고 거절했는지와 그 사유를 브라우저 한 장에 보여 주는 읽기 전용 화면이다(D-124). 시험·체험·PoC 중에 본다.
관리 키(`GATEWAY_ADMIN_KEY`)가 설정된 게이트웨이에만 있다(없으면 404). 화면은 인증 없이 주는 정적 HTML이라 데이터·키·버전이 없고,
화면의 스크립트가 탭에 넣은 관리 키로 `/__gateway/info`와 `/__gateway/stats`(이 프로세스의 누적과 최근 200줄)를 읽는다. 응답을 받고 2초 뒤 다시 읽고,
탭이 숨거나 [멈춤]이면 쉰다. 설정을 바꾸는 동작·로그인·원문 보기는 없다. 화면과 폴링은 감사 로그·지표·레이트리밋에 들어가지 않는다.

**여는 법**

| 환경 | 주소 | 관리 키 |
|---|---|---|
| 로컬 체험(compose) | `http://127.0.0.1:8080/__gateway/dashboard`(`HOST_PORT`를 바꿨으면 그 포트) | `local-admin-key` |
| Kubernetes | `kubectl port-forward -n <네임스페이스> pod/<파드> 8080:8080` 뒤 `http://127.0.0.1:8080/__gateway/dashboard` | `secret.env`의 `GATEWAY_ADMIN_KEY` |
| 시험 트래픽 | `python3 scripts/traffic.py`가 시작할 때 찍는 `http://127.0.0.1:8070/__gateway/dashboard` | `traffic-admin` |

- Kubernetes는 파드 하나씩 본다 — 숫자가 파드마다 따로다. 파드 이름은 `kubectl get pods -n <네임스페이스> -l app.kubernetes.io/name=llm-security-gateway`.
  Service 너머로(인그레스·클러스터 안의 Service 주소) 보면 폴링마다 다른 파드에 붙어 숫자가 튀고 '다시 시작했거나 다른 프로세스' 띠가 뜬다.
- `scripts/traffic.py`는 자기 스텁 앞에 게이트웨이를 띄우고, 합성 값으로 만든 16장면(가림·기록만·차단·거절·AI 회사 오류가 모두 나온다)을 2초 쉬며 되풀이 보낸 뒤
  대시보드의 줄과 기대를 대조한다. 시작할 때 주소·관리 키와 클라이언트 키를 찍는다 — 그 키로 직접 보낸 요청도 같은 화면에 보인다.
  `--rounds N`이면 N회 뒤 끝나고(어긋나면 종료 코드 1), `--port`로 포트를 바꾼다. 외부 공급자로는 보내지 않는다. 개발 의존성(`pip install -e ".[dev]"`)이 필요하다.

**키를 넣는 법과 보관**

- 키가 없으면 키 카드가 뜬다. 관리 키를 넣고 [열기]를 누른다.
- 키는 그 탭의 `sessionStorage`에만 둔다 — URL·쿠키·localStorage에는 두지 않는다. 탭을 닫거나 [잠금]을 누르면 사라진다(새로고침에는 남는다).
- 브라우저가 키(비밀번호) 저장을 물으면 저장하지 않는다 — 저장하면 탭을 닫아도 브라우저에 남는다.
- 화면은 키를 `Authorization: Bearer` 헤더로만 보낸다. 관리 경로는 `?key=`·Basic을 받지 않는다(404).
- 404를 받으면 키를 지우고 "키가 틀렸거나 이 게이트웨이에 관리 키가 없습니다"를 보인다. 관리 키를 바꾸면 열어 둔 탭도 이렇게 되므로 새 키를 다시 넣는다.
- 지표 수집기의 토큰과 같은 키다 — 그 토큰으로 최근 요청 요약(원문·가짜 값·위치·IP는 없다)도 열린다.

**머리 띠** — 버전·코드 지문·설정 버전·정책별 검사기(info), "시작 HH:MM:SS 이후(pid N) — 다시 시작하면 0", 마지막 갱신 시각, 연결 상태, [멈춤]·[잠금].
시작 시각이나 pid가 바뀌면 '다시 시작했거나 다른 프로세스 — 숫자가 0부터' 띠가, 읽기에 실패하면 '연결 끊김' 띠가 뜬다(5초 뒤 다시 시도).

**타일 8개** — 모두 이 프로세스가 시작한 뒤의 값이다.

| 타일 | 뜻 | 같은 값의 지표 |
|---|---|---|
| 요청 수 | 받은 요청(감사 줄 수). 보조 문구는 분당 평균·지금 초당 | `gateway_requests_total` |
| 가린 개인정보 | 가짜 값으로 바꾼 개수와 상위 3종 비율. '기록만 n'은 찾았지만 가리지 않은 수(detect 정책·감사만 종류) | `gateway_pii_masked_total` · `gateway_pii_unmasked_total` |
| 복원 실패 의심 | 응답에 가짜 값이나 그 조각(끝 4자리·로컬파트)이 남은 수. 0이 아니면 경고색과 '확인 필요' — 사용자가 가짜 값을 받았을 수 있다 | `gateway_pii_suspect_total` |
| 응답에 새로 나온 개인정보 | 모델이 스스로 낸 개인정보·비밀(가리지 않는다) | `gateway_pii_new_total` |
| 수상한 지시 기록 | 인젝션 룰 적중 — 기록만 n(observe) · 차단·이력 가림 m(block) | `gateway_injection_hits_total` |
| 게이트웨이 처리 시간 | 요청당 게이트웨이 몫의 평균(AI 응답 시간 빼고) = 감사 `gateway_ms`의 평균 | (`gateway_total_ms_sum` − `gateway_upstream_ms_sum`) ÷ `gateway_total_ms_count` |
| 사용 중 AI 연결 | 가장 바쁜 상류의 빌려 간 연결 / `GATEWAY_MAX_CONNECTIONS`, 진행 중인 대체값 세션. 연결이 가득 차면 새 요청이 기다리다 503 `upstream_busy` | `gateway_upstream_connections_in_use` · `gateway_vault_sessions` |
| 오류(5xx) 비율 | 5xx 응답의 비율 — 게이트웨이 500·503과 AI 회사 오류(502·504, 상류가 준 5xx), 본문 업로드 중 끊긴 요청(500 `ClientDisconnect`), 종료 유예를 넘겨 끝낸 요청(500 `CancelledError`). 스트림 도중의 끊김·AI 회사 오류는 200이라 들지 않는다(처리 결과에서 본다) | `gateway_requests_total{status=~"5.."}` |

**처리 결과와 사유** — 요청(감사 줄) 하나는 결과 7가지 중 하나다. 위에서부터 처음 맞는 것을 쓴다: 차단 → 거절 코드 → 상류 오류 → 그 밖의 예외 → 400 이상 상태 → 가림 → 기록만 → 그대로.
결과 칸을 누르면 최근 요청 표가 그 결과로 걸러진다. 지표 `gateway_outcomes_total{outcome,reason}`도 같은 코드다.

| 결과 | 화면 라벨 | 사유 코드 | 뜻 | HTTP | 상류 호출 |
|---|---|---|---|---|---|
| `masked` | 가림 후 전달 | `pii_mask` | 개인정보를 가짜 값으로 바꿈 | 200 | 있음 |
| `masked` | 가림 후 전달 | `masked_turns` | 이력의 수상한 턴을 가림 | 200 | 있음 |
| `passed` | 그대로 전달 | `none` | 해당 없음 | 200 | 있음 |
| `observed` | 기록만 | `injection_observe` | 수상한 지시 — 기록만 | 200 | 있음 |
| `observed` | 기록만 | `unmasked` | 가리지 않는 개인정보 — 기록만 | 200 | 있음 |
| `blocked` | 차단 | `injection_rule_turn` | 이번 턴의 수상한 지시(그 밖의 차단 검사기는 이름 그대로) | 200(차단 응답) | 없음 |
| `rejected` | 거절 | `unauthorized` | 키 없음·틀림 | 401 | 없음 |
| `rejected` | 거절 | `rate_limited` | 분당 한도 | 429 | 없음 |
| `rejected` | 거절 | `request_too_large` | 본문 상한 | 413 | 없음 |
| `rejected` | 거절 | `too_many_findings` | 개인정보가 너무 많음(가짜 값 발급 전) | 413 | 없음 |
| `rejected` | 거절 | `model_not_allowed` | 허용 안 된 모델 | 403 | 없음 |
| `rejected` | 거절 | `invalid_json`·`invalid_messages`·`invalid_request`·`invalid_stream` | 요청 형식 오류 | 400 | 없음 |
| `rejected` | 거절 | `not_found` | 허용 목록 밖 경로(인증 전에 걸러져 줄의 클라이언트·정책·API가 비어 있다) | 404 | 없음 |
| `rejected` | 거절 | `gateway_busy` | 게이트웨이 바쁨(진행 중인 대체값 세션 상한) | 503 | 없음 |
| `rejected` | 거절 | `upstream_busy` | AI 연결 가득(빈 상류 연결을 5초 기다려도 없음) | 503 | 없음 |
| `rejected` | 거절 | `http_<상태>` | 사유 코드가 없는 거절 — 나오지 않아야 한다(나오면 게이트웨이 버그다) | 그 상태 | 없음 |
| `upstream_error` | AI 회사 오류 | `upstream_<상태>` | AI 회사가 준 오류를 그대로 전달(예: `upstream_429`) | 상류가 준 상태 | 있음 |
| `upstream_error` | AI 회사 오류 | `upstream_stream_error` | AI 회사가 스트림 도중 오류를 보냄 | 200 | 있음 |
| `upstream_error` | AI 회사 오류 | `ConnectTimeout`·`ReadTimeout`·`WriteTimeout`·`PoolTimeout` | AI 응답 시간 초과 | 504(스트림 도중이면 200) | 시도함 |
| `upstream_error` | AI 회사 오류 | 그 밖의 상류 예외(`ConnectError`·`ReadError`·`RemoteProtocolError` 등) | AI 회사 연결 실패·끊김 | 502(스트림 도중이면 200) | 시도함 |
| `upstream_error` | AI 회사 오류 | `response_too_large` | AI 응답이 너무 큼(32MiB 초과) | 502 | 있음 |
| `failed` | 오류·끊김 | `ClientDisconnect` | 클라이언트가 끊음 | 200(스트림 도중)·500(본문을 보내다 끊음) | 경우에 따라 |
| `failed` | 오류·끊김 | `CancelledError` | 처리 중 취소됨 — 스트림 도중 클라이언트가 끊었거나(200), 종료·재시작 때 유예(25초)를 넘긴 진행 중 요청을 게이트웨이가 끝냄(500) | 200·500 | 경우에 따라 |
| `failed` | 오류·끊김 | 그 밖의 예외 이름 | 게이트웨이 내부 오류(예외 이름을 함께 보인다) | 500(스트림 도중이면 200) | 경우에 따라 |

**종류별 가린 개수** — 12종을 많은 순으로 막대와 수로 보이고, 아래 한 줄에 '기록만'(가리지 않은) 종류별 수를 보인다. 화면의 종류 이름:
`rrn` 주민등록번호 · `frn` 외국인등록번호 · `passport` 여권번호 · `driver` 운전면허번호 · `card` 카드번호 · `phone` 전화번호 · `email` 이메일 · `secret` 자격 증명 ·
`brn` 사업자등록번호 · `crn` 법인등록번호 · `account` 계좌번호 · `ipv4` IP 주소. 인젝션 룰: `R1` 지시 무효화 · `R2` 역할 전환·제약 해제.

**최근 요청** — 최신이 위, 200줄. 열은 시각(로컬) · 요청 ID · 클라이언트·정책 · API·모델 · 결과 · 어떻게 처리했나 · 복원(복원/발급, 의심·새 값 배지) · HTTP · 게이트웨이 ms다.
'어떻게 처리했나'의 예:

- `가짜 값으로 바꿔 보냄 — 전화번호 1 · 이메일 1 → 2개 되돌림 · 기록만: 계좌번호 1`
- `인젝션 룰 R1 지시 무효화(ignore + instructions) — 이번 턴 차단, 상류 호출 없음`
- `전화번호 1 찾음 — 가리지 않음(원래 값이 나감, 기록만)`
- `허용 안 된 모델(403 model_not_allowed) — 상류 호출 없음`
- `AI 응답 시간 초과(504 ReadTimeout)`

'상류 호출 없음'은 차단·거절 줄에만 붙는다(이 줄은 `upstream_ms`가 늘 비어 있다). 줄을 누르면 그 줄의 JSON 전체가 열린다 — 원문·가짜 값·위치·IP는 처음부터 없다.

**요청 ID로 그 줄 찾기.** 사용자가 받은 요청 ID — 차단 응답 문구 끝의 `(요청 ID: …)`, 또는 모든 응답(오류 포함)의 `x-gateway-request-id` 헤더 — 를 최근 요청 표의
찾기 칸에 넣는다(요청 ID나 클라이언트 이름의 앞부분만 넣어도 된다). 표에 없으면(200줄에서 밀려났거나, 다른 파드이거나, 재시작 전) 감사 로그에서 같은 `request_id`로 찾는다.

**한계**

- 프로세스(파드)마다 따로이고 재시작하면 0이다. 여러 파드는 파드 하나씩 본다 — 합산·기간 그래프·보관은 Prometheus(위 '지표')와 감사 로그 몫이다.
- 최근 200건만 남는다. 부하 중에는 차단·거절 줄도 몇 초 안에 밀려난다.
- 화면은 한국어다(코드 이름을 함께 적는다).
- 관리 키가 설정돼 있으면 화면 경로가 있다는 사실이 드러난다(정적 HTML — 데이터는 없다). 관리 키로 최근 요청 요약까지 열린다(원문·가짜 값·위치·IP는 없다).
- 틀린 관리 키는 404만 받고 감사·지표에 남지 않으며 레이트리밋도 걸리지 않는다(D-109·D-124 §2-6) — 추측을 막는 것은 키 길이뿐이니 `python -m gateway keygen`으로 만든 키를 쓴다.
- 스트림은 끝나야 줄이 생긴다. 진행 중인 스트림은 '사용 중 AI 연결'에만 보인다.
- 비스트리밍 요청을 클라이언트가 기다리다 끊으면 게이트웨이가 알지 못해 상류 응답대로 200(가림 후 전달·그대로 전달)으로 남는다(D-122).
- `scripts/traffic.py`는 게이트웨이가 스스로 내는 `rate_limited`(429)·`gateway_busy`·`upstream_busy`(503)·내부 오류(500)·끊김을 만들지 않는다(상류 429 전달은 만든다).

**밖으로 열지 않는다.** 인그레스로 `/__gateway/*`를 열지 않는다 — 클라이언트에게 필요한 경로는 `/v1/*`뿐이다. 원격에서 볼 때는 port-forward를 쓰거나 TLS 뒤에 둔다 —
관리 키가 폴링마다 `Authorization` 헤더로 지나간다.

## 용량

측정 환경: 맥북 M2 8코어에서 부하 생성기·스텁 상류·게이트웨이를 함께 돌렸다(2026-10-31, `scripts/load.py`). 게이트웨이는 워커 하나, 개발 venv의 Python 3.14에
이미지와 같은 서버 설정(asyncio·h11 — 이미지는 Python 3.12)이다.
x86 서버나 CPU 상한이 걸린 컨테이너의 값은 다르다 — 배포한 뒤에는 감사 줄 `gateway_ms`로 다시 본다.

**동시 100(스트림 50 + 비스트리밍 50), 60초.** 스텁 상류는 첫 바이트까지 300ms, 스트림 조각 사이 20ms. 세 API를 돌아가며 쓰고 요청마다 다른 합성 전화번호를 가린다.

| 구간(ms) | 게이트웨이 경유 p50 · p95 · p99 | 스텁 직접 p50 · p95 · p99 |
|---|---|---|
| 비스트리밍 응답 | 315 · 362 · 409 | 319 · 352 · 397 |
| 스트림 첫 내용 조각 | 313 · 364 · 781 | 314 · 346 · 605 |
| 스트림 끝 | 623 · 992 · 1,066 | 633 · 1,006 · 1,026 |
| 게이트웨이 자체 처리(감사 `gateway_ms`, 비스트리밍) | 4.0 · 18.5 · 30.7 | — |

- 13,367건(초당 219) — 오류·복원 실패·다른 요청 값 섞임 0, 감사 줄로 모든 요청이 실제로 가려졌음을 확인했다. 게이트웨이 CPU는 코어 하나의 48%(요청당 2.2ms),
  메모리 71MiB, 진행 중인 대체값 세션 최대 100(끝난 뒤 0), 끝난 뒤 빌려 간 상류 연결 0.
- 30분 soak(같은 부하, 상류 연결을 80으로 줄여 늘 20개 요청이 빈 연결을 기다리게 했다): 323,416건(초당 180) — 오류·복원 실패·섞임·503 0, 모두 실제로 가렸다.
  비스트리밍 p50·p95·p99 414·501·541ms(연결 대기 약 100ms 포함), 게이트웨이 자체 처리 2.5·8.9·18.4ms. 메모리는 53~80MiB에서 오르내리기만 했고
  (앞 4분의 1 대비 뒤 4분의 1 −2.4%), 열린 파일 일정, 끝난 뒤 대체값 세션·빌려 간 상류 연결 0.
- 큰 요청(Docker 이미지, Python 3.12, 상류 연결 풀을 바꾸기 전 — 따로 잰 값): 1MiB 요청(가짜 값 2,242개, 응답도 1MiB) 50건을 동시에 보내면 모두 200, 23.5초 — 요청·응답 한 쌍에 CPU 약 0.47초, 메모리는 유휴 36MiB에서 최대 256MiB
  (요청 하나에 약 4.4MiB). 탐지 시간은 텍스트 크기에 비례한다.
- 상한: 본문 1MiB(`GATEWAY_MAX_BODY_BYTES`) · 요청당 탐지 5,000(`GATEWAY_MAX_FINDINGS`) · 동시 연결 1,000(uvicorn, 쉬는 연결 포함) · 상류 연결 100(`GATEWAY_MAX_CONNECTIONS`,
  상류마다) · 진행 중인 대체값 세션 2,000(워커·정책당, 넘으면 503 `gateway_busy`) · 비스트리밍 응답 32MiB(넘으면 502).
- **상류 연결 수가 먼저 찬다.** 상류 요청 하나가 응답이 끝날 때까지 연결 하나를 쥔다 — 동시 상류 요청 = 초당 요청 × 상류 응답 시간. 30초짜리 스트림이면 연결 100개로
  초당 3건쯤이다. 빈 연결을 5초 기다려도 없으면 503 `upstream_busy`이므로, 긴 스트림이 많으면 `GATEWAY_MAX_CONNECTIONS`를 올리거나 파드를 늘린다(연결 하나는 메모리·파일 하나 정도다).
- k8s 견본 자원은 이것으로 잡은 잠정값이다 — 요청 CPU 500m·메모리 256Mi, 메모리 상한 1Gi(최대 크기 요청 약 200건이 동시에 들어가는 양). 본문 상한을 올리면 메모리 상한도 같은 비율로 올린다.

## 업그레이드

CHANGELOG를 읽고 이미지 주소를 바꿔 apply한다(롤링). 탐지 규칙이나 가짜 값 생성이 바뀐 버전은 대체값 키를 바꾼 것과 같다(위 '키 회전').
올린 뒤 `/__gateway/info`의 `version`·`code`(코드 지문)·`config`로 확인한다.

## 장애 신호

| 증상 | 감사 줄 | 볼 것 |
|---|---|---|
| 파드가 뜨지 않음(CrashLoopBackOff) | — | `kubectl logs`의 stderr — 기동 거부 문장이 고칠 것을 말한다(클라이언트 없음, 대체값 키 없음·짧음, `key_env` 값 없음, 설정 파일 오류) |
| 401이 늘어남 | `error: unauthorized`, `client: null`, `policy: null` | 클라이언트 키 회전 중인가, 클라이언트의 키 |
| 403 | `error: model_not_allowed` | 정책 `allowed_models` |
| 413 | `error: request_too_large`·`too_many_findings` | 본문 상한, 대량 데이터를 그대로 보내는 클라이언트 |
| 502·504 | `error`(예외 이름)·`upstream_ms` | 나가는 연결·DNS, 상류 장애·지연, `GATEWAY_TIMEOUT` |
| 503 | `error: upstream_busy`·`gateway_busy` | 상류 지연·풀 크기, 파드 수 |
| 대시보드 숫자가 튄다('다시 시작했거나 다른 프로세스' 띠가 자꾸 뜬다) | — | 여러 파드에 번갈아 붙는다 — 파드 하나씩 port-forward로 본다(위 '대시보드') |
| 사용자가 가짜 값을 받음 | `pii_suspect` > 0 | 모델이 가짜 값을 알아볼 수 없게 바꿔 썼다(구분자·대소문자 변경은 복원된다). 요청 ID로 사례를 모아 모델·프롬프트를 본다 |
