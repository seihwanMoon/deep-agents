import json
import time
import uuid

from fastapi import APIRouter, Header, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent

router = APIRouter(prefix="/v1", tags=["openai-compat"])


def _extract_agent_id(model_name: str) -> int:
    if not model_name.startswith("agent-"):
        raise HTTPException(status_code=400, detail="model must be agent-{id}")
    try:
        return int(model_name.split("agent-")[1])
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid model format")


@router.post('/chat/completions')
async def chat_completions(body: dict, authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.replace("Bearer ", "", 1)

    model_name = body.get("model", "")
    agent_id = _extract_agent_id(model_name)

    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent or agent.webhook_token != token:
        raise HTTPException(status_code=401, detail="Invalid token")

    messages = body.get("messages", [])
    user_content = messages[-1].get("content", "") if messages else ""
    answer = f"[agent-{agent_id}] {user_content}"

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if body.get("stream"):
        async def stream():
            role_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"delta": {"role": "assistant"}, "index": 0, "finish_reason": None}],
            }
            yield f"data: {json.dumps(role_chunk)}\n\n"

            content_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"delta": {"content": answer}, "index": 0, "finish_reason": None}],
            }
            yield f"data: {json.dumps(content_chunk)}\n\n"

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(user_content.split()),
            "completion_tokens": len(answer.split()),
            "total_tokens": len(user_content.split()) + len(answer.split()),
        },
    }
