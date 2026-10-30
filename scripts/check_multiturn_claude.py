#!/usr/bin/env python3
"""PLAN 7단계(D-114) — D-111 §6 사전 등록 실행: 실제 Claude API 앞의 2턴 대화.

옛 게이트웨이(`research-final`, 요청마다 난수 대체값)와 새 게이트웨이(현재 트리, 결정적 대체값)를 나란히 띄우고 팔마다 2턴 대화 5개를 보낸다.
턴 2는 게이트웨이가 돌려준 턴 1 응답(thinking 블록 포함)을 그대로 이력에 붙인다. 질문: 둘째 턴의 thinking 서명 검사와 프롬프트 캐시를 지키는가.

정상 요청·합성 값만 보낸다. 키는 `.env`의 ANTHROPIC_API_KEY로만 읽고 출력하지 않는다. 기록에 키·합성 원문·답 본문을 남기지 않는다.

  python3 scripts/check_multiturn_claude.py          # 실제 API — 기록 docs/verification/multiturn_claude.jsonl
  python3 scripts/check_multiturn_claude.py --stub   # 스텁 상류로 배선만 확인(비용 0, 판정 없음)
종료 코드: 0 성공 기준(P1·P2·P3·P5) 충족 / 1 미충족 / 2 준비 실패
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.detectors.patterns import find_all  # noqa: E402
from gateway.version import code_fingerprint  # noqa: E402
from tests.conftest import free_port, serve  # noqa: E402

API = "https://api.anthropic.com"
VERSION = "2023-06-01"
MODELS = ("claude-haiku-5-5", "claude-sonnet-5-5")       # D-111 §6: 앞이 거절되면 뒤(바꾼 사실을 기록)
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}  # $/MTok 입력·출력(claude-api 스킬 표, 2026-10-06)
CACHE_WRITE, CACHE_READ = 1.25, 0.10                     # 입력 단가 배수(5분 캐시)
MAX_COST, MAX_TOKENS, MIN_CACHE = 1.0, 1024, 512
BETA = "thinking-binding-controls-2026-08-01"
OLD_REF, OLD_CODE = "research-final", "ac56e263ddc6"     # D-107 코드 지문(34c16fb)
DETECTORS = ["injection_observe", "pii_mask"]            # 두 팔의 제품 기본 검사기
THINKING = ("thinking", "redacted_thinking")
USAGE = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
OUT = ROOT / "docs" / "verification" / "multiturn_claude.jsonl"

# 합성 업무 문서 — 개인정보 꼴이 없어야 한다(보내기 전에 확인). 캐시 최소 길이의 두 배를 넘기려고 품목마다 같은 틀로 늘린다.
RULES = [  # (품목군, 단순 변심 반품 기한(일, 0이면 받지 않음), 왕복 배송비, 개봉 차감률 %, 예외)
    ("가전", 14, "1만 2천 원", 10, "설치를 마친 대형 가전은 단순 변심 반품을 받지 않는다"),
    ("디지털 기기", 7, "6천 원", 15, "정품 등록이나 계정 연동을 마친 기기는 개봉한 것으로 본다"),
    ("가구", 7, "4만 원", 20, "주문 제작 가구는 단순 변심 반품을 받지 않는다"),
    ("의류·잡화", 30, "6천 원", 0, "상표를 떼었거나 세탁한 상품은 반품을 받지 않는다"),
    ("레저·캠핑", 14, "8천 원", 10, "한 번이라도 설치한 흔적이 있으면 개봉한 것으로 본다"),
    ("식품", 0, "없음", 0, "신선 식품은 하자가 아니면 반품을 받지 않는다"),
    ("도서", 14, "4천 원", 0, "비닐 포장을 뜯은 화보집은 반품을 받지 않는다"),
    ("뷰티", 7, "5천 원", 100, "개봉한 화장품은 피부 이상이 확인될 때만 반품한다"),
    ("유아동", 14, "6천 원", 10, "위생 용품은 개봉하면 반품을 받지 않는다"),
    ("생활용품", 14, "5천 원", 5, "묶음 상품은 일부만 반품할 수 없다"),
]
HEAD = """너는 가상 쇼핑몰 '한빛마켓'의 고객지원 상담 보조다. 아래 사내 규정만 근거로 답한다. 규정에 없는 내용은 "규정에 없음"이라고 말한다.
상담원이 고객에게 보낼 회신 초안을 요청하면 정중한 존댓말로, 요청한 길이 안에서 쓴다. 고객 연락처는 상담원이 요청한 그대로 옮겨 적는다.

