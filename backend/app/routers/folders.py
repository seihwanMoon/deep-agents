from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import AgentFolder, Agent, User
from ..schemas import FolderIn

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


def _normalize_folder_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="name is required")
    return normalized[:255]


async def _ensure_folder_name_available(db: AsyncSession, user_id: int, name: str, exclude_id: int | None = None) -> None:
    stmt = select(AgentFolder).where(AgentFolder.user_id == user_id, AgentFolder.name == name)
    if exclude_id is not None:
        stmt = stmt.where(AgentFolder.id != exclude_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Folder name already exists")


@router.get("")
async def list_folders(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folders = (await db.execute(select(AgentFolder).where(AgentFolder.user_id == user.id))).scalars().all()
    return [{"id": f.id, "name": f.name} for f in folders]


@router.get("/{folder_id}")
async def get_folder(folder_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folder = (
        await db.execute(select(AgentFolder).where(AgentFolder.id == folder_id, AgentFolder.user_id == user.id))
    ).scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    agent_count = (
        await db.execute(select(Agent).where(Agent.user_id == user.id, Agent.folder_id == folder.id))
    ).scalars().all()
    return {"id": folder.id, "name": folder.name, "agent_count": len(agent_count)}


@router.post("")
async def create_folder(body: FolderIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    name = _normalize_folder_name(body.name)
    await _ensure_folder_name_available(db, user.id, name)

    folder = AgentFolder(user_id=user.id, name=name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return {"id": folder.id, "name": folder.name}


@router.put("/{folder_id}")
async def rename_folder(folder_id: int, body: FolderIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folder = (
        await db.execute(select(AgentFolder).where(AgentFolder.id == folder_id, AgentFolder.user_id == user.id))
    ).scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    name = _normalize_folder_name(body.name)
    await _ensure_folder_name_available(db, user.id, name, exclude_id=folder.id)

    folder.name = name
    await db.commit()
    return {"ok": True, "name": folder.name}


@router.delete("/{folder_id}")
async def delete_folder(folder_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folder = (
        await db.execute(select(AgentFolder).where(AgentFolder.id == folder_id, AgentFolder.user_id == user.id))
    ).scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    await db.delete(folder)
    await db.commit()
    return {"ok": True}
