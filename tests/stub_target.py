"""가짜 타겟 앱 — 맥북에서 프록시를 검증하기 위한 도구. 게이트웨이 코드가 아니다.

맥북에는 AnythingLLM 상태가 없으므로(PROGRESS 주의사항), 타겟 흉내만 내는
최소 서버를 띄운다. 핵심은 '받은 것을 그대로 되돌려주는' echo 필드다.
이게 있어야 프록시가 요청을 망가뜨렸는지 비교로 확인할 수 있다.
"""
import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="stub target")
# 실제 AnythingLLM처럼 gzip 응답을 만든다 → 프록시의 content-encoding 처리 검증용
app.add_middleware(GZipMiddleware, minimum_size=100)


# D-086: 상류가 **실제로 받은** chat 본문. 응답은 게이트웨이가 복원하므로 응답만으로는
# "원문이 상류로 가지 않았다"를 증명할 수 없다. 이 기록이 그 증거다(테스트 전용 프로세스 메모리).
RECEIVED: list[str] = []


@app.get("/")
async def root():
    return {"ok": True}


@app.get("/__stub/received")
async def received():
    return {"bodies": RECEIVED}


@app.post("/api/v1/workspace/{slug}/chat")
async def chat(slug: str, request: Request):
    payload = await request.json()
    return {
        "id": "stub", "type": "textResponse",
        "textResponse": f"[stub] slug={slug} msg={payload.get('message')}",
        "sources": [], "metrics": {"duration": 0.01},
        "echo": {
            # 타겟이 마스킹된 본문을 받았는지. 불리언이라 4-F의 복원에 영향받지 않는다.
            # (echo.body는 복원 대상이므로 그것만으로는 마스킹 여부를 확인할 수 없다)
            "masked_seen": "[PII:" in (payload.get("message") or ""),
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "body": payload,
            "auth": request.headers.get("authorization"),
            "content_type": request.headers.get("content-type"),
        },
    }


def _message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"] for part in content
            if isinstance(part, dict) and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return ""


@app.post("/v1/chat/completions")
@app.post("/v1beta/openai/chat/completions")   # D-086 경로 매핑 확인용 (Gemini 모양)
async def openai_chat(request: Request):
    """OpenAI 호환 입구의 테스트 타겟. 모델을 흉내낼 뿐 공격 시나리오는 만들지 않는다.
    model 이름으로 상류 오류를 흉내낸다: stub-401 / stub-429 / stub-slow(2초 지연)."""
    RECEIVED.append((await request.body()).decode("utf-8", errors="replace"))
    payload = await request.json()
    model = payload.get("model") if isinstance(payload, dict) else None
    if model == "stub-401":
        return JSONResponse(status_code=401, content={"error": {
            "message": "Incorrect API key provided", "type": "invalid_request_error",
            "param": None, "code": "invalid_api_key"}})
    if model == "stub-429":
        return JSONResponse(status_code=429, headers={
            "retry-after": "7", "x-ratelimit-remaining-requests": "0"}, content={"error": {
            "message": "Rate limit reached", "type": "requests", "param": None,
            "code": "rate_limit_exceeded"}})
    if model == "stub-slow":
        await asyncio.sleep(2)
    messages = payload.get("messages") if isinstance(payload, dict) else None
    messages = messages if isinstance(messages, list) else []
    texts = [(m.get("role"), _message_text(m)) for m in messages if isinstance(m, dict)]
    user = next((text for role, text in reversed(texts) if role == "user"), "")
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": 0,
        "model": payload.get("model", "stub"),
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": f"[stub] {user}"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "gateway_test": {
            "user_masked_seen": any(role == "user" and "[PII:" in text for role, text in texts),
            "system_raw_seen": any(role == "system" and "system@example.com" in text
                                   for role, text in texts),
            "tool_raw_seen": any(role == "tool" and "rag@example.com" in text
                                 for role, text in texts),
            "auth": request.headers.get("authorization"),
            "path": request.url.path,
        },
    }