# 한빛마켓 고객지원 환불·교환 처리 규정 (가상 문서, 시험용)

## 제1장 총칙
1. 이 규정은 한빛마켓에서 판매한 상품의 반품·교환·환불 상담에 적용한다. 입점 판매자의 별도 규정이 있으면 고객에게 더 유리한 쪽을 따른다.
2. 기한은 상품을 받은 날의 다음 날부터 센다. 공휴일도 기한에 넣는다.
3. '단순 변심'은 상품에 하자가 없는데 고객이 마음을 바꾼 경우다. '하자'는 파손, 오배송, 표시와 다른 상품, 정상 사용 중의 고장이다.
4. '개봉'은 상품의 겉포장을 뜯은 상태를 말한다. 택배 상자를 연 것만으로는 개봉이 아니다.
5. 상담원은 고객이 말한 사실과 규정을 대조해 판단하고, 판단의 근거가 된 조항을 회신에 밝힌다.

## 제2장 접수와 회수
1. 반품 접수는 앱의 주문 내역이나 상담 채팅으로 받는다. 전화로 요청하면 상담원이 대신 입력한다.
2. 회수는 접수 다음 영업일부터 이틀 안에 택배 기사가 방문한다. 고객이 직접 보내면 배송비 영수증을 받아 둔다.
3. 회수한 상품은 물류센터에서 이틀 안에 검수한다. 검수 결과가 접수 내용과 다르면 상담원이 고객에게 다시 안내한다.
4. 대형 상품(가구, 대형 가전)은 회수 일정을 고객과 따로 잡는다. 승강기가 없는 건물의 세 층 이상이면 계단 운반비 1만 원을 더한다.

## 제3장 환불
1. 환불은 결제한 수단으로 돌려준다. 카드 결제는 승인 취소, 계좌이체는 고객 명의 계좌로 송금, 적립금은 적립금으로 되돌린다.
2. 환불 시점은 검수 완료 다음 영업일이다. 카드사 사정으로 승인 취소가 반영되기까지 영업일 기준 사흘에서 닷새가 걸릴 수 있다.
3. 고객이 부담할 배송비와 개봉 차감액은 환불액에서 뺀다. 환불액이 부담액보다 적으면 차액을 따로 청구하지 않고 환불액을 0원으로 한다.
4. 쿠폰으로 할인받은 주문을 일부만 반품하면 쿠폰 할인은 남는 상품에 다시 나눠 적용한다. 쿠폰 사용 기한이 지났으면 쿠폰은 돌려주지 않는다.

## 제4장 하자 판정
1. 하자 반품은 받은 날부터 90일 안이면 기한과 관계없이 접수한다. 배송비는 회사가 부담한다.
2. 하자 여부는 물류센터 검수로 확정한다. 고객이 보낸 사진만으로 하자가 분명하면 회수 전에 환불할 수 있다.
3. 정상 사용 중의 고장은 제조사 보증이 우선이다. 보증 기간이 지났으면 유상 수리를 안내한다.

## 제5장 상담 응대 원칙
1. 고객이 화가 나 있어도 사실 확인을 먼저 하고, 규정과 다른 약속을 하지 않는다.
2. 회신 초안은 결론, 근거 조항, 고객이 할 일의 순서로 쓴다.
3. 금액은 원 단위로 적고, 계산 과정이 필요하면 한 줄로 보인다.
4. 고객 연락처와 주문 정보는 상담 기록에만 남기고 다른 고객이나 외부에 말하지 않는다.

