from celery import Celery
from celery.schedules import crontab

from .config import settings

celery = Celery("deep_agents", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
)
celery.conf.beat_schedule = {}


def _cron_to_crontab(expr: str):
    minute, hour, day_of_month, month_of_year, day_of_week = expr.split()
    return crontab(
        minute=minute,
        hour=hour,
        day_of_month=day_of_month,
        month_of_year=month_of_year,
        day_of_week=day_of_week,
    )


def sync_agent_beat_schedule(agent_id: int, schedules: list[dict]) -> int:
    prefix = f"agent_schedule:{agent_id}:"

    # Remove existing entries for this agent.
    for key in [k for k in celery.conf.beat_schedule.keys() if k.startswith(prefix)]:
        del celery.conf.beat_schedule[key]

    count = 0
    for row in schedules:
        if not row.get("enabled", True):
            continue
        key = f"{prefix}{row['id']}"
        celery.conf.beat_schedule[key] = {
            "task": "agent.execute",
            "schedule": _cron_to_crontab(row["cron_expr"]),
            "args": (agent_id, str((row.get("payload") or {}).get("message", "scheduled-run"))),
        }
        count += 1
    return count
