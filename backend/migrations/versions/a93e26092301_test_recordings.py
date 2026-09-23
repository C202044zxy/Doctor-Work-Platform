"""Retain named local test recordings beside call recordings."""

import sqlalchemy as sa
from alembic import op

revision = "a93e26092301"
down_revision = "f7a8c9022026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "call_recording",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("call_recording", sa.Column("filename", sa.String(180), nullable=True))


def downgrade():
    op.drop_column("call_recording", "filename")
    op.drop_column("call_recording", "is_test")