## 제6장 품목별 기준
"""
CONVS = [  # (상품, 가격, 받은 지 며칠, 휴대전화, 이메일) — 합성 값. 이메일은 예약 도메인
    ("무선 청소기를", "32만 원", 5, "010-3812-4407", "minji.park@example.com"),
    ("원목 책상을", "45만 원", 9, "010-5274-9163", "seojun.lee@example.com"),
    ("겨울 패딩을", "18만 원", 12, "010-6409-2285", "jiwoo.choi@example.com"),
    ("전자책 단말기를", "21만 원", 3, "010-7731-0548", "hayun.kang@example.com"),
    ("캠핑 텐트를", "27만 원", 20, "010-8156-3392", "dohyun.yoon@example.com"),
]
TURN1 = ("[상담 접수] 고객이 {item} 받은 지 {days}일 됐는데 단순 변심으로 반품하고 싶다고 합니다. 상품 가격은 {price}이고, "
         "포장은 뜯었지만 쓰지는 않았다고 합니다. 고객 연락처는 휴대전화 {phone}, 이메일 {email}입니다.\n"
         "규정에 따라 (1) 반품이 되는지, (2) 고객이 부담할 금액이 얼마인지 따져 보고, (3) 고객에게 보낼 세 문장 이내의 회신 초안을 써 주세요. "
         "회신 초안 첫 줄에는 고객 연락처를 받은 그대로 적어 주세요.")
TURN2 = "방금 회신 초안에 적은 고객 연락처(휴대전화와 이메일)를 다른 말 없이 한 줄에 하나씩 다시 적어 주세요."


def system_doc() -> str:
    parts = [HEAD]
    for i, (kind, days, fee, cut, extra) in enumerate(RULES, 1):
        when = f"받은 날부터 {days}일 안에 받는다" if days else "받지 않는다"
        parts.append(f"""### {i}절. {kind}
