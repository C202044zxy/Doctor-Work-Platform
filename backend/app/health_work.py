"""T35 health plans and T36 scheduled reminders."""

from datetime import UTC, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit import mark_audit
from app.dependencies import Pagination
from app.models import Patient, User
from app.patients import visible_patient
from app.security import require_permission
from app.work_common import DB, fields, ok, page, patient_for, scoped, utc
from app.work_models import HealthPlan, ReminderLog, ReminderRule
from app.work_schemas import (
    Envelope,
    LogPage,
    LogRead,
    PageData,
    PlanRead,
    PlanWrite,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    UnreadRead,
)

router = APIRouter(tags=["Health"], dependencies=[Depends(require_permission("health.write"))])
Paging = Annotated[Pagination, Depends()]


def audit(db, action, row):
    mark_audit(db.info["request"], action, action.split(".")[0], row.id, patient_id=row.patient_id)


def plan_data(db, row):
    return {
        **fields(
            row,
            "id",
            "title",
            "goals",
            "instructions",
            "entries",
            "start_date",
            "end_date",
            "status",
            "created_at",
        ),
        "patient_no": db.get(Patient, row.patient_id).patient_no,
        "reminder_rule_ids": list(
            db.scalars(select(ReminderRule.id).where(ReminderRule.health_plan_id == row.id))
        ),
    }


def rule_data(db, row):
    return {
        **fields(row, "id", "rtype", "title", "cron_expr", "active", "health_plan_id"),
        "patient_no": db.get(Patient, row.patient_id).patient_no,
    }


def log_data(db, row):
    return {
        **fields(row, "id", "rule_id", "title", "due_at", "fired_at", "done", "done_at", "read"),
        "patient_no": db.get(Patient, row.patient_id).patient_no,
    }


def owned_rule(db, rule_id):
    row = db.get(ReminderRule, rule_id)
    if row is None or row.doctor_id != db.info["user"].id:
        raise HTTPException(404, "Reminder rule not found")
    patient_for(db, row.patient_id)
    return row


def get_plan(db, plan_id):
    row = db.get(HealthPlan, plan_id)
    if row is None:
        raise HTTPException(404, "Health plan not found")
    patient_for(db, row.patient_id)
    return row


def add_rule(db, body, plan=None):
    patient = visible_patient(db, db.info["user"], body.patient_no)
    if body.health_plan_id is not None:
        if plan and body.health_plan_id != plan.id:
            raise HTTPException(422, "health_plan_id does not match plan")
        plan = get_plan(db, body.health_plan_id)
    if plan and plan.patient_id != patient.id:
        raise HTTPException(422, "Reminder patient_no must match plan")
    row = ReminderRule(
        patient_id=patient.id,
        doctor_id=db.info["user"].id,
        health_plan_id=plan.id if plan else None,
        **body.model_dump(exclude={"patient_no", "health_plan_id"}),
    )
    db.add(row)
    db.flush()
    return row


def write_plan(db, body, row=None):
    patient = visible_patient(db, db.info["user"], body.patient_no)
    if row and row.patient_id != patient.id:
        raise HTTPException(422, "patient_no cannot change on an existing plan")
    is_new = row is None
    if is_new:
        row = HealthPlan(patient_id=patient.id, doctor_id=db.info["user"].id)
        db.add(row)
    for key, value in body.model_dump(
        exclude={"patient_no", "reminder_rule_ids", "new_reminder_rules"}
    ).items():
        setattr(row, key, value)
    db.flush()
    # Linking is atomic with plan creation. Never steal a rule from another plan.
    for rule_id in set(body.reminder_rule_ids):
        rule = owned_rule(db, rule_id)
        if rule.patient_id != patient.id or rule.health_plan_id not in (None, row.id):
            raise HTTPException(422, "Reminder rule belongs to another patient or plan")
        rule.health_plan_id = row.id
    for rule_body in body.new_reminder_rules:
        add_rule(db, rule_body, row)
    audit(db, "health_plan.create" if is_new else "health_plan.update", row)
    db.commit()
    return ok(plan_data(db, row))


@router.get("/api/health-plans", response_model=Envelope[PageData[PlanRead]])
def list_plans(db: DB, pagination: Paging, patient_no: str | None = None):
    stmt = scoped(HealthPlan, db)
    if patient_no:
        stmt = stmt.where(Patient.patient_no == patient_no)
    return ok(
        page(db, stmt.order_by(HealthPlan.id.desc()), pagination, lambda row: plan_data(db, row))
    )


@router.post("/api/health-plans", response_model=Envelope[PlanRead])
def create_plan(body: PlanWrite, db: DB):
    return write_plan(db, body)


@router.get("/api/health-plans/{id}", response_model=Envelope[PlanRead])
def read_plan(id: int, db: DB):
    row = get_plan(db, id)
    audit(db, "health_plan.view", row)
    return ok(plan_data(db, row))


