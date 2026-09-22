#!/usr/bin/env python3
"""돌고 있는 밤샘 런이 어디까지 갔는지 본다. **읽기 전용이다.**

파일만 읽는다 — docker 명령도, 컨테이너 접촉도 없다. 런 중에 아무 때나 돌려도
2026-08-19 사고(아침에 compose 명령을 쳐서 돌던 팔을 끊음)와 같은 일이 생기지 않는다.

출처 두 가지:
  results/night_ctl.log                      팔별 START/END 시각 (night_run_ctl.sh의 say())
  garak/logs/garak_runs/<팔>.report.jsonl    진행 중에도 계속 쓰인다 (compose 바인드 마운트)

한 attempt는 리포트에 두 줄로 남는다 — status=1(생성)과 status=2(채점 끝).
그래서 **완료 수 = status 2인 attempt 줄 수**다.

★ 남은 시간은 측정이 아니라 추정이다. 팔 시작부터의 평균 속도를 남은 건수에 곱한 값이고,
  프로브마다 프롬프트 길이가 달라 실제 속도는 구간마다 흔들린다. 판정에 쓰지 않는다.

사용: python3 scripts/run_progress.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ARMS = ("dan_c_base", "dan_c_none", "dan_c_pii")
ATTEMPTS = 400                       # D-060: 팔마다 채점된 attempt 400 (paired_arms V4)
LOG = Path("results/night_ctl.log")
REPORT_DIR = Path("garak/logs/garak_runs")
LINE = re.compile(r"^\[(?P<ts>[^\]]+)\] (?P<ev>START|END) (?P<name>\S+)")


def marks() -> dict[str, dict[str, list[datetime]]]:
    out: dict[str, dict[str, list[datetime]]] = {a: {"START": [], "END": []} for a in ARMS}
    if not LOG.exists():
        return out
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE.match(line)
        if m and m["name"] in out:
            out[m["name"]][m["ev"]].append(datetime.fromisoformat(m["ts"]))
    return out


def done(arm: str) -> int:
    """채점이 끝난 attempt 수. 진행 중이라 마지막 줄이 잘려 있을 수 있어 건너뛴다."""
    p = REPORT_DIR / f"{arm}.report.jsonl"
    if not p.exists():
        return 0
    n = 0
    with p.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue          # 지금 쓰이는 중인 마지막 줄
            if d.get("entry_type") == "attempt" and d.get("status") == 2:
                n += 1
    return n


def hm(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def main() -> int:
    now = datetime.now(timezone.utc).astimezone()
    mk = marks()
    print(f"D-060 세 팔 진행 — {now:%Y-%m-%d %H:%M:%S %z}   (읽기 전용)\n")
    print(f"{'팔':<12} {'상태':<10} {'시작':<17} {'경과':>9} {'완료/400':>10} {'진척':>7}")
    print("-" * 70)

    remaining_s = 0.0
    rate = None                      # 초/attempt. 진행 중인 팔에서만 구한다.
    for arm in ARMS:
        st, en = mk[arm]["START"], mk[arm]["END"]
        n = done(arm)
        if not st:
            print(f"{arm:<12} {'대기':<10} {'-':<17} {'-':>9} {n:>6}/400 {n/ATTEMPTS*100:>6.1f}%")
            continue
        if len(st) > 1:
            print(f"{arm:<12} ⚠ START가 {len(st)}번 찍혔다 — paired_arms V3이 무효로 잡는다")
        begin = st[-1]
        if en:
            state, elapsed = "끝남", (en[-1] - begin).total_seconds()
        else:
            state, elapsed = "▶ 진행 중", (now - begin).total_seconds()
            if n:
                rate = elapsed / n
                remaining_s += rate * (ATTEMPTS - n)
        print(f"{arm:<12} {state:<10} {begin:%m-%d %H:%M:%S}   {hm(elapsed):>9} "
              f"{n:>6}/400 {n/ATTEMPTS*100:>6.1f}%")

    started = [a for a in ARMS if mk[a]["START"]]
    not_started = [a for a in ARMS if not mk[a]["START"]]
    if rate and not_started:
        remaining_s += rate * ATTEMPTS * len(not_started)

    print()
    if all(mk[a]["END"] for a in ARMS):
        first = mk[ARMS[0]]["START"][-1]
        last = mk[ARMS[-1]]["END"][-1]
        print(f"세 팔 전부 끝났다. 총 {hm((last - first).total_seconds())}.")
        print("→ MORNING_20260922.md 1번부터. compose 명령 전에 컨테이너 로그부터 건진다.")
    elif rate:
        eta = now.timestamp() + remaining_s
        print(f"현재 팔 평균 {rate/60:.2f}분/attempt   남은 {hm(remaining_s)} 추정")
        print(f"종료 예상 {datetime.fromtimestamp(eta).astimezone():%Y-%m-%d %H:%M} "
              f"(안 끝난 팔 {len(ARMS) - len([a for a in ARMS if mk[a]['END']])}개)")
        print("★ 추정이다. 팔 시작부터의 평균이라 프로브 구간에 따라 흔들린다. 판정에 쓰지 않는다.")
    elif started:
        print("진행 중인 팔의 리포트가 아직 비어 있다. 첫 attempt 채점 전이다.")
    else:
        print(f"{LOG}에 START가 없다. 런이 아직 시작되지 않았거나 경로가 다르다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
