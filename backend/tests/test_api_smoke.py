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
from app.celery_app import celery

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
        json={"instruction": "{\"append_system_prompt\":\"이 프롬프트를 강화해줘\",\"replace_openers\":[\"첫 오프너\",\"두번째 오프너\"]}"},
    )
    assert fix.status_code == 200
    assert len(fix.json()["openers"]) == 2

    openers = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert openers.status_code == 200
    assert [o["content"] for o in openers.json()] == ["첫 오프너", "두번째 오프너"]

    exported = client.get("/api/v1/agents/1/export", headers={"Authorization": f"Bearer {token}"})
    assert exported.status_code == 200
    assert len(exported.json()["openers"]) == 2




def test_fix_rejects_non_json_instruction():
    token = create_access_token("1")

    resp = client.post(
        "/api/v1/agents/1/fix",
        headers={"Authorization": f"Bearer {token}"},
        json={"instruction": "plain text is not allowed"},
    )
    assert resp.status_code == 400
    assert "must be a JSON object" in resp.json()["detail"]


def test_fix_rolls_back_on_unexpected_error(monkeypatch):
    token = create_access_token("1")

    before_agent = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    before_openers = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert before_agent.status_code == 200
    assert before_openers.status_code == 200

    import app.routers.agents as agents_router

    def _boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(agents_router, "utcnow", _boom)

    payload = {
        "append_system_prompt": "should-not-persist",
        "replace_openers": ["will", "rollback"],
    }
    import pytest

    with pytest.raises(RuntimeError, match="boom"):
        client.post(
            "/api/v1/agents/1/fix",
            headers={"Authorization": f"Bearer {token}"},
            json={"instruction": __import__("json").dumps(payload)},
        )

    after_agent = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    after_openers = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert after_agent.status_code == 200
    assert after_openers.status_code == 200
    assert after_agent.json()["system_prompt"] == before_agent.json()["system_prompt"]
    assert after_openers.json() == before_openers.json()

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
    before_agent = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    assert before_agent.status_code == 200
    before_prompt = before_agent.json()["system_prompt"]
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

    after_agent = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    assert after_agent.status_code == 200
    assert after_agent.json()["system_prompt"] == before_prompt




def test_fix_json_schema_validation_rejects_extra_and_wrong_types():
    token = create_access_token("1")

    bad_extra = client.post(
        "/api/v1/agents/1/fix",
        headers={"Authorization": f"Bearer {token}"},
        json={"instruction": '{"append_system_prompt":"ok","replace_openers":[],"unknown":true}'},
    )
    assert bad_extra.status_code == 400
    assert "Invalid JSON fix operation" in bad_extra.json()["detail"]

    bad_type = client.post(
        "/api/v1/agents/1/fix",
        headers={"Authorization": f"Bearer {token}"},
        json={"instruction": '{"append_system_prompt":123,"replace_openers":[]}'},
    )
    assert bad_type.status_code == 400
    assert "Invalid JSON fix operation" in bad_type.json()["detail"]