@router.patch("/api/health-plans/{id}", response_model=Envelope[PlanRead])
def update_plan(id: int, body: PlanWrite, db: DB):
    return write_plan(db, body, get_plan(db, id))


@router.get("/api/reminder-rules", response_model=Envelope[list[RuleRead]])
def list_rules(db: DB, patient_no: str | None = None):
    stmt = scoped(ReminderRule, db).where(ReminderRule.doctor_id == db.info["user"].id)
    if patient_no:
        stmt = stmt.where(Patient.patient_no == patient_no)
    return ok([rule_data(db, row) for row in db.scalars(stmt.order_by(ReminderRule.id.desc()))])


@router.post("/api/reminder-rules", response_model=Envelope[RuleRead])
def create_rule(body: RuleCreate, db: DB):
    row = add_rule(db, body)
    audit(db, "reminder_rule.create", row)
    db.commit()
    return ok(rule_data(db, row))


@router.patch("/api/reminder-rules/{id}", response_model=Envelope[RuleRead])
def update_rule(id: int, body: RuleUpdate, db: DB):
    row = owned_rule(db, id)
    updates = body.model_dump(exclude_unset=True)
    if "patient_no" in updates:
        patient = visible_patient(db, db.info["user"], updates.pop("patient_no"))
        if row.health_plan_id and get_plan(db, row.health_plan_id).patient_id != patient.id:
            raise HTTPException(422, "patient_no must match plan")
        row.patient_id = patient.id
    for key, value in updates.items():
        setattr(row, key, value)
    audit(db, "reminder_rule.update", row)
    db.commit()
    return ok(rule_data(db, row))


def log_scope(db):
    return scoped(ReminderLog, db).where(ReminderLog.doctor_id == db.info["user"].id)


def unread_count(db):
    return (
        db.scalar(
            select(func.count()).select_from(
                log_scope(db).where(ReminderLog.read.is_(False)).subquery()
            )
        )
        or 0
    )


@router.get("/api/reminders/unread-count", response_model=Envelope[UnreadRead])
def count_reminders(db: DB):
    return ok({"unread_count": unread_count(db)})


@router.get("/api/reminders", response_model=Envelope[LogPage])
def list_reminders(
    db: DB,
    pagination: Paging,
    patient_no: str | None = None,
    done: bool | None = None,
    unread_only: bool = False,
):
    stmt = log_scope(db)
    if patient_no:
        stmt = stmt.where(Patient.patient_no == patient_no)
    if done is not None:
        stmt = stmt.where(ReminderLog.done == done)
    if unread_only:
        stmt = stmt.where(ReminderLog.read.is_(False))

    def render(row):
        if not unread_only:
            row.read = True
        return log_data(db, row)

    data = page(
        db, stmt.order_by(ReminderLog.due_at.desc(), ReminderLog.id.desc()), pagination, render
    )
    db.commit()
    data["unread_count"] = unread_count(db)
    mark_audit(db.info["request"], "reminder.view", "reminder")
    return ok(data)


@router.post("/api/reminders/{id}/done", response_model=Envelope[LogRead])
def done_reminder(id: int, db: DB):
    row = db.scalar(log_scope(db).where(ReminderLog.id == id))
    if row is None:
        raise HTTPException(404, "Reminder not found")
    if not row.done:
        row.done, row.read, row.done_at = True, True, datetime.now(UTC)
    audit(db, "reminder.done", row)
    db.commit()
    return ok(log_data(db, row))


def fire_reminders(sessions, timezone="Asia/Shanghai", at=None):
    """Evaluate current minute only; DB uniqueness also protects overlapping workers.

    No historical catch-up after downtime. Cron is hospital local time, persisted
    instants are UTC. Single worker is the supported SQLite deployment.
    """
    at = utc(at or datetime.now(UTC)).replace(second=0, microsecond=0)
    local = at.astimezone(ZoneInfo(timezone))
    with sessions() as db:
        rules = db.scalars(
            select(ReminderRule)
            .join(Patient)
            .join(User, User.id == ReminderRule.doctor_id)
            .where(
                ReminderRule.active.is_(True), Patient.deleted_at.is_(None), User.status == "active"
            )
        ).all()
        for rule in rules:
            if utc(rule.created_at) > at:
                continue
            plan = db.get(HealthPlan, rule.health_plan_id) if rule.health_plan_id else None
            if plan and (
                plan.status != "active" or not plan.start_date <= local.date() <= plan.end_date
            ):
                continue
            due = CronTrigger.from_crontab(rule.cron_expr, timezone=timezone).get_next_fire_time(
                None, local
            )
            if due is None or due.astimezone(UTC) != at:
                continue
            try:
                with db.begin_nested():
                    db.add(
                        ReminderLog(
                            rule_id=rule.id,
                            patient_id=rule.patient_id,
                            doctor_id=rule.doctor_id,
                            title=rule.title,
                            due_at=at,
                        )
                    )
                    db.flush()
            except IntegrityError:
                pass
        db.commit()
