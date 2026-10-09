#!/usr/bin/env python3
"""D-099 묶음의 변이 검사 — 고친 것을 되돌리거나 지나치게 고치면 테스트가 잡는지 본다.

`scripts/mutate_openai_gateway.py`와 같은 방식이다. **임시 복사본만 바꾼다.** 원본은 건드리지 않는다.
변이마다 지정한 테스트만 돌린다(시간 측정 테스트는 결함 상태에서 수 초~수십 초 걸린다).

  결함 복원        고친 결함을 되돌린다 → 지정 테스트가 실패해야 한다
  과잉 수정·부작용  고친 범위를 넘겨 기능을 망가뜨린다 → 지정 테스트가 실패해야 한다
  무해 변경        뜻이 같은 변경 → 지정 테스트가 그대로 통과해야 한다

사용: python3 scripts/mutate_d099.py
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
PII = "gateway/detectors/pii.py"
INJ = "gateway/detectors/injection.py"
MAIN = "gateway/main.py"

T_PII = "tests/test_pii.py"
T_SCOPE = "tests/test_inspection_scope.py"
T_VAULT = "tests/test_vault.py"
T_PASS = "tests/test_passthrough.py"
T_OAI = "tests/test_openai_gateway.py"

# (id, 종류, 설명, 파일, 기존, 변이, 돌릴 테스트 노드)
MUTATIONS = [
    ("D1", "결함 복원", "이메일 로컬 파트 길이 상한을 없앤다(제곱 시간)", PII,
     "[A-Za-z0-9._%+\\-]{1,64}@", "[A-Za-z0-9._%+\\-]+@",
     [f"{T_PII}::test_scan_time_is_linear_on_long_inputs[alnum]"]),
    ("D2", "결함 복원", "자격 증명을 탐지 종류에서 뺀다", PII,
     'ALL_KINDS = ("rrn", "card", "phone", "email", "secret")',
     'ALL_KINDS = ("rrn", "card", "phone", "email")',
     [f"{T_PII}::test_credential_is_masked_and_restored_in_openai_path",
      f"{T_OAI}::test_credential_does_not_reach_upstream_and_returns_to_user"]),
    ("O1", "과잉 수정·부작용", "개인 키 본문이 큰따옴표를 넘어 JSON 구조까지 먹는다", PII,
     "(?:[^-\"]|-(?!----END))", "(?:[^-]|-(?!----END))",
     [f"{T_PII}::test_pem_without_end_marker_stops_at_quote"]),
    ("D3", "결함 복원", "(C)가 이력까지 이번 턴으로 본다(세션 오염 되살림)", INJ,
     "for m in messages[start:] if m[\"role\"] in INJECTION_ROLES",
     "for m in messages if m[\"role\"] in INJECTION_ROLES",
     [f"{T_SCOPE}::test_turn_이력의_막힌_정상_질문은_가려지고_다음_질문은_상류로_간다",
      f"{T_SCOPE}::test_turn_이력_기한_없이_막던_요청도_상류로_간다"]),
    ("D4", "결함 복원", "(C)가 이력의 걸린 턴을 가리지 않는다", INJ,
     "                _redact(m)\n", "                pass\n",
     [f"{T_SCOPE}::test_turn_이력의_막힌_정상_질문은_가려지고_다음_질문은_상류로_간다"]),
    ("O2", "과잉 수정·부작용", "(C)가 이번 턴의 tool을 보지 않는다(간접 인젝션 통과)", INJ,
     "for m in messages[start:] if m[\"role\"] in INJECTION_ROLES",
     "for m in messages[start:] if m[\"role\"] == \"user\"",
     [f"{T_SCOPE}::test_turn_마지막_user_뒤의_tool은_이번_턴이다"]),
    ("D5", "결함 복원", "요청 단위 세션을 응답 뒤에 버리지 않는다", MAIN,
     "        if session == request.state.request_id:\n            await chain.release(session)",
     "        if False:\n            await chain.release(session)",
     [f"{T_VAULT}::test_gateway_releases_request_scoped_session_but_keeps_client_session"]),
    ("O3", "과잉 수정·부작용", "클라이언트 세션까지 버린다(다음 턴 복원 실패)", MAIN,
     "        if session == request.state.request_id:\n            await chain.release(session)",
     "        if True:\n            await chain.release(session)",
     [f"{T_VAULT}::test_gateway_releases_request_scoped_session_but_keeps_client_session"]),
    ("D6", "결함 복원", "본문 크기 상한을 없앤다", MAIN,
     "    return (b\"\".join(chunks) if size <= MAX_BODY_BYTES else None), size",
     "    return b\"\".join(chunks), size",
     [f"{T_PASS}::test_over_limit_is_413_and_never_reaches_target",
      f"{T_PASS}::test_over_limit_without_content_length_is_413"]),
    ("P1", "무해 변경", "가림 문구만 바꾼다", INJ,
     'REDACTED_TURN = "[보안 정책에 의해 가려진 이전 메시지]"',
     'REDACTED_TURN = "[이전 메시지는 보안 정책으로 가려졌습니다]"',
     [T_SCOPE]),
]


def run(root: pathlib.Path, nodes: list[str]) -> tuple[int, ET.Element, str]:
    report = root / "mutation-report.xml"
    report.unlink(missing_ok=True)
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("GATEWAY_DETECTORS", None)
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider",
         "--tb=line", f"--junitxml={report}"],
        cwd=root, capture_output=True, text=True, env=env,
    )
    if not report.exists():
        raise RuntimeError("pytest가 junit을 만들지 않았다\n" + proc.stdout + proc.stderr)
    return proc.returncode, ET.parse(report).getroot(), proc.stdout + proc.stderr


def outcome(report: ET.Element) -> tuple[int, int, list[str]]:
    cases = list(report.iter("testcase"))
    failed = sum(case.find("failure") is not None for case in cases)
    other = [f"{c.get('name')}: {tag}" for c in cases for tag in ("error", "skipped")
             if c.find(tag) is not None]
    return len(cases), failed, other


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="d099-mutations-") as tmp:
        root = pathlib.Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        for d in ("gateway", "tests", "eval"):
            shutil.copytree(ROOT / d, root / d, ignore=ignore)

        nodes = sorted({n.split("::")[0] for *_, ns in MUTATIONS for n in ns})
        code, report, out = run(root, nodes)
        if code != 0:
            print("기준선 실패\n" + out)
            return 1
        print(f"기준선: {outcome(report)[0]} passed ({', '.join(nodes)})", flush=True)

        missed: list[str] = []
        for mid, kind, desc, target, old, new, tests in MUTATIONS:
            path = root / target
            original = path.read_text(encoding="utf-8")
            if original.count(old) != 1:
                raise RuntimeError(f"{mid}: 앵커가 유일하지 않다 ({original.count(old)}회)")
            mutated = original.replace(old, new)
            compile(mutated, target, "exec")
            path.write_text(mutated, encoding="utf-8")
            try:
                code, report, _ = run(root, tests)
            finally:
                path.write_text(original, encoding="utf-8")
            count, failed, other = outcome(report)
            if kind == "무해 변경":
                ok = code == 0 and failed == 0 and not other
            else:
                ok = code == 1 and failed == len(tests) == count and not other
            print(f"{mid} [{kind}] {desc}: {'통과' if ok else '★ 검증 실패'} "
                  f"(테스트 {count}개, 실패 {failed}개{', ' + '; '.join(other) if other else ''})", flush=True)
            if not ok:
                missed.append(mid)

    print(f"결과: {len(MUTATIONS) - len(missed)}/{len(MUTATIONS)} 통과. 원본 파일 무수정.")
    if missed:
        print("검증 실패: " + ", ".join(missed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
