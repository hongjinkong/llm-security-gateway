"""D-129(PLAN 19단계): 보안 백서·법적 위치 메모(변호사 검토 전 초안)·PoC 리포트 — 문서 존재·링크·길이·개인정보 꼴 없음, 리포트에 원문·가짜 값 없음, 숫자 검산."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

from gateway.detectors.patterns import find_all

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CORPUS = ROOT / "eval" / "pii" / "corpus.jsonl"


def _poc():
    spec = importlib.util.spec_from_file_location("poc_report", ROOT / "scripts" / "poc_report.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_p1_documents_exist_are_linked_and_hold_no_personal_data():
    """P1: 두 문서가 있고 README 두 언어가 링크한다. 법률 메모는 9,000자 이하이고 머리에 '변호사 검토 전 초안'이 있다. 두 문서에 가리는 개인정보 꼴이 없다(합성 값도 없다)."""
    wp, legal = DOCS / "security-whitepaper.md", DOCS / "legal-position.md"
    assert wp.exists() and legal.exists()
    for readme in ("README.md", "README.en.md"):
        text = (ROOT / readme).read_text(encoding="utf-8")
        assert "docs/security-whitepaper.md" in text and "docs/legal-position.md" in text, readme
    memo = legal.read_text(encoding="utf-8")
    assert len(memo) <= 9000 and "변호사 검토 전 초안" in memo.split("\n## ")[0] and "법적 자문이 아니다" in memo
    for p in (wp, legal):
        body = p.read_text(encoding="utf-8")
        assert not [f for f in find_all(body) if f.mask], p.name            # 백서·메모에 전화·이메일·주민번호 꼴이 없다
    assert "D-128" in wp.read_text(encoding="utf-8") and "제28조의4" in memo and "제28조의2" in memo


def test_p2_report_has_no_raw_text_and_no_surrogates(tmp_path):
    """P2: 합성 코퍼스 표본으로 리포트를 만들면 샘플 원문도 발급한 가짜 값도 리포트에 없다 — 모양과 개수만. CLI도 같은 리포트를 파일로 쓴다."""
    poc = _poc()
    items = [json.loads(x) for x in CORPUS.read_text(encoding="utf-8").splitlines() if x][::8]     # 코퍼스 전체에서 고르게 — 앞 300줄에는 주민·카드·전화뿐이다(리뷰)
    a = poc.analyze(items, frozenset(poc.REGEX_KINDS), frozenset(k for k in poc.DETECT_ONLY if k in poc.REGEX_KINDS))
    text = poc.report(a, "corpus.jsonl")
    assert a["samples"] == 300 and a["issued"] > 0 and a["tokens"]
    assert {"rrn", "card", "phone", "email", "secret", "passport"} <= set(a["masked"])            # 글자가 든 종류의 모양 표도 아래 검사를 지난다
    values = {it["text"][f.start:f.end] for it in items for f in find_all(it["text"]) if f.mask}
    assert len(values) > 100 and not [v for v in values if len(v) >= 6 and v in text]              # 가린 값 자체가 리포트에 없다
    for it in items:
        value = it["text"]
        assert value not in text and value.strip()[:24] not in text, it["id"]
    assert not any(tok in text for tok in a["tokens"])
    # 리포트에서 개인정보 꼴로 잡히는 것은 모양 문자열뿐이다(이메일의 모양 `xxxx@xxxxxxx.xxx`도 이메일 꼴이다) — 실제 글자·숫자가 든 것은 없다
    assert not [text[f.start:f.end] for f in find_all(text) if f.mask and re.search(r"[0-9a-tvwyzA-Z가-힣]", text[f.start:f.end])]
    assert "## 종류별 탐지" in text and "## 오탐 후보" in text and "## 복원률" in text and "p95" in text
    sample = tmp_path / "s.jsonl"
    sample.write_bytes(b"\xef\xbb\xbf" + ("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items[:50]) + "\n{\"no_text\": 1}\nnot json\n").encode() + b"\xff\xfe broken\n" + b"[" * 3000 + b"\n")   # BOM·깨진 바이트·깊은 중첩
    out = tmp_path / "r.md"
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "poc_report.py"), str(sample), "--out", str(out)], capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stderr
    body = out.read_text(encoding="utf-8")
    assert "샘플 50건(건너뜀 4" in body and not any(it["text"] in body for it in items[:50])        # BOM 뒤 첫 줄도 읽었다
    typo = subprocess.run([sys.executable, str(ROOT / "scripts" / "poc_report.py"), str(sample), "--detect-kinds", "acount"], capture_output=True, text=True, cwd=ROOT)
    assert typo.returncode != 0 and "모르는 감사만 종류" in typo.stderr


def test_p3_counts_match_find_all_and_restore_is_complete():
    """P3: 종류별 탐지 수(가림 + 감사만) = find_all로 직접 센 수, 복원 수 = 발급 수(가짜 값을 그대로 되돌리면 전부 돌아온다), 잔여 0, 샘플 전부 원문과 같다."""
    poc = _poc()
    items = [json.loads(x) for x in CORPUS.read_text(encoding="utf-8").splitlines() if x][:400]
    kinds = frozenset(poc.REGEX_KINDS)
    detect = frozenset(k for k in poc.DETECT_ONLY if k in poc.REGEX_KINDS)
    a = poc.analyze(items, kinds, detect)
    want_masked: dict[str, int] = {}
    want_audit: dict[str, int] = {}
    for it in items:
        for f in find_all(it["text"]):
            d = want_audit if (f.kind in detect or not f.mask) else want_masked
            d[f.kind] = d.get(f.kind, 0) + 1
    assert a["masked"] == want_masked and a["audit"] == want_audit
    assert a["issued"] == sum(want_masked.values()) and a["restored"] == a["issued"] and a["residual"] == 0 and a["exact"] == a["samples"]
    assert poc.shape("010-1234-5678 홍길동 ab") == "###-####-#### ㅇㅇㅇ xx" and poc.shape("x" * 50).endswith("…")
    assert poc.shape("Ab1 가-ü") == "xx# ㅇ-u" and poc.percentile([1.0, 2.0, 3.0, 4.0], 0.5) == 3.0
    # 허용한 글자만 그대로 낸다 — 원 글자·전각 기호는 ?, 줄바꿈·탭은 ␤, 표를 깨는 |·`도 ?(리뷰)
    assert poc.shape("\u24d0\u24d1@example.com\n010\t1|2`3\uff20") == "??@xxxxxxx.xxx␤###␤#?#?#?"
    assert set("".join(poc.shape(chr(c)) for c in range(0x80, 0x3000))) <= set("#xuㅇ?␤")
