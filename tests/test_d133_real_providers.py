"""D-133(PLAN 20-1단계): 실 공급자 확인 스크립트 — 스텁 상류로 배선을 끝까지 돌리고(비용 0) 판정·파싱의 경계를 본다. 실제 호출은 등록 커밋 뒤에 사람이 돌린다."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("check_real_providers", ROOT / "scripts" / "check_real_providers.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def row(check: str, outcome: str = "ok", status: int = 200, issued: int = 2) -> dict:
    return {"check": check, "outcome": outcome, "status": status, "pii_issued": issued}


# ---------- V1 스텁 배선 ----------

def test_v1_stub_run_covers_three_apis_and_writes_no_text(tmp_path):
    out = tmp_path / "run"
    done = subprocess.run([sys.executable, "scripts/check_real_providers.py", "--stub", "--out", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-1500:]
    rows = [json.loads(line) for line in out.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
    mod = _mod()
    assert len(rows) == 60 <= mod.MAX_CALLS                                               # 5조합 × (E·S·T 3회 + M 3회)
    assert {(r["api"], r["check"]) for r in rows} == {(api, c) for api in ("chat", "responses", "messages") for c in "ESTM"}
    assert all(r["status"] == 200 and r["pii_issued"] >= 2 and r["pii_suspect"] == 0 for r in rows)     # 전화·메일이 가짜 값으로 나갔고 남은 것이 없다
    assert all(r["outcome"] == "ok" for r in rows if r["check"] in "EST")                 # 스텁은 받은 글을 되돌려준다 — 답·스트림·도구 인자에 원래 값이 온전히
    assert all(r["outcome"] == "no_echo" for r in rows if r["check"] == "M")              # 스텁은 마지막 문장만 되돌린다(메일이 없다) — 분모에서 빠진다
    report = out.with_suffix(".md").read_text(encoding="utf-8")
    assert report.count("**통과**") == 5 and "요청 60건" in report
    for text in (report, out.with_suffix(".jsonl").read_text(encoding="utf-8"), done.stdout):   # 기록에 값·키가 없다
        assert mod.PHONE not in text and mod.EMAIL not in text and "stub-upstream-key" not in text


def test_v1_refuses_to_run_without_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("MONOROUTER_KEY", raising=False)
    env_file = ROOT / ".env"
    if env_file.exists() and "MONOROUTER_KEY" in env_file.read_text(encoding="utf-8"):
        pytest.skip(".env에 키가 있다 — 이 시험은 실제 호출을 하지 않으려고 건너뛴다")
    done = subprocess.run([sys.executable, "scripts/check_real_providers.py", "--out", str(tmp_path / "x")], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and "MONOROUTER_KEY" in done.stdout and not (tmp_path / "x.md").exists()


# ---------- V2 판정·파싱의 경계 ----------

def test_v2_outcome_and_judge_boundaries():
    mod = _mod()
    audit = {"pii_issued": 2, "pii_suspect": 0}
    want = (mod.PHONE, mod.EMAIL)
    assert mod.outcome(200, f"{mod.PHONE} / {mod.EMAIL}", audit, want) == "ok"
    assert mod.outcome(200, f"전화는 {mod.PHONE}", audit, want) == "partial"
    assert mod.outcome(200, "저장했습니다", audit, want) == "no_echo"
    assert mod.outcome(200, f"{mod.PHONE} / {mod.EMAIL}", {"pii_suspect": 1}, want) == "surrogate_left"     # 값이 보여도 가짜 값이 남았으면 미달 쪽
    assert mod.outcome(400, "", audit, want) == mod.outcome(200, "x", None, want) == "error"

    base = [row(c) for c in "ESTM" for _ in range(3)]
    assert mod.judge(base)["verdict"] == "통과"
    assert mod.judge(base[:-1] + [row("M", "surrogate_left")])["verdict"] == "미달"       # P3: 한 건이라도
    assert mod.judge(base[:-1] + [row("M", "error", status=502)])["verdict"] == "미달"    # P1
    assert mod.judge(base[:-1] + [row("M", issued=1)])["verdict"] == "미달"               # P2: 둘 중 하나만 가렸다
    two_of_three = [row("E"), row("E"), row("E", "partial")] + [row(c) for c in "STM" for _ in range(3)]
    assert mod.judge(two_of_three)["verdict"] == "통과"                                   # 2/3은 통과
    one_of_three = [row("E"), row("E", "partial"), row("E", "partial")] + [row(c) for c in "STM" for _ in range(3)]
    assert mod.judge(one_of_three)["verdict"] == "미달"
    quiet = [row("E", "no_echo") for _ in range(3)] + [row(c) for c in "STM" for _ in range(3)]
    j = mod.judge(quiet)
    assert j["verdict"] == "통과" and j["undecided"] == ["E"]                             # 되풀이 안 함은 분모에서 빠진다
    assert mod.judge([row(c, "no_echo") for c in "ESTM"])["verdict"] == "판정 불가" and mod.judge([])["verdict"] == "미달"


def test_v2_parsers_read_each_api_shape():
    mod = _mod()
    chat = {"choices": [{"message": {"content": "답", "tool_calls": [{"function": {"arguments": '{"phone":"1"}'}}]}}]}
    resp = {"output": [{"type": "reasoning"}, {"type": "message", "content": [{"type": "output_text", "text": "답"}]}, {"type": "function_call", "arguments": '{"phone":"1"}'}]}
    msgs = {"content": [{"type": "text", "text": "답"}, {"type": "tool_use", "input": {"phone": "1"}}]}
    assert mod.answer("chat", chat) == mod.answer("responses", resp) == ("답", '{"phone":"1"}')
    assert mod.answer("messages", msgs) == ("답", '{"phone": "1"}') and mod.answer("chat", {"choices": [{"message": {"content": None}}]}) == ("", "")
    assert mod.stream_text("chat", ['data: {"choices":[{"delta":{"content":"가"}}]}', "data: [DONE]", ": ping", 'data: {"choices":[]}']) == "가"
    assert mod.stream_text("responses", ['data: {"type":"response.output_text.delta","delta":"가"}', 'data: {"type":"response.function_call_arguments.delta","delta":"x"}']) == "가"
    assert mod.stream_text("messages", ['data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"가"}}', 'data: {"type":"ping"}', "data: {깨진"]) == "가"
    for api in ("chat", "responses", "messages"):           # 요청 모양 — 도구는 강제 호출, 출력 상한이 있다
        body = mod.request(api, "m", [("user", "x")], tool=True)
        assert body["tool_choice"] and (body.get("max_tokens") or body.get("max_output_tokens")) == mod.MAX_TOKENS and "stream" not in body
        assert mod.request(api, "m", [("user", "x")], stream=True)["stream"] is True
    budget = mod.Budget(2)
    budget.spend()
    budget.spend()
    with pytest.raises(SystemExit):
        budget.spend()
