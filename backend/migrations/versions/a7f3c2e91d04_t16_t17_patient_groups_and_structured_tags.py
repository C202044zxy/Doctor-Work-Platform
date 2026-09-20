"""T16/T17: structured symptom tags, identifier blind indexes, patient groups.

Revision ID: a7f3c2e91d04
Revises: b4c6d0192026
Create Date: 2026-09-20 13:10:00.000000

Three changes that belong to one story -- the patient list, the patient detail
page and T17's grouping all read the same rows.

* `patients.symptom_tags` was a `",tag,tag,"` string. T16 asks for tags that
  support search, and a substring match against a joined string cannot do that
  ("胸" would hit "胸痛"): the tags move to `patient_symptom_tags`, one
  row per tag, where the search is an equality against an indexed column. The
  data is copied before the column is dropped, so no tag is lost.
* `phone_hash` / `id_card_hash` hold `app.crypto.blind_index` of the two
  encrypted identifiers. AES-GCM draws a fresh nonce per write, so the
  ciphertext can never be compared; the keyed digest beside it turns the list
  screen's exact-match `phone` / `id_card` search into an indexed comparison
  instead of a decrypt-every-row scan. Both are backfilled from the ciphertext
  that is already there.
* `patient_groups` / `patient_group_members` are T17's manual grouping. The two
  unique keys are what make a duplicate member a 409 naming the patient rather
  than a row that makes the member count lie.

A row whose ciphertext cannot be read with the current `PATIENT_DATA_KEY` keeps a
NULL hash instead of failing the migration: the search cannot find that row, and
its ciphertext is left exactly as it was.

No table is rebuilt here. On SQLite a batch rebuild of `patients` would drop the
append-only triggers that `c0311060809b` installed on `audit_logs` (see the T12
migration's note), and SQLite has supported `ALTER TABLE ... DROP COLUMN` since
3.35, which is what dropping `symptom_tags` uses.
"""

import sqlalchemy as sa
from alembic import op

from app import crypto

revision = "a7f3c2e91d04"
down_revision = "b4c6d0192026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "patient_symptom_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.String(50), nullable=False),
        sa.UniqueConstraint("patient_id", "tag", name="uq_patient_tag"),
    )
    op.create_index("ix_patient_symptom_tags_patient_id", "patient_symptom_tags", ["patient_id"])
    op.create_index("ix_patient_symptom_tags_tag", "patient_symptom_tags", ["tag"])

    op.add_column("patients", sa.Column("phone_hash", sa.String(64), nullable=True))
    op.add_column("patients", sa.Column("id_card_hash", sa.String(64), nullable=True))
    op.create_index("ix_patients_phone_hash", "patients", ["phone_hash"])
    op.create_index("ix_patients_id_card_hash", "patients", ["id_card_hash"])

    op.create_table(
        "patient_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=sa.text("''")),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("departments.id"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("department_id", "name", name="uq_group_name"),
    )
    op.create_index("ix_patient_groups_department_id", "patient_groups", ["department_id"])
    op.create_index("ix_patient_groups_created_at", "patient_groups", ["created_at"])

    op.create_table(
        "patient_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("patient_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.Integer(),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "patient_id", name="uq_group_member"),
    )
    op.create_index("ix_patient_group_members_group_id", "patient_group_members", ["group_id"])
    op.create_index("ix_patient_group_members_patient_id", "patient_group_members", ["patient_id"])

    connection = op.get_bind()
    _backfill_blind_indexes(connection)
    _move_tags_into_the_table(connection)
    op.drop_column("patients", "symptom_tags")


def downgrade():
    op.add_column(
        "patients",
        sa.Column("symptom_tags", sa.String(500), nullable=False, server_default=""),
    )
    _move_tags_back_to_the_column(op.get_bind())
    op.drop_index("ix_patient_group_members_patient_id", table_name="patient_group_members")
    op.drop_index("ix_patient_group_members_group_id", table_name="patient_group_members")
    op.drop_table("patient_group_members")
    op.drop_index("ix_patient_groups_created_at", table_name="patient_groups")
    op.drop_index("ix_patient_groups_department_id", table_name="patient_groups")
    op.drop_table("patient_groups")
    op.drop_index("ix_patients_id_card_hash", table_name="patients")
    op.drop_index("ix_patients_phone_hash", table_name="patients")
    op.drop_column("patients", "id_card_hash")
    op.drop_column("patients", "phone_hash")
    op.drop_index("ix_patient_symptom_tags_tag", table_name="patient_symptom_tags")
    op.drop_index("ix_patient_symptom_tags_patient_id", table_name="patient_symptom_tags")
    op.drop_table("patient_symptom_tags")


def _readable(token):
    """The plaintext behind a ciphertext, or None when the key cannot read it."""
    if not token:
        return None
    try:
        return crypto.decrypt(token)
    except Exception:  # noqa: BLE001 - a token this key cannot read must not stop the upgrade
        return None


def _backfill_blind_indexes(connection):
    """Fill `phone_hash` / `id_card_hash` from the ciphertext already stored."""
    rows = connection.execute(sa.text("SELECT id, phone_enc, id_card_enc FROM patients")).all()
    for patient_id, phone_enc, id_card_enc in rows:
        connection.execute(
            sa.text(
                "UPDATE patients SET phone_hash = :phone_hash, id_card_hash = :id_card_hash"
                " WHERE id = :id"
            ),
            {
                "phone_hash": crypto.blind_index("phone", _readable(phone_enc)),
                "id_card_hash": crypto.blind_index("id_card", _readable(id_card_enc)),
                "id": patient_id,
            },
        )


def _move_tags_into_the_table(connection):
    """Copy the `",tag,tag,"` column into one row per tag, then it can be dropped.

    The stored values went through `app.schemas.clean_tags`, so a tag is never
    blank, never carries a comma and is never repeated; the dedupe below is the
    one guard that does not depend on that.
    """
    rows = connection.execute(
        sa.text("SELECT id, symptom_tags FROM patients WHERE symptom_tags <> ''")
    ).all()
    for patient_id, stored in rows:
        seen = []
        for raw in stored.split(","):
            tag = raw.strip()
            if tag and tag not in seen:
                seen.append(tag)
        for tag in seen:
            connection.execute(
                sa.text(
                    "INSERT INTO patient_symptom_tags (patient_id, tag) VALUES (:patient_id, :tag)"
                ),
                {"patient_id": patient_id, "tag": tag},
            )


def _move_tags_back_to_the_column(connection):
    """Rebuild the legacy joined string, in the `",tag,tag,"` shape it was written in."""
    rows = connection.execute(
        sa.text("SELECT patient_id, tag FROM patient_symptom_tags ORDER BY patient_id, id")
    ).all()
    joined: dict[int, list[str]] = {}
    for patient_id, tag in rows:
        joined.setdefault(patient_id, []).append(tag)
    for patient_id, tags in joined.items():
        connection.execute(
            sa.text("UPDATE patients SET symptom_tags = :stored WHERE id = :id"),
            {"stored": f",{','.join(tags)},", "id": patient_id},
        )
