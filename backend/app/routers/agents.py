import uuid
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Header
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentFolder, AgentVersion, User, AgentDocument, AgentOpener, WebhookCallbackEvent
from ..schemas import AgentIn, AgentUpdate, FixRequest, FixOperation, WebhookCallbackIn
from ..tasks.agent_tasks import execute_agent
from ..time import utcnow

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _split_text(text: str, chunk_size: int = 500):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [""]


def _extract_openers(instruction: str) -> list[str]:
    openers: list[str] = []
    for line in instruction.splitlines():
        striped = line.strip()
        if striped.startswith('- '):
            openers.append(striped[2:].strip())
    return openers[:12]


def _parse_fix_operation(instruction: str) -> FixOperation:
    stripped = instruction.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON fix instruction: {exc.msg}") from exc
        return FixOperation.model_validate(data)
    return FixOperation(append_system_prompt=instruction, replace_openers=_extract_openers(instruction))


@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folders = (await db.execute(select(AgentFolder).where(AgentFolder.user_id == user.id))).scalars().all()
    agents = (await db.execute(select(Agent).where(Agent.user_id == user.id))).scalars().all()

    by_folder: dict[str, list[dict]] = {str(f.id): [] for f in folders}
    by_folder["null"] = []
    for agent in agents:
        item = {
            "id": agent.id,
            "name": agent.name,
            "folder_id": agent.folder_id,
            "is_favorite": agent.is_favorite,
            "updated_at": agent.updated_at.isoformat(),
        }
        by_folder[str(agent.folder_id) if agent.folder_id is not None else "null"].append(item)
    return {
        "folders": [{"id": f.id, "name": f.name} for f in folders],
        "agents_by_folder": by_folder,
    }


