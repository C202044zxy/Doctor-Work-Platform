"""M7 discussion forum, independent of patient records."""

import sqlalchemy as sa
from alembic import op

revision = "f7a920c13b08"
down_revision = "e2b7d4c1a905"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forum_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("seed_key", sa.String(80), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "forum_replies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("forum_posts.id"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("seed_key", sa.String(80), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_forum_replies_post_id", "forum_replies", ["post_id"])


def downgrade():
    op.drop_table("forum_replies")
    op.drop_table("forum_posts")
