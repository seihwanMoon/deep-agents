import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models import User, Agent, AgentOpener, AgentSchedule, Conversation, Message, WebhookCallbackEvent, Secret
from app.security import create_access_token, get_password_hash
from app.services.secrets import inject_secrets

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
            await session.execute(delete(Message))
            await session.execute(delete(Conversation))
            await session.execute(delete(AgentSchedule))
            await session.execute(delete(WebhookCallbackEvent))
            await session.execute(delete(Secret))
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


def test_openai_compat_errors_and_streaming_shape():
    bad_token = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer wrong"},
        json={"model": "agent-1", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert bad_token.status_code == 401

    bad_model = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert bad_model.status_code == 400

    stream_resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "hello stream"}],
            "stream": True,
        },
    )
    assert stream_resp.status_code == 200
    body = stream_resp.text
    assert "chat.completion.chunk" in body
    assert "[DONE]" in body


def test_agent_chat_sse_with_sources_and_done_payload():
    token = create_access_token("1")

    up = client.post(
        "/api/v1/agents/1/files",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload": ("notes.txt", b"rag line one\nrag line two", "text/plain")},
    )
    assert up.status_code == 200

    resp = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "contact me at test@example.com"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert '"type": "sources"' in body
    assert '"type": "token"' in body
    assert '"type": "done"' in body
    assert 'MASKED_EMAIL' in body


