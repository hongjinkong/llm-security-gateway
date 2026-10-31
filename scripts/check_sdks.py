#!/usr/bin/env python3
"""한 게이트웨이에 두 SDK(D-119 G7) — 스텁 둘(OpenAI 쪽·Anthropic 쪽)과, 설정 파일로 Messages만 Anthropic 쪽 스텁에 보내는 게이트웨이 하나를 띄우고
OpenAI·Anthropic SDK 점검(scripts/check_openai_sdk.py·check_anthropic_sdk.py)을 그 게이트웨이에 함께 붙인다. 상류는 스텁(합성 데이터)이다.

  python3 scripts/check_sdks.py --openai-python /tmp/sdkvenv/bin/python --anthropic-python /tmp/sdkvenv/bin/python

끝에 두 스텁이 받은 경로를 대조해 요청이 API별 상류로 갈렸는지 본다. 종료 코드: 0 둘 다 통과·상류 분리 확인 / 1 그 밖
"""
from __future__ import annotations

import argparse
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from tests.conftest import free_port, serve  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--openai-python", required=True, help="openai 패키지가 깔린 파이썬 실행 파일")
    ap.add_argument("--anthropic-python", required=True, help="anthropic 패키지가 깔린 파이썬 실행 파일")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        oai, ant, gp = free_port(), free_port(), free_port()
        procs = [serve("tests.stub_target:app", oai), serve("tests.stub_target:app", ant)]
        try:
            config = Path(tmp) / "gateway.toml"
            config.write_text(f'[upstreams.messages]\nbase_url = "http://127.0.0.1:{ant}"\n', encoding="utf-8")
            procs.append(serve("gateway.main:app", gp, {
                "TARGET_URL": f"http://127.0.0.1:{oai}",          # Chat·Responses·(헤더 없는) /v1/models
                "GATEWAY_CONFIG": str(config),
                "GATEWAY_LOG_PATH": str(Path(tmp) / "gateway.jsonl"),
                "GATEWAY_INJECTION": "block",                     # OpenAI 점검의 차단 항목 — Anthropic 점검에는 공격 문장이 없다
                "GATEWAY_CLIENT_KEYS": "sdk=test-key",
                "GATEWAY_SURROGATE_KEY": secrets.token_urlsafe(32),
            }, probe="/__gateway/health"))
            gateway = f"http://127.0.0.1:{gp}"
            codes = [subprocess.run([sys.executable, str(HERE / script), "--sdk-python", python, "--gateway", gateway]).returncode
                     for script, python in (("check_openai_sdk.py", a.openai_python), ("check_anthropic_sdk.py", a.anthropic_python))]
            paths = {port: {path for _, path in httpx.get(f"http://127.0.0.1:{port}/__stub/hits").json()["hits"] if path != "/"}   # `/`는 기동 확인
                     for port in (oai, ant)}
            split = ("/v1/chat/completions" in paths[oai] and "/v1/responses" in paths[oai] and "/v1/messages" not in paths[oai]
                     and paths[ant] == {"/v1/messages"})
            print(f"상류 분리: {'확인' if split else '실패'} — OpenAI 쪽 {sorted(paths[oai])}, Anthropic 쪽 {sorted(paths[ant])}")
            ok = all(code == 0 for code in codes) and split
            print("한 게이트웨이에 두 SDK:", "통과" if ok else "실패")
            return 0 if ok else 1
        finally:
            for p in reversed(procs):
                p.terminate()
                p.wait(10)


if __name__ == "__main__":
    raise SystemExit(main())
