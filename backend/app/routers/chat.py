import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import User, Agent, AgentDocument
from ..schemas import ChatRequest
from ..services.agent_graph import build_local_echo_graph, build_initial_state
from ..services.secrets import inject_secrets, with_secrets
from ..middleware.builtin.pii import PIIMiddleware
from ..middleware.builtin.summarization import SummarizationMiddleware

router = APIRouter(prefix="/api/v1/agents", tags=["chat"])


@router.post("/{agent_id}/chat")
async def chat(agent_id: int, body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    docs = (
        await db.execute(select(AgentDocument).where(AgentDocument.agent_id == agent_id).order_by(AgentDocument.chunk_index).limit(5))
    ).scalars().all()
    rag_context = "\n".join([d.content for d in docs])
    pii = PIIMiddleware()
    clean_message = pii.mask(body.message)
    summarized = SummarizationMiddleware().before_invoke([clean_message])[0]
    final_message = f"{summarized}\n\n[RAG]\n{rag_context}" if rag_context else summarized

    async def event_stream():
        graph = build_local_echo_graph()
        env = await inject_secrets(user.id, db)
        with with_secrets(env):
            async for event in graph.astream_events(build_initial_state(final_message), version="v2"):
                if event["event"] == "on_chain_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    messages = chunk.get("messages", []) if isinstance(chunk, dict) else []
                    if messages:
                        payload = {"type": "token", "content": getattr(messages[-1], "content", "")}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        yield "data: {\"type\":\"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
