"""`scripts/night_chain_oa.py` — D-092 주말 무인 연결(앞 밤 종료 대기 → 상태 보존 → 다음 밤 착수).

docker·pgrep·런처는 가짜 System으로 바꿔 끼운다. 실제 컨테이너·garak·타겟은 쓰지 않는다.
보는 것: 시작 검사(앞 밤 시작 줄·런처 실행 중), 대기(런처와 garak 컨테이너 둘 다), 대기 시간 초과,
보존 파일(덮어쓰지 않음, C1 멈춤으로 rule 컨테이너가 없는 경우), 감사·리포트 사본, 다음 밤 이름·날짜·종료 코드.
"""
from __future__ import annotations

import gzip
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import night_chain_oa as nc  # noqa: E402

AFTER = "oa_dan_20261009_01"
KST = timezone(timedelta(hours=9))


class FakeSystem:
    def __init__(self, root: Path, *, launcher_polls=2, garak_polls=0, arms=("none", "rule"),
                 launch_code=0, start=datetime(2026, 10, 9, 11, 30, tzinfo=KST)):
        self.root = root
        self.launcher_left = launcher_polls + 1     # 시작 검사에서 한 번 더 묻는다
        self.garak_left = garak_polls
        self.arms = arms
        self.launch_code = launch_code
        self.clock = start
        self.launched: list[tuple[str, str, Path]] = []
        self.slept = 0

    def launcher_running(self):
        if self.launcher_left > 0:
            self.launcher_left -= 1
            return True
        return False

    def garak_running(self):
        if self.garak_left > 0:
            self.garak_left -= 1
            return True
        return False

    def container_exists(self, name):
        return any(name == f"garak_{AFTER}_{arm}" for arm in self.arms)

    def inspect_line(self, name):
        return f"/{name} exit=0 oom=false status=exited"

    def logs(self, name):
        return f"log of {name}\n".encode()

    def host_boot(self):
        return "2026-10-06 10:38:08"

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.slept += 1
        self.clock += timedelta(seconds=seconds)

    def launch(self, night, day, log_path):
        self.launched.append((night, day, log_path))
        return self.launch_code


