import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentFolder, AgentVersion, User, AgentDocument
from ..schemas import AgentIn, AgentUpdate, FixRequest

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])


def _split_text(text: str, chunk_size: int = 500):
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)] or [""]


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
    agent.updated_at = datetime.utcnow()

    await db.commit()
    return {"ok": True}


@router.post("/{agent_id}/fix")
async def fix_agent(agent_id: int, body: FixRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    # structured output placeholder for Fix LLM
    new_prompt = f"{agent.system_prompt}\n\n[fix-instruction]\n{body.instruction}"
    agent.system_prompt = new_prompt.strip()
    agent.updated_at = datetime.utcnow()
    await db.commit()
    return {
        "system_prompt": agent.system_prompt,
        "tools_to_add": [],
        "tools_to_remove": [],
        "openers": [],
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
    return {"lang": lang, "snippet": snippets.get(lang, snippets["python"]) }


@router.get("/{agent_id}/mcp")
async def agent_mcp(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.mcp_enabled:
        raise HTTPException(status_code=400, detail="MCP is disabled")
    return {"agent_id": agent.id, "status": "mcp-active", "endpoint": f"/api/v1/agents/{agent.id}/mcp"}


@router.post("/{agent_id}/webhook")
async def webhook(agent_id: int, payload: dict, db: AsyncSession = Depends(get_db)):
    # token is expected in payload for simplified local webhook flow
    token = payload.get("token", "")
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if token != agent.webhook_token:
        raise HTTPException(status_code=401, detail="Invalid webhook token")
    return {"accepted": True, "agent_id": agent.id, "message": payload.get("message", "")}


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
        "openers": [],
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
