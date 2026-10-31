# LLM Security Gateway

[한국어](README.md)

A self-hosted proxy between your LLM apps and AI providers. **It replaces personal data and credentials in outgoing requests with fake values of the same shape,
restores the original values in the responses, observes (or optionally blocks) prompt injection, and writes one audit line per request.**
It passes the OpenAI Chat Completions and Responses APIs and the Anthropic Messages API through unchanged, including streaming and tool calls.
You do not change app or model code — only the client's `base_url` and API key (a gateway key). The provider key lives in the gateway only.

The detectors target Korean identifiers (resident registration numbers, foreign registration numbers, passports, driver's licenses, Korean phone numbers, business and bank numbers)
plus cards, emails and API keys. Operator messages default to Korean; set `GATEWAY_LANG=en` for English. The operations and API documents under `docs/` are in Korean.

> **Status**: 0.1.0, following the commercialization plan ([`PLAN.md`](PLAN.md), Korean). Decisions are recorded in [`DECISIONS.md`](DECISIONS.md) from D-108.

## 1. What it does

```
client (OpenAI SDK · Anthropic SDK · OpenAI-compatible apps — change only base_url and api_key)
    │  POST /v1/chat/completions · /v1/responses · /v1/messages (streaming and tools) · GET /v1/models
    ▼
gateway :8080   any other path → 404 (never forwarded) → client key (401) → rate limit (429) → body limit (413) → parse (400)
    request   injection rule (observe or block) → personal data and credentials in all roles (system, tool results, RAG documents) and in tool arguments
              are replaced with fake values of the same shape
    upstream  only allow-listed headers, plus the provider key (no cookies, X-Forwarded-*, org headers or gateway key)
    response  fake values restored (streaming: across chunk boundaries, per channel; thinking/reasoning untouched) · one audit line per request (no raw text)
    │
    ▼
upstream  OpenAI · Anthropic · OpenAI-compatible servers (Ollama, vLLM, …)
```

- **The upstream sees a value such as `010-8419-3027` and treats it as an ordinary value.** The model does not notice anything was hidden and uses it in tool arguments;
  the user gets the original value back. The provider's logs contain the fake value.
- **Raw values are not stored.** The mapping between fake and original values lives in the memory of one request and is dropped when the response ends.
  The audit log keeps only sizes and digests.
- **The same original value always becomes the same fake value.** Fake values are derived from the surrogate key (`GATEWAY_SURROGATE_KEY`), so history bytes stay identical
  on the next turn — prompt caching and Anthropic thinking signatures keep working. On the real Claude API (`claude-haiku-5-5`, five two-turn conversations) the second turn read
  the cache without a signature error; the old per-request random values were rejected 5/5 ([`docs/verification/multiturn_claude.md`](docs/verification/multiturn_claude.md), Korean).
- **Injection is not blocked by default.** There are two rules (instruction override and role switch, with Korean and English vocabulary), and they match benign sentences too ("ignore the instructions in the PDF and summarize").
  Hits are recorded in the audit log (`would_block`); operators opt in with `GATEWAY_INJECTION=block`.

### Detected kinds

The kind name is used in audit logs, metrics (`kind`) and `GATEWAY_PII_KINDS`. Detection looks at the shape only; context words (within 20 characters) decide only whether to mask —
so that a fake value coming back without context can still be restored. Formats that cannot be told apart from ordinary numbers without context are not supported.
**Audit-only** kinds are detected and recorded (`unmasked`) but sent as is — remove them from `GATEWAY_PII_DETECT_KINDS` to mask them.
Recall is measured on the synthetic corpus with masking on (`eval/pii/`, 100 positives per kind; false positives on 1,200 number-dense business sentences: 3 in total, 0.2%).

| Kind | Format | Validation | Default | Not masked / not supported | Recall |
|---|---|---|---|---|---|
| Resident registration no. `rrn` | 6 + 7 digits (hyphen, space or none), gender digit 1–4 | real date, checksum (grade only — numbers issued after 2020-10 have none) | mask | 13 digits failing the checksum with no separator or context word are audit-only; spaces around the hyphen | 98 (checksum-valid 55/55) |
| Foreign registration no. `frn` | same, gender digit 5–8 | real date, checksum (grade only) | mask | as `rrn` | 95 (checksum-valid 57/57) |
| Passport `passport` | M·S·R·O·D + 8 digits (old), + 3 digits, a capital letter, 4 digits (since 2021-12) | — | mask | old format without "여권/passport" nearby is audit-only; lowercase | 80 (new format 47/47) |
| Driver's license `driver` | `11-20-123456-78` (hyphens) | region 11–26, 28 | mask | 12 digits without separators; region-name format (before 2014-07) | 100 |
| Card `card` | 13–19 digits (hyphen, space or none) | Luhn, issuer ranges (incl. 9 domestic-only) | mask | out-of-range numbers (IMEI, order numbers) without card context are audit-only; dot separators | 100 |
| Phone `phone` | Korean numbers (010, 02, 031…, 070), area code in parentheses, `+country code` | — | mask | 050 safe numbers, numbers glued to letters (`TEL010-…`) | 100 |
| Email `email` | `local@domain` | — | mask | — | 100 |
| Credential `secret` | OpenAI, Anthropic, AWS, GitHub, Google and Slack keys, JWT, PEM private keys | prefix, format | mask | keys without a known prefix, passwords | 100 |
| Business registration no. `brn` | `123-45-67891` (hyphens) | checksum | **audit only** | 10 digits without separators | 100 |
| Corporate registration no. `crn` | `134511-0012340` (hyphen) | checksum | **audit only** | numbers shaped like an `rrn` are masked as `rrn` unless "법인" is nearby | 89 |
| Bank account `account` | 14 hyphenated bank formats (KB, Shinhan, Woori, Hana, NH, IBK, Kakao, Toss, K bank, Post Office, SC, MG) | — | **audit only** | audit-only without account context; no separators, spaces | 64 |
| IPv4 `ipv4` | public addresses (private, reserved, multicast and `.0` addresses excluded) | — | **audit only** | audit-only near "version/build/firmware"; four-part version numbers without context are taken for addresses; IPv6 | 100 |

## 2. What it does not stop

- **Unstructured personal data and secrets** — only the twelve kinds above. Names, addresses, IBANs, IPv6 and free-text sensitive data pass through, as do the unsupported formats in the table.
  Full-width digits, zero-width characters and dash variants are normalized and caught.
- **Ambiguous numbers are not masked** — see the "not masked" column. Those values reach the upstream; they are recorded as `unmasked`.
- **Business, corporate, account numbers and IPs are sent by default** (audit only). Enable them with `GATEWAY_PII_DETECT_KINDS` when you handle customer access logs or payments.
- **Non-text content** (images, PDFs, audio, files referenced by ID), **Responses custom tools** (`custom_tool_call`·`custom_tool_call_output`) and tool definitions are not inspected.
- **Provider-side tools receive fake values.** Web search, code execution and remote MCP run on the provider with the fake values — a remote tool that looks a value up gets the wrong record.
  Client-side function tools work: the gateway restores the arguments before your code runs the tool.
- **Thinking shows fake values.** Anthropic thinking and Responses reasoning summaries are returned as signed by the upstream.
- **Unknown attacks.** The injection rules only know a fixed Korean and English vocabulary. On the dev split of eval set v1 ([`eval/injection/`](eval/injection/SOURCES.md),
  built from public datasets, 1,592 Korean attacks) they catch **8.7%** of attacks (Korean 5.9%, English 16.0%; forged role headers 2.9%, obfuscation 2.9%, indirect 5.1%)
  with a 2.7% false-positive rate (0% on ordinary business text, 9.2% on benign text containing trigger words) — not usable for blocking; observe only.
- **Output direction.** Personal data the model produces on its own reaches the user; it is counted (`pii_new`, `gateway_pii_new_total`), not masked.
- **Restore failures are quiet.** If the model rewrites a fake value beyond recognition, the user receives the fake value (`x-gateway-pii`, `pii_suspect`, `gateway_pii_suspect_total` show it).
  Fake emails use reserved domains, but **a fake mobile number can be a real person's number** — Korea has no official fictitious number range.
- **Other provider features** (files, embeddings, audio, batches, `count_tokens`, stored conversations via `previous_response_id`) — see [`docs/api-compat.md`](docs/api-compat.md).
- **Linkability.** Under one surrogate key the same original value always maps to the same fake value, so requests carrying it can be linked in provider logs. Rotating the key breaks the link.
- **Operations.** Rate limits and metrics are per worker process. Configuration is read at start-up; changes need a restart.

## 3. Running

Python 3.12 or later.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q && ruff check . && mypy
python3 scripts/demo.py          # six scenes against a stub upstream, no Docker or provider needed
python3 web/app.py               # side-by-side browser view (without / with the gateway)
```

Local trial with Docker — gateway plus stub upstream, nothing leaves your machine (fixed keys, local use only):

```bash
docker compose -f deploy/compose.yml up --build
curl -s http://127.0.0.1:8080/v1/chat/completions -H 'Authorization: Bearer test-key' -H 'Content-Type: application/json' \
  -d '{"model":"stub-model","messages":[{"role":"user","content":"My number is 010-2345-6789"}]}'
curl -s http://127.0.0.1:8000/__stub/received     # what the upstream actually received
```

In front of a real provider:

```bash
APP_KEY="$(python3 -m gateway keygen)"; echo "client key: $APP_KEY"
GATEWAY_CLIENT_KEYS="app=$APP_KEY" GATEWAY_SURROGATE_KEY="$(python3 -m gateway keygen)" \
  GATEWAY_UPSTREAM_KEY=sk-ant-... TARGET_URL=https://api.anthropic.com uvicorn gateway.main:app --port 8080 --no-access-log
```

Clients set `base_url` to `http://localhost:8080` (Anthropic SDK) or `http://localhost:8080/v1` (OpenAI SDK) and `api_key` to the gateway key.
Keep the uvicorn access log off in production — it prints query values that the audit log deliberately drops.

Kubernetes: [`deploy/k8s/`](deploy/k8s/) (kustomize — `kubectl apply -k deploy/k8s`): two replicas, PodDisruptionBudget, readiness on `/__gateway/health`,
graceful shutdown (preStop 5 s + 25 s), Pod Security `restricted`. Configuration and secret changes roll the pods automatically. Steps, key rotation, logs, metrics and capacity:
[`docs/operations.md`](docs/operations.md) (Korean).

## 4. Configuration

Environment variables and an optional TOML file, both read once at start-up. The gateway does not read `.env` itself — use `uvicorn --env-file .env`.
Invalid choices, kinds and roles and unknown or invalid config-file keys stop start-up with a message in `GATEWAY_LANG` (malformed numbers fail with a plain Python error; URLs are not checked). Create keys with `python -m gateway keygen` (`--hash` for config-file clients).

| Variable | Default | Meaning |
|---|---|---|
| `TARGET_URL` | `http://localhost:8000` | Upstream for APIs not in the config file. The request path is kept (`https://host/openai` → `https://host/openai/v1/chat/completions`), query strings too |
| `GATEWAY_CLIENT_KEYS` | (none) | Client keys `name=key,name2=key2` (policy `default`), sent as `Authorization: Bearer` or `x-api-key`, held as SHA-256. Merged with `[[clients]]`; **start-up fails** when both are empty |
| `GATEWAY_AUTH` | (on) | `off` accepts requests without a client key — local experiments only. **Start-up fails** together with a provider key |
| `GATEWAY_CONFIG` | (none) | Path of the TOML config file (below) |
| `GATEWAY_UPSTREAM_KEY` | (none) | Provider key for upstreams not in the config file — `x-api-key` for `/v1/messages` and `anthropic-version` requests, `Authorization: Bearer` otherwise |
| `GATEWAY_ADMIN_KEY` | (none) | Opens `/__gateway/info` and `/__gateway/metrics` (`Authorization: Bearer`); without it both are 404 |
| `GATEWAY_SURROGATE_KEY` | (none) | Deterministic surrogate key, 32+ characters; **required** when any policy masks. Keep it like a provider key. Rotating it is described in `docs/operations.md` |
| `GATEWAY_PII` | `mask` | `mask` (replace and restore) · `detect` (audit only) · `off` |
| `GATEWAY_PII_KINDS` | all twelve | Kinds to detect, comma-separated |
| `GATEWAY_PII_DETECT_KINDS` | `account,brn,crn,ipv4` | Kinds that are detected but not masked; empty masks everything detected |
| `GATEWAY_PII_ROLES` | `user,assistant,tool,system` | Roles to mask (`developer` and Responses `instructions` are `system`) |
| `GATEWAY_INJECTION` | `observe` | `observe` (audit only) · `block` (blocked response, no upstream call) · `off` |
| `GATEWAY_LANG` | `ko` | Language of user and operator messages: `ko` or `en`. API error bodies are always English |
| `GATEWAY_BLOCKED_MESSAGE` | (catalog) | Text of the blocked response; the request ID is appended |
| `GATEWAY_MAX_BODY_BYTES` | `1048576` | Request body limit → 413 `request_too_large` |
| `GATEWAY_MAX_FINDINGS` | `5000` | Detection limit per request in mask mode → 413 `too_many_findings` |
| `GATEWAY_MAX_CONNECTIONS` | `100` | Concurrent connections per upstream; when all are in use requests wait in arrival order up to 5 s → 503 `upstream_busy` |
| `GATEWAY_RATE_PER_MINUTE` | `0` (off) | Requests per minute per client (per IP without auth) → 429 |
| `GATEWAY_TIMEOUT` | `600` | Upstream read timeout in seconds (connect 5 s, write 30 s fixed); any of them → 504 `upstream_timeout`, or a cut stream if it happens mid-stream |
| `GATEWAY_LOG_PATH` | `logs/gateway.jsonl` (image: `-`) | Audit log; `-` is stdout |
| `GATEWAY_LOG_MAX_BYTES` | `104857600` | Audit log rotation size (files only) |
| `GATEWAY_LOG_BACKUPS` | `5` | Rotated audit files kept |

Read by uvicorn in the image:

| Variable | Default | Meaning |
|---|---|---|
| `WEB_CONCURRENCY` | `1` | Worker processes. Keep 1 and scale with replicas — metrics, rate limits and surrogate-session limits are per process |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-For` is trusted |
| `UVICORN_TIMEOUT_KEEP_ALIVE` | `5` | Seconds before an idle client connection is closed. Behind an ingress or load balancer make it longer than its idle timeout (usually 60 s); the k8s sample uses 75 |

The config file (`GATEWAY_CONFIG`) adds per-client policies, allowed models and per-API upstreams. Provider keys stay in environment variables named by `key_env`;
client keys are stored as hashes. Missing policy values follow `[policies.default]`, which follows the environment variables. The full key reference is in
[`docs/configuration.md`](docs/configuration.md) (Korean).

```toml
[[clients]]
name = "support-bot"
key_sha256 = "…"                # second line of `python -m gateway keygen --hash`
policy = "strict"

[policies.strict]
injection = "block"             # observe | block | off
pii_mode = "mask"               # mask | detect | off
pii_detect_kinds = []           # also mask accounts, business numbers and IPs
allowed_models = ["gpt-4.1*", "claude-sonnet-*"]   # others → 403 model_not_allowed

[upstreams.chat]                # chat | responses | messages
base_url = "https://api.openai.com"
key_env = "OPENAI_API_KEY"

[upstreams.messages]
base_url = "https://api.anthropic.com"
key_env = "ANTHROPIC_API_KEY"
```

## 5. Layout

```
gateway/      app (main), settings, relay, auth, API adapters (api/), detectors (detectors/), surrogates, vault, streaming restore, audit, metrics, rate limit
deploy/       compose.yml (local trial) · k8s/ (kustomize)
docs/         configuration · operations · api-compat · verification/ (real-provider check)
scripts/      demo · SDK checks · real-provider two-turn check
tests/        unit and integration tests, stub upstream (tests/stub_target.py)
eval/         PII corpus and scoring (eval/pii/), injection eval set v1 with sources and licenses (eval/injection/), benign questions (eval/benign/)
web/          browser demo
```

## 6. Security

Report vulnerabilities privately — see [`SECURITY.md`](SECURITY.md).

## 7. License

[Apache-2.0](LICENSE).
