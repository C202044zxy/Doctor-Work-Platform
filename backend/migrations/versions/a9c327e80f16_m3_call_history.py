"""M3 finished call metadata and record lookup indexes."""

import sqlalchemy as sa
from alembic import op

revision = "a9c327e80f16"
down_revision = "f18a03c94b62"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "consultation_id", sa.Integer(), sa.ForeignKey("consultation.id"), nullable=False
        ),
        sa.Column("call_id", sa.String(64), nullable=False, unique=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("end_reason", sa.String(30), nullable=False),
    )
    op.create_index("ix_call_log_consultation_id", "call_log", ["consultation_id"])
    op.create_index("ix_consultation_created_at", "consultation", ["created_at"])


def downgrade():
    op.drop_index("ix_consultation_created_at", "consultation")
    op.drop_index("ix_call_log_consultation_id", "call_log")
    op.drop_table("call_log")
