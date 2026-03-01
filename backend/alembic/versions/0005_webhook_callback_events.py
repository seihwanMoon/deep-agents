"""add webhook callback events table

Revision ID: 0005_webhook_callback_events
Revises: 0004_conversations_messages
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_webhook_callback_events"
down_revision = "0004_conversations_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_callback_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="accepted"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("agent_id", "event_id", name="uq_webhook_callback_agent_event"),
    )
    op.create_index("ix_webhook_callback_events_agent_id", "webhook_callback_events", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_callback_events_agent_id", table_name="webhook_callback_events")
    op.drop_table("webhook_callback_events")
