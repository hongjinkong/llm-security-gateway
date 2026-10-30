#!/usr/bin/env python3
"""D-102 묶음의 변이 검사 — 고친 결함 10건을 하나씩 되돌렸을 때 tests/test_d102_fixes.py가 잡는지 센다.

`scripts/mutate_d099.py`와 같은 방식이다. **임시 복사본만 바꾼다.** 원본은 건드리지 않는다.

  결함 복원   고친 결함을 되돌린다 → 지정 테스트가 실패해야 한다
  무해 변경   뜻이 같은 변경 → 지정 테스트가 그대로 통과해야 한다

사용: python3 scripts/mutate_d102.py
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
PAT = "gateway/detectors/patterns.py"          # D-107 B: 탐지 패턴·겹침 해소는 patterns.py로 옮겨 갔다
OAI = "gateway/openai_api.py"
CHAT = "gateway/api/chat.py"                   # D-107 C: 도구 호출 인자 참조는 어댑터가 준다
MAIN = "gateway/main.py"
T = "tests/test_d102_fixes.py"

MERGE_LINEAR = '''    out: list[Finding] = []
    i = 0
    for c in cands:
        while i < len(taken) and taken[i].end <= c.start:
            out.append(taken[i])
            i += 1
        if i < len(taken) and taken[i].start < c.end:
            continue          # 더 높은 우선순위가 이미 차지한 자리
        out.append(c)
    out.extend(taken[i:])
    return out
'''
MERGE_QUADRATIC = '''    out = list(taken)
    for c in cands:
        if any(c.start < t.end and t.start < c.end for t in out):
            continue
        out.append(c)
    return sorted(out, key=lambda f: f.start)
'''
REPLACE_JOIN = '''    out: list[str] = []
    pos = 0
    for f, token in zip(found, tokens):
        out.append(text[pos:f.start])
        out.append(token)
        pos = f.end
    out.append(text[pos:])
    return "".join(out)
'''
REPLACE_COPY = '''    masked = text
    for f, token in zip(reversed(found), reversed(tokens)):
        masked = masked[:f.start] + token + masked[f.end:]
    return masked
'''

# (id, 종류, 설명, 파일, 기존, 변이, 돌릴 테스트 노드)
MUTATIONS = [
    ("D1", "결함 복원", "#1 겹침 해소를 건수의 제곱으로 되돌린다", PAT, MERGE_LINEAR, MERGE_QUADRATIC,
     [f"{T}::test_find_all_is_linear_in_hit_count"]),
    ("D2", "결함 복원", "#1 치환을 건마다 본문 전체 복사로 되돌린다", PII, REPLACE_JOIN, REPLACE_COPY,
     [f"{T}::test_masking_many_hits_is_fast_and_audit_meta_is_capped"]),
    ("D3", "결함 복원", "#1 감사 메타의 탐지 위치 상한을 없앤다", PII,
     "FINDINGS_LIMIT = 100\n", "FINDINGS_LIMIT = 10**9\n",
     [f"{T}::test_masking_many_hits_is_fast_and_audit_meta_is_capped"]),
    ("D4", "결함 복원", "#2 accept-encoding을 상류로 그대로 넘긴다", MAIN,
     '_DROP_REQ = frozenset({"host", "content-length", "accept-encoding"})',
     '_DROP_REQ = frozenset({"host", "content-length"})',
     [f"{T}::test_client_accept_encoding_is_not_forwarded"]),
    ("D5", "결함 복원", "#3 tool_calls 인자를 가리지 않는다", CHAT,
     '            calls = m.get("tool_calls")\n', '            calls = None\n',
     [f"{T}::test_tool_call_arguments_are_masked_on_the_next_turn"]),
    # D6(#4 PEM 본문이 역슬래시를 홀로 먹는다)는 D-107 B에서 뺐다 — 대체값이 원문과 같은 길이로 역슬래시 짝을 보존하므로
    # 그 변이로는 JSON이 깨지지 않는다(토큰 시절에는 역슬래시가 통째로 사라져 깨졌다). 정규식은 그대로 둔다(짝이 맞는 쪽이 옳다).
    ("D7", "결함 복원", "#5 옛 경로가 sessionId 값까지 가린다", PII,
     "        found = _outside(found, _session_spans(text, insp.body))   # 세션 키는 가리지 않는다(D-102)\n",
     "        found = found\n",
     [f"{T}::test_legacy_session_id_is_not_masked"]),
    ("D8", "결함 복원", "#6 헤더를 dict로 모아 같은 이름을 합친다", MAIN,
     "    return [(k, v) for k, v in pairs\n            if k.lower() not in HOP_BY_HOP and k.lower() not in drop]",
     "    return list({k: v for k, v in pairs\n            if k.lower() not in HOP_BY_HOP and k.lower() not in drop}.items())",
     [f"{T}::test_multi_value_headers_survive_both_ways"]),
    ("D9", "결함 복원", "#7 OPTIONS도 Chat Completions 본문으로 파싱한다", MAIN,
     '    adapter = adapter_for(request.url.path) if request.method == "POST" else None',
     '    adapter = adapter_for(request.url.path)',
     [f"{T}::test_options_on_chat_path_is_relayed_not_rejected"]),
    ("D10", "결함 복원", '#8 "stream": null을 거부한다', OAI,
     "    if stream is None:\n        stream = False", "    if stream is None:\n        pass",
     [f"{T}::test_stream_null_is_accepted"]),
    ("D11", "결함 복원", "#9 500 응답에 요청 ID를 붙이지 않는다", MAIN,
     'headers={"X-Gateway-Request-Id": rid} if rid else None', "headers=None",
     [f"{T}::test_unhandled_error_response_carries_request_id"]),
    ("D12", "결함 복원", "#10 상류의 date·server를 그대로 넘긴다", MAIN,
     '_DROP_RES = frozenset({"content-length", "content-encoding", "date", "server"})',
     '_DROP_RES = frozenset({"content-length", "content-encoding"})',
     [f"{T}::test_upstream_date_and_server_headers_are_not_duplicated"]),
    ("P1", "무해 변경", "500 본문의 문구만 바꾼다", MAIN,
     '"message": "internal gateway error"', '"message": "gateway internal error"', [T]),
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
    with tempfile.TemporaryDirectory(prefix="d102-mutations-") as tmp:
        root = pathlib.Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        for d in ("gateway", "tests", "eval"):
            shutil.copytree(ROOT / d, root / d, ignore=ignore)

        code, report, out = run(root, [T])
        if code != 0:
            print("기준선 실패\n" + out)
            return 1
        print(f"기준선: {outcome(report)[0]} passed ({T})", flush=True)

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
