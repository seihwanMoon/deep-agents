from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentSchedule, User
from ..schemas import ScheduleIn

router = APIRouter(prefix="/api/v1/agents", tags=["schedules"])


@router.get("/{agent_id}/schedules")
async def list_schedules(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    rows = (await db.execute(select(AgentSchedule).where(AgentSchedule.agent_id == agent_id))).scalars().all()
    return [{"id": r.id, "cron_expr": r.cron_expr, "enabled": r.enabled, "payload": r.payload} for r in rows]


@router.post("/{agent_id}/schedules")
async def create_schedule(agent_id: int, body: ScheduleIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    row = AgentSchedule(agent_id=agent_id, cron_expr=body.cron_expr, enabled=body.enabled, payload=body.payload)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id}