def test_fix_rejects_too_many_openers_without_side_effects():
    token = create_access_token("1")

    before_agent = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    before_openers = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert before_agent.status_code == 200
    assert before_openers.status_code == 200

    instruction = {
        "append_system_prompt": "should-not-apply",
        "replace_openers": [f"opener-{i}" for i in range(13)],
    }
    resp = client.post(
        "/api/v1/agents/1/fix",
        headers={"Authorization": f"Bearer {token}"},
        json={"instruction": __import__("json").dumps(instruction)},
    )
    assert resp.status_code == 400
    assert "replace_openers supports up to 12 items" in resp.json()["detail"]

    after_agent = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    after_openers = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert after_agent.status_code == 200
    assert after_openers.status_code == 200
    assert after_agent.json()["system_prompt"] == before_agent.json()["system_prompt"]
    assert after_openers.json() == before_openers.json()

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
        json={"event_id": "evt-1", "status": "failed", "payload": {"ok": False}},
    )
    assert callback_dupe.status_code == 200
    assert callback_dupe.json()["duplicate"] is True
    assert callback_dupe.json()["status"] == "completed"
    assert callback_dupe.json()["payload"] == {"ok": True}
    assert callback_dupe.json()["incoming_status"] == "failed"
    assert callback_dupe.json()["status_conflict"] is True

    token = create_access_token("1")
    listed = client.get(
        "/api/v1/agents/1/webhook/callbacks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert any(item["event_id"] == "evt-1" for item in listed.json())




def test_webhook_callbacks_listing_filters():
    token = create_access_token("1")

    c1 = client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-filter-1", "status": "completed", "payload": {"ok": True}},
    )
    assert c1.status_code == 200

    c2 = client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-filter-2", "status": "failed", "payload": {"ok": False}},
    )
    assert c2.status_code == 200

    by_status = client.get(
        "/api/v1/agents/1/webhook/callbacks?status=failed",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_status.status_code == 200
    assert len(by_status.json()) >= 1
    assert all(item["status"] == "failed" for item in by_status.json())

    by_event = client.get(
        "/api/v1/agents/1/webhook/callbacks?event_id=evt-filter-1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert by_event.status_code == 200
    assert len(by_event.json()) == 1
    assert by_event.json()[0]["event_id"] == "evt-filter-1"





def test_webhook_callback_rejects_unsupported_status():
    bad = client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-bad-status", "status": "unknown", "payload": {}},
    )
    assert bad.status_code == 400
    assert "unsupported status" in bad.json()["detail"]


def test_webhook_callbacks_filter_by_created_after():
    token = create_access_token("1")

    seeded = client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-created-after", "status": "completed", "payload": {"ok": True}},
    )
    assert seeded.status_code == 200

    listed = client.get(
        "/api/v1/agents/1/webhook/callbacks?created_after=2100-01-01T00:00:00",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert listed.json() == []


def test_webhook_callbacks_listing_offset_pagination():
    token = create_access_token("1")

    for i in range(3):
        resp = client.post(
            "/api/v1/agents/1/webhook/callback",
            headers={"Authorization": "Bearer dbuilder_test_token"},
            json={"event_id": f"evt-page-{i}", "status": "paged", "payload": {"i": i}},
        )
        assert resp.status_code == 200

    first = client.get(
        "/api/v1/agents/1/webhook/callbacks?status=paged&limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    assert len(first.json()) == 1

    second = client.get(
        "/api/v1/agents/1/webhook/callbacks?status=paged&limit=1&offset=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    assert len(second.json()) == 1
    assert first.json()[0]["event_id"] != second.json()[0]["event_id"]

def test_webhook_callback_stats_endpoint():
    token = create_access_token("1")

    client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-stats-1", "status": "completed", "payload": {"ok": True}},
    )
    client.post(
        "/api/v1/agents/1/webhook/callback",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={"event_id": "evt-stats-2", "status": "failed", "payload": {"ok": False}},
    )

    stats = client.get(
        "/api/v1/agents/1/webhook/callbacks/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert stats.status_code == 200
    body = stats.json()
    assert body["agent_id"] == 1
    assert body["total"] >= 2
    assert body["by_status"].get("completed", 0) >= 1
    assert body["by_status"].get("failed", 0) >= 1
    assert body["latest_event"] is not None
    assert body["latest_event"]["event_id"] in {"evt-stats-1", "evt-stats-2"}
    assert body["recent_limit"] == 20
    assert body["recent_count"] >= 2
    assert body["recent_by_status"].get("completed", 0) >= 1



def test_webhook_callback_stats_empty_for_new_agent():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "agent-no-callbacks", "description": "", "system_prompt": "hi", "model": "openai:gpt-4o-mini"},
    )
    assert created.status_code == 200
    agent_id = created.json()["id"]

    stats = client.get(
        f"/api/v1/agents/{agent_id}/webhook/callbacks/stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert stats.status_code == 200
    body = stats.json()
    assert body["agent_id"] == agent_id
    assert body["total"] == 0
    assert body["by_status"] == {}
    assert body["recent_count"] == 0
    assert body["recent_by_status"] == {}
    assert body["latest_event"] is None

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




def test_openai_models_auth_error_paths():
    missing = client.get("/v1/models")
    assert missing.status_code == 401

    bad = client.get("/v1/models", headers={"Authorization": "Bearer not-valid"})
    assert bad.status_code == 401


def test_openai_non_stream_usage_contract():
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "hello usage contract"}],
            "stream": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["finish_reason"] == "stop"
    usage = body["usage"]
    assert usage["prompt_tokens"] >= 1
    assert usage["completion_tokens"] >= 1
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]

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




def test_openai_stream_chunk_contract_usage_toggle():
    import json

    def _sse_json_chunks(body: str):
        chunks = []
        for line in body.splitlines():
            if not line.startswith("data: "):
                continue
            payload = line[len("data: "):].strip()
            if payload == "[DONE]" or not payload:
                continue
            chunks.append(json.loads(payload))
        return chunks

    no_usage = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "stream no usage"}],
            "stream": True,
        },
    )
    assert no_usage.status_code == 200
    chunks = _sse_json_chunks(no_usage.text)
    assert chunks[0]["choices"][0]["delta"].get("role") == "assistant"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert "usage" not in chunks[-1]

    with_usage = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "stream with usage"}],
            "stream": True,
            "stream_options": {"include_usage": True},
        },
    )
    assert with_usage.status_code == 200
    chunks2 = _sse_json_chunks(with_usage.text)
    assert chunks2[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks2[-1]["usage"]["total_tokens"] >= 1

def test_openai_compat_accepts_text_part_array_content():
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [
                {"role": "system", "content": "rules"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "first part"},
                        {"type": "text", "text": "second part"},
                    ],
                },
            ],
        },
    )
    assert resp.status_code == 200
    text = resp.json()["choices"][0]["message"]["content"]
    assert "first part" in text
    assert "second part" in text


