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


def _validate_messages(messages: list[dict]) -> str:
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list")

    for msg in messages:
        if not isinstance(msg, dict):
            raise HTTPException(status_code=400, detail="each message must be an object")
        if "role" not in msg or "content" not in msg:
            raise HTTPException(status_code=400, detail="each message requires role and content")

    return str(messages[-1].get("content", ""))


@router.get("/models")
async def list_models(authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.replace("Bearer ", "", 1)

    agent = (await db.execute(select(Agent).where(Agent.webhook_token == token))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid token")

    model_id = f"agent-{agent.id}"
    created = int(agent.created_at.timestamp()) if agent.created_at else int(time.time())
    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": created,
                "owned_by": "deep-agents",
            }
        ],
    }


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
    user_content = _validate_messages(messages)
    answer = f"[agent-{agent_id}] {user_content}"

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    prompt_tokens = len(user_content.split())
    completion_tokens = len(answer.split())
    total_tokens = prompt_tokens + completion_tokens

    if body.get("stream"):
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))

        async def stream():
            role_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"delta": {"role": "assistant"}, "index": 0, "finish_reason": None}],
            }
            yield f"data: {json.dumps(role_chunk)}\n\n"

            words = answer.split()
            for idx, word in enumerate(words):
                content = f"{word} " if idx < len(words) - 1 else word
                content_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_name,
                    "choices": [{"delta": {"content": content}, "index": 0, "finish_reason": None}],
                }
                yield f"data: {json.dumps(content_chunk)}\n\n"

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"delta": {}, "index": 0, "finish_reason": "stop"}],
            }
            if include_usage:
                final_chunk["usage"] = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
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
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }
