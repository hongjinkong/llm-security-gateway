#!/usr/bin/env python3
"""D-106 §6 — 실제 공급자(Claude, OpenAI 호환 입구) 앞에 게이트웨이를 끼우고 장면 1(개인정보)을 **스트리밍**으로 보낸다.

데모 웹(web/app.py)을 실제 공급자 모드(WEB_ON_TARGET=https://api.anthropic.com)로 띄우고 `/api/chat?stream=1`로 장면 1을 한 번 보낸다.
정상 질문만 보내고 공격 문장은 보내지 않는다(SCOPE 6절). 키는 환경변수 `ANTHROPIC_API_KEY`(또는 `.env`)로만 읽고 어디에도 쓰지 않는다.

합격(§6): "있음" 쪽 답이 조각(delta)으로 도착하고, 이어 붙인 답에 `010-2345-6789`가 있고 `[PII:`가 없으며,
감사 `pii_mask restored≥1`·`residual_tokens=0`. 모델이 번호를 되풀이하지 않아 restored=0이면 판정 불가 — D-103 C2처럼 받은 값을
그대로 적으라는 문장으로 한 번만 더 보낸다(합계 최대 2회, §6의 "정상 요청 1~2회").
비용: 스트리밍 응답에는 usage가 없어 상한으로 적는다 — 요청마다 입력 ≤ 100 토큰 + 출력 ≤ max_tokens 300.

  python3 scripts/check_claude_d106.py [--model claude-opus-5-5] [--date YYYYMMDD]
종료 코드: 0 합격 / 1 불합격·판정 불가 / 2 준비 실패(키 없음)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.conftest import free_port, serve  # noqa: E402

PHONE, EMAIL = "010-2345-6789", "j.hong@hanbit-tech.example"      # 장면 1의 합성 값(web/app.py SCENES[0])
PRICE = {"claude-opus-5-5": (4.0, 20.0)}                           # $/1M 입력·출력 (2026-10 기준)
MAX_COST = 0.01


def rows_of(web: str, messages: list[dict]) -> list[dict]:
    with httpx.stream("POST", f"{web}/api/chat?stream=1", json={"messages": messages}, timeout=120) as r:
        return [json.loads(line) for line in r.iter_lines() if line.strip()]


def judge(rows: list[dict]) -> tuple[dict, int, bool, str]:
    """(있음 결과 행, delta 수, 합격 여부, 설명)."""
    deltas = [x for x in rows if x.get("arm") == "on" and "delta" in x]
    final = rows[-1]
    answer = final.get("answer") or ""
    res = {d["detector"]: d for d in (final.get("audit") or {}).get("response_detectors", [])}
    restored = res.get("pii_mask", {}).get("restored", 0)
    residual = res.get("pii_mask", {}).get("residual_tokens", 0)
    ok = (final.get("status") == 200 and not final.get("blocked") and len(deltas) >= 2
          and PHONE in answer and "[PII:" not in answer and restored >= 1 and residual == 0)
    why = (f"status={final.get('status')} delta={len(deltas)}개 restored={restored} residual={residual} "
           f"번호 {'있음' if PHONE in answer else '없음'} 메일 {'있음' if EMAIL in answer else '없음'} "
           f"'[PII:' {'있음' if '[PII:' in answer else '없음'} upstream_ms={(final.get('audit') or {}).get('upstream_ms')}")
    return final, len(deltas), ok, why


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="claude-opus-5-5")
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"))
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY가 없다 — 환경변수나 .env에 넣는다(값은 출력하지 않는다)")
        return 2
    price_in, price_out = PRICE.get(args.model, (None, None))
    if price_in is None:
        print(f"{args.model}의 단가를 모른다 — PRICE에 추가한다")
        return 2
    bound = (100 * price_in + 300 * price_out) / 1e6          # 요청 1회 비용 상한
    out = ROOT / "results" / f"d106_claude_{args.date}.jsonl"

    port = free_port()
    proc = serve("web.app:app", port, {"WEB_ON_TARGET": "https://api.anthropic.com", "WEB_ON_MODEL": args.model}, probe="/api/info")
    try:
        web = f"http://127.0.0.1:{port}"
        info = httpx.get(f"{web}/api/info").json()
        print(f"info: real={info['real']} model={info['model']} on.upstream={info['on']['upstream']} code={info['on']['code']} "
              f"detectors={info['on']['detectors']}")
        if not info["real"] or info["on"]["upstream"] != "https://api.anthropic.com":
            print("실제 공급자 모드가 아니다")
            return 2
        scene = next(s for s in httpx.get(f"{web}/api/scenes").json() if s["id"] == 1)
        attempts = [("장면 1 그대로", scene["messages"]),
                    ("받은 값 되풀이 요청(D-103 C2 문장)", [{"role": "user", "content":
                        f"아래 값을 받은 그대로 한 줄씩 다시 적어 주세요. 다른 말은 하지 마세요.\n{PHONE}\n{EMAIL}"}])]
        calls, saved, ok = 0, [], False
        for label, messages in attempts:
            if calls * bound >= MAX_COST:
                print(f"비용 상한 ${MAX_COST} — 더 보내지 않는다")
                break
            rows = rows_of(web, messages)
            calls += 1
            saved.extend(rows)
            final, n_delta, ok, why = judge(rows)
            answer = (final.get("answer") or "").replace("\n", " ")
            print(f"[{calls}] {label}: {why}")
            print(f"    답(앞 200자): {answer[:200]}")
            if final.get("error"):
                print(f"    오류: {final['error']}")
            restored = {d["detector"]: d for d in (final.get("audit") or {}).get("response_detectors", [])}.get("pii_mask", {}).get("restored", 0)
            if ok or restored >= 1 or final.get("status") != 200:
                break
            print("    판정 불가(복원 0) — 되풀이 요청으로 한 번 더")
        out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in saved), encoding="utf-8")
        print(f"호출 {calls}회, 비용 상한 추정 ${calls * bound:.4f} / ${MAX_COST} (요청마다 입력 ≤100·출력 ≤300 토큰 기준), 사본 {out.relative_to(ROOT)}")
        print("결과:", "합격" if ok else "불합격·판정 불가")
        return 0 if ok else 1
    finally:
        proc.terminate()
        proc.wait(10)


if __name__ == "__main__":
    raise SystemExit(main())
