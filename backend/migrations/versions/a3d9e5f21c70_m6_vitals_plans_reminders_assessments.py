"""M6: vital signs, health plans, reminder rules and their log, assessments.

Six new tables, nothing altered, so no batch rebuild is needed -- which matters on
SQLite, where a rebuild would silently drop the append-only triggers that
`c0311060809b` installed on `audit_logs` (see the T12 migration's note).

Three invariants live in the database rather than in a route:

* `vital_thresholds.sign_type` is unique. Two ranges for one sign would make
  `is_abnormal` depend on which row a query happened to return.
* `reminder_logs (rule_id, due_at)` is unique. The scheduler re-evaluates the
  same window after every restart; that key is what makes a duplicate reminder
  impossible rather than merely unlikely (T36 scenario S2 restarts twice).
* `health_assessments (patient_id, period, version)` is unique. A revision is a
  new row, so the earlier conclusion stays readable as written (T37).

The three threshold rows are inserted here, not in `app.seed`: they are reference
data the service cannot work without, and a build that ran the migrations but not
the seeders would otherwise record every reading as in range.
"""

import sqlalchemy as sa
from alembic import op

revision = "a3d9e5f21c70"
down_revision = "f4b7c1e93a20"
branch_labels = None
depends_on = None

# The reference ranges the demo runs on. Blood pressure carries both halves of the
# pair: 90-139 systolic, 60-89 diastolic.
THRESHOLDS = (
    {
        "sign_type": "bp",
        "unit": "mmHg",
        "min_value": 90.0,
        "max_value": 139.0,
        "min_secondary": 60.0,
        "max_secondary": 89.0,
    },
    {
        "sign_type": "gl",
        "unit": "mmol/L",
        "min_value": 3.9,
        "max_value": 6.1,
        "min_secondary": None,
        "max_secondary": None,
    },
    {
        "sign_type": "hr",
        "unit": "bpm",
        "min_value": 60.0,
        "max_value": 100.0,
        "min_secondary": None,
        "max_secondary": None,
    },
)


def upgrade():
    thresholds = op.create_table(
        "vital_thresholds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sign_type", sa.String(10), nullable=False, unique=True),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("max_value", sa.Float(), nullable=False),
        sa.Column("min_secondary", sa.Float(), nullable=True),
        sa.Column("max_secondary", sa.Float(), nullable=True),
    )
    op.bulk_insert(thresholds, list(THRESHOLDS))

    op.create_table(
        "vital_signs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("sign_type", sa.String(10), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("value_secondary", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(10), nullable=False, server_default="manual"),
        sa.Column("is_abnormal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "patient_id",
        "sign_type",
        "recorded_at",
        "is_abnormal",
        "recorded_by",
        "created_at",
    ):
        op.create_index(f"ix_vital_signs_{column}", "vital_signs", [column])

    op.create_table(
        "health_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("goals", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("patient_id", "status", "created_at"):
        op.create_index(f"ix_health_plans_{column}", "health_plans", [column])

    op.create_table(
        "reminder_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("rtype", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("cron_expr", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("health_plan_id", sa.Integer(), sa.ForeignKey("health_plans.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("patient_id", "health_plan_id", "active", "created_at"):
        op.create_index(f"ix_reminder_rules_{column}", "reminder_rules", [column])

    op.create_table(
        "reminder_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("reminder_rules.id"), nullable=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("rule_id", "due_at", name="uq_reminder_log_due"),
    )
    for column in ("rule_id", "patient_id", "due_at", "done", "read"):
        op.create_index(f"ix_reminder_logs_{column}", "reminder_logs", [column])

    op.create_table(
        "health_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("conclusion", sa.Text(), nullable=False),
        sa.Column("plan_adjustment", sa.Text(), nullable=False, server_default=""),
        sa.Column("assessed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("patient_id", "period", "version", name="uq_assessment_version"),
    )
    for column in ("patient_id", "period", "assessed_by", "assessed_at", "created_at"):
        op.create_index(f"ix_health_assessments_{column}", "health_assessments", [column])


def downgrade():
    op.drop_table("health_assessments")
    op.drop_table("reminder_logs")
    op.drop_table("reminder_rules")
    op.drop_table("health_plans")
    op.drop_table("vital_signs")
    op.drop_table("vital_thresholds")
