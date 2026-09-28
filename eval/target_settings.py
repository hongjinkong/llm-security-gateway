"""
target_settings.py — 타겟 워크스페이스의 측정 조건과 그 검증 (D-082).
setup_target.py가 이 값을 세우고, 이 함수로 실제 워크스페이스와 대조한다.
네트워크·환경변수를 쓰지 않으므로 테스트에서 그대로 불러온다.
"""

SETTINGS = {
    "topN": 2,
    "openAiHistory": 0,      # D-015: 시도 간 독립성 확보. 이력 누적 시 컨텍스트 초과로 500 발생

    "similarityThreshold": 0.25,
    "openAiTemp": 0.7,
    "chatMode": "query",
    # D-082: 워크스페이스 개별 공급자·모델을 비워 시스템값(Compose의 LLM_PROVIDER·*_MODEL_PREF)을
    # 따르게 한다. 개별값이 남아 있으면 그것이 우선해 gateway를 건너뛴다(P1 실행 #1).
    "chatProvider": None,
    "chatModel": None,
}


def workspace_mismatches(w: dict, sys_prompt: str) -> list[str]:
    """실제 워크스페이스 w가 SETTINGS·시스템 프롬프트와 다른 항목을 사람이 읽을 줄로 돌려준다."""
    out = []
    for k, v in SETTINGS.items():
        # 키가 없는 것을 None으로 보지 않는다. w.get(k)는 없는 키도 None이라 null 기대값을 조용히 통과시킨다.
        if k not in w:
            out.append(f"불일치 {k}: 기대 {v!r} / 실제 (키 없음)")
        elif w[k] != v:
            out.append(f"불일치 {k}: 기대 {v!r} / 실제 {w[k]!r}")
    if (w.get("openAiPrompt") or "").strip() != sys_prompt.strip():
        out.append("불일치 openAiPrompt")
    return out
