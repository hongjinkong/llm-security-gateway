#!/usr/bin/env python3
"""2차 유사도 임계값 T 캘리브레이션 — D-044 절차의 실행본. 규칙은 D-049에 사전 등록됨.

    python3 scripts/calibrate_similarity.py

**이 스크립트를 고치기 전에 D-049를 읽을 것.**
게이트 규칙(D-049-1)과 T 선택 방식은 이 스크립트를 **한 번도 돌리기 전에** 확정됐다.
숫자를 보고 규칙을 고치면 게이트가 측정이 아니라 최적화 대상이 된다 — 그 순간
여기서 나온 T로 채운 EVAL 5.2 행은 전부 무효다.

무엇을 계산하나
---------------
    benign_nearest(i)   정상 질문 i ↔ 코퍼스 전체 최대 코사인      (FPR 축)
    benign_max(j)       코퍼스 항목 j ↔ 정상 질문 100문항 최대     (게이트)
    loo_max(j)          코퍼스 항목 j ↔ 자기 제외 코퍼스 최대      (공격 축 대용)

절차 (D-049)
------------
    1. 152문장(코퍼스 + 정상질문)을 임베딩한다.
    2. 게이트: benign_max(j) > loo_max(j) 인 항목을 **뺀다. 1회만.**
       = "다른 공격 항목들보다 정상 질문에 더 가까운" 항목. 0 탈락이 나올 수 있다.
    3. 살아남은 코퍼스로 세 분포를 재계산한다.
    4. T = [max(benign_nearest), min(loo_max)] 갭의 중점.
       갭이 음수면 **T를 정하지 않는다** — 코퍼스를 다시 짜라는 신호다(D-044).

원칙
----
- **원문을 출력하지 않는다**(D-029). 점수와 ID만 찍는다.
- `results/*.report.jsonl`을 열지 않는다(D-039 홀드아웃). 정상 질문셋만 쓴다.
- 백분위는 `int(n×q)` nearest-rank — `fpr_report.py`·`embed_latency.py`와 같은 방식.
  선형 보간을 쓰면 같은 데이터에서 다른 숫자가 나온다(D-035).
- 게이트웨이를 거치지 않는다. 임베더를 직접 부른다(D-049 결정 4).
  배선된 경로가 같은 점수를 내는지는 `injection_similarity_observe`로 따로 확인한다.

**이 스크립트는 코퍼스 파일을 고치지 않는다.** 뺄 항목의 ID를 출력할 뿐이다.
삭제는 사람이 한다 — 자동 삭제는 되돌리기 어렵고, 무엇이 왜 빠졌는지 기록이 남지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from gateway.detectors.similarity import CORPUS_PATH, load_corpus  # noqa: E402
from gateway.embedding import OllamaEmbedder  # noqa: E402

BENIGN_PATH = ROOT / "eval" / "benign" / "all100.jsonl"
OUT_DIR = ROOT / "results" / "calibration"

# D-044: FPR 잔여 예산 4%. B-103이 1차 룰에서 이미 1%를 쓰고 있다.
FPR_BUDGET = 4
# D-049-1 게이트 규칙: benign_max(j) > loo_max(j) 이면 항목 j를 뺀다.
# "이 항목은 다른 공격 항목들보다 정상 질문에 더 가깝다" = 공격 쪽이 아니라 정상 쪽에 산다.
# 자유 파라미터가 없다. 절대 임계값도, 분위수도 없다.
#
# 초안(p95 분위수)은 실제 임베딩을 돌리기 전에 폐기했다 — 상대 규칙이라 순위만 보고
# 크기를 안 봐서, 코퍼스가 정상 질문과 완전히 무관해도(benign_max 최대 -0.01) 항상
# 상위 몇 개를 잘라냈다. "0 탈락 = 코퍼스가 건강하다"를 영원히 말할 수 없는 규칙이었다.
# 경위는 D-049-1.


def pct(sorted_vals: list[float], q: float) -> float:
    """`fpr_report.py`·`embed_latency.py`와 동일한 nearest-rank 계열 백분위."""
    if not sorted_vals:
        return 0.0
    i = min(int(len(sorted_vals) * q), len(sorted_vals) - 1)
    return sorted_vals[i]


def load_benign(path: Path) -> list[dict]:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not rows:
        raise SystemExit(f"정상 질문셋이 비어 있다: {path}")
    bad = [r.get("id") for r in rows if not r.get("q")]
    if bad:
        raise SystemExit(f"q가 빈 문항이 있다: {bad[:5]}")
    return rows


async def embed_all(texts: list[str], *, model: str, endpoint: str,
                    chunk: int, timeout: float) -> np.ndarray:
    """청크로 나눠 임베딩한다. 152문장을 한 번에 보내도 되지만, 폴백 모델이나
    긴 입력에서 요청이 커지면 조용히 잘릴 수 있다(D-043의 최대 시퀀스 길이 주의)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        emb = OllamaEmbedder(client, model=model, endpoint=endpoint)
        out: list[list[float]] = []
        for i in range(0, len(texts), chunk):
            part = texts[i:i + chunk]
            out.extend(await emb.embed(part))
            print(f"  임베딩 {min(i + chunk, len(texts))}/{len(texts)}", flush=True)
        if emb.dim is None:
            raise SystemExit("임베딩 차원을 관측하지 못했다")
        print(f"  차원 {emb.dim}, 모델 {model}")
    return np.asarray(out, dtype=np.float32)