def test_openai_compat_uses_latest_non_empty_user_message():
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "ack"},
                {"role": "user", "content": "  "},
                {"role": "user", "content": "last-user-message"},
                {"role": "tool", "content": "tool output"},
            ],
        },
    )
    assert resp.status_code == 200
    text = resp.json()["choices"][0]["message"]["content"]
    assert "last-user-message" in text


def test_openai_compat_rejects_invalid_content_type():
    bad = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": 123}],
        },
    )
    assert bad.status_code == 400
    assert "message content must be a string or text-part array" in bad.json()["detail"]


def test_openai_compat_response_format_json_object_non_stream():
    import json

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "json please"}],
            "response_format": {"type": "json_object"},
        },
    )
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    assert isinstance(parsed, dict)
    assert "answer" in parsed


def test_openai_compat_response_format_json_object_streaming():
    import json

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "stream json please"}],
            "stream": True,
            "response_format": {"type": "json_object"},
        },
    )
    assert resp.status_code == 200

    chunks = []
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):].strip()
        if payload in {"", "[DONE]"}:
            continue
        chunks.append(json.loads(payload))

    content = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    parsed = json.loads(content)
    assert "answer" in parsed


def test_openai_compat_rejects_unsupported_response_format():
    bad = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer dbuilder_test_token"},
        json={
            "model": "agent-1",
            "messages": [{"role": "user", "content": "hello"}],
            "response_format": {"type": "xml"},
        },
    )
    assert bad.status_code == 400
    assert "unsupported response_format.type" in bad.json()["detail"]


