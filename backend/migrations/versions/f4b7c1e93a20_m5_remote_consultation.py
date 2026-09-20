"""T30/T31/T32: remote consultations, shared materials and the report archive.

Four tables, all new, so nothing here needs a batch rebuild -- which matters on
SQLite, where a rebuild would silently drop the append-only triggers that
`c0311060809b` installed on `audit_logs` (see the T12 migration's note).

`meeting_reports` carries a unique key on `(meeting_id, version)`: a report is
never overwritten in place, a later conclusion is a new version, and that
invariant is enforced by the database rather than by the route alone.
"""

import sqlalchemy as sa
from alembic import op

revision = "f4b7c1e93a20"
down_revision = "786395e6a0ba"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("initiator_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="requested"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("patient_id", "initiator_id", "status", "scheduled_at", "created_at"):
        op.create_index(f"ix_meetings_{column}", "meetings", [column])

    op.create_table(
        "meeting_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="invited"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("meeting_id", "user_id", name="uq_meeting_participant"),
    )
    for column in ("meeting_id", "user_id", "status"):
        op.create_index(f"ix_meeting_participants_{column}", "meeting_participants", [column])

    op.create_table(
        "meeting_materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(255), nullable=False, unique=True),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("meeting_id", "uploaded_by", "uploaded_at"):
        op.create_index(f"ix_meeting_materials_{column}", "meeting_materials", [column])

    op.create_table(
        "meeting_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "meeting_id",
            sa.Integer(),
            sa.ForeignKey("meetings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expert_opinions", sa.JSON(), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="final"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("meeting_id", "version", name="uq_meeting_report_version"),
    )
    for column in ("meeting_id", "created_at"):
        op.create_index(f"ix_meeting_reports_{column}", "meeting_reports", [column])


def downgrade():
    op.drop_table("meeting_reports")
    op.drop_table("meeting_materials")
    op.drop_table("meeting_participants")
    op.drop_table("meetings")
