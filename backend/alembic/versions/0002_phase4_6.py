"""phase4-6 schema"""

from alembic import op
import sqlalchemy as sa

revision = "0002_phase4_6"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tools_user_id", "tools", ["user_id"])

    op.create_table(
        "secrets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_name", sa.String(length=255), nullable=False),
        sa.Column("key_value", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=50), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_secrets_user_id", "secrets", ["user_id"])

    op.create_table(
        "agent_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
    )
    op.create_index("ix_agent_documents_agent_id", "agent_documents", ["agent_id"])

    op.create_table(
        "agent_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cron_expr", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_agent_schedules_agent_id", "agent_schedules", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_schedules_agent_id", table_name="agent_schedules")
    op.drop_table("agent_schedules")
    op.drop_index("ix_agent_documents_agent_id", table_name="agent_documents")
    op.drop_table("agent_documents")
    op.drop_index("ix_secrets_user_id", table_name="secrets")
    op.drop_table("secrets")
    op.drop_index("ix_tools_user_id", table_name="tools")
    op.drop_table("tools")