def test_agent_version_restore_flow():
    token = create_access_token("1")

    updated = client.put(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Changed Name", "description": "changed"},
    )
    assert updated.status_code == 200

    versions = client.get(
        "/api/v1/agents/1/versions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert versions.status_code == 200
    assert len(versions.json()) >= 1

    original_version_no = versions.json()[0]["version_no"]

    restored = client.post(
        f"/api/v1/agents/1/versions/{original_version_no}/restore",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert restored.status_code == 200
    assert restored.json()["ok"] is True

    exported = client.get(
        "/api/v1/agents/1/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exported.status_code == 200
    assert exported.json()["agent"]["name"] == "agent"


def test_agent_restore_missing_version_returns_404():
    token = create_access_token("1")
    restored = client.post(
        "/api/v1/agents/1/versions/999999/restore",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert restored.status_code == 404


def test_import_agent_with_openers_roundtrip():
    token = create_access_token("1")

    imported = client.post(
        "/api/v1/agents/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent": {
                "name": "Imported With Openers",
                "description": "desc",
                "system_prompt": "prompt",
                "model": "openai:gpt-4o-mini",
                "is_favorite": True,
                "recursion_limit": 33,
                "mcp_enabled": True,
            },
            "openers": [
                {"content": "Second opener", "order_no": 2},
                {"content": "First opener", "order_no": 1},
            ],
        },
    )
    assert imported.status_code == 200
    agent_id = imported.json()["id"]
    assert imported.json()["openers"] == 2

    openers = client.get(
        f"/api/v1/agents/{agent_id}/openers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert openers.status_code == 200
    assert [x["content"] for x in openers.json()] == ["First opener", "Second opener"]

    exported = client.get(
        f"/api/v1/agents/{agent_id}/export",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exported.status_code == 200
    assert exported.json()["agent"]["is_favorite"] is True
    assert exported.json()["agent"]["recursion_limit"] == 33
    assert exported.json()["agent"]["mcp_enabled"] is True


def test_import_agent_invalid_openers_rejected():
    token = create_access_token("1")

    bad = client.post(
        "/api/v1/agents/import",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent": {"name": "bad import"},
            "openers": [{"content": ""}],
        },
    )
    assert bad.status_code == 400


def test_secret_values_are_encrypted_at_rest():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/secrets",
        headers={"Authorization": f"Bearer {token}"},
        json={"key_name": "OPENAI_API_KEY", "key_value": "super-secret", "scope": "user"},
    )
    assert created.status_code == 200

    import asyncio

    async def _check():
        async with TestingSession() as session:
            row = (await session.execute(select(Secret).where(Secret.user_id == 1, Secret.key_name == "OPENAI_API_KEY"))).scalar_one()
            assert row.key_value != "super-secret"
            assert row.key_value.startswith("enc:v1:")

    asyncio.run(_check())


def test_secret_injection_decrypts_values():
    import asyncio

    async def _check():
        async with TestingSession() as session:
            env = await inject_secrets(1, session)
            assert env.get("OPENAI_API_KEY") == "super-secret"

    asyncio.run(_check())


def test_schedule_sync_to_celery_beat_filters_disabled():
    token = create_access_token("1")

    enabled = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/15 * * * *", "enabled": True, "payload": {"message": "enabled"}},
    )
    assert enabled.status_code == 200

    disabled = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/20 * * * *", "enabled": False, "payload": {"message": "disabled"}},
    )
    assert disabled.status_code == 200

    synced = client.post(
        "/api/v1/agents/1/schedules/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert synced.status_code == 200
    assert synced.json()["synced"] >= 1


def test_schedule_crud_auto_syncs_beat_entries():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/7 * * * *", "enabled": True, "payload": {"message": "auto-sync"}},
    )
    assert created.status_code == 200
    schedule_id = created.json()["id"]
    assert created.json()["synced"] >= 1
    assert created.json()["total_schedules"] >= created.json()["enabled_schedules"] >= 0

    assert any(k.startswith("agent_schedule:1:") for k in celery.conf.beat_schedule.keys())

    updated = client.put(
        f"/api/v1/agents/1/schedules/{schedule_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/9 * * * *", "enabled": False, "payload": {"message": "disabled"}},
    )
    assert updated.status_code == 200
    assert updated.json()["synced"] >= 0
    assert updated.json()["total_schedules"] >= updated.json()["enabled_schedules"] >= 0

    # disabled schedule should be removed from beat schedule after auto-sync
    assert not any(k == f"agent_schedule:1:{schedule_id}" for k in celery.conf.beat_schedule.keys())

    deleted = client.delete(
        f"/api/v1/agents/1/schedules/{schedule_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200




def test_schedule_sync_scoped_per_agent_keeps_other_agent_entries():
    token = create_access_token("1")

    created_agent = client.post(
        "/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "agent-scope", "description": "", "system_prompt": "hi", "model": "openai:gpt-4o-mini"},
    )
    assert created_agent.status_code == 200
    agent2_id = created_agent.json()["id"]

    s1 = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/11 * * * *", "enabled": True, "payload": {"message": "agent1"}},
    )
    assert s1.status_code == 200

    s2 = client.post(
        f"/api/v1/agents/{agent2_id}/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/13 * * * *", "enabled": True, "payload": {"message": "agent2"}},
    )
    assert s2.status_code == 200

    assert any(k.startswith("agent_schedule:1:") for k in celery.conf.beat_schedule.keys())
    assert any(k.startswith(f"agent_schedule:{agent2_id}:") for k in celery.conf.beat_schedule.keys())

    synced = client.post(
        "/api/v1/agents/1/schedules/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert synced.status_code == 200
    assert synced.json()["total_schedules"] >= synced.json()["enabled_schedules"] >= 0

    # sync for agent 1 should not drop agent 2 beat entries
    assert any(k.startswith(f"agent_schedule:{agent2_id}:") for k in celery.conf.beat_schedule.keys())



def test_schedule_sync_returns_scoped_schedule_keys():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/17 * * * *", "enabled": True, "payload": {"message": "keys-check"}},
    )
    assert created.status_code == 200

    synced = client.post(
        "/api/v1/agents/1/schedules/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert synced.status_code == 200
    body = synced.json()
    assert body["ok"] is True
    assert body["agent_id"] == 1
    assert body["total_schedules"] >= body["enabled_schedules"] >= 0
    assert isinstance(body["schedule_keys"], list)
    assert all(k.startswith("agent_schedule:1:") for k in body["schedule_keys"])
    assert body["synced"] == len(body["schedule_keys"])



def test_schedule_sync_reports_enabled_vs_total_counts():
    token = create_access_token("1")

    c1 = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/19 * * * *", "enabled": True, "payload": {"message": "enabled-one"}},
    )
    assert c1.status_code == 200

    c2 = client.post(
        "/api/v1/agents/1/schedules",
        headers={"Authorization": f"Bearer {token}"},
        json={"cron_expr": "*/23 * * * *", "enabled": False, "payload": {"message": "disabled-two"}},
    )
    assert c2.status_code == 200

    synced = client.post(
        "/api/v1/agents/1/schedules/sync",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert synced.status_code == 200
    body = synced.json()
    assert body["total_schedules"] >= 2
    assert body["enabled_schedules"] >= 1
    assert body["total_schedules"] >= body["enabled_schedules"]
    assert body["synced"] == len(body["schedule_keys"])

def test_rag_selects_relevant_source_first():
    token = create_access_token("1")

    up1 = client.post(
        "/api/v1/agents/1/files",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload": ("python.txt", b"python decorators and async await", "text/plain")},
    )
    assert up1.status_code == 200

    up2 = client.post(
        "/api/v1/agents/1/files",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload": ("golang.txt", b"goroutines channels and go routines", "text/plain")},
    )
    assert up2.status_code == 200

    resp = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "python async tips"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert '"type": "sources"' in body
    assert 'python.txt' in body


def test_rag_prefers_exact_phrase_match_when_tokens_overlap():
    token = create_access_token("1")

    up1 = client.post(
        "/api/v1/agents/1/files",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload": ("phrase.txt", b"python async tips for production systems", "text/plain")},
    )
    assert up1.status_code == 200

    up2 = client.post(
        "/api/v1/agents/1/files",
        headers={"Authorization": f"Bearer {token}"},
        files={"upload": ("mixed.txt", b"python intro and async examples", "text/plain")},
    )
    assert up2.status_code == 200

    resp = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "python async tips"},
    )
    assert resp.status_code == 200
    body = resp.text
    assert '"type": "sources"' in body
    assert 'phrase.txt' in body


