from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import AgentFolder, User
from ..schemas import FolderIn

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


@router.get("")
async def list_folders(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folders = (await db.execute(select(AgentFolder).where(AgentFolder.user_id == user.id))).scalars().all()
    return [{"id": f.id, "name": f.name} for f in folders]


@router.post("")
async def create_folder(body: FolderIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    folder = AgentFolder(user_id=user.id, name=body.name)
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
    folder.name = body.name
    await db.commit()
    return {"ok": True}


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
