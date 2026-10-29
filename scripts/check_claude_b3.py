#!/usr/bin/env python3
"""D-103 B3 Claude 기능 검증 — 게이트웨이를 Anthropic의 OpenAI 호환 입구 앞에 두고 정상 요청만 보낸다.

  python3 scripts/check_claude_b3.py [--date YYYYMMDD] [--model claude-opus-5-5]

키는 환경변수 `ANTHROPIC_API_KEY`(또는 저장소 `.env`의 같은 키)로만 읽는다. 명령 인자·파일·출력에 값을 쓰지 않는다.
키가 워크스페이스에 묶이지 않은 개인·서비스 계정 키면 `ANTHROPIC_WORKSPACE_ID`도 읽어 헤더로 넘긴다.
공격 문구·garak 프로브는 보내지 않는다(SCOPE 6절). 항목·합격 조건·상한은 D-103에 먼저 등록했다 — 이 스크립트는 그 절을 그대로 옮긴 것이다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.conftest import free_port, serve  # noqa: E402

PATH = "/v1/chat/completions"
TARGET = "https://api.anthropic.com"
DETECTORS = "injection_rule_turn,pii_mask"
PII = {  # tests/test_upstream_contract.py와 같은 합성값(D-087 §1)
    "phone": "010-2345-6789", "phone_nl": "010\n3456\n7890", "email": "kim.synthetic@example.com",
    "rrn": "900101-1234563", "card": "4111-1111-1111-1111",
}
# 가격(USD / 1M 토큰): Anthropic 가격표, 2026-10-06 조회값(claude-api 스킬 표). 모델이 다르면 --price-in/--price-out으로 넘긴다.
PRICE = {"claude-opus-5-5": (4.00, 20.00)}
MAX_CALLS, MAX_COST = 10, 0.50


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"))
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--price-in", type=float, default=None)
    ap.add_argument("--price-out", type=float, default=None)
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        print("ANTHROPIC_API_KEY가 없다 — 환경변수나 .env에 넣는다(값은 출력하지 않는다)")
        return 2
    price_in, price_out = PRICE.get(args.model, (args.price_in, args.price_out))
    if args.price_in is not None:
        price_in = args.price_in
    if args.price_out is not None:
        price_out = args.price_out
    if price_in is None or price_out is None:
        print(f"{args.model}의 가격을 모른다 — --price-in/--price-out")
        return 2

    tag = f"b3_claude_{args.date}"
    log = ROOT / "logs" / f"{tag}.jsonl"
    if log.exists():
        print(f"{log} 가 이미 있다 — 이 검증은 새 감사 파일로 시작한다(V3)")
        return 2
    head = subprocess.run(["git", "--no-optional-locks", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "--no-optional-locks", "status", "--short", "gateway/"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"HEAD {head}  gateway/ 미커밋 변경: {'없음' if not dirty else '있음 → V1 무효'}")
    if dirty:
        return 2

    port = free_port()
    proc = serve("gateway.main:app", port, {"TARGET_URL": TARGET, "GATEWAY_DETECTORS": DETECTORS,
                                             "GATEWAY_LOG_PATH": str(log)}, probe="/__gateway/health")
    try:
        gw = f"http://127.0.0.1:{port}"
        health = httpx.get(f"{gw}/__gateway/health").json()
        print("health:", {k: health.get(k) for k in ("target", "detectors", "chat_upstream_path", "code")})
        v2 = health.get("target") == TARGET and health.get("detectors") == DETECTORS.split(",") \
            and health.get("chat_upstream_path") == PATH
        auth = {"Authorization": f"Bearer {key}"}
        if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
            auth["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
        calls, cost, results, sent = 0, 0.0, {}, 0

        def post(body: dict, headers: dict, upstream: bool) -> httpx.Response:
            nonlocal calls, cost, sent
            if upstream and (calls >= MAX_CALLS or cost >= MAX_COST):
                raise RuntimeError("상한(V4) — 멈춘다")
            r = httpx.post(f"{gw}{PATH}", json=body, headers=headers, timeout=120)
            sent += 1
            if upstream:
                calls += 1
                usage = r.json().get("usage") if r.headers.get("content-type", "").startswith("application/json") else None
                if isinstance(usage, dict):
                    cost += usage.get("prompt_tokens", 0) * price_in / 1e6 + usage.get("completion_tokens", 0) * price_out / 1e6
            return r

        def audit_of(r: httpx.Response) -> dict | None:
            rid = r.headers.get("x-gateway-request-id")
            for line in reversed(log.read_text(encoding="utf-8").split("\n")):
                if line.strip() and json.loads(line).get("request_id") == rid:
                    return json.loads(line)
            return None

        def save(name: str, r: httpx.Response) -> None:
            (ROOT / "results" / f"{tag}_{name}.json").write_text(r.text, encoding="utf-8")

        # C1 정상 대화
        q = {"model": args.model, "max_tokens": 200,
             "messages": [{"role": "user", "content": "대한민국의 수도는 어디인가요? 한 문장으로 답하세요."}]}
        r = post(q, auth, True); save("c1", r); a = audit_of(r)
        body = r.json()
        c1 = r.status_code == 200 and body.get("object") == "chat.completion" \
            and isinstance(body["choices"][0]["message"].get("content"), str) and "usage" in body \
            and a and a["status"] == 200 and not a["blocked"] and not a["transformed"]
        results["C1 정상 대화"] = (c1, f"{r.status_code}, model={body.get('model')}, usage={body.get('usage')}, "
                                      f"upstream_ms={a and a.get('upstream_ms')}, gateway_ms={a and a.get('gateway_ms')}")

        # C2 PII 마스킹·복원 (복원 0이면 판정 불가 — 같은 요청 1회만 다시)
        content = "아래 값을 받은 그대로 한 줄씩 다시 적어 주세요. 다른 말은 하지 마세요.\n" + "\n".join(PII.values())
        for attempt in (1, 2):
            r = post({"model": args.model, "max_tokens": 300, "messages": [{"role": "user", "content": content}]}, auth, True)
            save("c2" if attempt == 1 else "c2_retry", r); a = audit_of(r)
            text = r.json()["choices"][0]["message"].get("content") or ""
            req_det = {d["detector"]: d for d in (a or {}).get("detectors", [])}
            res_det = {d["detector"]: d for d in (a or {}).get("response_detectors", [])}
            masked = req_det.get("pii_mask", {}).get("masked")
            restored = res_det.get("pii_mask", {}).get("restored", 0)
            residual = res_det.get("pii_mask", {}).get("residual_tokens", 0)
            base_ok = r.status_code == 200 and a and a["transformed"] and masked == 5 and residual == 0 and "[PII:" not in text
            if restored >= 1 or attempt == 2:
                break
        verdict = "판정 불가" if restored == 0 else ("합격" if base_ok else "불합격")
        results["C2 PII 마스킹·복원"] = (verdict == "합격", f"{verdict}: {r.status_code}, 마스킹 {masked}, 복원 {restored}, "
                                                            f"잔여 {residual}, '[PII:' {'있음' if '[PII:' in text else '없음'}, "
                                                            f"원문 되돌아옴 {sum(v in text for v in PII.values())}/5")

        # C3 잘못된 키 → 401 중계
        r = post(q, {"Authorization": f"Bearer sk-ant-invalid-b3-{args.date}"}, True); save("c3", r); a = audit_of(r)
        c3 = r.status_code == 401 and isinstance(r.json().get("error"), dict) and a and a["status"] == 401
        results["C3 잘못된 키"] = (c3, f"{r.status_code}, error.type={r.json().get('error', {}).get('type')}")

        # C5 stream:true 거부 — 상류 호출 없음(비용 0)
        r = post({**q, "stream": True}, auth, False); a = audit_of(r)
        c5 = r.status_code == 400 and r.json()["error"]["code"] == "unsupported_streaming" and a and a.get("upstream_ms") is None
        results["C5 stream 거부"] = (c5, f"{r.status_code}, upstream_ms={a and a.get('upstream_ms')}")

        # C4 로그 위생 — 감사 파일·응답 파일에 키·Bearer·합성 PII 원문이 없어야 한다
        blobs = [log.read_text(encoding="utf-8")] + [(ROOT / "results" / f"{tag}_{n}.json").read_text(encoding="utf-8")
                                                    for n in ("c1", "c3")]
        audit_text = blobs[0]
        bad = {"키 값": sum(key in b for b in blobs), "Bearer": audit_text.count("Bearer"),
               "sk-ant": audit_text.count("sk-ant"), "합성 PII 원문(감사)": sum(v in audit_text for v in PII.values()),
               "줄바꿈 전화(이스케이프)": audit_text.count("010\\n3456\\n7890")}
        c4 = not any(bad.values())
        results["C4 로그 위생"] = (c4, ", ".join(f"{k} {v}" for k, v in bad.items()))

        lines = [l for l in log.read_text(encoding="utf-8").split("\n") if l.strip()]
        v3 = len(lines) == sent
        print()
        print(f"| 검사 | 결과 |\n|---|---|\n| V1 코드 | HEAD `{head[:7]}`, gateway/ 미변경 |"
              f"\n| V2 설정 | {'통과' if v2 else '실패'} |\n| V3 감사 대응 | {'통과' if v3 else '실패'} — /v1 요청 {sent}회 = 감사 {len(lines)}줄 |"
              f"\n| V4 상한 | {'통과' if calls <= MAX_CALLS and cost <= MAX_COST else '실패'} — 호출 {calls}/{MAX_CALLS}회, 누적 추정 ${cost:.6f} / ${MAX_COST} |")
        print("\n| 항목 | 결과 | 근거 |\n|---|---|---|")
        for name, (ok, why) in results.items():
            print(f"| {name} | {'합격' if ok else '불합격·판정 불가'} | {why} |")
        if c4:
            (ROOT / "results" / f"audit_{tag}.jsonl").write_text(log.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"\n감사 사본 results/audit_{tag}.jsonl")
        else:
            print("\nC4 실패 — 감사 파일을 커밋하지 않는다")
        return 0 if all(ok for ok, _ in results.values()) and v2 and v3 else 1
    finally:
        proc.terminate(); proc.wait(10)


if __name__ == "__main__":
    raise SystemExit(main())
