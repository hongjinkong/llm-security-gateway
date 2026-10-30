#!/usr/bin/env python3
"""D-106 스트리밍의 변이 검사 — 설계의 핵심 아홉 가지를 하나씩 되돌렸을 때 tests/test_streaming.py가 잡는지 센다.

`scripts/mutate_d102.py`와 같은 방식이고 실행 도구(run·outcome)도 거기서 가져온다. **임시 복사본만 바꾼다.**

  결함 복원   설계를 되돌린다 → 지정 테스트가 실패해야 한다
  무해 변경   뜻이 같은 변경 → 지정 테스트가 그대로 통과해야 한다

사용: python3 scripts/mutate_d106.py
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mutate_d102 import outcome, run  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
STREAM = "gateway/streaming.py"
MAIN = "gateway/main.py"
T = "tests/test_streaming.py"
S3 = f"{T}::test_s3_tokens_split_across_chunks_are_restored_and_upstream_sees_only_tokens[stub-stream]"

# (id, 종류, 설명, 파일, 기존, 변이, 돌릴 테스트 노드)
MUTATIONS = [
    ("M1", "결함 복원", "조각 끝의 토큰 꼬리를 보류하지 않는다", STREAM,
     '        if not tail or len(tail) > MAX_HOLD:\n            return text, ""',
     '        if True:\n            return text, ""',
     [f"{T}::test_s1_restores_across_any_chunk_and_byte_boundary", S3]),
    ("M2", "결함 복원", "finish 조각에서 보류 꼬리를 버린다", STREAM,
     '            emit, self._pending = text, ""', '            emit, self._pending = content, ""',
     [f"{T}::test_s1_restores_across_any_chunk_and_byte_boundary"]),
    ("M3", "결함 복원", "[DONE] 앞의 합성 조각을 생략한다", STREAM,
     '            prefix = self._synthesized(ending) if self._pending else ""', '            prefix = ""',
     [f"{T}::test_s2_pending_tail_without_finish_chunk_becomes_one_synthesized_chunk"]),
    ("M4", "결함 복원", "UTF-8 증분 디코더 대신 조각마다 따로 디코딩한다", STREAM,
     "        text = self._line + self._decoder.decode(data)",
     '        text = self._line + data.decode("utf-8", errors="replace")',
     [f"{T}::test_s1_restores_across_any_chunk_and_byte_boundary"]),
    ("M5", "결함 복원", "미들웨어가 스트리밍 응답에도 바로 감사 줄을 쓴다(두 줄)", MAIN,
     "    if request.url.path.startswith(INTERNAL_PREFIX) or state.streaming:",
     "    if request.url.path.startswith(INTERNAL_PREFIX):",
     [f"{T}::test_s6_exactly_one_audit_line_written_after_the_stream_ends"]),
    ("M6", "결함 복원", "요청 단위 세션의 볼트를 스트림이 끝나기 전에 버린다", MAIN,
     "        if session == request.state.request_id and not request.state.streaming:",
     "        if session == request.state.request_id:",
     [S3, f"{T}::test_s6_exactly_one_audit_line_written_after_the_stream_ends"]),
    ("M7", "결함 복원", "스트리밍 요청의 차단을 JSON completion으로 돌려준다", MAIN,
     '        if wants_stream:\n            return _blocked_stream(request.state.request_id, chat_request.get("model", "gateway"))\n',
     "",
     [f"{T}::test_s4_blocked_stream_is_one_content_filter_chunk_and_done"]),
    ("M8", "결함 복원", "카나리를 이어 붙인 content가 아니라 내보낸 조각 바이트에서 센다(조각에 걸친 값을 놓친다)", MAIN,
     "    _, steps = await chain.run_response(session, restorer.content_in)",
     "    _, steps = await chain.run_response(session, restorer.out_text)",
     [f"{T}::test_s8_canary_split_across_chunks_is_counted_once"]),
    ("M9", "결함 복원", "내용이 바뀌지 않은 조각도 재직렬화한다", STREAM,
     "        if not isinstance(obj, dict) or not self._restore_chunk(obj):\n            return line + newline",
     "        if not isinstance(obj, dict):\n            return line + newline\n        self._restore_chunk(obj)",
     [f"{T}::test_s5_untouched_chunks_are_byte_identical_to_the_upstream"]),
    ("P1", "무해 변경", "data: 접두사 정규식을 뜻이 같은 꼴로 바꾼다", STREAM,
     'DATA_RE = re.compile(r"data: ?")', 'DATA_RE = re.compile(r"data:[ ]?")', [T]),
]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="d106-mutations-") as tmp:
        root = pathlib.Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache")
        for d in ("gateway", "tests"):
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