- 단순 변심 반품: {when}. 기한을 넘기면 하자가 아닌 한 반품을 받지 않는다.
- 단순 변심 반품의 왕복 배송비: {fee}, 고객 부담. 하자 반품은 회사가 부담한다.
- 개봉한 상품의 단순 변심 반품: 상품 가격의 {cut}%를 차감한다. 차감률이 100%면 반품을 받지 않는다는 뜻이다.
- 교환: 같은 상품의 다른 색상이나 크기로만 받는다. 교환 기한은 반품 기한과 같고, 왕복 배송비도 반품과 같은 기준으로 부담한다.
- 예외: {extra}.
- 구성품이나 사은품이 빠지면 반품을 받지 않는다. 사은품만 쓴 경우 사은품 가격을 환불액에서 뺀다.
""")
    return "\n".join(parts)


def lines(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x] if log.exists() else []


def audit_line(log: Path, n: int) -> dict:
    """n번째 감사 줄 — 응답을 보낸 뒤에 쓰일 수 있어 잠깐 기다린다."""
    for _ in range(50):
        rows = lines(log)
        if len(rows) > n:
            return rows[n]
        time.sleep(0.1)
    return {}


def cost(model: str, u: dict) -> float:
    p_in, p_out = PRICE.get(model, (0.0, 0.0))
    return ((u.get("input_tokens") or 0) * p_in + (u.get("cache_creation_input_tokens") or 0) * p_in * CACHE_WRITE
            + (u.get("cache_read_input_tokens") or 0) * p_in * CACHE_READ + (u.get("output_tokens") or 0) * p_out) / 1e6


def record(arm: str, conv: int, turn: int, model: str, attempt: int, binding: bool, messages: list, r: httpx.Response,
           audit: dict, phone: str, email: str) -> dict:
    try:
        data = r.json()
    except ValueError:
        data = {}
    data = data if isinstance(data, dict) else {}
    blocks = [b for b in data.get("content") or [] if isinstance(b, dict)]
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    err = data.get("error") if isinstance(data.get("error"), dict) else None
    pii = next((d for d in audit.get("response_detectors", []) if d.get("detector") == "pii_mask"), {})
    u = {k: (data.get("usage") or {}).get(k) for k in USAGE}
    return {"kind": "request", "attempt": attempt, "binding_controls": binding, "arm": arm, "conv": conv, "turn": turn,
            "model": model, "status": r.status_code, "error_type": err.get("type") if err else None,
            "error": str(err.get("message")).replace(phone, "<원문>").replace(email, "<원문>") if err else None,
            "input_transformations": data.get("input_transformations"), "usage": u, "stop_reason": data.get("stop_reason"),
            "thinking_out": sum(1 for b in blocks if b.get("type") in THINKING),
            "thinking_replayed": sum(1 for m in messages if m["role"] == "assistant" for b in m["content"]
                                     if isinstance(b, dict) and b.get("type") in THINKING),
            "issued": pii.get("issued"), "restored": pii.get("restored"), "residual_tokens": pii.get("residual_tokens"),
            "suspect": pii.get("suspect"), "phone_in_answer": phone in text, "email_in_answer": email in text,
            "cost_usd": round(cost(model, u), 6)}


def brief(r: dict) -> str:
    u = r["usage"]
    return (f"  {r['arm']} 대화{r['conv']} 턴{r['turn']}: {r['status']} 캐시 쓰기 {u['cache_creation_input_tokens']}·읽기 "
            f"{u['cache_read_input_tokens']}, thinking 받음 {r['thinking_out']}·다시 보냄 {r['thinking_replayed']}, 발급 {r['issued']} "
            f"복원 {r['restored']} 잔여 {r['residual_tokens']} 의심 {r['suspect']}, 답의 원래 전화 {'O' if r['phone_in_answer'] else '-'}"
            f"·메일 {'O' if r['email_in_answer'] else '-'}, {r['stop_reason']}, ${r['cost_usd']:.5f}"
            + (f"\n    오류: {r['error'][:300]}" if r["error"] else ""))


def run(arms: list[dict], model: str, sysdoc: str, binding: bool, rows: list[dict], attempt: int) -> str:
    """사전 등록 절차 한 번. 대화마다 A 2턴 → B 2턴. 반환: done | cost | binding_rejected."""
    with httpx.Client(timeout=300) as http:
        for c, (item, price, days, phone, email) in enumerate(CONVS, 1):
            user1 = {"role": "user", "content": [{"type": "text", "cache_control": {"type": "ephemeral"},
                                                  "text": TURN1.format(item=item, price=price, days=days, phone=phone, email=email)}]}
            for arm in arms:
                messages = [user1]
                for turn in (1, 2):
                    if sum(x["cost_usd"] for x in rows) >= MAX_COST:
                        return "cost"
                    thinking = {"type": "adaptive"}
                    headers = {"x-api-key": arm["key"], "anthropic-version": VERSION}
                    if binding:
                        thinking["block_binding"] = {"prefix_mismatch_behavior": "error"}
                        headers["anthropic-beta"] = BETA
                    body = {"model": model, "max_tokens": MAX_TOKENS, "system": sysdoc, "thinking": thinking, "messages": messages}
                    n = len(lines(arm["log"]))
                    r = http.post(f"{arm['url']}/v1/messages", json=body, headers=headers)
                    rec = record(arm["name"], c, turn, model, attempt, binding, messages, r, audit_line(arm["log"], n), phone, email)
                    rec["cum_cost_usd"] = round(sum(x["cost_usd"] for x in rows) + rec["cost_usd"], 6)
                    rows.append(rec)
                    print(brief(rec))
                    msg = rec["error"] or ""
                    # 턴 1의 400은 서명 검사일 수 없다 — 베타 헤더·필드를 거절한 것이면 둘 다 빼고 한 번 다시 돈다(D-111 §6)
                    if binding and turn == 1 and r.status_code == 400 and ("block_binding" in msg or "anthropic-beta" in msg or BETA in msg):
                        return "binding_rejected"
                    if r.status_code != 200:
                        break
                    messages = [user1, {"role": "assistant", "content": r.json()["content"]}, {"role": "user", "content": TURN2}]
    return "done"


def judge(rows: list[dict]) -> dict:
    last = [r for r in rows if r["attempt"] == max(x["attempt"] for x in rows)]
    a = [r for r in last if r["arm"] == "A"]
    b = [r for r in last if r["arm"] == "B"]
    b2 = [r for r in b if r["turn"] == 2]

    def read(r: dict) -> int:
        return r["usage"]["cache_read_input_tokens"] or 0
    p1 = len(b) == 2 * len(CONVS) and all(r["status"] == 200 for r in b)
    a400 = [r["conv"] for r in a if r["turn"] == 2 and r["status"] == 400 and "different conversation" in (r["error"] or "")]
    amiss = [r["conv"] for r in a if r["turn"] == 2 and r["status"] == 200 and read(r) == 0]
    spent = round(sum(r["cost_usd"] for r in rows), 6)
    return {
        "P1_b_no_400": p1,
        "P2_b_turn2_cache_read": len(b2) == len(CONVS) and all(read(r) > 0 for r in b2),
        "P3_b_restored": p1 and all(r["residual_tokens"] == 0 and not r["suspect"] for r in b)
                         and all(r["phone_in_answer"] and r["email_in_answer"] for r in b2),
        "P4_a_breaks": bool(a400 or amiss),
        "P5_cost": spent <= MAX_COST,
        "a_turn2_prefix_400": a400,
        "a_turn2_cache_miss": amiss,
        "b_turn2_thinking_replayed": sum(r["thinking_replayed"] for r in b2),
        "spent_usd": spent,
    }


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def preflight(api_key: str, sysdoc: str) -> tuple[str, int]:
    """무료 count_tokens(system만, 개인정보 없음) — 모델 이름이 받아들여지는지와 system 길이를 먼저 본다."""
    for model in MODELS:
        r = httpx.post(f"{API}/v1/messages/count_tokens", headers={"x-api-key": api_key, "anthropic-version": VERSION},
                       json={"model": model, "system": sysdoc, "messages": [{"role": "user", "content": "안녕하세요"}]}, timeout=60)
        if r.status_code == 200:
            return model, r.json()["input_tokens"]
        print(f"count_tokens {model}: {r.status_code} {r.text[:300]}")
        if r.status_code != 404 and "model" not in r.text:
            break
    raise SystemExit(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stub", action="store_true", help="스텁 상류로 배선만 확인한다(비용 0, 판정 없음)")
    args = ap.parse_args()
    sysdoc = system_doc()
    if find_all(sysdoc):
        print("system 문서에 개인정보 꼴이 있다:", [f.kind for f in find_all(sysdoc)])
        return 2
    for item, price, days, phone, email in CONVS:
        kinds = sorted(f.kind for f in find_all(TURN1.format(item=item, price=price, days=days, phone=phone, email=email)))
        if kinds != ["email", "phone"]:
            print("턴 1 문장의 탐지 결과가 전화·이메일 하나씩이 아니다:", kinds)
            return 2
    if not args.stub and git("status", "--porcelain", "--", "gateway"):
        print("gateway/에 커밋하지 않은 변경이 있다 — 새 팔은 커밋된 코드로 잰다")
        return 2
    if args.stub:
        api_key = "stub-upstream-key"
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or dotenv_values(ROOT / ".env").get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ANTHROPIC_API_KEY가 없다 — .env에 넣는다(값은 출력하지 않는다)")
            return 2

    tmp = Path(tempfile.mkdtemp(prefix="d114-"))
    tree = tmp / "research-final"
    procs: list[subprocess.Popen] = []
    try:
        if args.stub:
            port = free_port()
            procs.append(serve("tests.stub_target:app", port, cwd=ROOT))
            upstream, model, sys_tokens = f"http://127.0.0.1:{port}", "stub-thinking", None
        else:
            upstream = API
            model, sys_tokens = preflight(api_key, sysdoc)
            print(f"count_tokens: {model}, system+인사 {sys_tokens}토큰(최소 캐시 {MIN_CACHE}의 두 배 {2 * MIN_CACHE} 이상이어야 한다)")
            if sys_tokens < 2 * MIN_CACHE:
                return 2
        git("worktree", "add", "--detach", str(tree), OLD_REF)
        client_key, admin_key = "gw-" + secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        common = {"TARGET_URL": upstream, "GATEWAY_CLIENT_KEYS": f"d114={client_key}", "GATEWAY_UPSTREAM_KEY": api_key}
        arms = []
        for name, app_dir, extra in (("A", tree, {}),
                                     ("B", ROOT, {"GATEWAY_SURROGATE_KEY": secrets.token_urlsafe(32), "GATEWAY_ADMIN_KEY": admin_key})):
            log, port = tmp / f"{name}.jsonl", free_port()
            procs.append(serve("gateway.main:app", port, {**common, **extra, "GATEWAY_LOG_PATH": str(log)},
                               probe="/__gateway/health", cwd=app_dir))
            arms.append({"name": name, "url": f"http://127.0.0.1:{port}", "key": client_key, "log": log})
        old = httpx.get(f"{arms[0]['url']}/__gateway/health").json()
        new = httpx.get(f"{arms[1]['url']}/__gateway/info", headers={"Authorization": f"Bearer {admin_key}"}).json()
        head = git("rev-parse", "--short", "HEAD")
        print(f"A: 코드 {old.get('code')} 검사기 {old.get('detectors')} 상류 {old.get('target')}")
        print(f"B: 코드 {new.get('code')} 검사기 {new.get('detectors')} 상류 {new.get('target')} (HEAD {head})")
        if (old.get("code"), new.get("code")) != (OLD_CODE, code_fingerprint()) or old.get("detectors") != DETECTORS \
                or new.get("detectors") != DETECTORS or {old.get("target"), new.get("target")} != {upstream}:
            print("팔 구성이 사전 등록과 다르다 — 보내지 않는다")
            return 2

        rows: list[dict] = []
        binding, outcome = True, run(arms, model, sysdoc, True, rows, 1)
        if outcome == "binding_rejected":
            print("API가 thinking-binding 베타 헤더·필드를 거절했다 — 둘 다 빼고 한 번 다시 돈다(D-111 §6)")
            binding, outcome = False, run(arms, model, sysdoc, False, rows, 2)
        verdict = judge(rows)
        meta = {"kind": "meta", "date": dt.date.today().isoformat(), "plan_step": 7, "decision": "D-114 (사전 등록 D-111 §6)",
                "model": model, "upstream": upstream, "binding_controls": binding, "outcome": outcome,
                "system_tokens_count_api": sys_tokens, "min_cache_tokens": MIN_CACHE, "max_tokens": MAX_TOKENS,
                "code_old": old.get("code"), "code_new": new.get("code"), "head": head,
                "price_per_mtok": PRICE.get(model), "convs_per_arm": len(CONVS)}
        out = tmp / "stub.jsonl" if args.stub else OUT
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in [meta, *rows, {"kind": "summary", **verdict}]),
                       encoding="utf-8")
        print(f"기록: {out} ({len(rows)}건), 끝: {outcome}")
        if args.stub:
            ok = len(rows) == 4 * len(CONVS) and all(r["status"] == 200 for r in rows)
            print("스텁 배선:", "통과" if ok else "실패")
            return 0 if ok else 1
        print(json.dumps(verdict, ensure_ascii=False, indent=1))
        ok = all(verdict[k] for k in ("P1_b_no_400", "P2_b_turn2_cache_read", "P3_b_restored", "P5_cost"))
        print("결과:", "성공 기준 충족" if ok else "성공 기준 미충족", "/ 옛 팔 재현:", "예" if verdict["P4_a_breaks"] else "아니오")
        return 0 if ok else 1
    finally:
        for p in reversed(procs):
            p.terminate()
            p.wait(10)
        if tree.exists():
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)], capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
