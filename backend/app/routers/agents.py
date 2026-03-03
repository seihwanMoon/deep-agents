import uuid
import json
import secrets
import csv
from io import StringIO
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Header
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentFolder, AgentVersion, User, AgentDocument, AgentOpener, WebhookCallbackEvent
from ..schemas import AgentIn, AgentUpdate, FixRequest, FixOperation, WebhookCallbackIn, OpenersReplaceIn, AgentSettingsUpdate
from ..tasks.agent_tasks import execute_agent
from ..time import utcnow

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

SNIPPET_LANGS = ("python", "typescript", "curl", "langchain")


def _agent_snapshot(agent: Agent) -> dict:
    return {
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "folder_id": agent.folder_id,
        "model": agent.model,
        "is_favorite": agent.is_favorite,
        "recursion_limit": agent.recursion_limit,
        "mcp_enabled": agent.mcp_enabled,
    }

def _split_text(text: str, chunk_size: int = 500):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [""]


def _snapshot_diff(current: dict, target: dict) -> dict:
    changed = {}
    keys = sorted(set(current.keys()) | set(target.keys()))
    for key in keys:
        before = current.get(key)
        after = target.get(key)
        if before != after:
            changed[key] = {"current": before, "target": after}
    return changed


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




@router.get("/{agent_id}")
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    opener_count = (
        await db.execute(select(func.count(AgentOpener.id)).where(AgentOpener.agent_id == agent.id))
    ).scalar() or 0
    version_count = (
        await db.execute(select(func.count(AgentVersion.id)).where(AgentVersion.agent_id == agent.id))
    ).scalar() or 0

    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "folder_id": agent.folder_id,
        "model": agent.model,
        "is_favorite": agent.is_favorite,
        "recursion_limit": agent.recursion_limit,
        "mcp_enabled": agent.mcp_enabled,
        "created_at": agent.created_at.isoformat(),
        "updated_at": agent.updated_at.isoformat(),
        "opener_count": int(opener_count),
        "version_count": int(version_count),
        "webhook_token": agent.webhook_token,
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


@router.get("/{agent_id}/settings")
async def get_agent_settings(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "agent_id": agent.id,
        "recursion_limit": agent.recursion_limit,
        "mcp_enabled": agent.mcp_enabled,
        "webhook_token": agent.webhook_token,
    }


@router.put("/{agent_id}/settings")
async def update_agent_settings(agent_id: int, body: AgentSettingsUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    payload = body.model_dump(exclude_unset=True)
    if "recursion_limit" in payload:
        value = int(payload["recursion_limit"])
        if value < 1 or value > 1000:
            raise HTTPException(status_code=400, detail="recursion_limit must be between 1 and 1000")
        payload["recursion_limit"] = value

    if not payload:
        return {"ok": True, "recursion_limit": agent.recursion_limit, "mcp_enabled": agent.mcp_enabled}

    max_version = (
        await db.execute(select(func.max(AgentVersion.version_no)).where(AgentVersion.agent_id == agent.id))
    ).scalar()
    db.add(AgentVersion(agent_id=agent.id, version_no=(max_version or 0) + 1, snapshot=_agent_snapshot(agent)))

    if "recursion_limit" in payload:
        agent.recursion_limit = payload["recursion_limit"]

    if "mcp_enabled" in payload:
        agent.mcp_enabled = bool(payload["mcp_enabled"])

    agent.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "recursion_limit": agent.recursion_limit, "mcp_enabled": agent.mcp_enabled}


