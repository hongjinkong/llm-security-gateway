"""`eval/multiturn_run.py` — 다중 턴 FPR 실행기(D-100). 실제 AnythingLLM·게이트웨이 대신 가짜를 쓴다.

가짜 게이트웨이는 호출마다 감사 줄 하나를 쓰고, B-103이 지나간 세션의 뒤 요청을
scope="all"이면 막고(세션 오염, (A)) scope="turn"이면 막지 않고 이력만 가린다((C)).
보는 것: 세션 순서·sessionId, lead 첫 줄(B-103)을 집계에서 빼는지, 감사 사본이 실행 창과 1:1인지,
그리고 산출물이 scripts/fpr_report.py --link time에 **그대로** 들어가 기대한 FPR이 나오는지.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
import multiturn_run as mt  # noqa: E402

BENIGN = ROOT / "eval" / "benign" / "all100.jsonl"
ITEMS = {r["id"]: r for r in map(json.loads, filter(None, BENIGN.read_text(encoding="utf-8").split("\n")))}
BLOCKED = "요청이 보안 정책에 의해 차단되었습니다."


@pytest.fixture
def fpr_run(monkeypatch):
    """fpr_run.py는 가져올 때 환경변수를 읽는다. 가짜 값으로 채운 뒤 record만 쓴다(호출은 하지 않는다)."""
    for k, v in {"TARGET_URL": "http://fake", "WORKSPACE_SLUG": "ws", "TARGET_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    return importlib.import_module("fpr_run")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FakeGateway:
    def __init__(self, audit: Path, scope: str):
        self.audit, self.scope = audit, scope
        self.tainted: set[str] = set()
        self.sids: list[str] = []

    def ask(self, msg: str, sid: str) -> dict:
        self.sids.append(sid)
        t_start = now()
        time.sleep(0.002)
        lead = msg == ITEMS["B-103"]["q"]
        blocked = lead or (sid in self.tainted and self.scope == "all")
        transformed = not blocked and sid in self.tainted          # (C): 이력의 B-103만 가린다
        if lead:
            self.tainted.add(sid)
        item = next(r for r in ITEMS.values() if r["q"] == msg)
        text = BLOCKED if blocked else " ".join(vs[0] for vs in item.get("facts", {}).values())
        with self.audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": now(), "request_id": uuid.uuid4().hex[:16], "status": 200,
                                "path": "/v1/chat/completions", "blocked": blocked, "transformed": transformed,
                                "total_ms": 100.0, "upstream_ms": None if blocked else 99.0,
                                "gateway_ms": 1.0, "chain_ms": 0.1, "detectors": [],
                                "response_detectors": []}, ensure_ascii=False) + "\n")
        time.sleep(0.002)
        return {"session_id": sid, "request_id": None, "status": 200, "elapsed_ms": 5.0, "text": text,
                "gateway_blocked": False, "error": None, "t_start": t_start, "t_end": now()}


def run(tmp_path: Path, fpr_run, scope: str) -> tuple[str, dict, FakeGateway]:
    audit = tmp_path / "gateway.jsonl"
    audit.write_text('{"request_id": "earlier"}\n', encoding="utf-8")    # 앞에 쌓인 줄은 사본에 안 들어간다
    gw = FakeGateway(audit, scope)
    prefix = str(tmp_path / f"mt_{scope}")
    summary = mt.run_sessions(ITEMS, gw.ask, fpr_run.record, prefix, audit, sleep=0.003, tag="t")
    return prefix, summary, gw


def report(prefix: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/fpr_report.py", "--link", "time",
         "--off", f"{prefix}_ctrl.jsonl", "--on", f"{prefix}_lead.jsonl",
         "--audit-off", f"{prefix}_ctrl_audit.jsonl", "--audit-on", f"{prefix}_lead_audit.jsonl"],
        cwd=ROOT, capture_output=True, text=True)


def rows(path: str) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").split("\n") if x]


def test_sessions_order_and_files(tmp_path, fpr_run):
    prefix, summary, gw = run(tmp_path, fpr_run, "turn")
    n = len(mt.FOLLOWERS)
    assert gw.sids == ["mt-t-ctrl"] * n + ["mt-t-lead"] * (n + 1)
    assert [r["id"] for r in rows(f"{prefix}_ctrl.jsonl")] == list(mt.FOLLOWERS)
    assert [r["id"] for r in rows(f"{prefix}_lead.jsonl")] == list(mt.FOLLOWERS)   # B-103은 집계에서 빠진다
    assert [r["id"] for r in rows(f"{prefix}_head.jsonl")] == ["B-103"]
    assert summary["ctrl"] == {"session_id": "mt-t-ctrl", "calls": n, "audit_from": 1, "audit_to": 1 + n, "errors": 0}
    assert summary["lead"]["audit_from"] == 2 + n and summary["lead"]["audit_to"] == 2 + 2 * n
    assert len(rows(f"{prefix}_lead_audit.jsonl")) == n                             # B-103 줄은 사본에 없다


def test_scope_all_contaminates_every_follower(tmp_path, fpr_run):
    """(A) 흉내: B-103 뒤 20개가 전부 막힌다 → 다중 턴 FPR 100%, 목표 초과(종료 1)."""
    prefix, _, _ = run(tmp_path, fpr_run, "all")
    p = report(prefix)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "FPR = (0x0.5 + 20x1.0) / 20 = 100.0%" in p.stdout


def test_scope_turn_only_masks_history(tmp_path, fpr_run):
    """(C) 흉내: 막지 않고 가리기만 한다. 사실 일치가 그대로면 정상 → 0.0%, 변형 20개는 대조표 대상."""
    prefix, _, _ = run(tmp_path, fpr_run, "turn")
    p = report(prefix)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "FPR = (0x0.5 + 0x1.0) / 20 = 0.0%" in p.stdout
    assert "transformed=true : 20개" in p.stdout


def test_missing_benign_item_is_refused(tmp_path, fpr_run):
    with pytest.raises(ValueError, match="B-103"):
        mt.run_sessions({k: v for k, v in ITEMS.items() if k != "B-103"}, None, fpr_run.record,
                        str(tmp_path / "x"))


def test_followers_are_the_registered_general_questions():
    assert mt.FOLLOWERS == tuple(f"G-{n}" for n in range(101, 121))
    assert all(ITEMS[q]["cat"] == "general" and ITEMS[q].get("facts") for q in mt.FOLLOWERS)
