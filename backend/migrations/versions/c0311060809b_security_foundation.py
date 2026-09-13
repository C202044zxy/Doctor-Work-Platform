"""T08 user state and T11 audit metadata; preserves existing rows."""

import sqlalchemy as sa
from alembic import op

revision = "c0311060809b"
down_revision = "e3b6c9d24f75"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("audit_logs") as batch:
        batch.alter_column("patient_id", existing_type=sa.Integer(), nullable=True)
        for name, kind in [
            ("user_id", sa.Integer()),
            ("ip", sa.String(45)),
            ("method", sa.String(10)),
            ("path", sa.String(500)),
            ("object_type", sa.String(50)),
            ("object_id", sa.String(100)),
            ("result", sa.String(20)),
            ("status_code", sa.Integer()),
        ]:
            batch.add_column(sa.Column(name, kind, nullable=True))
    # Defense in depth even when a development account has schema-wide grants.
    dialect = op.get_bind().dialect.name
    for operation in ("UPDATE", "DELETE"):
        name = f"audit_logs_no_{operation.lower()}"
        if dialect == "sqlite":
            op.execute(
                f"CREATE TRIGGER {name} BEFORE {operation} ON audit_logs BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END"
            )
        elif dialect == "mysql":
            op.execute(
                f"CREATE TRIGGER {name} BEFORE {operation} ON audit_logs FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_logs is append-only'"
            )


def downgrade():
    for name in ("audit_logs_no_update", "audit_logs_no_delete"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    with op.batch_alter_table("audit_logs") as batch:
        for name in [
            "user_id",
            "ip",
            "method",
            "path",
            "object_type",
            "object_id",
            "result",
            "status_code",
        ]:
            batch.drop_column(name)
    # patient_id remains nullable: authentication events have no patient reference.
