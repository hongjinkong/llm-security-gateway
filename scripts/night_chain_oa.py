#!/usr/bin/env python3
"""D-092 주말 무인 연결 — 앞 밤 런처가 끝나면 그 밤의 실행 상태를 보존하고 다음 밤을 착수한다.

  nohup python3 scripts/night_chain_oa.py --after oa_dan_20261009_01 --next pi \
    >> results/night_chain_20261009.log 2>&1 &

순서
  1. 시작 검사: results/night_<after>.log에 `D-081 밤샘 시작: <after>`가 있고 night_run_oa.sh가 돌고 있어야 한다.
     아니면 아무것도 하지 않고 끝난다(종료 2). 앞 밤 없이 다음 밤이 바로 착수되는 것을 막는다.
  2. 대기: --poll-seconds(기본 300)마다 night_run_oa.sh 프로세스와 실행 중인 garak_ 컨테이너가 모두 없어질 때까지.
     --max-wait-hours(기본 40)를 넘으면 다음 밤을 착수하지 않고 끝난다(종료 3).
  3. 앞 밤 상태 보존(D-081 §12·§13 회수 1단계와 같은 파일): results/containerlogs/<after>/ 아래
     exitcodes.txt(inspect·host_boot·보존 시각), garak 팔 로그, llm-gateway.log, target-anythingllm.log.gz.
     있는 파일은 덮어쓰지 않는다. 감사 사본·팔 리포트 사본이 없으면(런처가 중간에 멈춘 경우) 이때 복사한다.
     다음 밤 런처가 gateway를 다시 만들면 앞 밤의 gateway 로그가 사라지므로 반드시 착수 전에 한다.
  4. 다음 밤 착수: bash scripts/night_run_oa.sh <next> <그날 YYYYMMDD> >> results/night_oa_<next>_<날짜>_01.log
     런처의 검사(이름 충돌·verify·E1/E3/E5)는 그대로다. 끝나면 종료 코드를 남긴다.

앞 밤이 유효든 무효든(C1 멈춤 포함) 다음 밤은 착수한다 — 두 밤은 독립이다. 재시도는 하지 않는다.

D-100: 팔이 셋(none·rule·turn)이고, dan은 팔마다 조각 컨테이너·리포트(`<팔>_p1`~`_p3`)가 생긴다.
보존은 있는 것만 한다 — 조각이 없는 밤(pi·enc)과 두 팔짜리 옛 밤도 그대로 다룬다.

종료 코드: 0 다음 밤 런처 종료 0 / 1 다음 밤 런처 종료≠0 / 2 시작 검사 실패 / 3 대기 시간 초과
"""
from __future__ import annotations

import argparse
import gzip
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

ROOT = Path("/home/smhrd/project/llm-security-gateway")
LAUNCHER = "scripts/night_run_oa.sh"
LAUNCHER_PATTERN = "scripts/night_run_oa.sh"
RUN_ID = re.compile(r"^oa_(pi|dan|enc)_\d{8}_01$")
INSPECT_FORMAT = ("{{.Name}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} status={{.State.Status}} "
                  "start={{.State.StartedAt}} end={{.State.FinishedAt}}")
ARMS = ("none", "rule", "turn")
PART_SUFFIXES = ("_p1", "_p2", "_p3")   # D-100: dan은 팔마다 garak을 세 조각으로 나눠 돌린다


class System:
    """docker·pgrep·런처 호출을 한곳에 모은다. 테스트는 이 클래스를 가짜로 바꿔 끼운다."""

    def __init__(self, root: Path):
        self.root = root

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def launcher_running(self) -> bool:
        return self._run(["pgrep", "-f", LAUNCHER_PATTERN]).returncode == 0

    def garak_running(self) -> bool:
        return bool(self._run(["docker", "ps", "-q", "--filter", "name=garak_"]).stdout.strip())

    def container_exists(self, name: str) -> bool:
        return self._run(["docker", "container", "inspect", name]).returncode == 0

    def inspect_line(self, name: str) -> str:
        return self._run(["docker", "inspect", "--format", INSPECT_FORMAT, name]).stdout.decode(
            "utf-8", "replace").strip()

    def logs(self, name: str) -> bytes:
        """`docker logs NAME > f 2>&1`과 같은 내용(두 흐름을 섞은 순서 그대로)."""
        return self._run(["docker", "logs", name]).stdout

    def host_boot(self) -> str:
        return self._run(["uptime", "-s"]).stdout.decode("utf-8", "replace").strip()

    def now(self) -> datetime:
        return datetime.now().astimezone()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def launch(self, night: str, day: str, log_path: Path) -> int:
        with open(log_path, "ab") as f:
            return subprocess.run(["bash", LAUNCHER, night, day], cwd=self.root,
                                  stdout=f, stderr=subprocess.STDOUT).returncode


def last_line(path: Path) -> str:
    lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def write_new(path: Path, data: bytes, log: Callable[[str], None]) -> None:
    if path.exists():
        log(f"보존 건너뜀(이미 있음): {path}")
        return
    path.write_bytes(data)
    log(f"보존: {path} ({len(data)}바이트)")