def git_hash() -> str:
    try:
        r = subprocess.run(["git", "--no-optional-locks", "rev-parse", "--short", "HEAD"],
                           cwd=ROOT, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def dist_line(name: str, vals: np.ndarray) -> str:
    s = sorted(float(v) for v in vals)
    return (f"  {name:22s} n={len(s):3d}  최소 {s[0]:.4f}  p50 {pct(s, 0.50):.4f}  "
            f"p95 {pct(s, 0.95):.4f}  최대 {s[-1]:.4f}")


@dataclass(frozen=True)
class Calibration:
    """캘리브레이션 결과. **순수 계산의 산출물** — IO도 출력도 하지 않는다.

    main()에서 분리한 이유: 계산을 print 사이에 묻어두면 시험할 수가 없고,
    그러면 "돌려보니 그럴듯한 숫자가 나왔다"가 유일한 검증이 된다.
    이 프로젝트가 반복해서 데인 실패다.
    """

    loo_all: np.ndarray             # 게이트 판정에 쓴 전체 코퍼스 기준 LOO
    dropped_idx: list[int]
    kept_idx: list[int]
    benign_nearest: np.ndarray      # 잔존 코퍼스 기준, 정상 질문별 최근접
    benign_near_idx: np.ndarray     # 그 최근접이 잔존 코퍼스의 몇 번째인가
    loo_max: np.ndarray             # 잔존 코퍼스 항목별 LOO 최근접
    loo_near_idx: np.ndarray
    benign_max_all: np.ndarray      # 게이트 판정에 쓴 값 (전체 코퍼스 기준)
    benign_arg_all: np.ndarray
    lo: float                       # 정상 분포의 위
    hi: float                       # LOO 분포의 아래
    gap: float
    budget_floor: float
    T: float | None


def calibrate(C_all: np.ndarray, B: np.ndarray, *,
              budget: int = FPR_BUDGET) -> Calibration:
    """D-049의 절차를 그대로 계산한다. 벡터는 **단위 길이여야 한다**(내적 = 코사인).

    게이트는 **1회만**이다(D-049 결정 2). 뺀 뒤 재계산해서 또 빼지 않는다 —
    반복하면 통과할 때까지 도는 최적화가 되고, 그 순간 게이트는 아무것도 측정하지 않는다.
    """
    if C_all.ndim != 2 or B.ndim != 2 or C_all.shape[1] != B.shape[1]:
        raise ValueError(f"차원이 맞지 않는다: 코퍼스 {C_all.shape}, 정상질문 {B.shape}")
    if C_all.shape[0] < 2:
        raise ValueError("LOO를 계산하려면 코퍼스가 2항목 이상이어야 한다")

    S = C_all @ B.T                                   # (코퍼스, 정상질문)
    benign_max_all = S.max(axis=1)
    benign_arg_all = S.argmax(axis=1)

    # 게이트 판정은 **전체 코퍼스 기준 LOO**와 비교한다.
    G_all = C_all @ C_all.T
    np.fill_diagonal(G_all, -2.0)
    loo_all = G_all.max(axis=1)

    dropped = [j for j in range(C_all.shape[0])
               if float(benign_max_all[j]) > float(loo_all[j])]
    kept = [j for j in range(C_all.shape[0]) if j not in set(dropped)]
    if len(kept) < 2:
        raise ValueError(
            f"게이트 후 잔존이 {len(kept)}항목이다. 규칙을 고치지 말고 코퍼스를 다시 볼 것(D-044)")

    C = C_all[kept]
    S2 = C @ B.T
    benign_nearest = S2.max(axis=0)
    benign_near_idx = S2.argmax(axis=0)

    G = C @ C.T
    np.fill_diagonal(G, -2.0)                         # leave-one-out
    loo_max = G.max(axis=1)
    loo_near_idx = G.argmax(axis=1)

    lo = float(benign_nearest.max())
    hi = float(loo_max.min())
    gap = hi - lo

    b_desc = sorted((float(v) for v in benign_nearest), reverse=True)
    budget_floor = b_desc[budget] if len(b_desc) > budget else 0.0

    # 갭이 음수면 T를 정하지 않는다. 억지로 뽑으면 D-044가 금지한 "한 축만 보기"가 된다.
    T = (lo + hi) / 2.0 if gap > 0 else None

    return Calibration(
        loo_all=loo_all, dropped_idx=dropped, kept_idx=kept,
        benign_nearest=benign_nearest, benign_near_idx=benign_near_idx,
        loo_max=loo_max, loo_near_idx=loo_near_idx,
        benign_max_all=benign_max_all, benign_arg_all=benign_arg_all,
        lo=lo, hi=hi, gap=gap, budget_floor=budget_floor, T=T)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://localhost:11434")
    ap.add_argument("--model", default="bge-m3")
    ap.add_argument("--chunk", type=int, default=32)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    ap.add_argument("--benign", type=Path, default=BENIGN_PATH)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()

    corpus = load_corpus(a.corpus)
    benign = load_benign(a.benign)
    print(f"코퍼스 {len(corpus)}항목 / 정상 질문 {len(benign)}문항")
    print("게이트 규칙: benign_max(j) > loo_max(j) → 제거 (D-049-1, 1회만)")
    print()

    vecs = asyncio.run(embed_all(
        [r["text"] for r in corpus] + [r["q"] for r in benign],
        model=a.model, endpoint=a.endpoint, chunk=a.chunk, timeout=a.timeout))
    C_all = vecs[:len(corpus)]
    B = vecs[len(corpus):]

    cal = calibrate(C_all, B)
    rows = [corpus[j] for j in cal.kept_idx]

    print("=" * 78)
    print("[1] 게이트 — 정상 질문셋 최대 유사도")
    print("=" * 78)
    print(dist_line("정상질문 최근접(전)", (C_all @ B.T).max(axis=0)))
    print(dist_line("코퍼스 benign_max", cal.benign_max_all))
    print(dist_line("코퍼스 LOO(전)", cal.loo_all))
    print(f"  규칙: benign_max(j) > loo_max(j) → 제거 (D-049-1, 1회만)")
    print(f"  탈락 {len(cal.dropped_idx)}항목 / 잔존 {len(cal.kept_idx)}항목")
    if not cal.dropped_idx:
        print("  → 0 탈락. 모든 항목이 정상 질문보다 다른 공격 항목에 더 가깝다 = 코퍼스가 건강하다.")
    if cal.dropped_idx:
        print()
        print(f"  {'항목':12s} {'cat':5s} {'benign_max':>10s} {'loo_max':>8s}  가장 가까운 정상질문")
        for j in sorted(cal.dropped_idx, key=lambda x: -float(cal.benign_max_all[x])):
            print(f"  {corpus[j]['id']:12s} {corpus[j].get('category',''):5s} "
                  f"{float(cal.benign_max_all[j]):10.4f} {float(cal.loo_all[j]):8.4f}  "
                  f"{benign[int(cal.benign_arg_all[j])]['id']}")

    drop_by_cat = {}
    print()
    print(f"  {'category':10s} {'전체':>5s} {'탈락':>5s} {'잔존':>5s}")
    for c in sorted({r.get("category", "") for r in corpus}):
        tot = sum(1 for r in corpus if r.get("category") == c)
        dr = sum(1 for j in cal.dropped_idx if corpus[j].get("category") == c)
        drop_by_cat[c] = dr
        print(f"  {c:10s} {tot:5d} {dr:5d} {tot - dr:5d}")

    print()
    print("=" * 78)
    print("[2] 두 분포 (잔존 코퍼스 기준)")
    print("=" * 78)
    print(dist_line("정상질문 최근접", cal.benign_nearest))
    print(dist_line("코퍼스 LOO", cal.loo_max))
    print()
    print(f"  정상 최대 {cal.lo:.4f}   LOO 최소 {cal.hi:.4f}   갭 {cal.gap:+.4f}")

    print()
    print("=" * 78)
    print("[3] T")
    print("=" * 78)
    print(f"  FPR 예산 {FPR_BUDGET}개 → 하한 {cal.budget_floor:.4f} 초과여야 함 "
          f"(D-044: 예산은 제약이지 목적이 아니다)")
    if cal.T is not None:
        blocked = int((cal.benign_nearest >= cal.T).sum())
        print(f"  갭 중점 T = {cal.T:.4f}")
        print(f"  이 T에서 차단되는 정상 질문 {blocked}개 (예산 {FPR_BUDGET})")
        if blocked > FPR_BUDGET:
            print("  ⚠ 예산 초과. T를 올리면 D-044의 '한 축만 보기'가 된다 — 코퍼스로 돌아간다.")
    else:
        print("  ✗ 갭이 없다(두 분포가 겹친다). **T를 정하지 않는다.**")
        print("    D-044: '갭이 없으면 코퍼스를 다시 짜라는 신호.'")
        print("    억지로 숫자를 뽑지 말 것. 규칙을 고치는 것은 D-049 위반이다.")

    print()
    print(f"  {'정상질문':10s} {'점수':>8s}  최근접 코퍼스   (상위 8)")
    for i in np.argsort(-cal.benign_nearest)[:8]:
        r = rows[int(cal.benign_near_idx[int(i)])]
        print(f"  {benign[int(i)]['id']:10s} {float(cal.benign_nearest[int(i)]):8.4f}  "
              f"{r['id']:12s} {r.get('category','')}")

    print()
    print(f"  {'코퍼스항목':12s} {'LOO':>8s}  최근접 항목   (LOO 상위 8 = 서로 닮은 쌍)")
    for j in np.argsort(-cal.loo_max)[:8]:
        print(f"  {rows[int(j)]['id']:12s} {float(cal.loo_max[int(j)]):8.4f}  "
              f"{rows[int(cal.loo_near_idx[int(j)])]['id']}")

    # --- 산출물 ---------------------------------------------------------------
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = a.out or (OUT_DIR / f"calibration_{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": stamp,
        "git": git_hash(),
        "model": a.model,
        "endpoint": a.endpoint,
        "dim": int(vecs.shape[1]),
        "rule": {
            "decision": "D-049-1",
            "gate": "benign_max(j) > loo_max(j), 1회만",
            "percentile": "nearest-rank int(n*q)",
            "fpr_budget": FPR_BUDGET,
        },
        "gate": {
            "dropped_ids": [corpus[j]["id"] for j in cal.dropped_idx],
            "dropped_by_category": drop_by_cat,
            "kept": len(cal.kept_idx),
        },
        "distributions": {
            "benign_nearest": [round(float(v), 6) for v in cal.benign_nearest],
            "corpus_loo_max": [round(float(v), 6) for v in cal.loo_max],
        },
        "per_benign": [
            {"id": benign[i]["id"], "score": round(float(cal.benign_nearest[i]), 6),
             "nearest_corpus_id": rows[int(cal.benign_near_idx[i])]["id"],
             "nearest_category": rows[int(cal.benign_near_idx[i])].get("category", "")}
            for i in range(len(benign))
        ],
        "per_corpus": [
            {"id": rows[j]["id"], "category": rows[j].get("category", ""),
             "loo_max": round(float(cal.loo_max[j]), 6),
             "loo_nearest_id": rows[int(cal.loo_near_idx[j])]["id"]}
            for j in range(len(rows))
        ],
        "gap": {"benign_max": cal.lo, "loo_min": cal.hi, "gap": cal.gap,
                "budget_floor": cal.budget_floor},
        "T": cal.T,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out            # --out 을 저장소 밖으로 준 경우
    print(f"산출물 → {shown}")
    print("원문은 들어 있지 않다 (점수와 ID만). D-029.")
    print()
    print("다음: 탈락 ID를 코퍼스에서 **사람이** 지우고, 무엇이 왜 빠졌는지 CORPUS.md에 남긴다.")
    print("      T가 나왔다면 GATEWAY_SIMILARITY_T로 동결하고 커밋 해시로 시각을 고정한다(D-044).")
    return 0 if cal.T is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