def test_chat_empty_message_rejected():
    token = create_access_token("1")
    resp = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "   "},
    )
    assert resp.status_code == 400


def test_new_conversation_title_uses_masked_message():
    token = create_access_token("1")

    created = client.post(
        "/api/v1/agents/1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "reach me at private@example.com"},
    )
    assert created.status_code == 200

    conversations = client.get(
        "/api/v1/agents/1/conversations?limit=1&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert conversations.status_code == 200
    assert len(conversations.json()) >= 1
    title = conversations.json()[0]["title"]
    assert "MASKED_EMAIL" in title


def test_get_agent_detail_includes_counts():
    token = create_access_token("1")

    detail = client.get(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == 1
    assert "opener_count" in body
    assert "version_count" in body


def test_get_agent_detail_not_found():
    token = create_access_token("1")
    detail = client.get(
        "/api/v1/agents/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 404


def test_folder_validation_uniqueness_and_detail():
    token = create_access_token("1")

    bad = client.post(
        "/api/v1/folders",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "   "},
    )
    assert bad.status_code == 400

    created = client.post(
        "/api/v1/folders",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": " Work Folder "},
    )
    assert created.status_code == 200
    folder_id = created.json()["id"]
    assert created.json()["name"] == "Work Folder"

    dup = client.post(
        "/api/v1/folders",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Work Folder"},
    )
    assert dup.status_code == 409

    detail = client.get(
        f"/api/v1/folders/{folder_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["agent_count"] >= 0

    renamed = client.put(
        f"/api/v1/folders/{folder_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": " Renamed Folder "},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Folder"


def test_folder_detail_not_found():
    token = create_access_token("1")
    detail = client.get(
        "/api/v1/folders/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 404


def test_middleware_registry_list():
    token = create_access_token("1")
    resp = client.get("/api/v1/middlewares", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 18
    keys = {m["key"] for m in body["items"]}
    assert "ModelRetryMiddleware" in keys
    assert "OpenAIResponsesModeMiddleware" in keys


def test_middleware_registry_filter_and_detail():
    token = create_access_token("1")

    filtered = client.get(
        "/api/v1/middlewares",
        params={"provider": "anthropic", "q": "memory"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["key"] == "MemoryMiddleware"

    detail = client.get(
        "/api/v1/middlewares/ModelRetryMiddleware",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["provider"] == "builtin"

    missing = client.get(
        "/api/v1/middlewares/NopeMiddleware",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404


def test_agent_version_detail_endpoint():
    token = create_access_token("1")

    listed = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
    version_no = listed.json()[0]["version_no"]

    detail = client.get(
        f"/api/v1/agents/1/versions/{version_no}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["version_no"] == version_no
    assert isinstance(body["snapshot"], dict)

    missing = client.get(
        "/api/v1/agents/1/versions/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404


def test_openers_replace_endpoint():
    token = create_access_token("1")

    replaced = client.put(
        "/api/v1/agents/1/openers",
        headers={"Authorization": f"Bearer {token}"},
        json={"openers": ["첫 질문", "두번째 질문"]},
    )
    assert replaced.status_code == 200
    assert replaced.json()["count"] == 2

    listed = client.get("/api/v1/agents/1/openers", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert [o["content"] for o in listed.json()] == ["첫 질문", "두번째 질문"]

    bad = client.put(
        "/api/v1/agents/1/openers",
        headers={"Authorization": f"Bearer {token}"},
        json={"openers": ["ok", "   "]},
    )
    assert bad.status_code == 400


def test_agent_get_includes_webhook_token_and_rotate():
    token = create_access_token("1")

    detail = client.get("/api/v1/agents/1", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    before = detail.json()["webhook_token"]
    assert before.startswith("dbuilder_")

    rotated = client.post("/api/v1/agents/1/webhook-token/rotate", headers={"Authorization": f"Bearer {token}"})
    assert rotated.status_code == 200
    assert rotated.json()["ok"] is True
    assert rotated.json()["rotated"] is True
    after = rotated.json()["webhook_token"]
    assert after.startswith("dbuilder_")
    assert after != before

    old_rejected = client.post(
        "/api/v1/agents/1/webhook",
        headers={"Authorization": f"Bearer {before}"},
        json={"message": "ping"},
    )
    assert old_rejected.status_code == 401

    new_accepted = client.post(
        "/api/v1/agents/1/webhook",
        headers={"Authorization": f"Bearer {after}"},
        json={"message": "ping"},
    )
    assert new_accepted.status_code == 200


def test_agent_version_diff_endpoint():
    token = create_access_token("1")

    changed = client.put(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "renamed-for-diff"},
    )
    assert changed.status_code == 200

    listed = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert len(listed.json()) >= 1
    latest_prev_version = listed.json()[0]["version_no"]

    diff = client.get(
        f"/api/v1/agents/1/versions/{latest_prev_version}/diff",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert diff.status_code == 200
    body = diff.json()
    assert body["version_no"] == latest_prev_version
    assert body["changed_count"] >= 1
    assert "name" in body["changed_fields"]

    missing = client.get(
        "/api/v1/agents/1/versions/999999/diff",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404


def test_agent_settings_get_and_update_validation():
    token = create_access_token("1")

    before_versions = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert before_versions.status_code == 200
    before_count = len(before_versions.json())

    current = client.get("/api/v1/agents/1/settings", headers={"Authorization": f"Bearer {token}"})
    assert current.status_code == 200
    assert "webhook_token" in current.json()

    updated = client.put(
        "/api/v1/agents/1/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"recursion_limit": 88, "mcp_enabled": True},
    )
    assert updated.status_code == 200
    assert updated.json()["recursion_limit"] == 88
    assert updated.json()["mcp_enabled"] is True

    after_versions = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert after_versions.status_code == 200
    assert len(after_versions.json()) == before_count + 1

    invalid = client.put(
        "/api/v1/agents/1/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"recursion_limit": 0},
    )
    assert invalid.status_code == 400


def test_agent_update_recursion_limit_validation():
    token = create_access_token("1")

    bad = client.put(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"recursion_limit": 0},
    )
    assert bad.status_code == 400

    good = client.put(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"recursion_limit": 1000},
    )
    assert good.status_code == 200


def test_agent_update_noop_does_not_create_version():
    token = create_access_token("1")

    before = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert before.status_code == 200
    before_count = len(before.json())

    resp = client.put(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert resp.status_code == 200

    after = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 200
    assert len(after.json()) == before_count


def test_snippet_languages_and_lang_validation():
    token = create_access_token("1")

    langs = client.get("/api/v1/agents/1/snippet/languages", headers={"Authorization": f"Bearer {token}"})
    assert langs.status_code == 200
    assert "python" in langs.json()["languages"]

    bad = client.get(
        "/api/v1/agents/1/snippet",
        params={"lang": "ruby"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad.status_code == 400


def test_agent_versions_list_pagination_params():
    token = create_access_token("1")

    # create extra versions by updating agent multiple times
    for i in range(3):
        resp = client.put(
            "/api/v1/agents/1",
            headers={"Authorization": f"Bearer {token}"},
            json={"description": f"desc-{i}"},
        )
        assert resp.status_code == 200

    all_versions = client.get("/api/v1/agents/1/versions", headers={"Authorization": f"Bearer {token}"})
    assert all_versions.status_code == 200
    assert len(all_versions.json()) >= 3

    first_one = client.get(
        "/api/v1/agents/1/versions",
        params={"limit": 1, "offset": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first_one.status_code == 200
    assert len(first_one.json()) == 1

    second_one = client.get(
        "/api/v1/agents/1/versions",
        params={"limit": 1, "offset": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second_one.status_code == 200
    assert len(second_one.json()) == 1
    assert first_one.json()[0]["version_no"] > second_one.json()[0]["version_no"]


def test_agent_versions_list_without_snapshot_payload():
    token = create_access_token("1")
    resp = client.get(
        "/api/v1/agents/1/versions",
        params={"include_snapshot": False, "limit": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    assert "snapshot" not in rows[0]
    assert "version_no" in rows[0]

def test_agent_editor_page_route_serves_html():
    resp = client.get('/app/agent/1/edit')
    assert resp.status_code == 200
    assert '에이전트 편집기' in resp.text
    assert 'JWT 토큰 입력' in resp.text
    assert '오프너 저장' in resp.text
    assert 'Restore' in resp.text
    assert '스냅샷 생성' in resp.text
    assert '버전 비교' in resp.text
    assert 'Webhook 토큰 재발급' in resp.text
    assert 'Delete' in resp.text
    assert '오래된 버전 정리' in resp.text
    assert '버전 통계' in resp.text
    assert 'View' in resp.text
    assert '타임라인' in resp.text
    assert '변경 필드 통계' in resp.text
    assert '필드 변경 검색' in resp.text
    assert '버전 리포트' in resp.text
    assert '리포트 요약' in resp.text
    assert '리포트 Markdown' in resp.text
    assert '리포트 CSV' in resp.text
    assert '상위 변경 필드' in resp.text
    assert '리포트 JSONL' in resp.text
    assert '리포트 YAML' in resp.text
    assert '리포트 XML' in resp.text
    assert '조회 조건 초기화' in resp.text
    assert '결과 복사' in resp.text
    assert '결과 초기화' in resp.text
    assert '결과 다운로드' in resp.text
    assert 'downloadFormatSelect' in resp.text
    assert 'diffFilterInput' in resp.text
    assert 'showFullOutputBtn' in resp.text
    assert 'reportLimitInput' in resp.text
    assert 'topNInput' in resp.text
    assert 'function getReportLimit()' in resp.text
    assert 'function getTopN()' in resp.text
    assert 'DEFAULT_DIFF_TEXT' in resp.text
    assert 'MAX_RENDER_CHARS' in resp.text
    assert 'function resetQueryControls()' in resp.text
    assert 'QUERY_CONTROLS_KEY' in resp.text
    assert 'function saveQueryControls()' in resp.text
    assert 'function loadQueryControls()' in resp.text
    assert 'keep_latest' in resp.text
    assert 'download_format' in resp.text
    assert 'diff_filter' in resp.text
    assert 'function copyToClipboard(text)' in resp.text
    assert 'function downloadDiff()' in resp.text
    assert 'function applyDiffFilter()' in resp.text
    assert 'function setVersionOutput(text, options = {})' in resp.text
    assert 'matchAll(regex)' in resp.text
    assert '/versions/meta/fields?limit=${getReportLimit()}' in resp.text
    assert "setStatus('versionStatus', 'XML 리포트 조회 중...')" in resp.text

def test_agent_version_manual_snapshot_creation():
    token = create_access_token("1")

    before = client.get(
        "/api/v1/agents/1/versions",
        params={"limit": 1, "include_snapshot": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert before.status_code == 200
    before_latest = before.json()[0]["version_no"] if before.json() else 0

    created = client.post(
        "/api/v1/agents/1/versions/snapshot",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200
    assert created.json()["ok"] is True
    assert created.json()["version_no"] >= before_latest + 1


def test_agent_version_compare_endpoint():
    token = create_access_token("1")

    snap1 = client.post("/api/v1/agents/1/versions/snapshot", headers={"Authorization": f"Bearer {token}"})
    assert snap1.status_code == 200
    v1 = snap1.json()["version_no"]

    upd = client.put(
        "/api/v1/agents/1",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "agent-compare-target"},
    )
    assert upd.status_code == 200

    snap2 = client.post("/api/v1/agents/1/versions/snapshot", headers={"Authorization": f"Bearer {token}"})
    assert snap2.status_code == 200
    v2 = snap2.json()["version_no"]

    cmp_resp = client.get(
        f"/api/v1/agents/1/versions/compare?from_version={v1}&to_version={v2}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cmp_resp.status_code == 200
    assert cmp_resp.json()["from_version"] == v1
    assert cmp_resp.json()["to"] == f"v{v2}"

    cmp_current = client.get(
        f"/api/v1/agents/1/versions/compare?from_version={v1}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cmp_current.status_code == 200
    assert cmp_current.json()["to"] == "current"


def test_agent_rotate_webhook_token_endpoint():
    token = create_access_token("1")

    before = client.get('/api/v1/agents/1', headers={"Authorization": f"Bearer {token}"})
    assert before.status_code == 200
    old_token = before.json()["webhook_token"]

    rotated = client.post('/api/v1/agents/1/webhook-token/rotate', headers={"Authorization": f"Bearer {token}"})
    assert rotated.status_code == 200
    assert rotated.json()["ok"] is True
    assert rotated.json()["webhook_token"] != old_token

    after = client.get('/api/v1/agents/1', headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 200
    assert after.json()["webhook_token"] == rotated.json()["webhook_token"]


def test_agent_version_delete_endpoint():
    token = create_access_token("1")

    created = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert created.status_code == 200
    target = created.json()["version_no"]

    deleted = client.delete(f'/api/v1/agents/1/versions/{target}', headers={"Authorization": f"Bearer {token}"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_version_no"] == target

    missing = client.get(
        f'/api/v1/agents/1/versions/{target}',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404


def test_agent_version_prune_endpoint():
    token = create_access_token("1")

    # create a few versions first
    for _ in range(3):
        made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
        assert made.status_code == 200

    pruned = client.delete('/api/v1/agents/1/versions?keep_latest=1', headers={"Authorization": f"Bearer {token}"})
    assert pruned.status_code == 200
    assert pruned.json()["ok"] is True
    assert pruned.json()["kept"] == 1

    after = client.get('/api/v1/agents/1/versions?limit=5&include_snapshot=false', headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 200
    assert len(after.json()) == 1


def test_agent_version_stats_endpoint():
    token = create_access_token("1")

    # ensure at least one version exists
    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    stats = client.get('/api/v1/agents/1/versions/meta/stats', headers={"Authorization": f"Bearer {token}"})
    assert stats.status_code == 200
    body = stats.json()
    assert body["count"] >= 1
    assert body["latest"] is not None
    assert body["oldest"] is not None


def test_agent_version_detail_endpoint_returns_snapshot():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200
    v = made.json()["version_no"]

    detail = client.get(f'/api/v1/agents/1/versions/{v}', headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    body = detail.json()
    assert body["version_no"] == v
    assert isinstance(body["snapshot"], dict)


def test_agent_version_timeline_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    timeline = client.get('/api/v1/agents/1/versions/meta/timeline?limit=5', headers={"Authorization": f"Bearer {token}"})
    assert timeline.status_code == 200
    body = timeline.json()
    assert "items" in body
    assert body["count"] >= 1
    assert "changed_count" in body["items"][0]


def test_agent_version_field_stats_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    stats = client.get('/api/v1/agents/1/versions/meta/fields?limit=20', headers={"Authorization": f"Bearer {token}"})
    assert stats.status_code == 200
    body = stats.json()
    assert "versions_scanned" in body
    assert "fields" in body
    assert isinstance(body["fields"], list)


def test_agent_version_search_by_field_endpoint():
    token = create_access_token("1")

    before = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert before.status_code == 200

    changed = client.put(
        '/api/v1/agents/1',
        headers={"Authorization": f"Bearer {token}"},
        json={"system_prompt": "searchable prompt change"},
    )
    assert changed.status_code == 200

    after = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert after.status_code == 200

    search = client.get(
        '/api/v1/agents/1/versions/meta/search?field=system_prompt&limit=10',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert search.status_code == 200
    body = search.json()
    assert body['field'] == 'system_prompt'
    assert body['count'] >= 1
    assert isinstance(body['items'], list)




def test_agent_version_search_limit_query_bounds():
    token = create_access_token("1")

    ok = client.get(
        '/api/v1/agents/1/versions/meta/search?field=system_prompt&limit=100',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 200

    low = client.get(
        '/api/v1/agents/1/versions/meta/search?field=system_prompt&limit=0',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert low.status_code == 422

    high = client.get(
        '/api/v1/agents/1/versions/meta/search?field=system_prompt&limit=101',
        headers={"Authorization": f"Bearer {token}"},
    )
    assert high.status_code == 422


def test_agent_version_fields_limit_query_bounds():
    token = create_access_token("1")

    ok = client.get('/api/v1/agents/1/versions/meta/fields?limit=100', headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200

    low = client.get('/api/v1/agents/1/versions/meta/fields?limit=0', headers={"Authorization": f"Bearer {token}"})
    assert low.status_code == 422

    high = client.get('/api/v1/agents/1/versions/meta/fields?limit=101', headers={"Authorization": f"Bearer {token}"})
    assert high.status_code == 422

def test_agent_version_report_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    report = client.get('/api/v1/agents/1/versions/meta/report?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert report.status_code == 200
    body = report.json()
    assert "count" in body
    assert "timeline" in body
    assert "field_stats" in body
    assert isinstance(body["timeline"], list)


def test_agent_version_report_summary_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    summary = client.get('/api/v1/agents/1/versions/meta/report/summary?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert summary.status_code == 200
    body = summary.json()
    assert 'summary' in body
    assert 'Agent Version Report Summary' in body['summary']


def test_agent_version_report_markdown_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/markdown?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'markdown' in body
    assert '# Agent Version Report' in body['markdown']


def test_agent_version_report_csv_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/csv?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'csv' in body
    assert 'version_no,compared_to,changed_count,changed_fields' in body['csv']




def test_agent_version_report_csv_handles_special_characters():
    import csv
    import io

    token = create_access_token("1")

    first = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert first.status_code == 200

    changed = client.put(
        '/api/v1/agents/1',
        headers={"Authorization": f"Bearer {token}"},
        json={
            'name': 'Agent,CSV',
            'description': 'line1\nline2,with,comma',
            'system_prompt': 'quote "and" comma, newline\nvalue',
        },
    )
    assert changed.status_code == 200

    second = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert second.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/csv?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'csv' in body

    reader = csv.reader(io.StringIO(body['csv']))
    rows = list(reader)
    assert rows[0] == ['version_no', 'compared_to', 'changed_count', 'changed_fields']
    assert all(len(r) == 4 for r in rows if r)


def test_agent_version_report_top_fields_query_bounds():
    token = create_access_token("1")

    ok = client.get('/api/v1/agents/1/versions/meta/report/top-fields?limit=10&top_n=50', headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200

    bad = client.get('/api/v1/agents/1/versions/meta/report/top-fields?limit=10&top_n=0', headers={"Authorization": f"Bearer {token}"})
    assert bad.status_code == 422

def test_agent_version_report_top_fields_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/top-fields?limit=10&top_n=3', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'analyzed_versions' in body
    assert 'top_fields' in body
    assert isinstance(body['top_fields'], list)


def test_agent_version_report_jsonl_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/jsonl?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'jsonl' in body
    # empty allowed, but if non-empty should contain JSON object lines
    if body['jsonl']:
        assert body['jsonl'].strip().startswith('{')




def test_agent_version_report_xml_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/xml?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'xml' in body
    assert '<version_report>' in body['xml']
    assert '<latest>' in body['xml']
    assert '<timeline>' in body['xml']
    assert '<changed_fields>' in body['xml']
    assert '<field_stats>' in body['xml']

def test_agent_version_report_yaml_endpoint():
    token = create_access_token("1")

    made = client.post('/api/v1/agents/1/versions/snapshot', headers={"Authorization": f"Bearer {token}"})
    assert made.status_code == 200

    resp = client.get('/api/v1/agents/1/versions/meta/report/yaml?limit=10', headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert 'yaml' in body
    assert 'count:' in body['yaml']
    assert 'timeline:' in body['yaml']
