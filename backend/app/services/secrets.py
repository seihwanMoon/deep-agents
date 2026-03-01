import base64
import hashlib
import os
from contextlib import contextmanager

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Secret

_ENC_PREFIX = "enc::"


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain: str) -> str:
    token = _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    if not value.startswith(_ENC_PREFIX):
        return value
    encrypted = value[len(_ENC_PREFIX):]
    try:
        return _fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt secret value") from exc


async def inject_secrets(user_id: int, db: AsyncSession) -> dict[str, str]:
    rows = (
        await db.execute(
            select(Secret).where(or_(Secret.user_id == user_id, Secret.scope == "workspace"))
        )
    ).scalars().all()
    resolved: dict[str, str] = {}
    for item in rows:
        resolved[item.key_name] = decrypt_secret(item.key_value)
    return resolved


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
