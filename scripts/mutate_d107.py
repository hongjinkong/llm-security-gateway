#!/usr/bin/env python3
"""D-107 제품 전환의 변이 검사 — 설계의 핵심을 하나씩 되돌렸을 때 tests/test_d107_*.py가 잡는지 센다.

`scripts/mutate_d102.py`와 같은 방식이고 실행 도구(run·outcome)도 거기서 가져온다. **임시 복사본만 바꾼다.**

  결함 복원   설계를 되돌린다 → 지정 테스트가 실패해야 한다
  무해 변경   뜻이 같은 변경 → 지정 테스트가 그대로 통과해야 한다

사용: python3 scripts/mutate_d107.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mutate_d102 import outcome, run  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN, AUTH, VAULT, AUDIT = "gateway/main.py", "gateway/auth.py", "gateway/vault.py", "gateway/audit.py"
INJ, STREAM, MSG = "gateway/detectors/injection.py", "gateway/streaming.py", "gateway/api/anthropic.py"
T_AUTH, T_SUR, T_API, T_OPS, T_STREAM = ("tests/test_d107_auth.py", "tests/test_d107_surrogate.py", "tests/test_d107_api.py",
                                        "tests/test_d107_ops.py", "tests/test_streaming.py")

# (id, 종류, 설명, 파일, 기존, 변이, 돌릴 테스트 노드)
MUTATIONS = [
    ("A1", "결함 복원", "틀린 키를 통과시킨다(인증 없음)", MAIN,
     "    if auth.enabled and request.state.client is None:", "    if False:",
     [f"{T_AUTH}::test_a1_missing_or_wrong_key_is_401_without_reading_or_relaying[headers1]"]),
    ("A2", "결함 복원", "상류 키로 바꾸지 않고 클라이언트 인증 헤더를 그대로 넘긴다", AUTH,
     "        kept = [(k, v) for k, v in pairs if k.lower() not in AUTH_HEADERS]", "        return list(pairs)",
     [f"{T_AUTH}::test_a2_upstream_sees_the_upstream_key_never_the_client_key", f"{T_AUTH}::test_upstream_headers_swap_by_path"]),
    ("A3", "결함 복원", "401을 본문을 읽은 뒤에 낸다(413이 먼저 난다)", MAIN,
     "    if auth.enabled and request.state.client is None:",
     "    body, size = await _read_body(request)\n    if body is None:\n        return error_format_for(request.url.path).error("
     "413, 'too large', 'invalid_request_error', 'request_too_large')\n    if auth.enabled and request.state.client is None:",
     [f"{T_AUTH}::test_a1_missing_or_wrong_key_is_401_without_reading_or_relaying[headers0]"]),
    ("A4", "결함 복원", "응답 뒤 볼트를 버리지 않는다(요청 단위 격리 붕괴)", MAIN,
     "        if not request.state.streaming:\n            await chain.release(session)",
     "        if False:\n            await chain.release(session)",
     ["tests/test_vault.py::test_gateway_releases_every_request_session"]),
    ("B1", "결함 복원", "대체값을 원문과 같게 둔다(마스킹 없음)", VAULT,
     "                if token != value and nk not in taken and nk != norm_key(kind, value):",
     "                token = value\n                if True:",
     [f"{T_SUR}::test_b1_surrogate_never_collides_with_values_already_in_the_request",
      f"{T_AUTH}::test_a4_guessed_session_id_cannot_restore_another_requests_value"]),
    ("B2", "결함 복원", "관대한 복원을 끈다(숫자열이 아니라 글자 그대로 찾는다)", VAULT,
     "        return digits(text)", "        return text",
     [f"{T_SUR}::test_b2_phone_restores_whatever_separator_the_model_uses[spaces]"]),
    ("B3", "결함 복원", "채널 구분 없이 꼬리를 하나로 보류한다", STREAM,
     '            restored, n = self._restore(self._pending.pop(channel, "") + text)',
     '            channel = "all"; restored, n = self._restore(self._pending.pop(channel, "") + text)',
     [f"{T_STREAM}::test_b4_channels_hold_independently"]),
    ("C1", "결함 복원", "Anthropic content_block_stop 앞에서 꼬리를 비우지 않는다", MSG,
     '        if t == "content_block_stop":\n            idx = f"b{obj.get(\'index\', 0)}"\n            return lambda ch: ch == idx',
     '        if t == "content_block_stop":\n            return None',
     [f"{T_API}::test_c2_messages_streaming_restores_text_and_tool_input_per_block"]),
    ("D1", "결함 복원", "observe 모드가 막는다", INJ,
     '            return Verdict.allow(self.name, **({"rules": [h.as_dict() for h in hits], "would_block": True} if hits else {}))',
     '            return self._verdict(hits)',
     [f"{T_OPS}::test_d1_defaults_are_observe_and_mask"]),
    ("E1", "결함 복원", "429 뒤에도 상류를 부른다(레이트리밋 무시)", MAIN,
     "    if not ok:\n        request.state.upstream_error = \"rate_limited\"", "    if False:\n        request.state.upstream_error = \"rate_limited\"",
     [f"{T_OPS}::test_e3_over_the_limit_is_429_without_upstream"]),
    ("E2", "결함 복원", "로그 회전을 끈다", AUDIT,
     "            self._handler = logging.handlers.RotatingFileHandler(\n                self.path, maxBytes=max_bytes, backupCount=backups, encoding=\"utf-8\")",
     "            self._handler = logging.FileHandler(self.path, encoding=\"utf-8\")",
     [f"{T_OPS}::test_e1_file_log_rotates_at_max_bytes"]),
    ("P1", "무해 변경", "401 문구만 바꾼다", MAIN,
     '"invalid or missing API key"', '"missing or invalid API key"',
     [f"{T_AUTH}::test_a1_missing_or_wrong_key_is_401_without_reading_or_relaying"]),
]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="d107-mutations-") as tmp:
        root = pathlib.Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        for d in ("gateway", "tests"):
            shutil.copytree(ROOT / d, root / d, ignore=ignore)

        all_tests = sorted({t.split("::")[0] for _, _, _, _, _, _, tests in MUTATIONS for t in tests})
        code, report, out = run(root, all_tests)
        if code != 0:
            print("기준선 실패\n" + out)
            return 1
        print(f"기준선: {outcome(report)[0]} passed ({', '.join(all_tests)})", flush=True)

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
