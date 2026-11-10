"""D-132(PLAN 22단계): v1.0 기준 판정 도구(scripts/poc_gate.py)와 가격·계약 초안(docs/pricing.md)."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 12, 1, tzinfo=timezone.utc)


def _gate():
    spec = importlib.util.spec_from_file_location("poc_gate", ROOT / "scripts" / "poc_gate.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def lines(n: int, days: float = 15.0, special: dict[int, dict] | None = None, **base) -> list[str]:
    """감사 줄 n개 — 기간에 고르게 편다. `special`은 줄 번호별로 덮어쓸 필드."""
    out = []
    for i in range(n):
        rec = {"ts": (T0 + timedelta(days=days * i / max(n - 1, 1))).isoformat(timespec="milliseconds"), "request_id": f"r{i}", "status": 200, "error": None,
               "upstream_ms": 5.0, "blocked": False, "transformed": True, "pii_issued": 2, "pii_suspect": 0,
               "detectors": [{"detector": "pii_mask", "action": "pass"}], "response_detectors": [],
               **base, **(special or {}).get(i, {})}
        out.append(json.dumps(rec, ensure_ascii=False))
    return out


# ---------- Q1 기준의 경계 ----------

def test_q1_suspect_rate_boundary():
    gate = _gate()
    m = gate.measure(lines(2000, special={7: {"pii_suspect": 1}}))
    assert (m["requests"], m["issued"], m["suspect"], m["gateway_failed"]) == (2000, 2000, 1, 0) and 14.9 < m["days"] <= 15.0 and m["empty_days"] == 0
    text, ok = gate.report(m)
    assert ok and "1 / 2,000 = 0.050%" in text and text.count("| 통과 |") == 2
    text, ok = gate.report(gate.measure(lines(2000, special={7: {"pii_suspect": 1}, 9: {"pii_suspect": 3}})))
    assert not ok and "2 / 2,000 = 0.100%" in text and "| 미달 |" in text        # 딱 0.1%는 '미만'이 아니다


def test_q1_small_denominators_and_short_periods_are_not_judged():
    gate = _gate()
    text, ok = gate.report(gate.measure(lines(999)))
    assert not ok and text.count("| 판정 불가 |") == 2
    # 요청은 많아도 가짜 값을 발급한 요청이 적으면 G1은 판정하지 않는다(G2는 한다)
    m = gate.measure(lines(2000, special={i: {"pii_issued": 0} for i in range(1500)}))
    text, ok = gate.report(m)
    assert m["issued"] == 500 and not ok and text.count("| 판정 불가 |") == 1 and text.count("| 통과 |") == 1
    text, ok = gate.report(gate.measure(lines(2000, days=13.9)))
    assert not ok and "기간 부족" in text and text.count("| 통과 |") == 2
    assert gate.report(gate.measure([]))[1] is False


def test_q1_gateway_5xx_counts_and_upstream_errors_do_not():
    gate = _gate()
    special = {
        1: {"status": 503, "error": "upstream_busy", "upstream_ms": None, "pii_issued": 0},      # 포화 — 게이트웨이 몫
        2: {"status": 500, "error": "RuntimeError", "upstream_ms": None, "pii_issued": 0},       # 게이트웨이 예외
        3: {"status": 502, "error": "ConnectError", "upstream_ms": None},                        # 상류 연결 실패
        4: {"status": 500, "error": None},                                                       # 상류가 준 500을 그대로 전달
        5: {"status": 200, "error": "upstream_stream_error"},                                    # 스트림 안 공급자 오류
        6: {"status": 429, "error": "rate_limited", "upstream_ms": None, "pii_issued": 0},       # 4xx는 세지 않는다
        7: {"status": 200, "error": "ClientDisconnect"},                                         # 클라이언트가 끊었다 — 게이트웨이 몫이 아니다
        8: {"status": 500, "error": "CancelledError", "upstream_ms": None},
    }
    m = gate.measure(lines(2000, special=special))
    assert (m["gateway_failed"], m["upstream_errors"], m["client_gone"]) == (2, 3, 2)
    # 스트림 도중의 게이트웨이 실패는 머리(200)가 나간 뒤라 status 200 + 오류로 남는다 — 5xx만 세면 놓친다(리뷰)
    assert gate.measure(lines(2000, special={3: {"status": 200, "error": "RuntimeError"}}))["gateway_failed"] == 1
    text, ok = gate.report(m)
    assert not ok and "2 / 2,000 = 0.100%" in text and "3 / 2,000 = 0.150%" in text
    del special[2]
    assert gate.report(gate.measure(lines(2000, special=special)))[1] is True                    # 1건(0.05%)이면 통과 — 상류 장애 3건은 게이트 밖


def test_q1_lines_that_are_not_audit_records_are_skipped_and_counted():
    gate = _gate()
    junk = ["", "   ", "{잘린 줄", "[1, 2]", '"text"', json.dumps({"ts": "2026-12-01T00:00:00+00:00"}), json.dumps({"request_id": "x", "ts": 5}),
            json.dumps({"request_id": "y", "ts": "어제"}), json.dumps({"request_id": "z", "ts": "2026-12-01T00:00:00"})]      # ISO가 아닌 시각·시간대 없는 시각
    m = gate.measure(lines(1000) + junk)
    assert (m["requests"], m["skipped"]) == (1000, 7) and "감사 줄이 아닌 7줄" in gate.report(m)[0]
    # 같은 파일을 두 번 줘도 분모가 부풀려지지 않는다, 파일 순서가 뒤바뀌어도 같다
    once, twice = gate.measure(lines(600)), gate.measure(lines(600) + lines(600))
    assert (twice["requests"], twice["duplicates"]) == (600, 600) and gate.report(twice)[1] is False and "되풀이된 600줄" in gate.report(twice)[0]
    assert gate.measure(list(reversed(lines(600)))) == once


def test_q1_only_the_mask_window_counts_and_it_must_have_no_empty_days():
    """D-132 §2: 'mask로 돈 연속 14일'. 관측 2주 + mask 1시간, 중간에 빈 날이 있는 로그는 통과가 아니다(리뷰)."""
    gate = _gate()
    observe = [json.dumps({**json.loads(x), "request_id": f"o{i}", "detectors": [{"detector": "pii"}], "pii_issued": 0}) for i, x in enumerate(lines(1500, days=14.0))]
    hour = [json.dumps({**json.loads(x), "ts": (T0 + timedelta(days=14, seconds=3 * i)).isoformat(timespec="milliseconds")}) for i, x in enumerate(lines(1100))]
    m = gate.measure(observe + hour)
    text, ok = gate.report(m)
    assert (m["requests"], m["before_mask"]) == (1100, 1500) and m["days"] < 0.1 and not ok and "기간 부족" in text and "관측 구간" in text
    # 하루치 1,000줄 + 13일 공백 + 60줄
    burst = [json.dumps({**json.loads(x), "ts": (T0 + timedelta(seconds=i)).isoformat(timespec="milliseconds")}) for i, x in enumerate(lines(1000))]
    tail = [json.dumps({**json.loads(x), "request_id": f"t{i}", "ts": (T0 + timedelta(days=14, minutes=i)).isoformat(timespec="milliseconds")}) for i, x in enumerate(lines(60))]
    m = gate.measure(burst + tail)
    text, ok = gate.report(m)
    assert m["days"] >= 14 and m["empty_days"] == 13 and not ok and "빈 날 13일" in text
    assert gate.report(gate.measure(lines(2000, days=15.0)))[1] is True


# ---------- Q2 실제 감사 로그 ----------

def test_q2_cli_reads_a_real_audit_log(make_stack):
    stack = make_stack(GATEWAY_DETECTORS="pii_mask")       # 마스킹 게이트웨이 + 스텁 상류
    url = f"{stack.gateway}/v1/chat/completions"
    for text in ("제 번호는 010-2345-6789입니다", "연차는 며칠인가요?"):
        assert httpx.post(url, json={"model": "stub-model", "messages": [{"role": "user", "content": text}]}).status_code == 200
    assert httpx.post(url, content=b"{", headers={"content-type": "application/json"}).status_code == 400
    done = subprocess.run([sys.executable, "scripts/poc_gate.py", str(stack.log_path)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 1 and "요청: 3건" in done.stdout                                     # 3건으로는 판정하지 않는다
    piped = subprocess.run([sys.executable, "scripts/poc_gate.py", "-"], cwd=ROOT, input=stack.log_path.read_bytes() + b"\xff broken\n", capture_output=True)
    assert piped.returncode == 1 and "요청: 3건".encode() in piped.stdout                         # 표준 입력, 깨진 바이트가 있어도
    assert "| 0 / 1 = 0.000% | 판정 불가 |" in done.stdout and "| 0 / 3 = 0.000% | 판정 불가 |" in done.stdout
    assert "010-2345-6789" not in done.stdout                                                     # 건수만 낸다
    assert subprocess.run([sys.executable, "scripts/poc_gate.py"], cwd=ROOT, capture_output=True, text=True).returncode == 2

    good = stack.log_path.with_name("two-weeks.jsonl")
    good.write_text("\n".join(lines(1200)) + "\n", encoding="utf-8")
    done = subprocess.run([sys.executable, "scripts/poc_gate.py", str(good)], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0 and "종합: **통과**" in done.stdout


# ---------- Q3 가격·계약 초안 ----------

def test_q3_pricing_draft_keeps_the_decided_principles():
    doc = (ROOT / "docs" / "pricing.md").read_text(encoding="utf-8")
    assert "초안" in doc.split("\n## ")[0]                                                        # 머리에서 초안임을 밝힌다
    for phrase in ("Apache-2.0", "배포 단위", "좌석·토큰", "자체 호스팅", "추정", "scripts/poc_gate.py"):
        assert phrase in doc, phrase
    for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", doc):
        assert target.startswith("https://") or (ROOT / "docs" / target).resolve().exists(), target
    for readme in ("README.md", "README.en.md"):
        assert "docs/pricing.md" in (ROOT / readme).read_text(encoding="utf-8")
