#!/usr/bin/env python3
"""빚 6-a — 군집(프롬프트)을 반영한 부트스트랩 CI. 사전 등록: DECISIONS.md D-062.

**무엇이 문제인가.** `n=7,680`은 출력 수이지 독립 관측 수가 아니다.
768 attempt x 프롬프트당 10회 = 7,680. 같은 프롬프트의 10개는 서로 독립이 아니다
(빚 3의 전건통과 81 / 전건차단 354 / 부분차단 0이 직접 증거다). 그런 자료에
n=7,680을 넣으면 Wilson CI가 실제보다 **좁다**.

**무엇을 하는가.** 군집(=프롬프트) 단위로 복원추출해 비율을 10,000번 다시 계산하고
percentile로 CI를 낸다. **점추정은 한 글자도 바꾸지 않는다**(C1). 기존 Wilson CI를
지우지 않고 **병기**한다. p값은 새로 만들지 않는다(D-062 4절).

**분자 정의.** `matched_baseline.py`의 `fails - blocked`는 그 도구가 쓰는 구간에서
blocked=0이라 맞는 식이다. +룰 팔 전체에 쓰면 363-6360으로 음수가 난다 — 존재 기반
판정기는 차단 응답을 애초에 실패로 잡지 않기 때문이다(F_blk=0 실측, rescore_pi).
여기서는 **fails - (차단이면서 동시에 실패로 채점된 출력 수)**를 쓴다. 두 체제 모두에서
맞고, 지금 자료에서는 그 교집합이 0이라 기존 값과 정수까지 같다. C1이 검사한다.

D-039 홀드아웃: 프롬프트 원문을 출력하지 않는다. SHA-1 키로만 다룬다.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import matched_baseline as mb  # noqa: E402

MSG = mb.MSG
wilson = mb.wilson
key_of = mb.key_of

B_DEFAULT = 10_000
SEED_DEFAULT = 20260921

# C1 대조표 — 기존 산출물에서 그대로 옮긴 (분자, 분모) 정수쌍.
# 비율이 아니라 정수로 대조한다. rescore_pi는 한 자리(73.5%), matched_pi는 두 자리
# (73.45%)로 찍혀 있어 반올림 경계에서 다투게 되기 때문이다. C1을 푸는 게 아니라 조인다.
EXPECTED = {
    "base_all":      (5641, 7680),  # matched_pi 베이스라인 ∩ 공통 전체 73.45%
    "rule_block":    (6360, 7680),  # rescore_pi +룰 차단율 82.8%
    "rule_asr_blk":  (363, 7680),   # rescore_pi +룰 ASR_blk 4.7%
    "rule_asr_pass": (363, 1320),   # rescore_pi +룰 ASR_pass 27.5%
    "base_passed":   (946, 1320),   # matched_pi 베이스라인 ∩ 통과 81개 71.67%
    "base_blocked":  (4695, 6360),  # matched_pi 베이스라인 ∩ 차단 354개 73.82%
}


# ------------------------------------------------------------------ 집계

def collect(path: pathlib.Path, detector: str, gen_name: str | None) -> dict[str, dict]:
    """프롬프트 키 -> {n, fails, blocked, fb}

    fb = 차단 문구이면서 **동시에** 실패로 채점된 출력 수. 부재 기반 판정기면 fb=blocked,
    존재 기반이면 fb=0이 예상값이다(SCORING_PROTOCOL 2절). 예상하지 않고 센다.
    """
    out: dict[str, dict] = {}
    for line in path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("entry_type") != "attempt" or r.get("status") != 2:
            continue
        scores = (r.get("detector_results") or {}).get(detector)
        if scores is None:
            continue
        outs = r.get("outputs") or []
        n = fails = blocked = fb = 0
        for i, sc in enumerate(scores):
            if sc is None:
                continue
            n += 1
            bad = sc >= 0.5
            o = outs[i] if i < len(outs) else None
            text = o.get("text") if isinstance(o, dict) else None
            blk = text is not None and text.strip() == MSG
            fails += bad
            blocked += blk
            fb += bad and blk
        k = key_of(r, gen_name).split("|", 1)[1]
        cur = out.setdefault(k, {"n": 0, "fails": 0, "blocked": 0, "fb": 0, "attempts": 0})
        cur["attempts"] += 1
        cur["n"] += n
        cur["fails"] += fails
        cur["blocked"] += blocked
        cur["fb"] += fb
    return out


def clusters(store: dict[str, dict], keys, kind: str) -> list[tuple[int, int]]:
    """군집별 (분자, 분모). kind='asr'이면 성공 수, 'blocked'면 차단 수."""
    out = []
    for k in sorted(keys):
        s = store[k]
        num = s["blocked"] if kind == "blocked" else s["fails"] - s["fb"]
        out.append((num, s["n"]))
    return out


def ratio(cl) -> float:
    n = sum(x[1] for x in cl)
    return sum(x[0] for x in cl) / n if n else 0.0


def totals(cl) -> tuple[int, int]:
    return sum(x[0] for x in cl), sum(x[1] for x in cl)


# ------------------------------------------------------------------ 부트스트랩

def percentile_ci(vals: list[float], alpha: float = 0.05) -> tuple[float, float]:
    """정렬된 표본에서 percentile 하한·상한. **순서를 뒤바꾸지 않는다**(변이 4)."""
    v = sorted(vals)
    m = len(v)
    lo = v[int(alpha / 2 * m)]
    hi = v[min(m - 1, int((1 - alpha / 2) * m))]
    return (lo, hi)


def boot_ratio_ci(cl, B: int = B_DEFAULT, seed: int = SEED_DEFAULT, alpha: float = 0.05):
    """군집을 **통째로 복원추출**한다. 군집 안에서 다시 뽑지 않고(변이 3),
    출력 단위로 뽑지 않는다(변이 1). 비복원으로 바꾸지 않는다(변이 2)."""
    rng = random.Random(seed)
    m = len(cl)
    if m == 0:
        return (0.0, 0.0)
    vals = [ratio([cl[rng.randrange(m)] for _ in range(m)]) for _ in range(B)]
    return percentile_ci(vals, alpha)


def boot_paired_diff_ci(pairs, B: int = B_DEFAULT, seed: int = SEED_DEFAULT, alpha: float = 0.05):
    """짝지은 차이. pairs: [((k_a,n_a),(k_b,n_b))] — 한 프롬프트를 뽑으면
    **두 팔의 값이 함께 따라온다**. 두 팔을 따로 뽑으면 짝이 깨진다(변이 5)."""
    rng = random.Random(seed)
    m = len(pairs)
    if m == 0:
        return (0.0, 0.0)
    vals = []
    for _ in range(B):
        idx = [rng.randrange(m) for _ in range(m)]
        a = [pairs[i][0] for i in idx]
        b = [pairs[i][1] for i in idx]
        vals.append(ratio(b) - ratio(a))
    return percentile_ci(vals, alpha)


def boot_unpaired_diff_ci(cl_a, cl_b, B: int = B_DEFAULT, seed: int = SEED_DEFAULT,
                          alpha: float = 0.05):
    """짝이 아닌 두 군의 차이(b - a). 각 군에서 독립으로 복원추출한다."""
    rng = random.Random(seed)
    ma, mbn = len(cl_a), len(cl_b)
    if not (ma and mbn):
        return (0.0, 0.0)
    vals = []
    for _ in range(B):
        a = [cl_a[rng.randrange(ma)] for _ in range(ma)]
        b = [cl_b[rng.randrange(mbn)] for _ in range(mbn)]
        vals.append(ratio(b) - ratio(a))
    return percentile_ci(vals, alpha)


def deff(cluster_ci, wilson_ci) -> float:
    """(군집 CI 폭 / Wilson CI 폭)^2. 서술용이며 판정에 쓰지 않는다(D-062 4절)."""
    w = wilson_ci[1] - wilson_ci[0]
    if w <= 0:
        return float("nan")
    return ((cluster_ci[1] - cluster_ci[0]) / w) ** 2


# ------------------------------------------------------------------ 보고

def pct(x: float) -> str:
    return f"{x * 100:.2f}%"


def measure(name: str, cl, B: int, seed: int, fails: list[str]) -> str:
    """한 비율을 Wilson과 군집 CI로 **병기**한 한 줄을 만든다. 찍지는 않는다.

    ★ 찍기와 판정을 나눈 이유: C3에 걸린 줄을 먼저 찍어 버리면 '무효일 때 숫자를 내지
    않는다'(D-062 9절)가 깨진다. 처음 판에서 실제로 그랬다 — fails에 담기만 하고
    exit 2 검사를 그 앞에서 해서, C3 위반이 숫자와 함께 exit 0으로 나갔다.
    """
    k, n = totals(cl)
    w = wilson(k, n)
    c = boot_ratio_ci(cl, B=B, seed=seed)
    ok = (c[1] - c[0]) >= (w[1] - w[0])
    if not ok:
        fails.append(f"C3 {name}: 군집 폭이 Wilson보다 좁다 (군집 수 {len(cl)})")
    return (f"  {name:<30} {pct(k / n if n else 0):>7}  "
            f"(Wilson {pct(w[0])}–{pct(w[1])} / 군집 {pct(c[0])}–{pct(c[1])})  "
            f"n={n} 군집={len(cl)} DEFF={deff(c, w):.2f}{'' if ok else '  ★C3'}")


def positive_controls(B: int, seed: int, fails: list[str]) -> None:
    """C4 — 합성 두 극단. rho=0이면 Wilson과 같아야 하고, rho=1이면 sqrt(10)배여야 한다."""
    print("## C4. 양성대조 — 합성 두 극단")
    cl1 = [(10, 10)] * 100 + [(0, 10)] * 100
    k, n = totals(cl1)
    got = boot_ratio_ci(cl1, B=B, seed=seed)
    want = (wilson(k, n)[1] - wilson(k, n)[0]) * 10 ** 0.5
    rel = abs((got[1] - got[0]) - want) / want
    ok1 = rel <= 0.10
    print(f"  rho=1  폭 {pct(got[1] - got[0])} vs Wilson x sqrt(10) {pct(want)}  "
          f"상대오차 {rel * 100:.1f}%  {'통과' if ok1 else '★실패'}")
    if not ok1:
        fails.append("C4 rho=1")

    rng = random.Random(7)
    cl0 = [(sum(rng.random() < 0.5 for _ in range(10)), 10) for _ in range(500)]
    k0, n0 = totals(cl0)
    g0, w0 = boot_ratio_ci(cl0, B=B, seed=seed), wilson(k0, n0)
    d = max(abs(g0[0] - w0[0]), abs(g0[1] - w0[1]))
    ok0 = d <= 0.003
    print(f"  rho=0  군집 {pct(g0[0])}–{pct(g0[1])} vs Wilson {pct(w0[0])}–{pct(w0[1])}  "
          f"최대차 {d * 100:.3f}%p  {'통과' if ok0 else '★실패'}")
    if not ok0:
        fails.append("C4 rho=0")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--rule", required=True)
    ap.add_argument("--detector", default="promptinject.AttackRogueString")
    ap.add_argument("--base-generator-name", default="target-anythingllm")
    ap.add_argument("--rule-generator-name", default="gateway-anythingllm")
    ap.add_argument("-B", type=int, default=B_DEFAULT)
    ap.add_argument("--seed", type=int, default=SEED_DEFAULT)
    ap.add_argument("--no-c1", action="store_true",
                    help="합성 자료로 돌릴 때만. 실제 리포트에는 쓰지 않는다")
    a = ap.parse_args()
    fails: list[str] = []

    base = collect(pathlib.Path(a.base), a.detector, a.base_generator_name)
    rule = collect(pathlib.Path(a.rule), a.detector, a.rule_generator_name)

    print("# 군집을 반영한 CI — 사전 등록 D-062")
    print()
    print(f"  대표 판정기 {a.detector}   B={a.B}  seed={a.seed}  percentile 95%")
    print("  군집 단위는 프롬프트 해시다(제너레이터 이름 정규화 후).")
    print("  점추정은 바꾸지 않는다. 기존 Wilson CI를 지우지 않고 병기한다. p값은 내지 않는다.")
    print()

    common = set(base) & set(rule)
    passed = {k for k in common if rule[k]["blocked"] == 0}
    blocked_all = {k for k in common if rule[k]["blocked"] == rule[k]["n"]}
    partial = common - passed - blocked_all

    print("## C2. 집계 경로")
    for nm, st in (("베이스라인", base), ("+룰", rule)):
        att = sum(v["attempts"] for v in st.values())
        out = sum(v["n"] for v in st.values())
        agree = sum(n for _, n in clusters(st, st.keys(), "asr")) == out
        print(f"  {nm:<6} 고유 프롬프트 {len(st)}  attempt {att}  총 출력 {out}  "
              f"Σ(프롬프트별 출력)=총 출력: {'일치' if agree else '★불일치'}")
        if not agree:
            fails.append(f"C2 {nm}")
    print(f"  공통 {len(common)}   +룰 기준 전건통과 {len(passed)} / "
          f"전건차단 {len(blocked_all)} / 부분차단 {len(partial)}")
    if partial:
        print("  ★ 부분차단이 있다. 프롬프트 단위 결정성이 깨졌다.")
    print()

    got = {
        "base_all":      totals(clusters(base, common, "asr")),
        "rule_block":    totals(clusters(rule, common, "blocked")),
        "rule_asr_blk":  totals(clusters(rule, common, "asr")),
        "rule_asr_pass": totals(clusters(rule, passed, "asr")),
        "base_passed":   totals(clusters(base, passed, "asr")),
        "base_blocked":  totals(clusters(base, blocked_all, "asr")),
    }
    print("## C1. 점추정 대조 — 비율이 아니라 (분자, 분모) 정수쌍으로 본다")
    if a.no_c1:
        print("  --no-c1: 합성 자료 실행이므로 대조하지 않는다.")
        for key, v in got.items():
            print(f"  {key:<16} {v}")
    else:
        for key, want in EXPECTED.items():
            ok = got[key] == want
            print(f"  {key:<16} 기존 {want}  이번 {got[key]}  {'일치' if ok else '★불일치'}")
            if not ok:
                fails.append(f"C1 {key}")
    print()

    positive_controls(a.B, a.seed, fails)

    specs = [
        ("베이스라인 ASR", clusters(base, common, "asr")),
        ("+룰 차단율", clusters(rule, common, "blocked")),
        ("+룰 ASR_blk", clusters(rule, common, "asr")),
        ("+룰 ASR_pass", clusters(rule, passed, "asr")),
        ("base ∩ 통과", clusters(base, passed, "asr")),
        ("base ∩ 차단", clusters(base, blocked_all, "asr")),
    ]
    rows = [measure(nm, cl, a.B, a.seed, fails) for nm, cl in specs]

    order = sorted(passed)
    pairs = [((base[k]["fails"] - base[k]["fb"], base[k]["n"]),
              (rule[k]["fails"] - rule[k]["fb"], rule[k]["n"])) for k in order]
    d1 = ratio([p[1] for p in pairs]) - ratio([p[0] for p in pairs])
    ci1 = boot_paired_diff_ci(pairs, B=a.B, seed=a.seed)
    ca = clusters(base, sorted(blocked_all), "asr")
    cb = clusters(base, order, "asr")
    d2 = ratio(cb) - ratio(ca)
    ci2 = boot_unpaired_diff_ci(ca, cb, B=a.B, seed=a.seed)

    if fails:
        print("## 판정")
        print("  ★ 무효 조건에 걸렸다. **숫자를 내지 않는다**(D-062 9절).")
        for f in fails:
            print(f"    - {f}")
        print("  규칙을 고쳐 맞추지 않는다. 원인부터 본다.")
        return 2

    print("## 단일 비율 — Wilson / 군집 병기")
    for r in rows:
        print(r)
    print()

    print("## 검정 1 — 짝지은 차이 (같은 통과 프롬프트에서 +룰 − 베이스라인)")
    print(f"  점추정 {d1 * 100:+.2f}%p   군집 95% CI {ci1[0] * 100:+.2f} ~ {ci1[1] * 100:+.2f}%p"
          f"   (프롬프트 {len(pairs)}개를 통째로 재표집, 두 팔이 함께 따라온다)")
    print(f"  0 포함: {'예 — 군집을 반영하면 차이의 증거가 약해진다' if ci1[0] <= 0 <= ci1[1] else '아니오 — 차이의 방향은 유지된다'}")
    print()

    print("## 검정 2 — 짝이 아닌 차이 (룰이 통과시킨 군 − 막은 군, 베이스라인 안에서)")
    print(f"  점추정 {d2 * 100:+.2f}%p   군집 95% CI {ci2[0] * 100:+.2f} ~ {ci2[1] * 100:+.2f}%p")
    print(f"  0 포함: {'예 — 선택성 차이의 증거 없음' if ci2[0] <= 0 <= ci2[1] else '아니오'}")
    print()
    print("  ※ 동등성은 주장하지 않는다. CI가 0을 포함하면 '차이의 증거 없음'까지만 쓴다.")
    print("  ※ p값을 새로 만들지 않았다(D-062 4절). 내는 것은 차이의 CI까지다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
