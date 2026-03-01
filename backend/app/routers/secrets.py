from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import get_current_user
from ..models import Secret, User
from ..schemas import SecretIn
from ..services.secrets import encrypt_secret

router = APIRouter(prefix="/api/v1/secrets", tags=["secrets"])


@router.get("")
async def list_secrets(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (await db.execute(select(Secret).where(Secret.user_id == user.id))).scalars().all()
    return [
        {
            "id": r.id,
            "key_name": r.key_name,
            "scope": r.scope,
            "masked_value": "*" * 8,
        }
        for r in rows
    ]


@router.post("")
async def create_secret(body: SecretIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = Secret(user_id=user.id, key_name=body.key_name, key_value=encrypt_secret(body.key_value), scope=body.scope)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id}


@router.put("/{secret_id}")
async def update_secret(secret_id: int, body: SecretIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = (await db.execute(select(Secret).where(Secret.id == secret_id, Secret.user_id == user.id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Secret not found")
    row.key_name = body.key_name
    row.key_value = encrypt_secret(body.key_value)
    row.scope = body.scope
    await db.commit()
    return {"ok": True}


@router.delete("/{secret_id}")
async def delete_secret(secret_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    row = (await db.execute(select(Secret).where(Secret.id == secret_id, Secret.user_id == user.id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Secret not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}
