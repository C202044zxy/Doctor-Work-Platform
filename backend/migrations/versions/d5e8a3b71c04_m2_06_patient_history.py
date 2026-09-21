"""M2-06: the patient medical history table.

Revision ID: d5e8a3b71c04
Revises: e6a31c29d408
Create Date: 2026-09-21 10:00:00.000000

The timeline view's data source. The contract has carried
`/api/patients/{patient_no}/histories` and `/api/histories/{id}` since before
this revision, with `PatientDetail.histories` marked required while the
endpoint returned a hard-coded empty list. This is the table that fills it.

`onset_date` is nullable because the contract requires only `diagnosis` on a
create. An entry recorded without a date is a real record: it is kept and
sorted to the bottom of the timeline rather than refused -- see
`app.histories.histories_for_patient` for why that sort is written as
`onset_date IS NULL` and not `NULLS LAST`.

`created_at` is deliberately unindexed, unlike the timestamp on most tables
here: the timeline orders by `onset_date` and nothing filters by creation
order, so an index would be write cost with no reader. The contract names the
field, so the column stays.

Nothing is altered on `patients`. On SQLite a batch rebuild of that table
would drop the append-only triggers `c0311060809b` installed on `audit_logs`,
which is the same reason `a7f3c2e91d04` created standalone child tables
instead of widening the parent.
"""

import sqlalchemy as sa
from alembic import op

revision = "d5e8a3b71c04"
down_revision = "e6a31c29d408"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "patient_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("diagnosis", sa.String(200), nullable=False),
        sa.Column("onset_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_patient_history_patient_id", "patient_history", ["patient_id"])


def downgrade():
    op.drop_index("ix_patient_history_patient_id", table_name="patient_history")
    op.drop_table("patient_history")
