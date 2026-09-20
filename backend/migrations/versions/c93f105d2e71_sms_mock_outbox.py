"""S1 simulated SMS delivery records."""

import sqlalchemy as sa
from alembic import op

revision = "c93f105d2e71"
down_revision = "a9c327e80f16"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notify_outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("target", sa.String(100), nullable=False),
        sa.Column("template", sa.String(100), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("code", sa.String(6)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("notify_outbox")
