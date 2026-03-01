import os
from contextlib import contextmanager
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Secret


async def inject_secrets(user_id: int, db: AsyncSession) -> dict[str, str]:
    rows = (
        await db.execute(
            select(Secret).where(or_(Secret.user_id == user_id, Secret.scope == "workspace"))
        )
    ).scalars().all()
    return {s.key_name: s.key_value for s in rows}


@contextmanager
def with_secrets(env_vars: dict[str, str]):
    old = {k: os.environ.get(k) for k in env_vars}
    os.environ.update(env_vars)
    try:
        yield
    finally:
        for k, old_value in old.items():
            if old_value is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old_value
