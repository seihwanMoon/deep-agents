"""add agent_openers"""

from alembic import op
import sqlalchemy as sa

revision = "0003_agent_openers"
down_revision = "0002_phase4_6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_openers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_agent_openers_agent_id", "agent_openers", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_openers_agent_id", table_name="agent_openers")
    op.drop_table("agent_openers")
