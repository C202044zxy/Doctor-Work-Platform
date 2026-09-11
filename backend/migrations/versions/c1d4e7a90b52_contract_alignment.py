"""align patient and allergy records with the API contract

Revision ID: c1d4e7a90b52
Revises: 9f2c7b41d5ae
Create Date: 2026-09-11 15:30:00.000000

T13 follow-up. The patient module predates docs/api/openapi.yaml and still used
integer path keys, offset/limit paging and a hard DELETE. This revision adds the
columns the contract needs: gender, birth date and the soft-delete stamp on
patients, the T14 allergy fields on allergies, and the audit detail that carries
the removed allergen's name.

The four new allergy columns are added with a server default so SQLite accepts
them on a populated table, are backfilled from ``substance``, and only then is
the old column dropped.
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "c1d4e7a90b52"
down_revision = "9f2c7b41d5ae"
branch_labels = None
depends_on = None

_PLACEHOLDER_DATE = "1970-01-01"


def upgrade():
    op.add_column(
        "patients",
        sa.Column("gender", sa.String(length=10), nullable=False, server_default="unknown"),
    )
    op.add_column("patients", sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("patients", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_patients_deleted_at", "patients", ["deleted_at"])

    op.add_column(
        "allergies",
        sa.Column("allergen", sa.String(length=50), nullable=False, server_default=""),
    )
    op.add_column(
        "allergies",
        sa.Column("allergy_type", sa.String(length=20), nullable=False, server_default="other"),
    )
    op.add_column(
        "allergies",
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="moderate"),
    )
    op.add_column("allergies", sa.Column("reaction", sa.String(length=255), nullable=True))
    op.add_column(
        "allergies",
        sa.Column("recorded_at", sa.Date(), nullable=False, server_default=_PLACEHOLDER_DATE),
    )

    connection = op.get_bind()
    # Pre-existing rows only carried a free-text substance; keep it as the code and
    # take the contract's default category and severity rather than guessing.
    connection.execute(sa.text("UPDATE allergies SET allergen = substance WHERE allergen = ''"))
    connection.execute(
        sa.text("UPDATE allergies SET recorded_at = :today WHERE recorded_at = :placeholder"),
        {
            "today": datetime.now(UTC).date().isoformat(),
            "placeholder": _PLACEHOLDER_DATE,
        },
    )
    op.create_index("ix_allergies_patient_id", "allergies", ["patient_id"])
    op.drop_column("allergies", "substance")

    op.add_column("audit_logs", sa.Column("detail", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("audit_logs", "detail")

    op.drop_index("ix_allergies_patient_id", table_name="allergies")
    op.add_column(
        "allergies",
        sa.Column("substance", sa.String(length=100), nullable=False, server_default=""),
    )
    op.get_bind().execute(sa.text("UPDATE allergies SET substance = allergen"))
    op.drop_column("allergies", "recorded_at")
    op.drop_column("allergies", "reaction")
    op.drop_column("allergies", "severity")
    op.drop_column("allergies", "allergy_type")
    op.drop_column("allergies", "allergen")

    op.drop_index("ix_patients_deleted_at", table_name="patients")
    op.drop_column("patients", "deleted_at")
    op.drop_column("patients", "birth_date")
    op.drop_column("patients", "gender")