def make_root(tmp: Path, *, started=True, audit_copy=False, rule_report=True) -> Path:
    (tmp / "results").mkdir()
    (tmp / "logs").mkdir()
    runs = tmp / "garak" / "logs" / "garak_runs"
    runs.mkdir(parents=True)
    lines = ["[2026-10-09T11:23:08+09:00] D-081 밤샘 시작: " + AFTER] if started else ["other"]
    lines.append("[2026-10-10T06:24:15+09:00] ERROR launcher exit=2")
    (tmp / "results" / f"night_{AFTER}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp / "logs" / "gateway.jsonl").write_text("a\nb\nc\n", encoding="utf-8")
    if audit_copy:
        (tmp / "results" / f"audit_{AFTER}.jsonl").write_text("launcher copy\n", encoding="utf-8")
    (runs / f"{AFTER}_none.report.jsonl").write_text("none\n", encoding="utf-8")
    if rule_report:
        (runs / f"{AFTER}_rule.report.jsonl").write_text("rule\n", encoding="utf-8")
    (tmp / "results" / f"{AFTER}_none.report.jsonl").write_text("none\n", encoding="utf-8")
    return tmp


def run(root: Path, fake: FakeSystem, *extra: str) -> int:
    return nc.main(["--after", AFTER, "--next", "pi", "--poll-seconds", "300", "--root", str(root), *extra], sysm=fake)


def test_waits_preserves_and_launches(tmp_path, capsys):
    root = make_root(tmp_path)
    fake = FakeSystem(root, launcher_polls=3, garak_polls=2)
    assert run(root, fake) == 0
    assert fake.slept == 5                       # 런처 3회 + garak 2회
    day = "20261009"                             # 가짜 시계: 11:30 + 25분
    assert fake.launched == [("pi", day, root / "results" / f"night_oa_pi_{day}_01.log")]
    out = root / "results" / "containerlogs" / AFTER
    ex = (out / "exitcodes.txt").read_text(encoding="utf-8")
    assert f"/garak_{AFTER}_none exit=0" in ex and f"/garak_{AFTER}_rule exit=0" in ex
    assert "/llm-gateway" in ex and "/target-anythingllm" in ex
    assert "host_boot=2026-10-06 10:38:08" in ex and "saved_at=2026-10-09T11:55:00+09:00" in ex
    assert (out / f"garak_{AFTER}_rule.log").read_bytes() == f"log of garak_{AFTER}_rule\n".encode()
    assert (out / "llm-gateway.log").read_bytes() == b"log of llm-gateway\n"
    assert gzip.decompress((out / "target-anythingllm.log.gz").read_bytes()) == b"log of target-anythingllm\n"
    assert (root / "results" / f"audit_{AFTER}.jsonl").read_text(encoding="utf-8") == "a\nb\nc\n"
    assert (root / "results" / f"{AFTER}_rule.report.jsonl").read_text(encoding="utf-8") == "rule\n"
    log = capsys.readouterr().out
    assert "감사 사본 복사(런처 대신)" in log and "감사 로그 줄 수(보존 시점): 3" in log
    assert "ERROR launcher exit=2" in log         # 앞 밤 마지막 줄을 남긴다
    assert "다음 밤 런처 종료 exit=0" in log


def test_preservation_happens_before_launch(tmp_path):
    root = make_root(tmp_path)
    seen = {}

    class Recording(FakeSystem):
        def launch(self, night, day, log_path):
            seen["gateway_log"] = (root / "results" / "containerlogs" / AFTER / "llm-gateway.log").exists()
            return super().launch(night, day, log_path)

    assert run(root, Recording(root)) == 0
    assert seen == {"gateway_log": True}


def test_existing_files_are_not_overwritten(tmp_path, capsys):
    root = make_root(tmp_path, audit_copy=True)
    out = root / "results" / "containerlogs" / AFTER
    out.mkdir(parents=True)
    (out / "llm-gateway.log").write_bytes(b"kept\n")
    assert run(root, FakeSystem(root)) == 0
    assert (out / "llm-gateway.log").read_bytes() == b"kept\n"
    assert (root / "results" / f"audit_{AFTER}.jsonl").read_text(encoding="utf-8") == "launcher copy\n"
    assert (root / "results" / f"{AFTER}_none.report.jsonl").read_text(encoding="utf-8") == "none\n"
    log = capsys.readouterr().out
    assert "보존 건너뜀(이미 있음)" in log and "감사 사본 있음(런처가 만듦)" in log


def test_c1_stop_without_rule_container(tmp_path, capsys):
    root = make_root(tmp_path, rule_report=False)
    fake = FakeSystem(root, arms=("none",))
    assert run(root, fake) == 0
    out = root / "results" / "containerlogs" / AFTER
    assert (out / f"garak_{AFTER}_none.log").exists()
    assert not (out / f"garak_{AFTER}_rule.log").exists()
    assert f"garak_{AFTER}_rule" not in (out / "exitcodes.txt").read_text(encoding="utf-8")
    assert "rule 리포트 원본 없음" in capsys.readouterr().out
    assert len(fake.launched) == 1


def test_refuses_without_start_line(tmp_path, capsys):
    root = make_root(tmp_path, started=False)
    fake = FakeSystem(root)
    assert run(root, fake) == 2
    assert fake.launched == [] and not (root / "results" / "containerlogs").exists()
    assert "시작 검사 실패" in capsys.readouterr().out


def test_refuses_when_launcher_not_running(tmp_path, capsys):
    root = make_root(tmp_path)
    fake = FakeSystem(root)
    fake.launcher_left = 0
    assert run(root, fake) == 2
    assert fake.launched == []
    assert "돌고 있지 않다" in capsys.readouterr().out


def test_timeout_does_not_launch_or_preserve(tmp_path, capsys):
    root = make_root(tmp_path)
    fake = FakeSystem(root, launcher_polls=10_000)
    assert run(root, fake, "--max-wait-hours", "1") == 3
    assert fake.launched == [] and not (root / "results" / "containerlogs").exists()
    assert fake.slept == 13                      # 확인은 잠들기 전에 한다: 3,600초는 아직, 3,900초에서 초과
    assert "대기 시간 초과" in capsys.readouterr().out


def test_next_launcher_failure_returns_1(tmp_path, capsys):
    root = make_root(tmp_path)
    assert run(root, FakeSystem(root, launch_code=2)) == 1
    assert "다음 밤 런처 종료 exit=2" in capsys.readouterr().out


def test_next_day_name_uses_launch_date(tmp_path):
    root = make_root(tmp_path)
    fake = FakeSystem(root, launcher_polls=13, start=datetime(2026, 10, 9, 23, 0, tzinfo=KST))   # 23:00 + 65분
    assert run(root, fake) == 0
    assert fake.launched[0][1] == "20261010"     # 앞 밤이 자정을 넘겨 끝나면 그날 날짜로 이름을 짓는다
    assert fake.launched[0][2].name == "night_oa_pi_20261010_01.log"


@pytest.mark.parametrize("bad", ["oa_dan_2026109_01", "oa_xx_20261009_01", "oa_dan_20261009_02", "dan"])
def test_after_name_must_be_launcher_run_id(tmp_path, bad):
    with pytest.raises(SystemExit) as e:
        nc.main(["--after", bad, "--next", "pi", "--root", str(tmp_path)], sysm=FakeSystem(tmp_path))
    assert e.value.code == 2


def test_launcher_pattern_does_not_match_chain_itself():
    assert nc.LAUNCHER_PATTERN not in "python3 scripts/night_chain_oa.py --after oa_dan_20261009_01 --next pi"
    assert nc.LAUNCHER_PATTERN in "bash scripts/night_run_oa.sh dan 20261009"
