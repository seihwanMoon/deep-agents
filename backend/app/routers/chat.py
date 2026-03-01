import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import User, Agent, AgentDocument, Conversation, Message
from ..schemas import ChatRequest
from ..services.agent_graph import build_local_echo_graph, build_initial_state
from ..services.secrets import inject_secrets, with_secrets
from ..middleware.builtin.pii import PIIMiddleware
from ..middleware.builtin.summarization import SummarizationMiddleware
from ..time import utcnow

router = APIRouter(prefix="/api/v1/agents", tags=["chat"])


async def _get_agent_or_404(agent_id: int, user_id: int, db: AsyncSession) -> Agent:
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_conversation_or_404(agent_id: int, conversation_id: int, user_id: int, db: AsyncSession) -> Conversation:
    convo = (
        await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.agent_id == agent_id,
                Conversation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return convo


async def _conversation_stats(conversation_id: int, db: AsyncSession) -> dict:
    msgs = (
        await db.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc()))
    ).scalars().all()
    last_message_preview = msgs[-1].content[:80] if msgs else ""
    return {"message_count": len(msgs), "last_message_preview": last_message_preview}


def _retitle_from_first_user_message(messages: list[Message], default_title: str) -> str:
    for m in messages:
        if m.role == "user" and m.content.strip():
            return m.content.strip()[:40]
    return default_title


@router.post("/{agent_id}/chat")
async def chat(agent_id: int, body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_agent_or_404(agent_id, user.id, db)

    if body.conversation_id is not None:
        conversation = await _get_conversation_or_404(agent_id, body.conversation_id, user.id, db)
    else:
        conversation = Conversation(agent_id=agent_id, user_id=user.id, title=(body.message[:40] or "Chat"))
        db.add(conversation)
        await db.flush()

    docs = (
        await db.execute(
            select(AgentDocument)
            .where(AgentDocument.agent_id == agent_id)
            .order_by(AgentDocument.chunk_index)
            .limit(5)
        )
    ).scalars().all()
    rag_context = "\n".join([d.content for d in docs])
    rag_sources = [{"file_name": d.file_name, "chunk_index": d.chunk_index} for d in docs]

    pii = PIIMiddleware()
    clean_message = pii.mask(body.message)
    summarized = SummarizationMiddleware().before_invoke([clean_message])[0]
    final_message = f"{summarized}\n\n[RAG]\n{rag_context}" if rag_context else summarized

    db.add(Message(conversation_id=conversation.id, role="user", content=clean_message))

    async def event_stream():
        graph = build_local_echo_graph()
        env = await inject_secrets(user.id, db)
        assistant_chunks: list[str] = []
        with with_secrets(env):
            if rag_sources:
                yield f"data: {json.dumps({'type': 'sources', 'sources': rag_sources}, ensure_ascii=False)}\n\n"
            async for event in graph.astream_events(build_initial_state(final_message), version="v2"):
                if event["event"] == "on_chain_stream":
                    chunk = event.get("data", {}).get("chunk", {})
                    messages = chunk.get("messages", []) if isinstance(chunk, dict) else []
                    if messages:
                        content = getattr(messages[-1], "content", "")
                        assistant_chunks.append(content)
                        payload = {"type": "token", "content": content}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        assistant_text = "".join(assistant_chunks).strip()
        db.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_text))
        conversation.updated_at = utcnow()
        await db.commit()

        done_payload = {
            "type": "done",
            "agent_id": agent_id,
            "conversation_id": conversation.id,
            "sources_count": len(rag_sources),
        }
        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/{agent_id}/conversations")
async def list_conversations(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_agent_or_404(agent_id, user.id, db)

    stmt = select(Conversation).where(Conversation.agent_id == agent_id, Conversation.user_id == user.id)
    if q:
        stmt = stmt.where(Conversation.title.ilike(f"%{q}%"))

    rows = (
        await db.execute(
            stmt.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit)
        )
    ).scalars().all()
    data = []
    for c in rows:
        stats = await _conversation_stats(c.id, db)
        data.append({
            "id": c.id,
            "title": c.title,
            "updated_at": c.updated_at.isoformat(),
            "created_at": c.created_at.isoformat(),
            **stats,
        })
    return data


@router.get("/{agent_id}/conversations/{conversation_id}")
async def get_conversation(
    agent_id: int,
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    convo = await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    stats = await _conversation_stats(conversation_id, db)
    return {
        "id": convo.id,
        "title": convo.title,
        "created_at": convo.created_at.isoformat(),
        "updated_at": convo.updated_at.isoformat(),
        **stats,
    }


@router.put("/{agent_id}/conversations/{conversation_id}")
async def rename_conversation(
    agent_id: int,
    conversation_id: int,
    payload: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    new_title = (payload.get("title") or "").strip()
    if not new_title:
        raise HTTPException(status_code=400, detail="title is required")
    conversation.title = new_title[:255]
    conversation.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "id": conversation.id, "title": conversation.title}


@router.delete("/{agent_id}/conversations/{conversation_id}")
async def delete_conversation(
    agent_id: int,
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conversation = await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    await db.delete(conversation)
    await db.commit()
    return {"ok": True}


@router.get("/{agent_id}/conversations/{conversation_id}/messages")
async def list_messages(
    agent_id: int,
    conversation_id: int,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_conversation_or_404(agent_id, conversation_id, user.id, db)

    msgs = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in msgs]


@router.delete("/{agent_id}/conversations/{conversation_id}/messages")
async def clear_messages(agent_id: int, conversation_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    result = await db.execute(delete(Message).where(Message.conversation_id == conversation_id))
    conversation = await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    conversation.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "deleted": result.rowcount or 0}


@router.delete("/{agent_id}/conversations/{conversation_id}/messages/{message_id}")
async def delete_message(
    agent_id: int,
    conversation_id: int,
    message_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    msg = (
        await db.execute(
            select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
        )
    ).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.delete(msg)
    remaining = (
        await db.execute(
            select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id.asc())
        )
    ).scalars().all()
    conversation = await _get_conversation_or_404(agent_id, conversation_id, user.id, db)
    conversation.title = _retitle_from_first_user_message(remaining, conversation.title)
    conversation.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "id": message_id}