@router.put("/{agent_id}")
async def update_agent(agent_id: int, body: AgentUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    payload = body.model_dump(exclude_unset=True)
    if not payload:
        return {"ok": True}

    max_version = (
        await db.execute(select(func.max(AgentVersion.version_no)).where(AgentVersion.agent_id == agent.id))
    ).scalar()
    snapshot = _agent_snapshot(agent)
    db.add(AgentVersion(agent_id=agent.id, version_no=(max_version or 0) + 1, snapshot=snapshot))

    if "recursion_limit" in payload:
        value = int(payload["recursion_limit"])
        if value < 1 or value > 1000:
            raise HTTPException(status_code=400, detail="recursion_limit must be between 1 and 1000")
        payload["recursion_limit"] = value

    for field, value in payload.items():
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


@router.get("/{agent_id}/snippet/languages")
async def snippet_languages(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"default": "python", "languages": list(SNIPPET_LANGS)}


@router.get("/{agent_id}/snippet")
async def snippet(agent_id: int, lang: str = Query("python"), db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if lang not in SNIPPET_LANGS:
        raise HTTPException(status_code=400, detail=f"Unsupported lang: {lang}")

    model_name = f"agent-{agent.id}"
    token = agent.webhook_token
    base_url = "http://localhost:8000"
    snippets = {
        "python": f'from openai import OpenAI\nclient=OpenAI(base_url="{base_url}/v1", api_key="{token}")\nprint(client.chat.completions.create(model="{model_name}", messages=[{{"role":"user","content":"hi"}}]))',
        "typescript": f'// use OpenAI SDK\n// baseURL: {base_url}/v1\n// apiKey: {token}\n',
        "curl": f'curl -X POST {base_url}/v1/chat/completions -H "Authorization: Bearer {token}" -H "Content-Type: application/json" -d "{{\"model\":\"{model_name}\",\"messages\":[{{\"role\":\"user\",\"content\":\"hi\"}}]}}"',
        "langchain": f'from langchain_openai import ChatOpenAI\nllm=ChatOpenAI(base_url="{base_url}/v1", api_key="{token}", model="{model_name}")',
    }
    return {"lang": lang, "snippet": snippets[lang]}


@router.get("/{agent_id}/mcp")
async def agent_mcp(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.mcp_enabled:
        raise HTTPException(status_code=400, detail="MCP is disabled")
    return {"agent_id": agent.id, "status": "mcp-active", "endpoint": f"/api/v1/agents/{agent.id}/mcp"}


@router.post("/{agent_id}/webhook-token/rotate")
async def rotate_webhook_token(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    old_token = agent.webhook_token
    agent.webhook_token = "dbuilder_" + secrets.token_urlsafe(24)
    agent.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "webhook_token": agent.webhook_token, "rotated": old_token != agent.webhook_token}



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


@router.put("/{agent_id}/openers")
async def replace_openers(agent_id: int, body: OpenersReplaceIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    clean_openers = [str(x).strip() for x in body.openers]
    if len(clean_openers) > 12:
        raise HTTPException(status_code=400, detail="openers supports up to 12 items")
    if any(not x for x in clean_openers):
        raise HTTPException(status_code=400, detail="openers cannot include empty text")

    max_version = (
        await db.execute(select(func.max(AgentVersion.version_no)).where(AgentVersion.agent_id == agent.id))
    ).scalar()
    db.add(AgentVersion(agent_id=agent.id, version_no=(max_version or 0) + 1, snapshot=_agent_snapshot(agent)))

    existing_rows = (
        await db.execute(select(AgentOpener).where(AgentOpener.agent_id == agent.id))
    ).scalars().all()
    for row in existing_rows:
        await db.delete(row)

    for i, content in enumerate(clean_openers):
        db.add(AgentOpener(agent_id=agent.id, content=content, order_no=i))

    agent.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "count": len(clean_openers)}


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
    openers_payload = payload.get("openers", [])

    if not isinstance(openers_payload, list):
        raise HTTPException(status_code=400, detail="openers must be a list")
    if len(openers_payload) > 12:
        raise HTTPException(status_code=400, detail="openers supports up to 12 items")

    parsed_openers: list[tuple[str, int]] = []
    for idx, item in enumerate(openers_payload):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="each opener must be an object")
        content = str(item.get("content", "")).strip()
        if not content:
            raise HTTPException(status_code=400, detail="opener content cannot be empty")
        order_no = int(item.get("order_no", idx))
        parsed_openers.append((content, order_no))

    agent = Agent(
        user_id=user.id,
        folder_id=agent_data.get("folder_id"),
        name=agent_data.get("name", "Imported Agent"),
        description=agent_data.get("description", ""),
        system_prompt=agent_data.get("system_prompt", ""),
        model=agent_data.get("model", "openai:gpt-4o-mini"),
        webhook_token="dbuilder_" + secrets.token_urlsafe(24),
        is_favorite=bool(agent_data.get("is_favorite", False)),
        recursion_limit=int(agent_data.get("recursion_limit", 25)),
        mcp_enabled=bool(agent_data.get("mcp_enabled", False)),
    )
    db.add(agent)
    await db.flush()

    for content, order_no in sorted(parsed_openers, key=lambda x: x[1]):
        db.add(AgentOpener(agent_id=agent.id, content=content, order_no=order_no))

    await db.commit()
    await db.refresh(agent)
    return {"id": agent.id, "openers": len(parsed_openers)}


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




@router.post("/{agent_id}/versions/snapshot")
async def create_version_snapshot(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    max_version = (
        await db.execute(select(func.max(AgentVersion.version_no)).where(AgentVersion.agent_id == agent.id))
    ).scalar()
    next_no = (max_version or 0) + 1
    db.add(AgentVersion(agent_id=agent.id, version_no=next_no, snapshot=_agent_snapshot(agent)))
    await db.commit()
    return {"ok": True, "version_no": next_no}

@router.get("/{agent_id}/versions")
async def list_versions(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    include_snapshot: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    versions = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return [
        ({"version_no": v.version_no, "snapshot": v.snapshot, "created_at": v.created_at.isoformat()} if include_snapshot
         else {"version_no": v.version_no, "created_at": v.created_at.isoformat()})
        for v in versions
    ]




@router.get("/{agent_id}/versions/compare")
async def compare_versions(
    agent_id: int,
    from_version: int = Query(..., ge=1),
    to_version: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from_row = (
        await db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version_no == from_version)
        )
    ).scalar_one_or_none()
    if not from_row:
        raise HTTPException(status_code=404, detail="from_version not found")

    if to_version is None:
        target_snapshot = _agent_snapshot(agent)
        target_label = "current"
    else:
        to_row = (
            await db.execute(
                select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version_no == to_version)
            )
        ).scalar_one_or_none()
        if not to_row:
            raise HTTPException(status_code=404, detail="to_version not found")
        target_snapshot = to_row.snapshot or {}
        target_label = f"v{to_version}"

    base_snapshot = from_row.snapshot or {}
    changed = _snapshot_diff(base_snapshot, target_snapshot)
    return {
        "from_version": from_version,
        "to": target_label,
        "changed_count": len(changed),
        "changed_fields": changed,
    }

@router.get("/{agent_id}/versions/{version_no}")
async def get_version_detail(agent_id: int, version_no: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    version = (
        await db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version_no == version_no)
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    return {"version_no": version.version_no, "snapshot": version.snapshot, "created_at": version.created_at.isoformat()}


@router.get("/{agent_id}/versions/{version_no}/diff")
async def version_diff(agent_id: int, version_no: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    version = (
        await db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version_no == version_no)
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    current_snapshot = _agent_snapshot(agent)
    target_snapshot = version.snapshot or {}
    changed = _snapshot_diff(current_snapshot, target_snapshot)
    return {
        "version_no": version_no,
        "changed_count": len(changed),
        "changed_fields": changed,
    }










@router.get("/{agent_id}/versions/meta/timeline")
async def version_timeline(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
            .limit(limit)
        )
    ).scalars().all()

    items = []
    prev_snapshot = _agent_snapshot(agent)
    prev_label = "current"
    for row in rows:
        snap = row.snapshot or {}
        changed = _snapshot_diff(snap, prev_snapshot)
        items.append({
            "version_no": row.version_no,
            "created_at": row.created_at.isoformat(),
            "compared_to": prev_label,
            "changed_count": len(changed),
            "changed_fields": list(changed.keys()),
        })
        prev_snapshot = snap
        prev_label = f"v{row.version_no}"

    return {"count": len(items), "items": items}



@router.get("/{agent_id}/versions/meta/fields")
async def version_field_stats(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
            .limit(limit)
        )
    ).scalars().all()

    prev_snapshot = _agent_snapshot(agent)
    counts: dict[str, int] = {}
    for row in rows:
        changed = _snapshot_diff(row.snapshot or {}, prev_snapshot)
        for key in changed.keys():
            counts[key] = counts.get(key, 0) + 1
        prev_snapshot = row.snapshot or {}

    sorted_items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "versions_scanned": len(rows),
        "fields": [{"field": k, "changes": v} for k, v in sorted_items],
    }



@router.get("/{agent_id}/versions/meta/search")
async def search_versions_by_changed_field(
    agent_id: int,
    field: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    field = field.strip()
    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
            .limit(200)
        )
    ).scalars().all()

    prev_snapshot = _agent_snapshot(agent)
    prev_label = "current"
    matched: list[dict] = []
    for row in rows:
        snap = row.snapshot or {}
        changed = _snapshot_diff(snap, prev_snapshot)
        if field in changed:
            matched.append({
                "version_no": row.version_no,
                "created_at": row.created_at.isoformat(),
                "compared_to": prev_label,
                "change": changed[field],
            })
            if len(matched) >= limit:
                break
        prev_snapshot = snap
        prev_label = f"v{row.version_no}"

    return {"field": field, "count": len(matched), "items": matched}



