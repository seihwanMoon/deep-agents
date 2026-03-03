import json
import re

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




def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-zA-Z0-9가-힣_]+", text.lower()) if len(tok) >= 2}


def _rag_score(query_tokens: set[str], raw_query: str, doc: AgentDocument) -> tuple[int, int, int]:
    doc_text = (doc.content or "").lower()
    doc_tokens = _tokenize(doc_text)
    overlap = query_tokens.intersection(doc_tokens)

    substring_hits = sum(1 for tok in query_tokens if tok in doc_text)
    phrase_boost = 1 if raw_query and raw_query in doc_text else 0

    # Prefer lexical overlap first, then broad substring matches, then full phrase match.
    return (len(overlap), substring_hits, phrase_boost)


def _select_rag_docs(message: str, docs: list[AgentDocument], top_k: int = 5) -> list[AgentDocument]:
    query_tokens = _tokenize(message)
    raw_query = message.strip().lower()
    if not query_tokens and not raw_query:
        return docs[:top_k]

    scored: list[tuple[tuple[int, int, int], AgentDocument]] = []
    for doc in docs:
        score = _rag_score(query_tokens, raw_query, doc)
        scored.append((score, doc))

    scored.sort(key=lambda x: (x[0][0], x[0][1], x[0][2], -x[1].chunk_index), reverse=True)
    selected = [doc for score, doc in scored if score[0] > 0 or score[1] > 0 or score[2] > 0][:top_k]
    return selected if selected else docs[:top_k]

def _conversation_title_from_message(message: str) -> str:
    title = message.strip()[:40]
    return title or "Chat"


def _retitle_from_first_user_message(messages: list[Message], default_title: str) -> str:
    for m in messages:
        if m.role == "user" and m.content.strip():
            return m.content.strip()[:40]
    return default_title


@router.post("/{agent_id}/chat")
async def chat(agent_id: int, body: ChatRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_agent_or_404(agent_id, user.id, db)

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    pii = PIIMiddleware()
    clean_message = pii.mask(body.message)

    if body.conversation_id is not None:
        conversation = await _get_conversation_or_404(agent_id, body.conversation_id, user.id, db)
    else:
        conversation = Conversation(agent_id=agent_id, user_id=user.id, title=_conversation_title_from_message(clean_message))
        db.add(conversation)
        await db.flush()

    docs = (
        await db.execute(
            select(AgentDocument).where(AgentDocument.agent_id == agent_id).order_by(AgentDocument.chunk_index)
        )
    ).scalars().all()
    docs = _select_rag_docs(body.message, docs, top_k=5)
    rag_context = "\n".join([d.content for d in docs])
    rag_sources = [{"file_name": d.file_name, "chunk_index": d.chunk_index} for d in docs]

    summarized = SummarizationMiddleware().before_invoke([clean_message])[0]
    final_message = f"{summarized}\n\n[RAG]\n{rag_context}" if rag_context else summarized

    db.add(Message(conversation_id=conversation.id, role="user", content=clean_message))

    graph = build_local_echo_graph()
    env = await inject_secrets(user.id, db)
    with with_secrets(env):
        result = await graph.ainvoke(build_initial_state(final_message))
    assistant_messages = result.get("messages", []) if isinstance(result, dict) else []
    assistant_text = getattr(assistant_messages[-1], "content", "") if assistant_messages else ""

    db.add(Message(conversation_id=conversation.id, role="assistant", content=assistant_text))
    conversation.updated_at = utcnow()
    await db.commit()

    async def event_stream():
        if rag_sources:
            yield f"data: {json.dumps({'type': 'sources', 'sources': rag_sources}, ensure_ascii=False)}\n\n"

        if assistant_text:
            yield f"data: {json.dumps({'type': 'token', 'content': assistant_text}, ensure_ascii=False)}\n\n"

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
