#!/usr/bin/env python3
"""임베딩 왕복 지연의 자릿수 확인 (D-043 폴백 게이트).

⚠️ 이 스크립트의 출력은 **측정값이 아니다.** EVAL 5.2 표에 넣지 않는다.
   게이트웨이를 거치지 않은 Ollama 단독 왕복이며, 실제 `gateway_ms`는
   여기에 체인 오버헤드와 numpy 코사인이 더해진다.

용도는 하나다 — 학원 PC에서 15시간짜리 garak 런을 시작하기 **전에**,
D-043의 지연 예산(기본 50ms)을 넘는지 5분 안에 확인하는 것.
넘으면 그 자리에서 경량 다국어 모델 폴백을 검토한다(D-006 되돌릴 조건).

두 기계에서 같은 명령으로 돌려 나란히 비교한다.
    python3 scripts/embed_latency.py

의존성 없음(표준 라이브러리만). 게이트웨이 코드를 import 하지 않으므로
Python 3.11 미만에서도 동작한다.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

# 길이 측정용 중립 더미 문장. 공격 문구를 쓰지 않는다 —
# 여기서 재는 것은 '내용'이 아니라 '길이에 따른 연산 비용'이다.
# 코퍼스가 한·영 두 갈래이므로(D-042) 더미도 두 언어를 섞는다.
FILLER = (
    "회사의 연차 휴가 규정과 신청 절차에 대해 문의드립니다. "
    "I would like to ask about the annual leave policy and how to apply for it. "
)

# 문자 수 기준. 토큰 수가 아니다 — 토크나이저 없이 토큰을 세지 않는다.
# garak dan 계열 프롬프트가 장문이라는 점을 감안해 3000자까지 본다.
LENGTHS = [20, 200, 1000, 3000]


def pct(sorted_vals: list[float], q: float) -> float:
    """scripts/fpr_report.py와 동일한 nearest-rank 계열 백분위.

    선형 보간을 쓰면 같은 로그에서 다른 숫자가 나온다(D-035 주석 참조).
    두 스크립트의 숫자를 나란히 놓으려면 방식이 같아야 한다.
    """
    if not sorted_vals:
        return 0.0
    i = min(int(len(sorted_vals) * q), len(sorted_vals) - 1)
    return sorted_vals[i]


def make_input(target_chars: int) -> str:
    reps = target_chars // len(FILLER) + 1
    return (FILLER * reps)[:target_chars]


def post_ms(url: str, payload: dict, timeout: float) -> float:
    """왕복 1회의 벽시계 시간(ms). 응답 본문은 끝까지 읽는다."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()
    return (time.perf_counter() - t0) * 1000.0


def get_ms(url: str, timeout: float) -> float:
    t0 = time.perf_counter()
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        resp.read()
    return (time.perf_counter() - t0) * 1000.0


