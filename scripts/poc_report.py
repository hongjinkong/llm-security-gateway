#!/usr/bin/env python3
"""PoC 리포트(D-129, PLAN 19단계) — 고객 샘플 JSONL을 게이트웨이의 탐지·대체값 코드로 훑어 마크다운 리포트를 낸다. 게이트웨이를 띄우지 않는다.

  python3 scripts/poc_report.py samples.jsonl                 # 한 줄 = {"text": "...", "id": "선택"}
  python3 scripts/poc_report.py samples.jsonl --out report.md --limit 5000 --kinds rrn,phone,email --detect-kinds account,brn,crn,ipv4

리포트에는 **원문도 가짜 값도 없다** — 종류별 탐지 수, 값의 모양(숫자→#·영문→x·한글→ㅇ) 빈도, 복원률(가짜 값을 그대로 되돌릴 때의 상한), 샘플마다의 처리 시간 p50·p95만.
정규식 종류 12개만 본다(이름·주소·직장은 탐지 사이드카가 필요하다 — 리포트에 그렇게 적는다). 게이트웨이 경유 지연은 D-122의 측정값을 인용한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gateway.detectors.patterns import find_all  # noqa: E402
from gateway.detectors.pii import DETECT_ONLY, REGEX_KINDS  # noqa: E402
from gateway.vault import TokenVault  # noqa: E402

KEY = hashlib.sha256(b"poc-report-local-key").digest()     # 리포트용 고정 키 — 가짜 값은 리포트에 나오지 않으므로 값 자체는 뜻이 없다
SHAPE_MAX = 40


def shape(value: str) -> str:
    """값의 모양 — 숫자는 #, 영문은 x, 한글은 ㅇ, 그 밖(구분자·공백)은 그대로. 원문을 드러내지 않고 오탐을 가려내는 데 쓴다."""
    out = []
    for c in value[:SHAPE_MAX]:
        if c.isdigit():
            out.append("#")
        elif c.isascii() and c.isalpha():
            out.append("x")
        elif "가" <= c <= "힣" or "ㄱ" <= c <= "ㆎ":
            out.append("ㅇ")
        elif c.isalpha():
            out.append("u")
        else:
            out.append(c)
    return "".join(out) + ("…" if len(value) > SHAPE_MAX else "")


def pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "—"


def percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q * (len(s) - 1))))]


def analyze(items: list[dict], kinds: frozenset[str], detect_kinds: frozenset[str]) -> dict:
    """샘플마다 탐지 → 가림(대체값 발급) → 그대로 복원. 돌려주는 집계에는 원문·가짜 값이 없다(tokens는 테스트가 리포트에 없음을 확인하는 데만 쓴다)."""
    masked_by_kind: Counter = Counter()
    audit_by_kind: Counter = Counter()
    shapes: dict[str, Counter] = defaultdict(Counter)
    samples_with: Counter = Counter()
    issued = restored = residual = exact = 0
    times: list[float] = []
    lengths: list[int] = []
    tokens: set[str] = set()
    skipped = 0
    for i, it in enumerate(items):
        text = it.get("text") if isinstance(it, dict) else None
        if not isinstance(text, str) or not text.strip():
            skipped += 1
            continue
        lengths.append(len(text))
        t0 = time.perf_counter()
        found = [f for f in find_all(text) if f.kind in kinds]
        vault = TokenVault(key=KEY)
        session = f"poc-{i}"
        out, pos, n_issued = [], 0, 0
        seen_kinds: set[str] = set()
        for f in found:
            seen_kinds.add(f.kind)
            value = text[f.start:f.end]
            if f.kind in detect_kinds or not f.mask:
                audit_by_kind[f.kind] += 1
                continue
            masked_by_kind[f.kind] += 1
            shapes[f.kind][shape(value)] += 1
            token = vault.token_for(session, f.kind, value)
            tokens.add(token)
            out.append(text[pos:f.start])
            out.append(token)
            pos = f.end
            n_issued += 1
        out.append(text[pos:])
        masked = "".join(out)
        back, n_restored = vault.restore(session, masked) if n_issued else (text, 0)
        times.append((time.perf_counter() - t0) * 1000)
        issued += n_issued
        restored += n_restored
        residual += vault.residual(session, back) if n_issued else 0
        exact += back == text
        for k in seen_kinds:
            samples_with[k] += 1
    n = len(items) - skipped
    return {"samples": n, "skipped": skipped, "bytes": sum(len(t.encode("utf-8")) for t in (it.get("text", "") for it in items if isinstance(it, dict)) if isinstance(t, str)),
            "lengths": {"p50": percentile([float(x) for x in lengths], 0.5), "p95": percentile([float(x) for x in lengths], 0.95), "max": max(lengths) if lengths else 0},
            "masked": dict(masked_by_kind), "audit": dict(audit_by_kind), "samples_with": dict(samples_with), "shapes": {k: v.most_common(20) for k, v in shapes.items()},
            "issued": issued, "restored": restored, "residual": residual, "exact": exact,
            "ms": {"p50": percentile(times, 0.5), "p95": percentile(times, 0.95), "max": max(times) if times else 0.0}, "tokens": tokens, "kinds": sorted(kinds), "detect_kinds": sorted(detect_kinds & kinds)}