def test_conversation_list_and_messages_history():
    token = create_access_token("1")

    first = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "first conversation message"},
    )
    assert first.status_code == 200
    body = first.text
    assert '"conversation_id"' in body

    conversations = client.get(
        "/api/v1/agents/1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    assert len(conversations.json()) >= 1
    conversation_id = conversations.json()[0]["id"]

    second = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "follow up", "conversation_id": conversation_id},
    )
    assert second.status_code == 200

    history = client.get(
        f"/api/v1/agents/1/conversations/{conversation_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history.status_code == 200
    roles = [m["role"] for m in history.json()]
    assert "user" in roles and "assistant" in roles


def test_conversation_rename_and_delete():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "rename me"},
    )
    assert created.status_code == 200

    conversations = client.get(
        "/api/v1/agents/1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    conv_id = conversations.json()[0]["id"]

    bad_rename = client.put(
        f"/api/v1/agents/1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "   "},
    )
    assert bad_rename.status_code == 400

    renamed = client.put(
        f"/api/v1/agents/1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Important Chat"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Important Chat"

    deleted = client.delete(
        f"/api/v1/agents/1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200

    not_found = client.get(
        f"/api/v1/agents/1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert not_found.status_code == 404


def test_conversation_pagination_and_clear_messages():
    token = create_access_token("1")

    for i in range(3):
        r = client.post(
            "/api/v1/agents/1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": f"batch-{i}"},
        )
        assert r.status_code == 200

    paged = client.get(
        "/api/v1/agents/1/conversations?limit=2&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert paged.status_code == 200
    assert len(paged.json()) <= 2

    conv_id = paged.json()[0]["id"]
    msgs1 = client.get(
        f"/api/v1/agents/1/conversations/{conv_id}/messages?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert msgs1.status_code == 200
    assert len(msgs1.json()) <= 1

    cleared = client.delete(
        f"/api/v1/agents/1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cleared.status_code == 200

    msgs2 = client.get(
        f"/api/v1/agents/1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert msgs2.status_code == 200
    assert msgs2.json() == []


def test_conversation_detail_contains_stats():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "stats message test"},
    )
    assert created.status_code == 200

    conversations = client.get(
        "/api/v1/agents/1/conversations?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    convo = conversations.json()[0]
    assert "message_count" in convo

    detail = client.get(
        f"/api/v1/agents/1/conversations/{convo['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["message_count"] >= 1
    assert "last_message_preview" in detail.json()


def test_conversation_search_and_single_message_delete():
    token = create_access_token("1")

    c = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "searchable conversation"},
    )
    assert c.status_code == 200

    conversations = client.get(
        "/api/v1/agents/1/conversations?limit=20&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    conv_id = conversations.json()[0]["id"]

    renamed = client.put(
        f"/api/v1/agents/1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": "Search Target Conversation"},
    )
    assert renamed.status_code == 200

    searched = client.get(
        "/api/v1/agents/1/conversations?q=Target&limit=20&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert searched.status_code == 200
    assert any("Target" in item["title"] for item in searched.json())

    history = client.get(
        f"/api/v1/agents/1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history.status_code == 200
    assert len(history.json()) >= 1
    msg_id = history.json()[0]["id"]

    deleted = client.delete(
        f"/api/v1/agents/1/conversations/{conv_id}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200

    deleted_again = client.delete(
        f"/api/v1/agents/1/conversations/{conv_id}/messages/{msg_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted_again.status_code == 404


def test_delete_user_message_retitles_conversation():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Title Basis Message"},
    )
    assert created.status_code == 200

    conversations = client.get(
        "/api/v1/agents/1/conversations?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    conv_id = conversations.json()[0]["id"]

    history = client.get(
        f"/api/v1/agents/1/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert history.status_code == 200
    user_message = next(m for m in history.json() if m["role"] == "user")

    deleted = client.delete(
        f"/api/v1/agents/1/conversations/{conv_id}/messages/{user_message['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200

    detail = client.get(
        f"/api/v1/agents/1/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["title"] != ""


def test_fix_json_validation_and_atomicity():
    token = create_access_token("1")

    baseline = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert baseline.status_code == 200

    bad = client.post(
        "/api/v1/agents/1/fix",
        headers={"Authorization": f"Bearer {token}"},
        json={"instruction": '{"append_system_prompt":"ok","replace_openers":["a",""]}'},
    )
    assert bad.status_code == 400

    after = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 200
    assert after.json() == baseline.json()


def test_schedule_run_now_and_disabled_guard():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/10 * * * *", "enabled": True, "payload": {"message": "hello from schedule"}},
    )
    assert created.status_code == 200
    schedule_id = created.json()["id"]

    run_ok = client.post(
        f"/api/v1/agents/1/schedules/{schedule_id}/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "manual run"},
    )
    assert run_ok.status_code == 200
    assert run_ok.json()["ok"] is True
    assert run_ok.json()["task_id"]

    updated = client.put(
        f"/api/v1/agents/1/schedules/{schedule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/10 * * * *", "enabled": False, "payload": {}},
    )
    assert updated.status_code == 200

    run_disabled = client.post(
        f"/api/v1/agents/1/schedules/{schedule_id}/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "manual run"},
    )
    assert run_disabled.status_code == 400


def test_webhook_callback_idempotency_and_listing():
    callback = client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-1", "status": "completed", "payload": {"ok": True}},
    )
    assert callback.status_code == 200
    assert callback.json()["duplicate"] is False

    callback_dupe = client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-1", "status": "completed", "payload": {"ok": True}},
    )
    assert callback_dupe.status_code == 200
    assert callback_dupe.json()["duplicate"] is True

    token = create_access_token("1")
    listed = client.get(
        "/api/v1/agents/1/webhook/callbacks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert any(item["event_id"] == "evt-1" for item in listed.json())


def test_tools_discover_and_invoke_local_mcp_runner():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Local MCP", "type": "mcp", "config": {"mode": "local"}},
    )
    assert created.status_code == 200
    tool_id = created.json()["id"]

    discovered = client.get(
        f"/api/v1/tools/{tool_id}/discover",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert discovered.status_code == 200
    assert any(t["name"] == "echo" for t in discovered.json()["tools"])

    invoked = client.post(
        f"/api/v1/tools/{tool_id}/invoke/echo",
        headers={"Authorization": f"Bearer {token}"},
        json={"args": {"hello": "world"}},
    )
    assert invoked.status_code == 200
    assert invoked.json()["invocation"]["result"]["hello"] == "world"


def test_tools_remote_failure_returns_bad_gateway():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Remote MCP",
            "type": "mcp",
            "config": {"mode": "remote", "endpoint": "http://127.0.0.1:9"},
        },
    )
    assert created.status_code == 200
    tool_id = created.json()["id"]

    discovered = client.get(
        f"/api/v1/tools/{tool_id}/discover",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert discovered.status_code == 502


def test_openai_models_list_for_agent_token():
    resp = client.get(
        "/v1/models",
        headers={"Authorization": "Bearer dbuilder_test_token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any(item["id"] == "agent-1" for item in data)


def test_openai_compat_message_validation_and_stream_usage():
    bad_messages = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"model": "agent-1", "messages": []},
    )
    assert bad_messages.status_code == 400

    stream_resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "count usage"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )
    assert stream_resp.status_code == 200
    body = stream_resp.text
    assert '"usage":' in body
    assert '[DONE]' in body


def test_secrets_encrypted_at_rest_and_resolved_on_injection():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/secrets",
        headers={"Authorization": f"Bearer {token}"},
        json={"key_name": "OPENAI_API_KEY", "key_value": "sk-test-123", "scope": "user"},
    )
    assert created.status_code == 200

    import asyncio

    async def _verify():
        async with TestingSession() as session:
            row = (await session.execute(select(Secret).where(Secret.user_id == 1, Secret.key_name == "OPENAI_API_KEY").order_by(Secret.id.desc()))).scalars().first()
            assert row is not None
            assert row.key_value != "sk-test-123"
            assert row.key_value.startswith("enc::")

            resolved = await inject_secrets(1, session)
            assert resolved["OPENAI_API_KEY"] == "sk-test-123"

    asyncio.run(_verify())