def copy_new(src: Path, dst: Path, what: str, log: Callable[[str], None]) -> None:
    if dst.exists():
        log(f"{what} 사본 있음(런처가 만듦): {dst}")
    elif not src.exists():
        log(f"{what} 원본 없음: {src}")
    else:
        shutil.copyfile(src, dst)
        log(f"{what} 사본 복사(런처 대신): {src} → {dst}")


def preserve(sysm: System, root: Path, after: str, log: Callable[[str], None]) -> None:
    out = root / "results" / "containerlogs" / after
    out.mkdir(parents=True, exist_ok=True)
    arms = [f"garak_{after}_{arm}{suf}" for arm in ARMS for suf in ("",) + PART_SUFFIXES
            if sysm.container_exists(f"garak_{after}_{arm}{suf}")]
    names = arms + ["llm-gateway", "target-anythingllm"]
    text = "\n".join(sysm.inspect_line(n) for n in names)
    text += f"\nhost_boot={sysm.host_boot()}\nsaved_at={sysm.now().isoformat(timespec='seconds')} (night_chain_oa.py)\n"
    write_new(out / "exitcodes.txt", text.encode("utf-8"), log)
    for name in arms:
        write_new(out / f"{name}.log", sysm.logs(name), log)
    write_new(out / "llm-gateway.log", sysm.logs("llm-gateway"), log)
    write_new(out / "target-anythingllm.log.gz", gzip.compress(sysm.logs("target-anythingllm"), compresslevel=9), log)

    audit = root / "logs" / "gateway.jsonl"
    copy_new(audit, root / "results" / f"audit_{after}.jsonl", "감사", log)
    if audit.exists():
        with open(audit, "rb") as f:
            log(f"감사 로그 줄 수(보존 시점): {sum(1 for _ in f)}")
    runs = root / "garak" / "logs" / "garak_runs"
    for arm in ARMS:
        name = f"{after}_{arm}"
        copy_new(runs / f"{name}.report.jsonl", root / "results" / f"{name}.report.jsonl", f"{arm} 리포트", log)
        for suf in PART_SUFFIXES:            # 런처가 중간에 멈췄으면 이은 팔 리포트가 없다 — 조각이라도 남긴다
            if (runs / f"{name}{suf}.report.jsonl").exists():
                copy_new(runs / f"{name}{suf}.report.jsonl", root / "results" / f"{name}{suf}.report.jsonl",
                         f"{arm}{suf} 리포트", log)


def chain(sysm: System, root: Path, after: str, nxt: str, poll: float, max_wait_hours: float,
          log: Callable[[str], None]) -> int:
    night_log = root / "results" / f"night_{after}.log"
    marker = f"D-081 밤샘 시작: {after}"
    if not night_log.is_file() or marker not in night_log.read_text(encoding="utf-8", errors="replace"):
        log(f"시작 검사 실패: {night_log}에 '{marker}' 없음 — 아무것도 하지 않는다")
        return 2
    if not sysm.launcher_running():
        log("시작 검사 실패: night_run_oa.sh가 돌고 있지 않다 — 앞 밤 없이 다음 밤을 착수하지 않는다")
        return 2

    log(f"대기 시작: {after} 런처가 끝나면 {nxt} 착수 (확인 간격 {poll}초, 최대 {max_wait_hours}시간)")
    start = sysm.now()
    polls = 0
    while sysm.launcher_running() or sysm.garak_running():
        if (sysm.now() - start).total_seconds() > max_wait_hours * 3600:
            log(f"대기 시간 초과({max_wait_hours}시간) — {nxt}를 착수하지 않는다")
            return 3
        sysm.sleep(poll)
        polls += 1
        if polls % 12 == 0:
            log(f"대기 중 (night log 마지막 줄: {last_line(night_log)})")

    log(f"앞 밤 종료 확인. night log 마지막 줄: {last_line(night_log)}")
    preserve(sysm, root, after, log)

    day = sysm.now().strftime("%Y%m%d")
    next_log = root / "results" / f"night_oa_{nxt}_{day}_01.log"
    log(f"다음 밤 착수: bash {LAUNCHER} {nxt} {day} >> {next_log}")
    code = sysm.launch(nxt, day, next_log)
    log(f"다음 밤 런처 종료 exit={code}")
    return 0 if code == 0 else 1


def main(argv: list[str] | None = None, sysm: System | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--after", required=True, help="앞 밤 run_id, 예: oa_dan_20261009_01")
    ap.add_argument("--next", required=True, choices=("pi", "dan", "enc"), dest="nxt")
    ap.add_argument("--poll-seconds", type=float, default=300)
    ap.add_argument("--max-wait-hours", type=float, default=40)
    ap.add_argument("--root", type=Path, default=ROOT)
    a = ap.parse_args(argv)
    if not RUN_ID.match(a.after):
        ap.error(f"--after 형식 오류: {a.after} (예: oa_dan_20261009_01)")
    sysm = sysm or System(a.root)

    def log(msg: str) -> None:
        print(f"[{sysm.now().isoformat(timespec='seconds')}] {msg}", flush=True)

    return chain(sysm, a.root, a.after, a.nxt, a.poll_seconds, a.max_wait_hours, log)


if __name__ == "__main__":
    raise SystemExit(main())
