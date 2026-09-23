"""Self-service password session revocation and real browser call recordings."""

import sqlalchemy as sa
from alembic import op

revision = "f7a8c9022026"
down_revision = "e2b7d4c1a905"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.create_table(
        "call_recording",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("room_key", sa.String(32), nullable=False),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("next_sequence", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("call_id", "owner_id", name="uq_call_recorder"),
    )
    op.create_index("ix_call_recording_room_key", "call_recording", ["room_key"])


def downgrade():
    op.drop_table("call_recording")
    op.drop_column("users", "session_version")
