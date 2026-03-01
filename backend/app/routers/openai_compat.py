import json

from fastapi import APIRouter, Header, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent

router = APIRouter(prefix="/v1", tags=["openai-compat"])


@router.post('/chat/completions')
async def chat_completions(body: dict, authorization: str = Header(default=""), db: AsyncSession = Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.replace("Bearer ", "", 1)

    model = body.get("model", "")
    if not model.startswith("agent-"):
        raise HTTPException(status_code=400, detail="model must be agent-{id}")
    try:
        agent_id = int(model.split("agent-")[1])
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid model format")

    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent or agent.webhook_token != token:
        raise HTTPException(status_code=401, detail="Invalid token")

    messages = body.get("messages", [])
    user_content = messages[-1].get("content", "") if messages else ""
    answer = f"[agent-{agent_id}] {user_content}"

    if body.get("stream"):
        async def stream():
            payload = {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "choices": [{"delta": {"content": answer}, "index": 0, "finish_reason": None}],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
    }
