"""M5 chat and video reuse the M3 room through a shared, namespaced room key.

Adds `room_key` to the three tables that hang off a live room, and relaxes
`consultation_id`, which could only ever name a consultation.

`room_key` is digits for a consultation and `m<id>` for a meeting (see `app.rooms`).
Existing rows are backfilled from `consultation_id`, which is exactly what the digits
spelling already means, so no data is rewritten -- a column is filled in.

`consultation_id` stays populated for consultation rows: record search and the demo
seeders read it. It becomes nullable because a meeting message has no consultation to
point at. The retry key on `consult_message` moves from the consultation to the room,
or two rooms could collide on a `client_id`.

SQLite cannot relax a NOT NULL or drop a constraint in place, so those two tables are
recreated through batch mode with `recreate="always"` stated rather than inferred.
"""

import sqlalchemy as sa
from alembic import op

revision = "e2b7d4c1a905"
down_revision = "d5e8a3b71c04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("consult_message", sa.Column("room_key", sa.String(32), nullable=True))
    op.add_column("call_log", sa.Column("room_key", sa.String(32), nullable=True))
    op.add_column("image_upload", sa.Column("room_key", sa.String(32), nullable=True))
    op.execute("UPDATE consult_message SET room_key = CAST(consultation_id AS TEXT)")
    op.execute("UPDATE call_log SET room_key = CAST(consultation_id AS TEXT)")
    op.execute(
        "UPDATE image_upload SET room_key = CAST(consultation_id AS TEXT) "
        "WHERE consultation_id IS NOT NULL"
    )

    with op.batch_alter_table("consult_message", recreate="always") as batch:
        batch.alter_column("room_key", existing_type=sa.String(32), nullable=False)
        batch.alter_column("consultation_id", existing_type=sa.Integer(), nullable=True)
        batch.drop_constraint("uq_message_retry", type_="unique")
        batch.create_unique_constraint("uq_message_retry", ["room_key", "sender_id", "client_id"])
        batch.create_index("ix_consult_message_room_key", ["room_key"])

    with op.batch_alter_table("call_log", recreate="always") as batch:
        batch.alter_column("room_key", existing_type=sa.String(32), nullable=False)
        batch.alter_column("consultation_id", existing_type=sa.Integer(), nullable=True)
        batch.create_index("ix_call_log_room_key", ["room_key"])

    op.create_index("ix_image_upload_room_key", "image_upload", ["room_key"])


def downgrade():
    # The pre-upgrade schema cannot hold a meeting message or a meeting call: its
    # `consultation_id` is NOT NULL and there is no consultation to name. Such rows are
    # dropped rather than failing the ALTER halfway through -- a downgrade past this
    # revision loses meeting rooms, and saying so is better than a broken schema.
    op.drop_index("ix_image_upload_room_key", "image_upload")
    op.execute("DELETE FROM consult_message WHERE consultation_id IS NULL")
    op.execute("DELETE FROM call_log WHERE consultation_id IS NULL")
    with op.batch_alter_table("call_log", recreate="always") as batch:
        batch.drop_index("ix_call_log_room_key")
        batch.alter_column("room_key", existing_type=sa.String(32), nullable=True)
        batch.alter_column("consultation_id", existing_type=sa.Integer(), nullable=False)
    with op.batch_alter_table("consult_message", recreate="always") as batch:
        batch.drop_index("ix_consult_message_room_key")
        batch.alter_column("room_key", existing_type=sa.String(32), nullable=True)
        batch.alter_column("consultation_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_constraint("uq_message_retry", type_="unique")
        batch.create_unique_constraint(
            "uq_message_retry", ["consultation_id", "sender_id", "client_id"]
        )
    for table in ("consult_message", "call_log", "image_upload"):
        op.drop_column(table, "room_key")
