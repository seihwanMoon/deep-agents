import base64
import hashlib
import os
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Secret

_SECRET_PREFIX = "enc:v1:"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret_value(raw_value: str) -> str:
    token = _fernet().encrypt(raw_value.encode("utf-8")).decode("utf-8")
    return f"{_SECRET_PREFIX}{token}"


def decrypt_secret_value(stored_value: str) -> str:
    if not stored_value.startswith(_SECRET_PREFIX):
        # Backward compatibility for legacy plaintext rows.
        return stored_value

    token = stored_value[len(_SECRET_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


async def inject_secrets(user_id: int, db: AsyncSession) -> dict[str, str]:
    rows = (
        await db.execute(
            select(Secret).where(or_(Secret.user_id == user_id, Secret.scope == "workspace"))
        )
    ).scalars().all()
    return {s.key_name: decrypt_secret_value(s.key_value) for s in rows}


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
