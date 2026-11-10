#!/usr/bin/env python3
"""실 공급자 확인 2(D-133) — 실제 OpenAI·Gemini·Claude 모델 앞에서 가림·복원(스트리밍·도구 인자·2턴)이 되는가. 상류는 여러 공급자를 한 키로 부르는 라우터(MonoRouter)다.

  python3 scripts/check_real_providers.py --stub     # 스텁 상류로 배선만 확인한다(비용 0)
  python3 scripts/check_real_providers.py            # 실제 — .env의 MONOROUTER_KEY(필수)·MONOROUTER_ANTHROPIC_KEY(있으면 Messages도)

D-133 §2의 사전 등록 그대로다: 조합(API × 모델)마다 E(되풀이)·S(스트리밍)·T(도구 인자)·M(2턴)을 3번씩. 정상 문장과 합성 값만 보낸다. 키는 .env에서만 읽고 출력·기록하지 않는다.
기록(docs/verification/real_providers_router.jsonl·.md)에는 상태·개수·판정·토큰 사용량만 남긴다(답 본문 없음). 종료 코드: 0 모든 조합 통과 / 1 미달·판정 불가 있음 / 2 준비 실패
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.detectors.patterns import find_all  # noqa: E402
from gateway.version import code_fingerprint  # noqa: E402
from tests.procs import free_port, serve  # noqa: E402

ROUTER = "https://monogpt.kr/api/monorouter"                 # OpenAI 호환 — 뒤에 /v1/chat/completions·/v1/responses·/v1/models가 붙는다(Bearer)
ROUTER_ANTHROPIC = ROUTER + "/v1/anthropic"                   # Anthropic 호환 — 뒤에 /v1/messages가 붙는다(x-api-key)
PHONE, EMAIL = "010-2345-6789", "j.hong@hanbit-tech.example"  # 합성 값(예약 도메인)
ASK = f"아래 연락처를 고치지 말고 한 줄로 그대로 다시 적어 주세요.\n전화: {PHONE}\n메일: {EMAIL}"
AGAIN = "방금 적은 메일 주소만 한 번 더 적어 주세요."
SAVE = f"아래 연락처를 save_contact 도구로 저장해 주세요.\n전화: {PHONE}\n메일: {EMAIL}"
SCHEMA = {"type": "object", "properties": {"phone": {"type": "string"}, "email": {"type": "string"}}, "required": ["phone", "email"]}
DEFAULTS = {"chat": ["gpt-5.4-mini", "gemini-3.5-flash", "claude-haiku-4.5"], "responses": ["gpt-5.4-mini"], "messages": ["claude-haiku-4.5"]}
STUB_MODEL = {"E": "stub-model", "S": "stub-stream", "M": "stub-model", "T": {"chat": "stub-toolcall", "responses": "stub-tool", "messages": "stub-tool"}}
PATHS = {"chat": "/v1/chat/completions", "responses": "/v1/responses", "messages": "/v1/messages"}
REPEAT, MAX_TOKENS, MAX_CALLS = 3, 512, 90
OUT = ROOT / "docs" / "verification" / "real_providers_router"


def request(api: str, model: str, turns: list[tuple[str, str]], stream: bool = False, tool: bool = False) -> dict:
    """그 API 모양의 요청 본문. turns는 (역할, 글)."""
    messages = [{"role": role, "content": text} for role, text in turns]
    if api == "chat":
        body: dict = {"model": model, "messages": messages, "max_tokens": MAX_TOKENS}
        if tool:
            body |= {"tools": [{"type": "function", "function": {"name": "save_contact", "description": "연락처를 저장한다", "parameters": SCHEMA}}],
                     "tool_choice": {"type": "function", "function": {"name": "save_contact"}}}
    elif api == "responses":
        body = {"model": model, "input": messages, "max_output_tokens": MAX_TOKENS}
        if tool:
            body |= {"tools": [{"type": "function", "name": "save_contact", "description": "연락처를 저장한다", "parameters": SCHEMA}],
                     "tool_choice": {"type": "function", "name": "save_contact"}}
    else:
        body = {"model": model, "messages": messages, "max_tokens": MAX_TOKENS}
        if tool:
            body |= {"tools": [{"name": "save_contact", "description": "연락처를 저장한다", "input_schema": SCHEMA}], "tool_choice": {"type": "tool", "name": "save_contact"}}
    return body | ({"stream": True} if stream else {})


def answer(api: str, data: dict) -> tuple[str, str]:
    """비스트리밍 응답에서 (답 글, 도구 인자 문자열)."""
    if api == "chat":
        message = (data.get("choices") or [{}])[0].get("message") or {}
        return message.get("content") or "", "".join(c.get("function", {}).get("arguments") or "" for c in message.get("tool_calls") or [])
    if api == "responses":
        items = data.get("output") or []
        text = "".join(p.get("text") or "" for it in items if it.get("type") == "message" for p in it.get("content") or [] if p.get("type") == "output_text")
        return text, "".join(it.get("arguments") or "" for it in items if it.get("type") == "function_call")
    blocks = data.get("content") or []
    return ("".join(b.get("text") or "" for b in blocks if b.get("type") == "text"),
            "".join(json.dumps(b.get("input"), ensure_ascii=False) for b in blocks if b.get("type") == "tool_use"))


def stream_text(api: str, lines: list[str]) -> str:
    """SSE 줄들에서 답 글 조각을 이어 붙인다."""
    out = []
    for line in lines:
        if not line.startswith("data:") or line[5:].strip() in ("", "[DONE]"):
            continue
        try:
            event = json.loads(line[5:])
        except ValueError:
            continue
        if api == "chat":
            out.append(((event.get("choices") or [{}])[0].get("delta") or {}).get("content") or "")
        elif api == "responses":
            out.append((event.get("delta") or "") if event.get("type") == "response.output_text.delta" else "")
        elif event.get("type") == "content_block_delta":
            out.append((event.get("delta") or {}).get("text") or "")
    return "".join(out)


def outcome(status: int, shown: str, audit: dict | None, want: tuple[str, ...]) -> str:
    """요청 하나의 판정(D-133 §2-3): error(200이 아니거나 감사 줄이 없음) · surrogate_left(가짜 값이 남음) · ok(원래 값이 온전히) · no_echo(값을 적지 않음) · partial(일부만)."""
    if status != 200 or audit is None:
        return "error"
    if (audit.get("pii_suspect") or 0) > 0:
        return "surrogate_left"
    hit = sum(v in shown for v in want)
    return "ok" if hit == len(want) else "no_echo" if hit == 0 else "partial"


def judge(rows: list[dict]) -> dict:
    """한 조합(API × 모델)의 판정 — P1 200만 · P2 pii_issued ≥ 2 · P3 가짜 값 0건 · P4 값을 적은 요청 중 온전한 비율 ≥ 2/3(검사마다)."""
    counts = {check: {k: sum(r["check"] == check and r["outcome"] == k for r in rows) for k in ("ok", "partial", "no_echo", "surrogate_left", "error")} for check in "ESTM"}
    p1 = bool(rows) and all(r["status"] == 200 and r["outcome"] != "error" for r in rows)
    p2 = all((r.get("pii_issued") or 0) >= 2 for r in rows if r["status"] == 200)
    p3 = not any(r["outcome"] == "surrogate_left" for r in rows)
    ratios = {check: (c["ok"] / (c["ok"] + c["partial"]) if c["ok"] + c["partial"] else None) for check, c in counts.items()}
    p4 = all(v is None or v >= 2 / 3 for v in ratios.values())
    undecided = [c for c, v in ratios.items() if v is None]
    verdict = "미달" if not (p1 and p2 and p3 and p4) else "판정 불가" if len(undecided) == len(ratios) else "통과"
    return {"verdict": verdict, "P1": p1, "P2": p2, "P3": p3, "P4": p4, "undecided": undecided, "counts": counts}


def audit_line(log: Path, request_id: str | None) -> dict | None:
    if not request_id or not log.exists():
        return None
    for line in reversed(log.read_text(encoding="utf-8").splitlines()):
        if line.strip() and json.loads(line).get("request_id") == request_id:
            return json.loads(line)
    return None


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit, self.calls = limit, 0

    def spend(self) -> None:
        if self.calls >= self.limit:
            raise SystemExit(f"요청 상한 {self.limit}건에 닿았다 — 멈춘다(D-133 §2-4)")
        self.calls += 1


def call(client: httpx.Client, gw: dict, api: str, model: str, check: str, turns: list[tuple[str, str]], budget: Budget) -> tuple[dict, str]:
    """요청 하나 → (기록 행, 답 글). 기록에는 본문을 넣지 않는다."""
    budget.spend()
    headers = {"Authorization": f"Bearer {gw['client_key']}"} | ({"anthropic-version": "2023-06-01"} if api == "messages" else {})
    body = request(api, model, turns, stream=check == "S", tool=check == "T")
    text = args = ""
    if check == "S":
        with client.stream("POST", gw["url"] + PATHS[api], json=body, headers=headers) as r:
            lines = list(r.iter_lines())
        text = stream_text(api, lines) if r.status_code == 200 else ""
    else:
        r = client.post(gw["url"] + PATHS[api], json=body, headers=headers)
        if r.status_code == 200:
            text, args = answer(api, r.json())
    audit = audit_line(gw["log"], r.headers.get("x-gateway-request-id"))
    shown, want = (args, (PHONE, EMAIL)) if check == "T" else (text, (EMAIL,) if check == "M" else (PHONE, EMAIL))
    row = {"api": api, "model": model, "check": check, "status": r.status_code, "outcome": outcome(r.status_code, shown, audit, want),
           "error": (audit or {}).get("error"), "pii_issued": (audit or {}).get("pii_issued"), "pii_restored": (audit or {}).get("pii_restored"),
           "pii_suspect": (audit or {}).get("pii_suspect"), "usage": (audit or {}).get("usage"), "chars": len(shown)}
    return row, text


def run(gw: dict, api: str, model: str, stub: bool, budget: Budget) -> list[dict]:
    rows = []
    with httpx.Client(timeout=180) as client:
        for _ in range(REPEAT):
            for check in "EST":
                name = (STUB_MODEL["T"][api] if check == "T" else STUB_MODEL[check]) if stub else model
                row, text = call(client, gw, api, name, check, [("user", SAVE if check == "T" else ASK)], budget)
                rows.append(row | {"model": model})
                if check == "E" and row["status"] == 200 and text:          # M: E의 답(복원된 값)을 이력에 붙인다 — 다음 턴에서 다시 가려져야 한다
                    row2, _ = call(client, gw, api, STUB_MODEL["M"] if stub else model, "M", [("user", ASK), ("assistant", text), ("user", AGAIN)], budget)
                    rows.append(row2 | {"model": model})
    return rows


def report(results: list[dict], meta: dict) -> str:
    lines = ["# 실 공급자 확인 2 — 라우터 경유(D-133)", "",
             f"{meta['when']} · 게이트웨이 코드 {meta['code']} · 요청 {meta['calls']}건 · 상류 {meta['upstream']}. 정상 문장과 합성 값만 보냈다. 답 본문은 기록하지 않는다.", "",
             "| API | 모델 | 판정 | P1 200만 | P2 가림 | P3 가짜 값 0 | P4 복원 | E | S | T | M |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    mark = {True: "○", False: "✕"}
    for r in results:
        j = r["judge"]
        cells = [f"{j['counts'][c]['ok']}/{sum(j['counts'][c].values())}" + (f" (되풀이 안 함 {j['counts'][c]['no_echo']})" if j["counts"][c]["no_echo"] else "") for c in "ESTM"]
        lines.append(f"| {r['api']} | `{r['model']}` | **{j['verdict']}** | {mark[j['P1']]} | {mark[j['P2']]} | {mark[j['P3']]} | {mark[j['P4']]} | " + " | ".join(cells) + " |")
    lines += ["", "칸의 숫자는 원래 값이 온전히 돌아온 요청 / 보낸 요청. " + (f"건너뛴 조합: {', '.join(meta['skipped'])}." if meta["skipped"] else "건너뛴 조합 없음."),
              f"토큰 사용량(감사 줄의 `usage` 합): 입력 {meta['tokens'][0]:,} · 출력 {meta['tokens'][1]:,}." + (f" 라우터 잔액 숫자 앞뒤: {meta['credits']}." if meta.get("credits") else "")]
    return "\n".join(lines) + "\n"


def credits(key: str) -> dict | None:
    try:
        data = httpx.get(ROUTER + "/v1/credits", headers={"Authorization": f"Bearer {key}"}, timeout=20).json()
    except (httpx.HTTPError, ValueError):
        return None
    return {k: v for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)} if isinstance(data, dict) else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stub", action="store_true", help="스텁 상류로 배선만 확인한다(비용 0)")
    for api in PATHS:
        ap.add_argument(f"--{api}-models", default=",".join(DEFAULTS[api]), help=f"{api} API로 볼 모델(쉼표)")
    ap.add_argument("--out", type=Path, default=OUT, help="기록 파일 이름(확장자 없이)")
    a = ap.parse_args()
    kinds = [sorted(f.kind for f in find_all(text) if f.mask) for text in (ASK, SAVE)]
    if kinds != [["email", "phone"]] * 2 or [f for f in find_all(AGAIN) if f.mask]:
        print("보낼 문장의 탐지 결과가 전화·메일 하나씩이 아니다:", kinds)
        return 2
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    keys = {"chat": env.get("MONOROUTER_KEY") or "", "messages": env.get("MONOROUTER_ANTHROPIC_KEY") or ""}
    if a.stub:
        keys = {"chat": "stub-upstream-key", "messages": "stub-upstream-key"}
    elif not keys["chat"]:
        print("MONOROUTER_KEY가 없다 — .env에 넣는다(채팅에 붙이지 않는다). 배선만 보려면 --stub")
        return 2
    procs, results, skipped = [], [], []
    budget, tmp = Budget(MAX_CALLS), tempfile.TemporaryDirectory(prefix="d133-")
    before = after = None
    try:
        bases = {"chat": ROUTER, "messages": ROUTER_ANTHROPIC}
        if a.stub:
            port = free_port()
            procs.append(serve("tests.stub_target:app", port, cwd=ROOT))
            bases = dict.fromkeys(bases, f"http://127.0.0.1:{port}")
        gateways = {}
        for group in ("chat", "messages"):                 # chat·responses는 같은 상류(Bearer), messages는 Anthropic 호환 상류(x-api-key)
            if not keys[group]:
                continue
            port, client_key, log = free_port(), secrets.token_urlsafe(16), Path(tmp.name) / f"{group}.jsonl"
            procs.append(serve("gateway.main:app", port, {"TARGET_URL": bases[group], "GATEWAY_UPSTREAM_KEY": keys[group], "GATEWAY_CLIENT_KEYS": f"d133={client_key}",
                                                         "GATEWAY_SURROGATE_KEY": secrets.token_urlsafe(32), "GATEWAY_LOG_PATH": str(log), "GATEWAY_PII": "mask"},
                               probe="/__gateway/health", cwd=ROOT))
            gateways[group] = {"url": f"http://127.0.0.1:{port}", "client_key": client_key, "log": log}
        before = None if a.stub else credits(keys["chat"])
        for api in PATHS:
            gw = gateways.get("messages" if api == "messages" else "chat")
            models = [m for m in getattr(a, f"{api}_models").split(",") if m]
            if gw is None:
                skipped += [f"{api}:{m}(키 없음)" for m in models]
                continue
            listed = None
            if not a.stub:                                  # 모델 목록(무료) — 없는 모델은 보내지 않는다. 목록을 못 읽으면 그대로 보낸다
                r = httpx.get(gw["url"] + "/v1/models", headers={"Authorization": f"Bearer {gw['client_key']}"} | ({"anthropic-version": "2023-06-01"} if api == "messages" else {}), timeout=60)
                data = r.json().get("data") if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json") else None
                listed = {m.get("id") for m in data if isinstance(m, dict)} if isinstance(data, list) else None
            for model in models:
                if listed is not None and model not in listed:
                    skipped.append(f"{api}:{model}(목록에 없음)")
                    continue
                rows = run(gw, api, model, a.stub, budget)
                results.append({"api": api, "model": model, "rows": rows, "judge": judge(rows)})
                print(f"{api} {model}: {results[-1]['judge']['verdict']}", flush=True)
        after = None if a.stub else credits(keys["chat"])
    finally:
        for p in reversed(procs):
            p.terminate()
            p.wait(10)
        tmp.cleanup()
    usage = [r.get("usage") or {} for res in results for r in res["rows"]]
    meta = {"when": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "code": code_fingerprint(), "calls": budget.calls, "skipped": skipped,
            "upstream": "스텁" if a.stub else "MonoRouter", "tokens": (sum(u.get("input") or 0 for u in usage), sum(u.get("output") or 0 for u in usage)),
            "credits": None if before is None or after is None else {"before": before, "after": after}}
    text = report(results, meta)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".md").write_text(text, encoding="utf-8")
    a.out.with_suffix(".jsonl").write_text("".join(json.dumps({"verdict": res["judge"]["verdict"], **row}, ensure_ascii=False) + "\n" for res in results for row in res["rows"]), encoding="utf-8")
    print(text)
    return 0 if results and all(res["judge"]["verdict"] == "통과" for res in results) else 1


if __name__ == "__main__":
    sys.exit(main())
