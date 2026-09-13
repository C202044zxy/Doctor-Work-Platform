"""T02/T05/T10: contract user identities and patient-scoped temporary grants."""

import sqlalchemy as sa
from alembic import op

revision = "d2a5f8b13c64"
down_revision = "c1d4e7a90b52"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("username", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("name", sa.String(100), nullable=True))
    op.add_column(
        "users", sa.Column("status", sa.String(20), nullable=False, server_default="active")
    )
    op.add_column("users", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE users SET username = CONCAT('user_', id), name = email, created_at = CURRENT_TIMESTAMP"
        )
        if conn.dialect.name == "mysql"
        else sa.text(
            "UPDATE users SET username = 'user_' || id, name = email, created_at = CURRENT_TIMESTAMP"
        )
    )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("username", existing_type=sa.String(100), nullable=False)
        batch.alter_column("name", existing_type=sa.String(100), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_unique_constraint("uq_users_username", ["username"])
    for old, new in (
        ("administrator", "admin"),
        ("department_manager", "senior"),
        ("doctor", "junior"),
    ):
        old_id = conn.execute(
            sa.text("SELECT id FROM roles WHERE name=:name"), {"name": old}
        ).scalar()
        new_id = conn.execute(
            sa.text("SELECT id FROM roles WHERE name=:name"), {"name": new}
        ).scalar()
        if old_id is not None and new_id is not None:
            conn.execute(
                sa.text("UPDATE users SET role_id=:new WHERE role_id=:old"),
                {"new": new_id, "old": old_id},
            )
            conn.execute(sa.text("DELETE FROM roles WHERE id=:id"), {"id": old_id})
        elif old_id is not None:
            conn.execute(
                sa.text("UPDATE roles SET name=:new WHERE id=:id"), {"new": new, "id": old_id}
            )
    op.create_table(
        "temp_grant",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("grantee_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_valid", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("grantee_id", "patient_id", "expire_at", "is_valid"):
        op.create_index(f"ix_temp_grant_{column}", "temp_grant", [column])


def downgrade():
    op.drop_table("temp_grant")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_username", type_="unique")
        for column in ("username", "name", "status", "created_at"):
            batch.drop_column(column)
    for old, new in (
        ("administrator", "admin"),
        ("department_manager", "senior"),
        ("doctor", "junior"),
    ):
        op.get_bind().execute(
            sa.text("UPDATE roles SET name=:old WHERE name=:new"), {"old": old, "new": new}
        )
