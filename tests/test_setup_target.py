"""D-082: 워크스페이스 공급자 개별값을 비우고, 비었는지를 검증한다.

2026-09-28 P1 실행 #1에서 워크스페이스 `chatProvider='ollama'`가 시스템 공급자(generic-openai)보다
우선해 요청이 gateway를 건너뛰었다. setup_target.py의 설정 검증은 이 키를 보지 않아 "통과"였다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
import target_settings as ts  # noqa: E402

PROMPT = "시스템 프롬프트"

# EVAL 7절 동결값. D-082는 이 다섯 개를 바꾸지 않는다.
FROZEN = {
    "topN": 2,
    "openAiHistory": 0,
    "similarityThreshold": 0.25,
    "openAiTemp": 0.7,
    "chatMode": "query",
}


def workspace(**over) -> dict:
    """API가 돌려주는 워크스페이스 레코드 모양. 기본은 모든 조건이 맞는 상태."""
    w = {**FROZEN, "chatProvider": None, "chatModel": None, "openAiPrompt": PROMPT}
    w.update(over)
    return w


def test_t1_settings_clear_provider_and_keep_frozen_values():
    assert "chatProvider" in ts.SETTINGS and ts.SETTINGS["chatProvider"] is None
    assert "chatModel" in ts.SETTINGS and ts.SETTINGS["chatModel"] is None
    for k, v in FROZEN.items():
        assert ts.SETTINGS[k] == v, k


def test_t2_stored_ollama_provider_is_a_mismatch():
    bad = ts.workspace_mismatches(workspace(chatProvider="ollama", chatModel="gemma3:4b"), PROMPT)
    assert any("chatProvider" in b for b in bad)
    assert any("chatModel" in b for b in bad)


def test_t3_missing_key_is_not_treated_as_null():
    w = workspace()
    del w["chatProvider"]
    bad = ts.workspace_mismatches(w, PROMPT)
    assert any("chatProvider" in b for b in bad)


def test_t4_matching_workspace_has_no_mismatch():
    assert ts.workspace_mismatches(workspace(), PROMPT) == []


def test_t5_prompt_mismatch_is_still_caught():
    bad = ts.workspace_mismatches(workspace(openAiPrompt="다른 프롬프트"), PROMPT)
    assert bad == ["불일치 openAiPrompt"]
