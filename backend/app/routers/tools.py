from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Tool, User
from ..schemas import ToolIn

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.get("")
async def list_tools(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    tools = (await db.execute(select(Tool).where(Tool.user_id == user.id))).scalars().all()
    return [{"id": t.id, "name": t.name, "type": t.type, "config": t.config} for t in tools]


@router.post("")
async def create_tool(body: ToolIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    tool = Tool(user_id=user.id, name=body.name, type=body.type, config=body.config)
    db.add(tool)
    await db.commit()
    await db.refresh(tool)
    return {"id": tool.id}


@router.put("/{tool_id}")
async def update_tool(tool_id: int, body: ToolIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    tool = (await db.execute(select(Tool).where(Tool.id == tool_id, Tool.user_id == user.id))).scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    tool.name = body.name
    tool.type = body.type
    tool.config = body.config
    await db.commit()
    return {"ok": True}


@router.delete("/{tool_id}")
async def delete_tool(tool_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    tool = (await db.execute(select(Tool).where(Tool.id == tool_id, Tool.user_id == user.id))).scalar_one_or_none()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    await db.delete(tool)
    await db.commit()
    return {"ok": True}
