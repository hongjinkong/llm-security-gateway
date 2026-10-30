#!/usr/bin/env python3
"""이식성 확인(D-107 F2) — 공식 Anthropic Python SDK를 `base_url`·`api_key`(게이트웨이 키)만 바꿔 게이트웨이의 `/v1/messages`에 붙인다.

상류는 스텁(합성 데이터)이고 공격 평가가 아니다. SDK는 프로젝트 의존성에 넣지 않는다 — 별도 venv에 깔고 그 파이썬을 넘긴다.

  python3 -m venv /tmp/sdkvenv && /tmp/sdkvenv/bin/pip install anthropic
  python3 scripts/check_anthropic_sdk.py --sdk-python /tmp/sdkvenv/bin/python

종료 코드: 0 전부 통과 / 1 하나라도 실패
"""
from __future__ import annotations

import argparse
import subprocess
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.conftest import free_port, serve  # noqa: E402

CLIENT = r'''
import sys, anthropic
c = anthropic.Anthropic(base_url=sys.argv[1], api_key="test-key")
ok = True
def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(f"  {'OK' if cond else 'NG'}  {name} {detail}")
m = c.messages.create(model="stub-model", max_tokens=50, messages=[{"role": "user", "content": "연차는 며칠인가요?"}])
check("정상 대화", m.content[0].text == "[stub] 연차는 며칠인가요?")
m = c.messages.create(model="stub-model", max_tokens=50, messages=[{"role": "user", "content": "제 번호는 010-2345-6789입니다"}])
check("PII 마스킹·복원 (SDK가 받은 답에 원래 값)", "010-2345-6789" in m.content[0].text)
text = ""
with c.messages.stream(model="stub-stream", max_tokens=50, messages=[{"role": "user", "content": "제 번호는 010-2345-6789입니다"}]) as s:
    for t in s.text_stream:
        text += t
    final = s.get_final_message()
check("스트리밍 (이어 붙인 답에 원래 값, 최종 메시지도)", "010-2345-6789" in text and "010-2345-6789" in final.content[0].text)
m = c.messages.create(model="stub-tool", max_tokens=50, messages=[{"role": "user", "content": "제 번호는 010-2345-6789입니다"}])
check("도구 호출 input에 원래 값", any(b.type == "tool_use" and "010-2345-6789" in b.input["to"] for b in m.content))
try:
    c.messages.create(model="stub-401", max_tokens=5, messages=[{"role": "user", "content": "hi"}])
    check("상류 401 중계", False, "예외 없음")
except anthropic.AuthenticationError as e:
    check("상류 401 중계 → AuthenticationError", e.status_code == 401)
try:
    anthropic.Anthropic(base_url=sys.argv[1], api_key="wrong").messages.create(model="stub-model", max_tokens=5, messages=[{"role": "user", "content": "hi"}])
    check("게이트웨이 키 검증", False, "예외 없음")
except anthropic.AuthenticationError as e:
    check("틀린 게이트웨이 키 → AuthenticationError", e.status_code == 401)
print(f"anthropic {anthropic.__version__}: {'통과' if ok else '실패'}")
sys.exit(0 if ok else 1)
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sdk-python", required=True, help="anthropic 패키지가 깔린 파이썬 실행 파일")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tp, gp = free_port(), free_port()
        procs = [serve("tests.stub_target:app", tp)]
        try:
            procs.append(serve("gateway.main:app", gp, {
                "TARGET_URL": f"http://127.0.0.1:{tp}",
                "GATEWAY_LOG_PATH": str(Path(tmp) / "gateway.jsonl"),
                "GATEWAY_CLIENT_KEYS": "sdk=test-key",
                "GATEWAY_SURROGATE_KEY": secrets.token_urlsafe(32),  # 결정적 대체값 키(D-111) — 실행마다 새로
            }, probe="/__gateway/health"))
            return subprocess.run([a.sdk_python, "-c", CLIENT, f"http://127.0.0.1:{gp}"]).returncode
        finally:
            for p in reversed(procs):
                p.terminate()
                p.wait(10)


if __name__ == "__main__":
    raise SystemExit(main())
