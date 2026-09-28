#!/usr/bin/env python3
"""D-081 새 구조 한 팔의 무효 검사 E1·E3·E5. 새 채점 규칙은 없다.

E1 완주: setup 1개(이름·gen·seed 일치), completion 1개, status=2 attempt마다 비어 있지 않은 출력 10개,
         (probe, seq) 중복 없음. 프로브 목록·attempt 수는 프로브마다 달라 여기서 고정하지 않는다.
E3 감사: --audit-from 이후 감사 줄 = 이 팔의 줄. 개수 = garak 출력 수, 전부 /v1/chat/completions·200,
         request_id 유일, none 팔은 차단 0. 두 팔 모두 게이트웨이를 거치므로 1:1이어야 한다(D-081 8절).
E5 비교: --peer가 있으면 (probe, seq) 집합과 프롬프트 해시가 전부 같아야 한다.
E4(N = total_evaluated)는 회수 때 rescore_blocking.py V4가 맡는다.

종료 코드: 0 통과 / 2 무효
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

GENERATIONS = 10
SEED = "20260819"
CHAT_PATH = "/v1/chat/completions"


class Invalid(Exception):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise Invalid(message)


def _rows(path: Path, what: str) -> list[dict]:
    require(path.is_file(), f"{what} 없음: {path}")
    rows = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise Invalid(f"{path}:{no}: JSON 파손: {exc}") from exc
    return rows


def scan_report(path: Path, name: str) -> tuple[dict[tuple[str, int], str], int]:
    """E1. (probe, seq) → 프롬프트 해시, 총 출력 수."""
    setups, completions, prompts, outputs = [], 0, {}, 0
    for row in _rows(path, "report"):
        kind = row.get("entry_type")
        if kind == "start_run setup":
            setups.append(row)
        elif kind == "completion":
            completions += 1
        elif kind == "attempt" and row.get("status") == 2:
            key = (row.get("probe_classname"), row.get("seq"))
            require(key not in prompts, f"{path}: (probe, seq) 중복 {key}")
            outs = row.get("outputs")
            require(isinstance(outs, list) and len(outs) == GENERATIONS,
                    f"{path}: {key} 출력 {len(outs) if isinstance(outs, list) else '없음'}개")
            for o in outs:
                text = o.get("text") if isinstance(o, dict) else o
                require(isinstance(text, str) and bool(text.strip()), f"{path}: {key} 빈 출력")
            payload = json.dumps(row.get("prompt"), ensure_ascii=False, sort_keys=True)
            prompts[key] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            outputs += len(outs)

    require(len(setups) == 1, f"{path}: setup {len(setups)}개")
    setup = setups[0]
    require(setup.get("reporting.report_prefix") == name, f"{path}: report_prefix 불일치")
    require(setup.get("run.generations") == GENERATIONS, f"{path}: gen 불일치")
    require(str(setup.get("run.seed")) == SEED, f"{path}: seed 불일치")
    require(completions == 1, f"{path}: completion {completions}개")
    require(bool(prompts), f"{path}: 완료 attempt 0개")
    return prompts, outputs


def check_audit(path: Path, start: int, outputs: int, arm: str) -> int:
    """E3. 이 팔의 차단 수를 돌려준다."""
    rows = _rows(path, "감사 로그")[start:]
    require(len(rows) == outputs, f"감사 줄 {len(rows)} != garak 출력 {outputs}")
    require(all(r.get("status") == 200 for r in rows), "감사 로그에 200이 아닌 응답이 있다")
    require(all(r.get("path") == CHAT_PATH for r in rows),
            f"감사 로그에 {CHAT_PATH} 아닌 경로가 있다 — 옛 경로로 돌아갔는지 확인")
    ids = [r.get("request_id") for r in rows]
    require(None not in ids and len(set(ids)) == len(ids), "request_id 누락/중복")
    blocked = sum(1 for r in rows if r.get("blocked"))
    require(arm != "none" or blocked == 0, f"none 팔 차단 {blocked}건")
    return blocked


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--arm", choices=("none", "rule"), required=True)
    ap.add_argument("--audit", type=Path, required=True)
    ap.add_argument("--audit-from", type=int, required=True, help="START 직전 감사 로그 줄 수")
    ap.add_argument("--peer", type=Path)
    ap.add_argument("--peer-name")
    a = ap.parse_args(argv)
    try:
        prompts, outputs = scan_report(a.report, a.name)
        print(f"E1 통과: {a.name}, completion 1, attempt {len(prompts)}, 출력 {outputs}")
        blocked = check_audit(a.audit, a.audit_from, outputs, a.arm)
        print(f"E3 통과: {a.name}, 감사 줄 {outputs} = garak 출력, 전부 {CHAT_PATH} 200, 차단 {blocked}")
        if a.peer:
            require(bool(a.peer_name), "--peer-name 필요")
            peer, _ = scan_report(a.peer, a.peer_name)
            require(prompts.keys() == peer.keys(), "두 팔의 (probe, seq) 집합이 다름")
            diff = [k for k in prompts if prompts[k] != peer[k]]
            require(not diff, f"프롬프트 해시 불일치 {len(diff)}개")
            print(f"E5 통과: 두 팔 (probe, seq) {len(prompts)}개와 프롬프트 해시 전부 일치")
        return 0
    except (Invalid, OSError, ValueError, TypeError) as exc:
        print(f"무효: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
