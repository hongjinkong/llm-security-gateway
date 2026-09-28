"""`scripts/validate_oa_arm.py` — D-081 새 구조 한 팔의 무효 검사 E1·E3·E5.

왜 새로 만드나. `validate_encoding.py`는 encoding 두 프로브·두 판정기·256개가 박혀 있어
promptinject·dan 밤에 쓸 수 없다. 새 구조에서는 두 팔 모두 게이트웨이를 거치므로
E3도 바뀐다: "base 창 감사 0건"이 아니라 **팔마다 감사 줄 수 = garak 출력 수**다(D-081 8절).

감사 로그는 append라 FPR·점검 요청이 앞에 쌓여 있다. 런처가 START 직전 줄 수를 넘기면
그 뒤만 이 팔의 줄로 센다(--audit-from).

종료 코드: 0 통과 / 2 무효
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_oa_arm as v  # noqa: E402

GEN = 10
PROBES = ("promptinject.A", "promptinject.B")
PER_PROBE = 3                      # 합성 자료: 프로브당 attempt 3개 → 출력 60개


def write(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def report_rows(name: str) -> list[dict]:
    rows: list[dict] = [{"entry_type": "start_run setup", "reporting.report_prefix": name,
                         "run.generations": GEN, "run.seed": 20260819}]
    for probe in PROBES:
        for seq in range(PER_PROBE):
            rows.append({"entry_type": "attempt", "status": 1, "probe_classname": probe, "seq": seq})
            rows.append({"entry_type": "attempt", "status": 2, "probe_classname": probe, "seq": seq,
                         "prompt": {"text": f"{probe}-{seq}"},
                         "outputs": [{"text": f"out {k}"} for k in range(GEN)]})
    rows.append({"entry_type": "completion"})
    return rows


def audit_rows(n: int, *, blocked: int = 0, prefix: int = 0) -> list[dict]:
    """prefix: 이 팔 이전에 쌓인 줄(FPR 등). 앞쪽 blocked개는 차단."""
    old = [{"request_id": f"old{i}", "path": "/api/v1/workspace/s/chat", "status": 500,
            "blocked": True} for i in range(prefix)]
    return old + [{"request_id": f"r{i}", "path": "/v1/chat/completions", "status": 200,
                   "blocked": i < blocked} for i in range(n)]


N_OUT = len(PROBES) * PER_PROBE * GEN


def make(tmp: Path, *, name="oa_pi_x_none", arm="none", blocked=0, prefix=0,
         rep=None, aud=None) -> list[str]:
    r = write(tmp / f"{name}.report.jsonl", rep if rep is not None else report_rows(name))
    a = write(tmp / "gateway.jsonl",
              aud if aud is not None else audit_rows(N_OUT, blocked=blocked, prefix=prefix))
    return ["--report", str(r), "--name", name, "--arm", arm, "--audit", str(a),
            "--audit-from", str(prefix)]


# ---------------------------------------------------------------- 정상 경로

def test_none_팔_정상(tmp_path, capsys):
    assert v.main(make(tmp_path)) == 0
    out = capsys.readouterr().out
    assert "E1 통과" in out and "E3 통과" in out
    assert f"출력 {N_OUT}" in out


def test_rule_팔은_차단_수를_보고한다(tmp_path, capsys):
    assert v.main(make(tmp_path, name="oa_pi_x_rule", arm="rule", blocked=7)) == 0
    assert "차단 7" in capsys.readouterr().out


def test_앞에_쌓인_감사_줄은_세지_않는다(tmp_path, capsys):
    """FPR·점검 요청 12줄이 앞에 있다. 이걸 세면 개수가 안 맞아 정상 팔이 무효가 된다."""
    assert v.main(make(tmp_path, prefix=12)) == 0


def test_E5_두_팔의_프롬프트가_같다(tmp_path, capsys):
    peer = write(tmp_path / "peer.report.jsonl", report_rows("oa_pi_x_none"))
    args = make(tmp_path, name="oa_pi_x_rule", arm="rule")
    assert v.main(args + ["--peer", str(peer), "--peer-name", "oa_pi_x_none"]) == 0
    assert "E5 통과" in capsys.readouterr().out


# -------------------------------------------------- E1 완주 — 전부 무효

def invalid(capsys, args, why: str) -> None:
    assert v.main(args) == 2
    err = capsys.readouterr().err
    assert why in err, err


def test_E1_completion이_없다(tmp_path, capsys):
    rep = [r for r in report_rows("oa_pi_x_none") if r["entry_type"] != "completion"]
    invalid(capsys, make(tmp_path, rep=rep), "completion 0개")


def test_E1_출력이_10개가_아니다(tmp_path, capsys):
    rep = report_rows("oa_pi_x_none")
    rep[2]["outputs"] = rep[2]["outputs"][:9]
    invalid(capsys, make(tmp_path, rep=rep), "출력 9개")


def test_E1_빈_출력(tmp_path, capsys):
    rep = report_rows("oa_pi_x_none")
    rep[2]["outputs"][4] = {"text": "  "}
    invalid(capsys, make(tmp_path, rep=rep), "빈 출력")


def test_E1_probe_seq_중복(tmp_path, capsys):
    rep = report_rows("oa_pi_x_none")
    rep.insert(-1, dict(rep[2]))
    invalid(capsys, make(tmp_path, rep=rep), "중복")


def test_E1_이름이_다르다(tmp_path, capsys):
    rep = report_rows("oa_pi_OTHER_none")
    invalid(capsys, make(tmp_path, rep=rep), "report_prefix")


def test_E1_seed가_다르다(tmp_path, capsys):
    rep = report_rows("oa_pi_x_none")
    rep[0]["run.seed"] = 1
    invalid(capsys, make(tmp_path, rep=rep), "seed")


# -------------------------------------------------- E3 감사 대조 — 전부 무효

def test_E3_감사_줄이_하나_모자라다(tmp_path, capsys):
    invalid(capsys, make(tmp_path, aud=audit_rows(N_OUT - 1)),
            f"감사 줄 {N_OUT - 1} != garak 출력 {N_OUT}")


def test_E3_감사_줄이_하나_많다(tmp_path, capsys):
    """garak 재시도나 AnythingLLM의 추가 호출. 조용히 넘기면 1:1 전제가 깨진 채 짝을 짓는다."""
    invalid(capsys, make(tmp_path, aud=audit_rows(N_OUT + 1)),
            f"감사 줄 {N_OUT + 1} != garak 출력 {N_OUT}")


def test_E3_200이_아닌_응답(tmp_path, capsys):
    aud = audit_rows(N_OUT)
    aud[5]["status"] = 400
    invalid(capsys, make(tmp_path, aud=aud), "200이 아닌")


def test_E3_다른_경로(tmp_path, capsys):
    """옛 경로(gateway → AnythingLLM)로 돌아간 흔적. 새 구조의 측정이 아니다."""
    aud = audit_rows(N_OUT)
    aud[0]["path"] = "/api/v1/workspace/s/chat"
    invalid(capsys, make(tmp_path, aud=aud), "/v1/chat/completions 아닌")


def test_E3_none_팔에_차단이_있다(tmp_path, capsys):
    invalid(capsys, make(tmp_path, blocked=1), "none 팔 차단 1")


def test_E3_request_id_중복(tmp_path, capsys):
    aud = audit_rows(N_OUT)
    aud[3]["request_id"] = aud[2]["request_id"]
    invalid(capsys, make(tmp_path, aud=aud), "request_id")


def test_E3_감사_로그가_없다(tmp_path, capsys):
    args = make(tmp_path)
    args[args.index("--audit") + 1] = str(tmp_path / "없음.jsonl")
    invalid(capsys, args, "감사 로그")


# -------------------------------------------------- E5 비교 가능성 — 무효

def test_E5_프롬프트가_하나_다르다(tmp_path, capsys):
    peer_rows = report_rows("oa_pi_x_none")
    peer_rows[2]["prompt"] = {"text": "different"}
    peer = write(tmp_path / "peer.report.jsonl", peer_rows)
    args = make(tmp_path, name="oa_pi_x_rule", arm="rule")
    invalid(capsys, args + ["--peer", str(peer), "--peer-name", "oa_pi_x_none"],
            "프롬프트 해시 불일치 1")
