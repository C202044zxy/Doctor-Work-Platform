"""M1/T05: passkeys associated with existing accounts."""

import sqlalchemy as sa
from alembic import op

revision = "e3b6c9d24f75"
down_revision = "d2a5f8b13c64"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "passkeys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(1024), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(2048), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_passkeys_user_id", "passkeys", ["user_id"])


def downgrade():
    op.drop_table("passkeys")
