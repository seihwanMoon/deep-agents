import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models import User, Agent, AgentOpener, AgentSchedule
from app.security import create_access_token, get_password_hash

TEST_DB_URL = "sqlite+aiosqlite:///./test.db"
engine = create_async_engine(TEST_DB_URL, future=True)
TestingSession = async_sessionmaker(engine, expire_on_commit=False)


async def override_get_db():
    async with TestingSession() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def setup_module():
    import asyncio

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with TestingSession() as session:
            await session.execute(delete(AgentSchedule))
            await session.execute(delete(AgentOpener))
            await session.execute(delete(Agent))
            await session.execute(delete(User))
            user = User(email="test@example.com", password_hash=get_password_hash("pass1234"))
            session.add(user)
            await session.commit()
            await session.refresh(user)
            agent = Agent(
                user_id=user.id,
                name="agent",
                description="",
                system_prompt="hi",
                model="openai:gpt-4o-mini",
                webhook_token="dbuilder_test_token",
            )
            session.add(agent)
            await session.commit()

    asyncio.run(_setup())


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_auth_register_login_and_me():
    reg = client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "newpass123"})
    assert reg.status_code == 200

    dup = client.post("/api/v1/auth/register", json={"email": "new@example.com", "password": "newpass123"})
    assert dup.status_code == 409

    resp = client.post("/api/v1/auth/login", json={"email": "test@example.com", "password": "pass1234"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "test@example.com"


def test_openai_compat_and_webhook_header_auth():
    token = create_access_token("1")
    list_resp = client.get("/api/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert list_resp.status_code == 200

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    assert "agent-1" in resp.json()["choices"][0]["message"]["content"]

    wh = client.post(
        "/api/v1/agents/1/webhook",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"message": "ping"},
    )
    assert wh.status_code == 200
    assert wh.json()["accepted"] is True


def test_fix_updates_openers_and_exports():
    token = create_access_token("1")
    fix = client.post(
        "/api/v1/agents/1/fix",
        headers={"Authorization": f"Bearer {token}"},
        json={"instruction": "이 프롬프트를 강화해줘\n- 첫 오프너\n- 두번째 오프너"},
    )
    assert fix.status_code == 200
    assert len(fix.json()["openers"]) == 2

    openers = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert openers.status_code == 200
    assert [o["content"] for o in openers.json()] == ["첫 오프너", "두번째 오프너"]

    exported = client.get("/api/v1/agents/1/export", headers={"Authorization": f"Bearer {token}"})
    assert exported.status_code == 200
    assert len(exported.json()["openers"]) == 2


def test_schedule_crud_and_validation():
    token = create_access_token("1")

    invalid = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "* * *", "enabled": True, "payload": {}},
    )
    assert invalid.status_code == 400

    created = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/5 * * * *", "enabled": True, "payload": {"message": "hello"}},
    )
    assert created.status_code == 200
    schedule_id = created.json()["id"]

    listed = client.get("/api/v1/agents/1/schedules", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert len(listed.json()) >= 1

    updated = client.put(
        f"/api/v1/agents/1/schedules/{schedule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "0 * * * *", "enabled": False, "payload": {"message": "updated"}},
    )
    assert updated.status_code == 200

    deleted = client.delete(
        f"/api/v1/agents/1/schedules/{schedule_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200
