#!/usr/bin/env python3
"""D-094 rule 팔 "이력 전염 차단" 오프라인 대조 — 실제 차단(S1) vs 프롬프트 단독 판정.

등록: DECISIONS.md D-094. 입력은 등록된 표(ARMS·CONTROLS)로 고정한다.
요청 = garak 출력 1개, 순서 = 리포트 status=2 attempt 순서 × 출력 번호(D-094 §2-3).
단독 판정 = `{"messages":[{"role":"user","content":프롬프트}]}`를 현재 `injection_rule`에 넣어 BLOCK인가.

D-039: 프롬프트·출력 원문을 화면이나 파일에 쓰지 않는다. 개수·비율·(probe, seq, 출력 번호)만 낸다.

  .venv/bin/python scripts/d094_alone_vs_actual.py > results/d094_alone_vs_actual.md

종료 코드: 0 대조 완료(수치는 출력에) / 2 입력 오류
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.detectors.base import Action, Inspection  # noqa: E402
from gateway.detectors.injection import InjectionRuleDetector  # noqa: E402
from gateway.openai_api import CHAT_COMPLETIONS_PATH  # noqa: E402
from gateway.version import code_fingerprint  # noqa: E402
from rescore_blocking import DEFAULT_BLOCKED_MESSAGE, is_blocked  # noqa: E402

GENERATIONS = 10
WINDOW = 20        # AnythingLLM 공유 이력 20 (D-084 §1)
MAX_LIST = 20

# (이름, 지위, 리포트, 감사 사본, audit_from) — D-094 §2-5·§3
ARMS = (
    ("oa_pi_20260928_01_rule", "주", "results/oa_pi_20260928_01_rule.report.jsonl",
     "results/audit_oa_pi_20260928_01.jsonl", 13254),
    ("oa_dan_20260930_01_rule", "주", "results/oa_dan_20260930_01_rule.report.jsonl",
     "results/audit_oa_dan_20260930_01.jsonl", 25134),
    ("oa_enc_20261001_01_rule", "주", "results/oa_enc_20261001_01_rule.report.jsonl",
     "results/audit_oa_enc_20261001_01.jsonl", 34454),
    ("oa_dan_20261006_01_rule", "무효 밤 — 보조", "results/oa_dan_20261006_01_rule.report.jsonl",
     "results/audit_oa_dan_20261006_01.jsonl", 43826),
)
# 양성 대조 — v1 구조에서는 게이트웨이가 프롬프트만 봤다 (D-094 §2-6)
CONTROLS = (
    ("pi_rule (v1, D-061)", "results/pi_rule.report.jsonl"),
    ("night_rule_dan (v1, D-056)", "results/night_rule_dan.report.jsonl"),
    ("enc_20260923_01_rule (v1, D-068)", "results/enc_20260923_01_rule.report.jsonl"),
)

DETECTOR = InjectionRuleDetector()


class InputError(Exception):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise InputError(message)


@dataclass(frozen=True)
class Attempt:
    probe: str
    seq: int
    alone: bool               # 프롬프트 단독 판정이 차단인가
    s1: tuple[bool, ...]      # 출력마다 S1 차단인가


@dataclass
class Table:
    a: int = 0    # S1 차단 ∧ 단독 차단
    b: int = 0    # S1 차단 ∧ 단독 통과 — 핵심
    c: int = 0    # S1 통과 ∧ 단독 차단
    d: int = 0    # S1 통과 ∧ 단독 통과
    b_attempts: int = 0
    c_keys: list[tuple[str, int, int]] = field(default_factory=list)


def prompt_text(row: dict) -> str:
    """user turn이 정확히 하나이고 마지막 turn이어야 한다. 오류 문구에 원문을 넣지 않는다."""
    turns = (row.get("prompt") or {}).get("turns") or []
    users = [i for i, t in enumerate(turns) if isinstance(t, dict) and t.get("role") == "user"]
    require(len(users) == 1 and users[0] == len(turns) - 1,
            f"user turn {len(users)}개 / turn {len(turns)}개 — 마지막 user turn 하나가 아니다")
    content = turns[-1].get("content")
    text = content.get("text") if isinstance(content, dict) else None
    require(isinstance(text, str), "user turn 텍스트가 문자열이 아니다")
    return text


def alone_blocked(text: str) -> bool:
    body = json.dumps({"messages": [{"role": "user", "content": text}]}, ensure_ascii=False).encode()
    insp = Inspection(request_id="d094", method="POST", path=CHAT_COMPLETIONS_PATH, headers={}, body=body)
    return asyncio.run(DETECTOR.inspect(insp)).action is Action.BLOCK


def _rows(path: Path, what: str) -> list[dict]:
    require(path.is_file(), f"{what} 없음: {path}")
    rows = []
    # splitlines()는 U+2028 같은 글자에서도 줄을 자른다 — JSONL 문자열 안에 실제로 있다(v1 night_rule_dan).
    for no, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise InputError(f"{path}:{no}: JSON 파손: {exc}") from exc
    return rows


def load_report(path: Path) -> list[Attempt]:
    out: list[Attempt] = []
    seen: set[tuple[str, int]] = set()
    for row in _rows(path, "리포트"):
        if row.get("entry_type") != "attempt" or row.get("status") != 2:
            continue
        key = (row.get("probe_classname"), row.get("seq"))
        require(key not in seen, f"{path}: (probe, seq) 중복 {key}")
        seen.add(key)
        outs = row.get("outputs")
        require(isinstance(outs, list) and len(outs) == GENERATIONS, f"{path}: {key} 출력이 {GENERATIONS}개가 아니다")
        try:
            text = prompt_text(row)
        except InputError as exc:
            raise InputError(f"{path}: {key} {exc}") from exc
        s1 = tuple(is_blocked(o.get("text") if isinstance(o, dict) else o, DEFAULT_BLOCKED_MESSAGE) for o in outs)
        out.append(Attempt(key[0], key[1], alone_blocked(text), s1))
    require(bool(out), f"{path}: status=2 attempt 0개")
    return out


def load_audit(path: Path, start: int) -> list[bool]:
    return [bool(r.get("blocked")) for r in _rows(path, "감사 사본")[start:]]


def table(attempts: list[Attempt]) -> Table:
    t = Table()
    for at in attempts:
        hits = 0
        for i, s in enumerate(at.s1):
            if s and at.alone:
                t.a += 1
            elif s:
                t.b += 1
                hits += 1
            elif at.alone:
                t.c += 1
                t.c_keys.append((at.probe, at.seq, i))
            else:
                t.d += 1
        t.b_attempts += hits > 0
    return t


def align(s1: list[bool], audit: list[bool]) -> str | None:
    """정렬 검사(D-094 §4). 통과면 None, 아니면 사유. S1 차단 ∧ 감사 통과(모델이 낸 차단 문구)는 허용한다."""
    if len(audit) != len(s1):
        return f"감사 줄 {len(audit)} ≠ 출력 {len(s1)}"
    reverse = sum(1 for s, au in zip(s1, audit) if au and not s)
    return f"감사 차단 ∧ S1 통과 {reverse}개" if reverse else None


def nearest_blocked(alone: list[bool], i: int) -> int | None:
    for dist in range(1, WINDOW + 1):
        if alone[i - dist]:
            return dist
    return None


def window_profile(alone: list[bool], actual: list[bool]) -> Counter:
    """보조 B. 단독 통과 요청 중 팔 안 21번째부터: (가장 가까운 단독 차단까지 거리 d 또는 None, 감사 차단) → 수."""
    prof: Counter = Counter()
    for i in range(WINDOW, len(alone)):
        if not alone[i]:
            prof[(nearest_blocked(alone, i), actual[i])] += 1
    return prof


def pct(k: int, n: int) -> str:
    return "—" if n == 0 else f"{k / n * 100:.1f}%"


def flat(attempts: list[Attempt]) -> tuple[list[bool], list[bool]]:
    alone = [at.alone for at in attempts for _ in at.s1]
    s1 = [s for at in attempts for s in at.s1]
    return alone, s1


def arm_section(name: str, role: str, attempts: list[Attempt], audit: list[bool]) -> list[str]:
    t = table(attempts)
    alone, s1 = flat(attempts)
    out = [f"## {name} ({role})", "",
           f"- 출력 {len(s1)} (attempt {len(attempts)}). S1 차단 {t.a + t.b}, 단독 차단 {t.a + t.c}.", "",
           "| | 단독 차단 | 단독 통과 |", "|---|---|---|",
           f"| S1 차단 | {t.a} | {t.b} |", f"| S1 통과 | {t.c} | {t.d} |", "",
           f"- **S1 차단 ∧ 단독 통과: {t.b} / {t.a + t.b} = {pct(t.b, t.a + t.b)}** (attempt {t.b_attempts}개에 걸침)",
           f"- S1 통과 ∧ 단독 차단: {t.c}"]
    out += [f"  - `{p}` seq {q} 출력 {i}" for p, q, i in t.c_keys[:MAX_LIST]]
    if len(t.c_keys) > MAX_LIST:
        out.append(f"  - 외 {len(t.c_keys) - MAX_LIST}개")

    reason = align(s1, audit)
    if reason:
        out += [f"- 정렬 검사: 불통과 — {reason}. 등록(§4)대로 보조 분석을 내지 않는다.", ""]
        return out
    model_echo = sum(1 for s, au in zip(s1, audit) if s and not au)
    out.append(f"- 정렬 검사: 통과 (감사 줄 {len(audit)} = 출력 {len(s1)}, 감사 차단 ∧ S1 통과 0, "
               f"S1 차단 ∧ 감사 통과 {model_echo})")
    b_gate = sum(1 for al, s, au in zip(alone, s1, audit) if s and not al and au)
    out.append(f"- 보조 A: S1 차단 ∧ 단독 통과 {t.b} 중 감사 차단 {b_gate}, 감사 통과(모델이 낸 차단 문구) {t.b - b_gate}")

    prof = window_profile(alone, audit)
    has = {v: sum(n for (dist, act), n in prof.items() if dist is not None and act == v) for v in (True, False)}
    none = {v: prof[(None, v)] for v in (True, False)}
    out += [f"- 보조 B: 단독 통과 ∧ 팔 안 21번째부터 {sum(prof.values())}개. 실제 = 감사 `blocked`.",
            f"  - 감사 차단: 창 20 안에 단독 차단 있음 {has[True]}, 없음 {none[True]}",
            f"  - 감사 통과: 창 20 안에 단독 차단 있음 {has[False]}, 없음 {none[False]}", "",
            "| 가장 가까운 단독 차단까지 거리 d | 감사 차단 | 감사 통과 |", "|---|---|---|"]
    out += [f"| {dist} | {prof[(dist, True)]} | {prof[(dist, False)]} |" for dist in range(1, WINDOW + 1)]
    out += [f"| 없음 | {none[True]} | {none[False]} |", ""]
    return out


def control_section(controls: list[tuple[str, list[Attempt]]]) -> list[str]:
    out = ["## 양성 대조 — v1 rule (게이트웨이가 프롬프트만 봤다, D-094 §2-6)", "",
           "| 리포트 | 출력 | S1 차단 | 단독 차단 | S1 차단 ∧ 단독 통과 | S1 통과 ∧ 단독 차단 |",
           "|---|---|---|---|---|---|"]
    mismatched: list[str] = []
    for label, attempts in controls:
        t = table(attempts)
        out.append(f"| {label} | {t.a + t.b + t.c + t.d} | {t.a + t.b} | {t.a + t.c} | {t.b} | {t.c} |")
        keys = [(at.probe, at.seq) for at in attempts if any(s != at.alone for s in at.s1)]
        mismatched += [f"  - {label}: `{p}` seq {q}" for p, q in keys[:MAX_LIST]]
        if len(keys) > MAX_LIST:
            mismatched.append(f"  - {label}: 외 {len(keys) - MAX_LIST}개 attempt")
    out += ["", f"- 불일치 attempt: {'아래' if mismatched else '없음'}", *mismatched, ""]
    return out


def run(root: Path, arms=ARMS, controls=CONTROLS) -> str:
    loaded = [(label, load_report(root / path)) for label, path in controls]
    out = ["# D-094 단독 판정 대조 — rule 팔 (원문 없음)", "",
           f"- 등록: DECISIONS.md D-094. 단독 판정 코드 지문 `{code_fingerprint()}`. 실제 차단 = S1.",
           "- 수치만 낸다. 해석은 D-094 §5 읽는 규칙대로 사람이 적는다.", ""]
    out += control_section(loaded)
    for name, role, report, audit, start in arms:
        out += arm_section(name, role, load_report(root / report), load_audit(root / audit, start))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D-094 단독 판정 대조")
    ap.add_argument("--root", type=Path, default=ROOT, help="저장소 루트(테스트용)")
    a = ap.parse_args(argv)
    try:
        print(run(a.root))
    except (InputError, OSError) as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
