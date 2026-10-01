"""`fpr_report.py --link time` — 새 경로의 감사 연결 (D-081 7절 P3).

왜 필요한가. 새 구조는 클라이언트 → AnythingLLM → gateway `/v1`이다. 게이트웨이가 붙이는
`X-Gateway-Request-Id`는 AnythingLLM에서 끝나고 클라이언트까지 오지 않는다. 그래서 실행 기록의
`request_id`가 비고, 기존 F4는 전 문항을 "연결 없음"으로 무효 처리한다.

대신 시간으로 잇는다. `fpr_run.py`는 요청을 하나씩 순서대로 보내므로 호출 창
[t_start, t_end]가 겹치지 않고, 게이트웨이 감사 줄의 `ts`는 그 창 안에 찍힌다.
**창 하나에 감사 줄이 정확히 하나**일 때만 잇는다. 0개(게이트웨이에 안 왔다)·2개 이상(한 요청이
여러 번 불렸다)·어느 창에도 없는 감사 줄(설명 안 되는 트래픽)은 전부 F4 무효다.
추측으로 짝짓지 않는다 — 자료의 부재는 결과가 아니다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_fpr_report import GOLDEN, dataset, rows, write  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import fpr_report as fr  # noqa: E402

T0 = datetime(2026, 9, 28, tzinfo=timezone.utc)


def iso(sec: float) -> str:
    return (T0 + timedelta(seconds=sec)).isoformat(timespec="milliseconds")


def as_new_path(d: dict[str, Path]) -> dict[str, Path]:
    """기존 정상 자료를 새 경로 모양으로 바꾼다. 실행 k의 창은 [10k, 10k+5]초, 감사 줄은 10k+2초."""
    for run_key, aud_key in (("off", "ao"), ("on", "an")):
        rs, aud = rows(d[run_key]), rows(d[aud_key])
        for k, (r, a) in enumerate(zip(rs, aud)):
            r["request_id"] = None
            r["t_start"], r["t_end"] = iso(10 * k), iso(10 * k + 5)
            a["ts"] = iso(10 * k + 2)
        write(d[run_key], rs)
        write(d[aud_key], aud)
    return d


def call(monkeypatch, d: dict[str, Path], *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", [
        "fpr_report.py", "--off", str(d["off"]), "--on", str(d["on"]),
        "--audit-off", str(d["ao"]), "--audit-on", str(d["an"]), *extra])
    return fr.main()


# ---------------------------------------------------------------- 정상 경로

def test_시간_연결은_헤더_연결과_같은_숫자를_낸다(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    assert call(monkeypatch, d, "--link", "time") == 1
    out = capsys.readouterr().out
    assert GOLDEN in out, "연결 방식만 바꿨는데 FPR 집계가 달라졌다"
    assert "injection_rule/R1  2건" in out


def test_창의_양끝에_찍힌_감사_줄도_잇는다(tmp_path, monkeypatch, capsys):
    """ms로 잘린 시각은 창 경계와 같아질 수 있다. 경계를 빼면 정상 자료를 무효로 만든다."""
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["an"])
    aud[0]["ts"], aud[1]["ts"] = iso(0), iso(15)      # 실행 0의 시작, 실행 1의 끝
    write(d["an"], aud)
    assert call(monkeypatch, d, "--link", "time") == 1
    assert GOLDEN in capsys.readouterr().out


def test_기본값은_여전히_헤더_연결이다(tmp_path, monkeypatch, capsys):
    """새 경로 자료를 옵션 없이 넣으면 기존 F4가 그대로 무효를 낸다 — 조용히 시간으로 넘어가지 않는다."""
    d = as_new_path(dataset(tmp_path))
    assert call(monkeypatch, d) == 2
    assert "F4" in capsys.readouterr().out


# -------------------------------------------------- 망가진 입력 — 전부 무효

def test_T1_창_안에_감사_줄이_없다(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["an"])
    del aud[4]
    write(d["an"], aud)
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out
    assert "F4" in out and "감사 줄 0개" in out


def test_T2_창_하나에_감사_줄이_둘(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["an"])
    aud.append({**aud[3], "request_id": "extra", "ts": iso(10 * 3 + 4)})
    write(d["an"], aud)
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out
    assert "감사 줄 2개" in out


def test_T3_어느_창에도_속하지_않는_감사_줄(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["ao"])
    aud.append({**aud[0], "request_id": "stray", "ts": iso(10_000)})
    write(d["ao"], aud)
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out
    assert "어느 실행 창에도 속하지 않는" in out and "stray" in out


def test_T4_실행_기록에_시각이_없다(tmp_path, monkeypatch, capsys):
    """옛 fpr_run.py 산출물(t_start 없음)을 --link time으로 넣은 경우."""
    d = as_new_path(dataset(tmp_path))
    rs = rows(d["on"])
    del rs[6]["t_start"]
    write(d["on"], rs)
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out
    assert "시각이 없는 실행" in out


def test_T5_창이_겹친다(tmp_path, monkeypatch, capsys):
    """순차 실행이라는 전제가 깨지면 시간으로는 잇지 못한다."""
    d = as_new_path(dataset(tmp_path))
    rs = rows(d["off"])
    rs[1]["t_start"] = iso(3)          # 실행 0의 창 [0, 5]와 겹친다
    write(d["off"], rs)
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out
    assert "창이 겹친다" in out


def test_T6_앞_창의_끝과_다음_창의_시작이_같은_ms면_겹침이다(tmp_path, monkeypatch, capsys):
    """D-083. SLEEP=0에서 실제로 난 경우다(관문 실행 #1, OFF 76·ON 80쌍). 공유 경계에 찍힌 감사 줄은
    두 창 모두에 속해 어느 문항 것인지 가릴 수 없다. 맞닿은 창을 허용하도록 고치면 이 테스트가 잡는다."""
    d = as_new_path(dataset(tmp_path))
    rs = rows(d["on"])
    rs[1]["t_start"] = rs[0]["t_end"]
    write(d["on"], rs)
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out
    assert "창이 겹친다" in out


# ---------------------------------------------- fpr_run.py가 창을 남기는가

def test_fpr_run은_감사_로그와_같은_형식으로_창을_남긴다(monkeypatch):
    for k, v in {"TARGET_URL": "http://x", "WORKSPACE_SLUG": "s", "TARGET_API_KEY": "k"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.syspath_prepend(str(ROOT / "eval"))
    sys.modules.pop("fpr_run", None)
    import fpr_run

    class Resp:
        status, headers = 200, {}
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"textResponse": "ok"}).encode()

    monkeypatch.setattr(fpr_run.urllib.request, "urlopen", lambda *a, **k: Resp())
    r = fpr_run.ask("q")
    start, end = (datetime.fromisoformat(r[k]) for k in ("t_start", "t_end"))
    assert start.tzinfo is not None and start <= end
    # 감사 로그 utcnow()와 같은 모양이어야 한다 (ms 단위, UTC 오프셋)
    assert len(r["t_start"]) == len(iso(0))


# ------------------------------- 2026-10-01 리뷰: load_audit이 줄을 조용히 버렸다
# request_id를 dict 키로 써서 같은 ID의 두 번째 줄이 첫 줄을 덮었다. 창 하나에 감사 줄이
# 둘이어도 link_by_time에는 하나만 보여 T2("정확히 하나")가 놓쳤다. request_id 없는 줄도
# 조용히 빠져 같은 구멍이었다. 새 기준이 아니라 기존 검증 의도의 구현 누락을 메운다.

def test_T7_같은_줄이_두_번_있다(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["an"])
    write(d["an"], aud + [aud[3]])
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out and "중복 request_id" in out


def test_T8_같은_ID의_서로_다른_줄(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["an"])
    write(d["an"], aud + [{**aud[3], "ts": iso(10 * 3 + 4), "status": 500}])
    for link in ("time", "header"):
        assert call(monkeypatch, d, "--link", link) == 2
        out = capsys.readouterr().out
        assert "FPR =" not in out and "중복 request_id" in out


def test_T9_request_id가_없는_감사_줄(tmp_path, monkeypatch, capsys):
    d = as_new_path(dataset(tmp_path))
    aud = rows(d["ao"])
    write(d["ao"], aud + [{**aud[0], "request_id": None, "ts": iso(4)}])
    assert call(monkeypatch, d, "--link", "time") == 2
    out = capsys.readouterr().out
    assert "FPR =" not in out and "request_id가 없는 줄" in out
