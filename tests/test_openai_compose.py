"""D-075: B2 모드가 로컬 게이트웨이를 거치고 기존 기본 모드는 보존되는지 검사한다."""
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def environment(service: str) -> dict[str, str]:
    entries = COMPOSE["services"][service]["environment"]
    return dict(entry.split("=", 1) for entry in entries)


def test_existing_ollama_route_remains_the_default():
    target = environment("target-app")
    gateway = environment("gateway")
    assert target["LLM_PROVIDER"] == "${ANYTHINGLLM_LLM_PROVIDER:-ollama}"
    assert gateway["TARGET_URL"] == "${GATEWAY_TARGET_URL:-http://target-app:3001}"


def test_generic_openai_mode_routes_through_gateway_without_streaming():
    target = environment("target-app")
    assert target["GENERIC_OPEN_AI_BASE_PATH"] == "http://gateway:8080/v1"
    assert target["GENERIC_OPEN_AI_MODEL_PREF"] == "${ANYTHINGLLM_MODEL:-gemma3:4b}"
    assert target["GENERIC_OPEN_AI_MODEL_TOKEN_LIMIT"] == "4096"
    assert target["GENERIC_OPEN_AI_API_KEY"] == "local-only"
    assert target["GENERIC_OPEN_AI_STREAMING_DISABLED"] == "true"
    assert target["GENERIC_OPENAI_STREAMING_DISABLED"] == "true"


def test_embeddings_stay_on_local_ollama():
    target = environment("target-app")
    assert target["EMBEDDING_ENGINE"] == "ollama"
    assert target["EMBEDDING_BASE_PATH"] == "http://host.docker.internal:11434"
    assert target["EMBEDDING_MODEL_PREF"] == "bge-m3:latest"