@router.get("/{agent_id}/versions/meta/report")
async def version_report(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
            .limit(limit)
        )
    ).scalars().all()

    prev_snapshot = _agent_snapshot(agent)
    prev_label = "current"
    timeline_items: list[dict] = []
    field_counts: dict[str, int] = {}

    for row in rows:
        snap = row.snapshot or {}
        changed = _snapshot_diff(snap, prev_snapshot)
        for key in changed.keys():
            field_counts[key] = field_counts.get(key, 0) + 1
        timeline_items.append({
            "version_no": row.version_no,
            "created_at": row.created_at.isoformat(),
            "compared_to": prev_label,
            "changed_count": len(changed),
            "changed_fields": list(changed.keys()),
        })
        prev_snapshot = snap
        prev_label = f"v{row.version_no}"

    fields_sorted = sorted(field_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {
        "count": len(rows),
        "latest": timeline_items[0] if timeline_items else None,
        "timeline": timeline_items,
        "field_stats": [{"field": k, "changes": v} for k, v in fields_sorted],
    }



@router.get("/{agent_id}/versions/meta/report/summary")
async def version_report_summary(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)
    lines = [
        f"Agent Version Report Summary (agent_id={agent_id})",
        f"- analyzed versions: {report['count']}",
    ]
    latest = report.get("latest")
    if latest:
        lines.append(f"- latest version: v{latest['version_no']} (changed={latest['changed_count']})")

    top_fields = report.get("field_stats", [])[:5]
    if top_fields:
        lines.append("- top changed fields:")
        for item in top_fields:
            lines.append(f"  - {item['field']}: {item['changes']}")

    timeline = report.get("timeline", [])[:5]
    if timeline:
        lines.append("- recent timeline:")
        for item in timeline:
            lines.append(
                f"  - v{item['version_no']} vs {item['compared_to']}: changed={item['changed_count']} fields={','.join(item['changed_fields']) or '-'}"
            )

    return {"summary": "\n".join(lines)}



@router.get("/{agent_id}/versions/meta/report/markdown")
async def version_report_markdown(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)

    lines = ["# Agent Version Report", ""]
    lines.append(f"- analyzed versions: {report['count']}")
    latest = report.get('latest')
    if latest:
        lines.append(f"- latest: v{latest['version_no']} (changed={latest['changed_count']})")

    lines.append("")
    lines.append("## Top Changed Fields")
    for item in report.get('field_stats', [])[:10]:
        lines.append(f"- `{item['field']}`: {item['changes']}")

    lines.append("")
    lines.append("## Timeline")
    for item in report.get('timeline', [])[:20]:
        fields = ", ".join(item.get('changed_fields', [])) or "-"
        lines.append(f"- v{item['version_no']} vs {item['compared_to']} · changed={item['changed_count']} · fields={fields}")

    return {"markdown": "\n".join(lines)}



@router.get("/{agent_id}/versions/meta/report/csv")
async def version_report_csv(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["version_no", "compared_to", "changed_count", "changed_fields"])
    for item in report.get("timeline", []):
        fields = "|".join(item.get("changed_fields", []))
        writer.writerow([item["version_no"], item["compared_to"], item["changed_count"], fields])
    return {"csv": output.getvalue().strip("\n")}



@router.get("/{agent_id}/versions/meta/report/top-fields")
async def version_report_top_fields(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    top_n: int = Query(default=5, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)
    return {
        "analyzed_versions": report.get("count", 0),
        "top_fields": report.get("field_stats", [])[:top_n],
    }



@router.get("/{agent_id}/versions/meta/report/jsonl")
async def version_report_jsonl(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)
    lines: list[str] = []
    for item in report.get("timeline", []):
        lines.append(json.dumps(item, ensure_ascii=False))
    return {"jsonl": "\n".join(lines)}



@router.get("/{agent_id}/versions/meta/report/yaml")
async def version_report_yaml(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)

    lines = ["count: {}".format(report.get("count", 0)), "timeline:"]
    for item in report.get("timeline", []):
        fields = item.get("changed_fields", [])
        lines.append(f"  - version_no: {item['version_no']}")
        lines.append(f"    compared_to: {item['compared_to']}")
        lines.append(f"    changed_count: {item['changed_count']}")
        lines.append("    changed_fields:")
        if fields:
            for f in fields:
                lines.append(f"      - {f}")
        else:
            lines.append("      -")

    lines.append("field_stats:")
    for item in report.get("field_stats", []):
        lines.append(f"  - field: {item['field']}")
        lines.append(f"    changes: {item['changes']}")

    return {"yaml": "\n".join(lines)}



@router.get("/{agent_id}/versions/meta/report/xml")
async def version_report_xml(
    agent_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = await version_report(agent_id=agent_id, limit=limit, db=db, user=user)

    lines = ["<version_report>", f"  <count>{report.get('count', 0)}</count>"]

    latest = report.get("latest")
    if latest:
        lines.append("  <latest>")
        lines.append(f"    <version_no>{latest['version_no']}</version_no>")
        lines.append(f"    <compared_to>{xml_escape(str(latest['compared_to']))}</compared_to>")
        lines.append(f"    <changed_count>{latest['changed_count']}</changed_count>")
        lines.append("  </latest>")

    lines.append("  <timeline>")
    for item in report.get("timeline", []):
        lines.append("    <item>")
        lines.append(f"      <version_no>{item['version_no']}</version_no>")
        lines.append(f"      <compared_to>{xml_escape(str(item['compared_to']))}</compared_to>")
        lines.append(f"      <changed_count>{item['changed_count']}</changed_count>")
        lines.append("      <changed_fields>")
        for field in item.get("changed_fields", []):
            lines.append(f"        <field>{xml_escape(str(field))}</field>")
        lines.append("      </changed_fields>")
        lines.append("    </item>")
    lines.append("  </timeline>")

    lines.append("  <field_stats>")
    for item in report.get("field_stats", []):
        lines.append("    <item>")
        lines.append(f"      <field>{xml_escape(str(item['field']))}</field>")
        lines.append(f"      <changes>{item['changes']}</changes>")
        lines.append("    </item>")
    lines.append("  </field_stats>")

    lines.append("</version_report>")
    return {"xml": "\n".join(lines)}

@router.get("/{agent_id}/versions/meta/stats")
async def version_stats(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.asc())
        )
    ).scalars().all()
    if not rows:
        return {"count": 0, "latest": None, "oldest": None}

    return {
        "count": len(rows),
        "oldest": {"version_no": rows[0].version_no, "created_at": rows[0].created_at.isoformat()},
        "latest": {"version_no": rows[-1].version_no, "created_at": rows[-1].created_at.isoformat()},
    }

@router.delete("/{agent_id}/versions")
async def prune_versions(
    agent_id: int,
    keep_latest: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    rows = (
        await db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_no.desc())
        )
    ).scalars().all()

    to_delete = rows[keep_latest:]
    for row in to_delete:
        await db.delete(row)
    await db.commit()
    return {"ok": True, "kept": min(len(rows), keep_latest), "deleted": len(to_delete)}

@router.delete("/{agent_id}/versions/{version_no}")
async def delete_version(agent_id: int, version_no: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    row = (
        await db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version_no == version_no)
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")

    await db.delete(row)
    await db.commit()
    return {"ok": True, "deleted_version_no": version_no}

@router.post("/{agent_id}/versions/{version_no}/restore")
async def restore_version(agent_id: int, version_no: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (
        await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    version = (
        await db.execute(
            select(AgentVersion).where(AgentVersion.agent_id == agent_id, AgentVersion.version_no == version_no)
        )
    ).scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Version not found")

    max_version = (
        await db.execute(select(func.max(AgentVersion.version_no)).where(AgentVersion.agent_id == agent.id))
    ).scalar()

    db.add(AgentVersion(agent_id=agent.id, version_no=(max_version or 0) + 1, snapshot=_agent_snapshot(agent)))

    snapshot = version.snapshot or {}
    for field in [
        "name",
        "description",
        "system_prompt",
        "folder_id",
        "model",
        "is_favorite",
        "recursion_limit",
        "mcp_enabled",
    ]:
        if field in snapshot:
            setattr(agent, field, snapshot[field])

    agent.updated_at = utcnow()
    await db.commit()
    return {"ok": True, "restored_version_no": version_no}