def report(a: dict, source: str) -> str:
    n = a["samples"]
    lines = [f"# PoC 리포트 — `{source}`", "",
             f"샘플 {n:,}건(건너뜀 {a['skipped']} — `text` 없음·빈 줄) · {a['bytes']:,}바이트 · 길이 중앙값 {a['lengths']['p50']:.0f}자, p95 {a['lengths']['p95']:.0f}자, 최대 {a['lengths']['max']:,}자.",
             "원문과 가짜 값은 이 리포트에 없다 — 모양(숫자 `#`·영문 `x`·한글 `ㅇ`)과 개수만. 정규식 종류 " + ", ".join(f"`{k}`" for k in a["kinds"]) + "만 봤다(이름·주소·직장은 탐지 사이드카가 필요하다).",
             "", "## 종류별 탐지", "", "| 종류 | 가림 | 감사만 | 샘플 수(이 종류가 있는) | 샘플당 평균 |", "|---|---|---|---|---|"]
    for k in a["kinds"]:
        m, au, sw = a["masked"].get(k, 0), a["audit"].get(k, 0), a["samples_with"].get(k, 0)
        if m or au:
            lines.append(f"| `{k}` | {m:,} | {au:,} | {sw:,} ({pct(sw, n)}) | {(m + au) / n:.2f} |")
    lines += ["", f"감사만 종류(`--detect-kinds`): {', '.join(f'`{k}`' for k in a['detect_kinds']) or '없음'} — 탐지하지만 가리지 않고 감사 줄에만 남긴다. 그 밖에 검증식이 약한 꼴(문맥어 없는 주민번호 등)도 감사만으로 내려간다(D-116).",
              "", "## 오탐 후보 — 값의 모양(종류별 빈도순 20개)", "", "모양만 보고도 오탐을 가려낼 수 있다(예: 전화번호 꼴인데 주문번호, 계좌 꼴인데 송장번호). 많은 모양부터 확인한다.", ""]
    for k in a["kinds"]:
        if a["shapes"].get(k):
            lines += [f"### `{k}`", "", "| 모양 | 수 |", "|---|---|"] + [f"| `{s}` | {c:,} |" for s, c in a["shapes"][k]] + [""]
    issued, restored = a["issued"], a["restored"]
    lines += ["## 복원률", "",
              f"가짜 값으로 바꾼 뒤 그 텍스트를 그대로 되돌렸을 때: 발급 {issued:,} · 복원 {restored:,} ({pct(restored, issued)}) · 복원 뒤 남은 가짜 값 {a['residual']:,} · 원문과 완전히 같은 샘플 {a['exact']:,}/{n:,}.",
              "이 숫자는 모델이 가짜 값을 **그대로** 돌려줄 때의 상한이다 — 실제 응답에서 모델이 값을 고쳐 쓰면 복원이 빠진다(감사 `pii_suspect`로 본다).", "",
              "## 처리 시간(이 프로세스 안, 샘플마다 탐지 + 가림 + 복원)", "",
              f"p50 {a['ms']['p50']:.2f}ms · p95 {a['ms']['p95']:.2f}ms · 최대 {a['ms']['max']:.1f}ms. 게이트웨이 경유 지연(인증·중계 포함)은 D-122 측정값을 본다 — 동시 100(스트림 50 + 비스트리밍 50)에서 게이트웨이 자체 처리 `gateway_ms` p95 18.5ms.",
              "", "## 한계", "",
              "- 정규식 종류만 봤다. 이름·주소·직장(`person`·`address`·`org`)은 탐지 사이드카를 켠 게이트웨이로 재야 한다(D-126).",
              "- 탐지 수는 샘플 텍스트 안의 꼴 기준이다 — 가린 값이 정말 개인정보인지는 위 모양 표로 사람이 확인한다.",
              "- 복원률은 가짜 값을 그대로 되돌린 경우만이다. 스트리밍·JSON 이스케이프 경로의 복원은 게이트웨이 테스트가 지킨다(D-113)."]
    return "\n".join(lines) + "\n"


def load(path: Path, limit: int | None) -> list[dict]:
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            items.append({})
            continue
        items.append(obj if isinstance(obj, dict) else {})
        if limit and len(items) >= limit:
            break
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="PoC 리포트(D-129) — 샘플 JSONL → 마크다운, 원문 없음")
    ap.add_argument("samples", type=Path)
    ap.add_argument("--out", type=Path, help="리포트 파일(없으면 표준 출력)")
    ap.add_argument("--limit", type=int, help="앞 N줄만")
    ap.add_argument("--kinds", default=",".join(REGEX_KINDS), help="볼 종류(쉼표) — 기본 정규식 12종")
    ap.add_argument("--detect-kinds", default=",".join(k for k in DETECT_ONLY if k in REGEX_KINDS), help="감사만 종류(쉼표) — 기본은 게이트웨이 기본값")
    a = ap.parse_args()
    kinds = frozenset(k for k in a.kinds.split(",") if k)
    bad = kinds - set(REGEX_KINDS)
    if bad:
        sys.exit(f"모르는 종류: {sorted(bad)} — 정규식 종류 {REGEX_KINDS}")
    text = report(analyze(load(a.samples, a.limit), kinds, frozenset(k for k in a.detect_kinds.split(",") if k)), a.samples.name)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"리포트 {a.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
