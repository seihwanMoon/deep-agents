from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Agent, AgentSchedule, User
from ..schemas import ScheduleIn

router = APIRouter(prefix="/api/v1/agents", tags=["schedules"])


def _validate_cron_expr(expr: str) -> None:
    parts = expr.split()
    if len(parts) != 5:
        raise HTTPException(status_code=400, detail="cron_expr must have 5 fields")


async def _get_agent_or_404(agent_id: int, user_id: int, db: AsyncSession) -> Agent:
    agent = (await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/{agent_id}/schedules")
async def list_schedules(agent_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _get_agent_or_404(agent_id, user.id, db)
    rows = (await db.execute(select(AgentSchedule).where(AgentSchedule.agent_id == agent_id))).scalars().all()
    return [{"id": r.id, "cron_expr": r.cron_expr, "enabled": r.enabled, "payload": r.payload} for r in rows]


@router.post("/{agent_id}/schedules")
async def create_schedule(agent_id: int, body: ScheduleIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await _get_agent_or_404(agent_id, user.id, db)
    _validate_cron_expr(body.cron_expr)
    row = AgentSchedule(agent_id=agent_id, cron_expr=body.cron_expr, enabled=body.enabled, payload=body.payload)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id}


@router.put("/{agent_id}/schedules/{schedule_id}")
async def update_schedule(
    agent_id: int,
    schedule_id: int,
    body: ScheduleIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_agent_or_404(agent_id, user.id, db)
    _validate_cron_expr(body.cron_expr)
    schedule = (
        await db.execute(select(AgentSchedule).where(AgentSchedule.id == schedule_id, AgentSchedule.agent_id == agent_id))
    ).scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    schedule.cron_expr = body.cron_expr
    schedule.enabled = body.enabled
    schedule.payload = body.payload
    await db.commit()
    return {"ok": True}


@router.delete("/{agent_id}/schedules/{schedule_id}")
async def delete_schedule(
    agent_id: int,
    schedule_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_agent_or_404(agent_id, user.id, db)
    schedule = (
        await db.execute(select(AgentSchedule).where(AgentSchedule.id == schedule_id, AgentSchedule.agent_id == agent_id))
    ).scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    await db.delete(schedule)
    await db.commit()
    return {"ok": True}