def probe_dim(endpoint: str, model: str, timeout: float) -> int | None:
    """벡터 차원. numpy 배열 모양을 정하는 데 필요하다."""
    data = json.dumps(
        {"model": model, "input": "차원 확인"}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{endpoint}/api/embed", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
        return len(body["embeddings"][0])
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--endpoint", default="http://localhost:11434")
    p.add_argument("--model", default="bge-m3")
    p.add_argument("--reps", type=int, default=30, help="길이당 반복 횟수")
    p.add_argument("--warmup", type=int, default=3, help="집계에서 제외할 선행 호출")
    p.add_argument("--budget-ms", type=float, default=50.0, help="D-043 지연 예산")
    p.add_argument("--timeout", type=float, default=120.0)
    a = p.parse_args()

    embed_url = f"{a.endpoint}/api/embed"

    print("# 임베딩 지연 자릿수 (D-043 게이트)")
    print("※ 측정값이 아니다. EVAL 5.2 표에 넣지 않는다.")
    print(f"  endpoint={a.endpoint}  model={a.model}  reps={a.reps}  warmup={a.warmup}\n")

    # 1. HTTP 바닥값. 추론이 없는 엔드포인트라 순수 왕복 비용만 나온다.
    #    이 값을 빼야 '얼마가 모델 연산인지'를 말할 수 있다.
    try:
        floor = sorted(get_ms(f"{a.endpoint}/api/tags", a.timeout) for _ in range(6))[1:]
    except urllib.error.URLError as e:
        print(f"❌ Ollama에 붙지 못했다: {e}")
        print(f"   {a.endpoint} 가 떠 있는지 확인할 것 (ollama serve).")
        return 1
    floor_p50 = pct(sorted(floor), 0.50)
    print("## HTTP 바닥값 (/api/tags, 추론 없음)")
    print(f"  p50 {floor_p50:7.1f} ms   ← 이만큼은 모델과 무관한 왕복 비용\n")

    dim = probe_dim(a.endpoint, a.model, a.timeout)
    if dim is None:
        print(f"❌ {a.model} 임베딩 호출에 실패했다. ollama list 로 모델을 확인할 것.")
        return 1
    print(f"## 벡터 차원: {dim}\n")

    # 2. 길이별 왕복. 실제로 임베딩할 것은 garak 공격 프롬프트이고
    #    dan 계열은 장문이다. 짧은 문장 하나로 판단하면 과소평가한다.
    print("## 입력 길이별 왕복 (모델 연산 = 아래 값 − 바닥값)")
    print(f"  {'문자수':>8}  {'p50':>9}  {'p95':>9}  {'최소':>9}  {'최대':>9}  판정")

    worst_p95 = 0.0
    rows: list[tuple[int, float, float]] = []
    for n_chars in LENGTHS:
        text = make_input(n_chars)
        payload = {"model": a.model, "input": text}
        try:
            for _ in range(a.warmup):
                post_ms(embed_url, payload, a.timeout)
            samples = sorted(
                post_ms(embed_url, payload, a.timeout) for _ in range(a.reps)
            )
        except urllib.error.URLError as e:
            print(f"  {n_chars:>8}  호출 실패: {e}")
            continue

        p50, p95 = pct(samples, 0.50), pct(samples, 0.95)
        worst_p95 = max(worst_p95, p95)
        rows.append((n_chars, p50, p95))
        mark = "예산 내" if p95 <= a.budget_ms else "초과"
        print(
            f"  {n_chars:>8}  {p50:>7.1f}ms  {p95:>7.1f}ms  "
            f"{samples[0]:>7.1f}ms  {samples[-1]:>7.1f}ms  {mark}"
        )

    # 3. 판정. 예산은 가장 나쁜 길이 기준으로 본다 —
    #    공격 프롬프트가 길다는 것이 바로 이 탐지기의 부담이기 때문이다.
    print(f"\n## 판정 (D-043 예산 {a.budget_ms:.0f}ms, 최장 입력 기준)")
    if worst_p95 <= a.budget_ms:
        print(f"  ✅ 최악 p95 {worst_p95:.1f}ms ≤ {a.budget_ms:.0f}ms — 예산 내")
        print("     단 이 값에는 체인 오버헤드와 코사인 계산이 빠져 있다.")
    else:
        print(f"  ❌ 최악 p95 {worst_p95:.1f}ms > {a.budget_ms:.0f}ms — 예산 초과")
        print("     D-006 '되돌릴 조건'에 따라 경량 다국어 모델 폴백을 검토할 것.")
        print("     all-minilm은 후보가 아니다 — D-006 실측에서 한국어 판별 마진이")
        print("     0.132로 bge-m3(0.275)의 절반이라 D-044의 갭 기반 임계값과 맞지 않는다.")

    if len(rows) >= 2:
        (c0, p0, _), (c1, p1, _) = rows[0], rows[-1]
        if p0 > 0:
            print(
                f"\n  길이 {c0}자 → {c1}자에서 p50이 {p0:.1f}ms → {p1:.1f}ms "
                f"({p1 / p0:.1f}배)"
            )
            print("  공격 프롬프트가 장문이면 이 배수만큼 불리해진다.")

    print("\n※ 문자 수는 토큰 수가 아니다. 토크나이저 없이 토큰을 세지 않았다.")
    print("※ 두 기계(맥북 / 학원 PC)에서 같은 명령으로 돌려 나란히 비교할 것.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
