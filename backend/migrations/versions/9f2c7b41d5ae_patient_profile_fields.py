"""patient profile fields

Revision ID: 9f2c7b41d5ae
Revises: b75f06934276
Create Date: 2026-09-11 00:00:00.000000

Adds the columns task T13 needs: a server-generated patient number, encrypted
phone and national ID, symptom tags, admission date, and a creation timestamp.

patient_no is nullable in the database on purpose. SQLite cannot add a NOT NULL
column to a populated table without a default, and rebuilding the table to drop
that default would break the ON DELETE CASCADE link from allergies while
PRAGMA foreign_keys is on. Existing rows are backfilled here and the unique
index below keeps the values unique; the API always supplies one.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "9f2c7b41d5ae"
down_revision = "b75f06934276"
branch_labels = None
depends_on = None

_PLACEHOLDER_CREATED_AT = "1970-01-01 00:00:00"


def upgrade():
    op.add_column("patients", sa.Column("patient_no", sa.String(length=20), nullable=True))
    op.add_column("patients", sa.Column("phone_enc", sa.String(length=255), nullable=True))
    op.add_column("patients", sa.Column("id_card_enc", sa.String(length=255), nullable=True))
    op.add_column(
        "patients",
        sa.Column("symptom_tags", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column("patients", sa.Column("admitted_at", sa.Date(), nullable=True))
    op.add_column(
        "patients",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            # A constant is the only default SQLite accepts on ADD COLUMN; the API
            # always writes a real timestamp and the backfill below fixes old rows.
            server_default=sa.text(f"'{_PLACEHOLDER_CREATED_AT}'"),
        ),
    )

    connection = op.get_bind()
    year = datetime.now(UTC).year
    legacy_ids = list(connection.execute(sa.text("SELECT id FROM patients ORDER BY id")).scalars())
    for sequence, patient_id in enumerate(legacy_ids, start=1):
        connection.execute(
            sa.text("UPDATE patients SET patient_no = :number WHERE id = :id"),
            {"number": f"P{year}{sequence:04d}", "id": patient_id},
        )
    connection.execute(
        sa.text("UPDATE patients SET created_at = :now WHERE created_at = :placeholder"),
        {
            "now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "placeholder": _PLACEHOLDER_CREATED_AT,
        },
    )

    op.create_index("ix_patients_patient_no", "patients", ["patient_no"], unique=True)
    op.create_index("ix_patients_created_at", "patients", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_patients_created_at", table_name="patients")
    op.drop_index("ix_patients_patient_no", table_name="patients")
    op.drop_column("patients", "created_at")
    op.drop_column("patients", "admitted_at")
    op.drop_column("patients", "symptom_tags")
    op.drop_column("patients", "id_card_enc")
    op.drop_column("patients", "phone_enc")
    op.drop_column("patients", "patient_no")