@router.post("")
async def create_agent(body: AgentIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    webhook_token = "dbuilder_" + secrets.token_urlsafe(24)
    agent = Agent(
        user_id=user.id,
        folder_id=body.folder_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        model=body.model,
        webhook_token=webhook_token,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return {"id": agent.id, "webhook_token": webhook_token}


@router.put("/{agent_id}")
async def update_agent(agent_id: int, body: AgentUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    max_version = (
        await db.execute(select(func.max(AgentVersion.version_no)).where(AgentVersion.agent_id == agent.id))
    ).scalar()
    snapshot = {
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "folder_id": agent.folder_id,
        "model": agent.model,
        "is_favorite": agent.is_favorite,
        "recursion_limit": agent.recursion_limit,
        "mcp_enabled": agent.mcp_enabled,
    }
    db.add(AgentVersion(agent_id=agent.id, version_no=(max_version or 0) + 1, snapshot=snapshot))

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(agent, field, value)
    agent.updated_at = utcnow()

    await db.commit()
    return {"ok": True}


@router.post("/{agent_id}/fix")
async def fix_agent(agent_id: int, body: FixRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    op = _parse_fix_operation(body.instruction)

    if len(op.replace_openers) > 12:
        raise HTTPException(status_code=400, detail="replace_openers supports up to 12 items")

    previous_prompt = agent.system_prompt
    previous_openers = (
        await db.execute(select(AgentOpener).where(AgentOpener.agent_id == agent.id).order_by(AgentOpener.order_no.asc()))
    ).scalars().all()

    try:
        async with db.begin_nested():
            if op.append_system_prompt.strip():
                agent.system_prompt = f"{agent.system_prompt}\n\n[fix-instruction]\n{op.append_system_prompt}".strip()
            agent.updated_at = utcnow()

            if op.replace_openers:
                existing = (await db.execute(select(AgentOpener).where(AgentOpener.agent_id == agent.id))).scalars().all()
                for item in existing:
                    await db.delete(item)
                for i, opener in enumerate(op.replace_openers):
                    if not opener.strip():
                        raise HTTPException(status_code=400, detail="replace_openers cannot include empty text")
                    db.add(AgentOpener(agent_id=agent.id, content=opener.strip(), order_no=i))

        await db.commit()
    except HTTPException:
        await db.rollback()
        raise

    return {
        "system_prompt": agent.system_prompt,
        "tools_to_add": [],
        "tools_to_remove": [],
        "openers": op.replace_openers,
        "applied": {
            "appended_prompt": bool(op.append_system_prompt.strip()),
            "replaced_openers": bool(op.replace_openers),
        },
        "before": {
            "system_prompt": previous_prompt,
            "openers_count": len(previous_openers),
        },
    }


@router.post("/{agent_id}/files")
async def upload_file(agent_id: int, upload: UploadFile = File(...), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    content = (await upload.read()).decode("utf-8", errors="ignore")
    chunks = _split_text(content)
    for idx, chunk in enumerate(chunks):
        db.add(AgentDocument(agent_id=agent.id, file_name=upload.filename or "uploaded.txt", chunk_index=idx, content=chunk, meta={}))
    await db.commit()
    return {"chunks": len(chunks)}


@router.get("/{agent_id}/snippet")
async def snippet(agent_id: int, lang: str = Query("python"), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    model_name = f"agent-{agent.id}"
    token = agent.webhook_token
    base_url = "http://localhost:8000"
    snippets = {
        "python": f'from openai import OpenAI\nclient=OpenAI(base_url="{base_url}/v1", api_key="{token}")\nprint(client.chat.completions.create(model="{model_name}", messages=[{{"role":"user","content":"hi"}}]))',
        "typescript": f'// use OpenAI SDK\n// baseURL: {base_url}/v1\n// apiKey: {token}\n',
        "curl": f'curl -X POST {base_url}/v1/chat/completions -H "Authorization: Bearer {token}" -H "Content-Type: application/json" -d "{{\\"model\\":\\"{model_name}\\",\\"messages\\":[{{\\"role\\":\\"user\\",\\"content\\":\\"hi\\"}}]}}"',
        "langchain": f'from langchain_openai import ChatOpenAI\nllm=ChatOpenAI(base_url="{base_url}/v1", api_key="{token}", model="{model_name}")',
    }
    return {"lang": lang, "snippet": snippets.get(lang, snippets["python"])}


@router.get("/{agent_id}/mcp")
async def agent_mcp(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.mcp_enabled:
        raise HTTPException(status_code=400, detail="MCP is disabled")
    return {"agent_id": agent.id, "status": "mcp-active", "endpoint": f"/api/v1/agents/{agent.id}/mcp"}


@router.post("/{agent_id}/webhook")
async def webhook(
    agent_id: int,
    payload: dict,
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    header_token = authorization.replace("Bearer ", "", 1) if authorization.startswith("Bearer ") else ""
    body_token = payload.get("token", "")
    token = header_token or body_token
    if token != agent.webhook_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    message = str(payload.get("message", "")).strip() or "webhook-run"
    execute_agent.run(agent.id, message)
    return {"accepted": True, "agent_id": agent.id, "message": message, "task_id": f"local-{uuid.uuid4()}"}


@router.post("/{agent_id}/webhook/callback")
async def webhook_callback(
    agent_id: int,
    body: WebhookCallbackIn,
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    token = authorization.replace("Bearer ", "", 1) if authorization.startswith("Bearer ") else ""
    if token != agent.webhook_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    event = WebhookCallbackEvent(
        agent_id=agent.id,
        event_id=body.event_id,
        status=body.status,
        payload=body.payload,
    )
    db.add(event)
    try:
        await db.commit()
        await db.refresh(event)
        return {"ok": True, "event_id": event.event_id, "duplicate": False}
    except IntegrityError:
        await db.rollback()
        return {"ok": True, "event_id": body.event_id, "duplicate": True}


@router.get("/{agent_id}/webhook/callbacks")
async def list_webhook_callbacks(agent_id: int, limit: int = Query(default=20, ge=1, le=100), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    rows = (
        await db.execute(
            select(WebhookCallbackEvent)
            .where(WebhookCallbackEvent.agent_id == agent.id)
            .order_by(WebhookCallbackEvent.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {"id": r.id, "event_id": r.event_id, "status": r.status, "payload": r.payload, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@router.get("/{agent_id}/openers")
async def list_openers(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    rows = (
        await db.execute(select(AgentOpener).where(AgentOpener.agent_id == agent_id).order_by(AgentOpener.order_no.asc()))
    ).scalars().all()
    return [{"id": r.id, "content": r.content, "order_no": r.order_no} for r in rows]


@router.delete("/{agent_id}")
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
    await db.commit()
    return {"ok": True}


@router.post("/import")
async def import_agent(payload: dict, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent_data = payload.get("agent", {})
    agent = Agent(
        user_id=user.id,
        folder_id=agent_data.get("folder_id"),
        name=agent_data.get("name", "Imported Agent"),
        description=agent_data.get("description", ""),
        system_prompt=agent_data.get("system_prompt", ""),
        model=agent_data.get("model", "openai:gpt-4o-mini"),
        webhook_token="dbuilder_" + secrets.token_urlsafe(24),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return {"id": agent.id}


@router.get("/{agent_id}/export")
async def export_agent(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "agent": {
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "folder_id": agent.folder_id,
            "model": agent.model,
            "is_favorite": agent.is_favorite,
            "recursion_limit": agent.recursion_limit,
            "mcp_enabled": agent.mcp_enabled,
        },
        "tools": [],
        "middlewares": [],
        "openers": [
            {"content": o.content, "order_no": o.order_no}
            for o in (
                await db.execute(select(AgentOpener).where(AgentOpener.agent_id == agent_id).order_by(AgentOpener.order_no.asc()))
            ).scalars().all()
        ],
    }


@router.get("/{agent_id}/versions")
async def list_versions(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    versions = (
        await db.execute(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version_no.desc()))
    ).scalars().all()
    return [{"version_no": v.version_no, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()} for v in versions]
