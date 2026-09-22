#!/usr/bin/env python3
"""D-067 변이 8종 — 2026-09-22 외부 검토로 재현된 게이트웨이 결함 3건의 수정을 검증한다.

`scripts/mutate_canary.py`·`mutate_cluster_ci.py`와 같은 방식이다.
**임시 복사본만 바꾼다.** 원본 코드는 건드리지 않으므로 중간에 죽어도 되돌릴 것이 없다.

무엇을 확인하나 — "고쳤다"가 아니라 "고친 것이 풀리면 테스트가 잡는다"이다.
세 결함 다 기존 테스트가 통과한 채로 존재했다. 특히 볼트 TTL은 **테스트가 있었는데도**
못 잡았다(`session_count`를 읽는 그 접근이 정리를 유발해 복원 경로를 안 지났다).
그래서 이번 수정에는 변이 검사를 붙인다.

사용: python3 scripts/mutate_audit_vault.py
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ["tests/test_vault.py", "tests/test_audit_log.py"]

V = "gateway/vault.py"
M = "gateway/main.py"

MUTATIONS = [
    # ---- 1. 볼트 만료 (복원 경로) --------------------------------------
    (V, "M1 복원 경로의 만료 정리를 없앤다 (결함 복원)",
     "        self._purge_expired()\n        entry = self._sessions.get(session)\n"
     "        if entry is None:\n            return text, 0",
     "        entry = self._sessions.get(session)\n"
     "        if entry is None:\n            return text, 0",
     "tests/test_vault.py::test_만료된_세션은_복원되지_않는다"),
    (V, "M2 살아 있는 세션까지 복원을 막는다 (과잉 수정)",
     "        entry = self._sessions.get(session)\n"
     "        if entry is None:\n            return text, 0",
     "        entry = None\n"
     "        if entry is None:\n            return text, 0",
     "tests/test_vault.py::test_만료_전에는_복원된다"),

    # ---- 2. 예외 요청의 감사 로그 ---------------------------------------
    (M, "M3 예외 시 기록을 건너뛴다 (결함 복원)",
     "            if not request.url.path.startswith(INTERNAL_PREFIX):",
     "            if False:",
     "tests/test_audit_log.py::test_예외로_끝난_요청도_감사_로그_1줄"),
    (M, "M4 예외 메시지까지 남긴다",
     "                    error=type(exc).__name__))",
     "                    error=str(exc) or type(exc).__name__))",
     "tests/test_audit_log.py::test_예외는_타입_이름만_남긴다"),
    (M, "M5 예외 줄의 status를 200으로",
     '"status": response.status_code if response is not None else 500,',
     '"status": response.status_code if response is not None else 200,',
     "tests/test_audit_log.py::test_예외로_끝난_요청도_감사_로그_1줄"),
    (M, "M6 부르지도 못한 타겟 호출에 시간을 붙인다",
     '"upstream_ms": None if upstream_ms is None else round(upstream_ms, 2),',
     '"upstream_ms": round(upstream_ms or 0.0, 2),',
     "tests/test_audit_log.py::test_타겟을_못_불렀으면_upstream_ms가_없다"),

    # ---- 3. 쿼리 문자열 --------------------------------------------------
    (M, "M7 쿼리 원문을 그대로 남긴다 (결함 복원)",
     '"query_keys": _query_keys(request.url.query),',
     '"query_keys": request.url.query,',
     "tests/test_audit_log.py::test_쿼리_값은_로그에_남지_않는다"),
    (M, "M8 키 이름과 값을 함께 남긴다",
     '        name = unquote(part.split("=", 1)[0])',
     "        name = unquote(part)",
     "tests/test_audit_log.py::test_쿼리_값은_로그에_남지_않는다"),
]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="audit-vault-mutations-") as tmp:
        root = pathlib.Path(tmp)
        for d in ("gateway", "tests"):
            shutil.copytree(ROOT / d, root / d,
                            ignore=shutil.ignore_patterns("__pycache__"))
        originals = {f: (root / f).read_text(encoding="utf-8") for f in (V, M)}

        def run(nodes):
            report = root / "pytest.xml"
            report.unlink(missing_ok=True)
            p = subprocess.run([sys.executable, "-B", "-m", "pytest", *nodes,
                                "-q", "--tb=short", f"--junitxml={report}"],
                               cwd=root, capture_output=True, text=True)
            if not report.exists():
                raise RuntimeError(p.stdout + p.stderr)
            return p, ET.parse(report).getroot()

        p, report = run(TESTS)
        if p.returncode != 0:
            print(p.stdout + p.stderr)
            return 1
        print(f"기준선: {len(report.findall('.//testcase'))} passed", flush=True)

        caught_n = 0
        for path, name, old, new, test in MUTATIONS:
            src = originals[path]
            if src.count(old) != 1:
                raise RuntimeError(f"{name}: 앵커가 유일하지 않다 ({src.count(old)}회)")
            mutated = src.replace(old, new)
            compile(mutated, path, "exec")
            (root / path).write_text(mutated, encoding="utf-8")
            p, report = run([test])
            failures = report.findall(".//failure")
            caught = (p.returncode == 1 and len(failures) == 1
                      and not report.findall(".//error")
                      and ("AssertionError" in failures[0].get("message", "")
                           or failures[0].get("message", "").startswith("assert ")))
            caught_n += caught
            print(f"{name}: {'검출' if caught else '★ 검증 실패'} — {test.split('::')[-1]}",
                  flush=True)
            if not caught:
                print(p.stdout + p.stderr)
                return 1
            (root / path).write_text(src, encoding="utf-8")

        print(f"{caught_n}/{len(MUTATIONS)} 검출. 원본 파일 무수정.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
