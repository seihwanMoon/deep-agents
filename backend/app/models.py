from datetime import datetime
from sqlalchemy import String, Text, DateTime, Integer, Boolean, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base
from .time import utcnow


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentFolder(Base):
    __tablename__ = "agent_folders"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("agent_folders.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(255), default="openai:gpt-4o-mini")
    webhook_token: Mapped[str] = mapped_column(String(255), unique=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    recursion_limit: Mapped[int] = mapped_column(Integer, default=25)
    mcp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentOpener(Base):
    __tablename__ = "agent_openers"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    order_no: Mapped[int] = mapped_column(Integer, default=0)


class Tool(Base):
    __tablename__ = "tools"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    type: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Secret(Base):
    __tablename__ = "secrets"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key_name: Mapped[str] = mapped_column(String(255), index=True)
    key_value: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(String(50), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AgentDocument(Base):
    __tablename__ = "agent_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentSchedule(Base):
    __tablename__ = "agent_schedules"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    cron_expr: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="Chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WebhookCallbackEvent(Base):
    __tablename__ = "webhook_callback_events"
    __table_args__ = (UniqueConstraint("agent_id", "event_id", name="uq_webhook_callback_agent_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="accepted")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
