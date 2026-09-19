"""M6: vital signs, health plans, reminder rules and their log, assessments.

One module because the five pieces are one workflow, in the order the module was
specified: 方案 → 体征 → 趋势图 → 提醒 → 评估. A plan is written, readings are
recorded against it, the readings are what the trend chart draws, the plan's
reminder rules are what the scheduler fires, and the assessment is the periodic
review that may adjust the plan. Splitting them would put the threshold lookup,
the department scope and the audit marking in five places.

Three things here are decisions rather than transcription:

* **Thresholds are read, never hard-coded.** `is_abnormal` is decided at write
  time from the `vital_thresholds` row for that `sign_type`, and the same row is
  what the trend endpoint hands the chart. The client must not recompute it, or
  the chart and the record would disagree the day a clinician moves a bound.
* **Reminder generation is idempotent on `(rule_id, due_at)`.** The job
  re-evaluates the previous minute on every tick and again after every restart;
  the unique key is what makes a second entry impossible rather than unlikely.
* **A revision writes a new row.** `PATCH /api/assessments/{id}` does not edit
  the original, so the earlier conclusion stays readable as written.

The department rule is the ordinary one: a patient outside the caller's scope is
a 404, never an empty page. Every patient-scoped route goes through
`app.patients.visible_patient` for exactly that reason.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import health_schemas as contract
from app.audit import mark_audit
from app.auth import CurrentUser, ok
from app.dependencies import Pagination
from app.models import (
    HealthAssessment,
    HealthPlan,
    Patient,
    ReminderLog,
    ReminderRule,
    User,
    VitalSign,
    VitalThreshold,
)
from app.patients import patient_scope, visible_patient
from app.security import require_permission

router = APIRouter()

# Every role that can sign in holds `health.write` (see `app.security.CLINICAL`),
# so this is a statement of intent rather than a narrowing: it says these routes
# are clinical writes, and the day a read-only role is added it is refused here
# instead of silently allowed.
WRITE = [Depends(require_permission("health.write"))]


def acting_user(request: Request, user: CurrentUser):
    """Name the actor for the audit middleware.

    `app.audit.audit_request` attributes a write to `request.state.identity`, and
    only `main.get_session` sets it -- `auth.current_user` does not. This module
    opens its own sessions, so without this every row it writes would land in the
    trail with a null actor: the log would say a reading was recorded but not by
    whom, which is the one thing the trail exists to answer.
    """
    request.state.identity = user
    return user


Actor = Annotated[User, Depends(acting_user)]


def _utc(value: datetime) -> datetime:
    """SQLite drops the offset, so re-attach UTC before serializing.

    Same reason as `main._as_utc`: without it the browser reads a UTC stamp as
    local time and the trend chart's x-axis is hours out.
    """
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _patient(patient_no: str, user: User, db) -> Patient:
    """The shared scope gate: out of department is a 404, not an empty result."""
    return visible_patient(db, user, patient_no)


def _threshold(db, sign_type: str) -> VitalThreshold:
    row = db.scalar(select(VitalThreshold).where(VitalThreshold.sign_type == sign_type))
    if row is None:
        # Not a 404: the reading is fine, the server has no reference range to
        # judge it against, and recording it as "in range" would be a lie.
        raise HTTPException(503, f"No threshold is configured for {sign_type}")
    return row


def _is_abnormal(row: VitalThreshold, value: float, secondary: float | None) -> bool:
    """Judge one reading against the configured range.

    For `bp` both halves of the pair are tested, so a normal systolic with a high
    diastolic is still abnormal -- which is the case a single-value check misses.
    """
    if value > row.max_value or value < row.min_value:
        return True
    if secondary is None:
        return False
    if row.min_secondary is not None and secondary < row.min_secondary:
        return True
    return row.max_secondary is not None and secondary > row.max_secondary


def _vital(row: VitalSign) -> contract.VitalSignRead:
    return contract.VitalSignRead(
        id=row.id,
        patient_no=row.patient.patient_no,
        sign_type=row.sign_type,
        value=row.value,
        value_secondary=row.value_secondary,
        unit=row.unit,
        recorded_at=_utc(row.recorded_at),
        source=row.source,
        is_abnormal=row.is_abnormal,
        recorded_by=row.recorded_by,
    )


def _rule(row: ReminderRule) -> contract.ReminderRuleRead:
    return contract.ReminderRuleRead(
        id=row.id,
        patient_no=row.patient.patient_no,
        rtype=row.rtype,
        title=row.title,
        cron_expr=row.cron_expr,
        active=row.active,
        health_plan_id=row.health_plan_id,
    )


def _log(row: ReminderLog) -> contract.ReminderLogRead:
    return contract.ReminderLogRead(
        id=row.id,
        rule_id=row.rule_id,
        patient_no=row.patient.patient_no,
        title=row.title,
        due_at=_utc(row.due_at),
        fired_at=_utc(row.fired_at),
        done=row.done,
        done_at=_utc(row.done_at) if row.done_at else None,
        read=row.read,
    )


def _assessment(row: HealthAssessment) -> contract.HealthAssessmentRead:
    return contract.HealthAssessmentRead(
        id=row.id,
        patient_no=row.patient.patient_no,
        period=row.period,
        conclusion=row.conclusion,
        plan_adjustment=row.plan_adjustment or "",
        assessed_by=row.assessed_by,
        assessed_by_name=row.author.name if row.author else "",
        assessed_at=_utc(row.assessed_at),
        version=row.version,
        updated_at=_utc(row.updated_at) if row.updated_at else None,
    )


def _own_rules(db, plan_ids: list[int]) -> dict[int, list[int]]:
    """Reminder-rule ids per plan, for the plans in hand.

    One query for the page rather than one per row: the plan read is on the
    critical path of a clinic screen, and a rule lookup per plan would make it
    N+1 for no benefit.
    """
    found: dict[int, list[int]] = {}
    if not plan_ids:
        return found
    rows = db.execute(
        select(ReminderRule.id, ReminderRule.health_plan_id).where(
            ReminderRule.health_plan_id.in_(plan_ids)
        )
    )
    for rule_id, plan_id in rows:
        found.setdefault(plan_id, []).append(rule_id)
    return found


def _plan(row: HealthPlan, rule_ids: list[int]) -> contract.HealthPlanRead:
    return contract.HealthPlanRead(
        id=row.id,
        patient_no=row.patient.patient_no,
        title=row.title,
        goals=row.goals or "",
        instructions=row.instructions or "",
        entries=[contract.HealthPlanEntry(**entry) for entry in (row.entries or [])],
        start_date=row.start_date,
        end_date=row.end_date,
        status=row.status,
        reminder_rule_ids=rule_ids,
        created_at=_utc(row.created_at),
    )


def _rule_for(db, user: User, rule_id: int) -> ReminderRule:
    row = db.scalar(
        select(ReminderRule)
        .join(Patient, ReminderRule.patient_id == Patient.id)
        .where(
            ReminderRule.id == rule_id,
            Patient.deleted_at.is_(None),
            patient_scope(user),
        )
    )
    if row is None:
        raise HTTPException(404, "Reminder rule not found")
    return row


# ---------------------------------------------------------------- health plans


@router.get("/api/health-plans", response_model=contract.HealthPlanListResponse)
def list_health_plans(
    request: Request,
    user: Actor,
    pagination: Annotated[Pagination, Depends()],
    patient_no: Annotated[str, Query(max_length=20)] = "",
):
    """健康方案列表 / List health plans.

    Scoped by department like every other patient read. A `patient_no` outside the
    caller's scope yields an empty page rather than a 404, which is the same
    choice `list_meetings` makes: a filter that matches nothing is not an error,
    and the 404 belongs to the patient routes.
    """
    with request.app.state.sessions() as db:
        query = (
            select(HealthPlan)
            .join(Patient, HealthPlan.patient_id == Patient.id)
            .where(Patient.deleted_at.is_(None), patient_scope(user))
        )
        if patient_no:
            query = query.where(Patient.patient_no == patient_no)
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            db.scalars(
                query.order_by(HealthPlan.created_at.desc(), HealthPlan.id.desc())
                .offset(pagination.offset)
                .limit(pagination.size)
            )
        )
        rules = _own_rules(db, [row.id for row in rows])
        return ok(
            contract.HealthPlanListData(
                items=[_plan(row, rules.get(row.id, [])) for row in rows],
                total=total,
                page=pagination.page,
                size=pagination.size,
            )
        )


@router.post(
    "/api/health-plans",
    response_model=contract.HealthPlanResponse,
    dependencies=WRITE,
)
def create_health_plan(request: Request, user: Actor, body: contract.HealthPlanWriteRequest):
    """新建健康方案 / Create a health plan.

    The plan and the reminder rules it carries are written in one transaction, so
    scenario S1's "tick the daily 09:00 medication reminder while creating the
    plan, then find the matching rule in the T36 list" cannot half-succeed.
    """
    with request.app.state.sessions() as db:
        patient = _patient(body.patient_no, user, db)
        if body.end_date < body.start_date:
            raise HTTPException(422, "Invalid request: end_date")

        plan = HealthPlan(
            patient_id=patient.id,
            title=body.title,
            goals=body.goals,
            instructions=body.instructions,
            entries=[
                {"kind": entry.kind.value, "text": entry.text, "done": False}
                for entry in body.entries
            ],
            start_date=body.start_date,
            end_date=body.end_date,
            status=body.status.value if body.status else "active",
            created_by=user.id,
        )
        db.add(plan)
        db.flush()

        linked = [_link_rule(db, patient, rule_id, plan).id for rule_id in body.reminder_rule_ids]
        linked += [_new_rule(db, patient, rule, plan, user).id for rule in body.new_reminder_rules]
        mark_audit(
            request,
            "health_plan.create",
            "health_plan",
            plan.id,
            patient_id=patient.id,
            detail={"title": plan.title, "reminder_rules": len(linked)},
        )
        db.commit()
        return ok(_plan(plan, linked))


def _link_rule(db, patient: Patient, rule_id: int, plan: HealthPlan) -> ReminderRule:
    """Attach an existing rule to the new plan.

    The rule has to belong to the same patient: linking a plan to another
    patient's rule would let one department's schedule drive another's care, and
    it is the one way this route could reach outside the caller's scope.
    """
    rule = db.get(ReminderRule, rule_id)
    if rule is None or rule.patient_id != patient.id:
        raise HTTPException(404, "Reminder rule not found")
    rule.health_plan_id = plan.id
    return rule


def _new_rule(
    db, patient: Patient, body: contract.ReminderRuleWriteRequest, plan: HealthPlan, user: User
) -> ReminderRule:
    """Create a rule inline with the plan.

    The stored patient is the plan's, not the one repeated in the nested body.
    The contract says the nested block repeats it; when the two disagree the plan
    is the authority, because the rule is being created *as part of* that plan.
    """
    rule = ReminderRule(
        patient_id=patient.id,
        rtype=body.rtype.value,
        title=body.title,
        cron_expr=body.cron_expr,
        active=body.active,
        health_plan_id=plan.id if plan is not None else None,
        created_by=user.id,
    )
    db.add(rule)
    db.flush()
    return rule


@router.get("/api/health-plans/{plan_id}", response_model=contract.HealthPlanResponse)
def get_health_plan(request: Request, user: Actor, plan_id: int):
    """方案详情 / Read a health plan, with its entries and linked reminder rules."""
    with request.app.state.sessions() as db:
        plan = _plan_row(db, user, plan_id)
        return ok(_plan(plan, _own_rules(db, [plan.id]).get(plan.id, [])))


def _plan_row(db, user: User, plan_id: int) -> HealthPlan:
    row = db.scalar(
        select(HealthPlan)
        .join(Patient, HealthPlan.patient_id == Patient.id)
        .where(
            HealthPlan.id == plan_id,
            Patient.deleted_at.is_(None),
            patient_scope(user),
        )
    )
    if row is None:
        raise HTTPException(404, "Health plan not found")
    return row


@router.patch(
    "/api/health-plans/{plan_id}",
    response_model=contract.HealthPlanResponse,
    dependencies=WRITE,
)
def update_health_plan(
    request: Request, user: Actor, plan_id: int, body: contract.HealthPlanWriteRequest
):
    """更新健康方案 / Update a health plan, including its `status`.

    The body is the full write shape, per the contract, so `patient_no` comes
    along. It is checked rather than applied: retargeting an existing plan at
    another patient is not an update, it is a new plan, and honouring it would be
    a way to move a record out of its department.
    """
    with request.app.state.sessions() as db:
        plan = _plan_row(db, user, plan_id)
        if body.patient_no != plan.patient.patient_no:
            raise HTTPException(404, "Health plan not found")
        if body.end_date < body.start_date:
            raise HTTPException(422, "Invalid request: end_date")

        plan.title = body.title
        plan.goals = body.goals
        plan.instructions = body.instructions
        plan.entries = [
            {"kind": entry.kind.value, "text": entry.text, "done": False} for entry in body.entries
        ]
        plan.start_date = body.start_date
        plan.end_date = body.end_date
        plan.updated_at = datetime.now(UTC)
        detail = {"title": plan.title}
        if body.status is not None and body.status.value != plan.status:
            # T35 asks for each status change to leave a trace. It goes into this
            # same entry rather than a second one: `mark_audit` records one event
            # per request, and a status change *is* this update -- a second call
            # would overwrite the first and lose the transition silently.
            detail |= {"status_from": plan.status, "status_to": body.status.value}
            plan.status = body.status.value
        mark_audit(
            request,
            "health_plan.update",
            "health_plan",
            plan.id,
            patient_id=plan.patient_id,
            detail=detail,
        )
        db.commit()
        return ok(_plan(plan, _own_rules(db, [plan.id]).get(plan.id, [])))


# --------------------------------------------------------------------- vitals


@router.get(
    "/api/patients/{patient_no}/vitals",
    response_model=contract.VitalSignListResponse,
)
def list_vitals(
    request: Request,
    user: Actor,
    patient_no: str,
    pagination: Annotated[Pagination, Depends()],
    sign_type: Annotated[contract.VitalType | None, Query()] = None,
    from_: Annotated[
        datetime | None, Query(alias="from", description="测量时间起（含）/ Recorded at or after")
    ] = None,
    to: Annotated[
        datetime | None, Query(description="测量时间止（含）/ Recorded at or before")
    ] = None,
):
    """体征列表 / List vital sign readings, newest first."""
    with request.app.state.sessions() as db:
        patient = _patient(patient_no, user, db)
        conditions = [VitalSign.patient_id == patient.id]
        if sign_type is not None:
            conditions.append(VitalSign.sign_type == sign_type.value)
        if from_ is not None:
            conditions.append(VitalSign.recorded_at >= from_)
        if to is not None:
            conditions.append(VitalSign.recorded_at <= to)
        total = db.scalar(select(func.count()).select_from(VitalSign).where(*conditions)) or 0
        rows = list(
            db.scalars(
                select(VitalSign)
                .where(*conditions)
                # `id` breaks the tie on purpose: readings entered in the same
                # minute are ordinary, and without it the sort is free to put the
                # same row on two pages.
                .order_by(VitalSign.recorded_at.desc(), VitalSign.id.desc())
                .offset(pagination.offset)
                .limit(pagination.size)
            )
        )
        return ok(
            contract.VitalSignListData(
                items=[_vital(row) for row in rows],
                total=total,
                page=pagination.page,
                size=pagination.size,
            )
        )


@router.post(
    "/api/patients/{patient_no}/vitals",
    response_model=contract.VitalSignResponse,
    dependencies=WRITE,
)
def create_vital(
    request: Request, user: Actor, patient_no: str, body: contract.VitalSignCreateRequest
):
    """录入体征 / Record one reading and judge it against the threshold.

    Two checks sit here rather than in the schema, because the contract wants the
    422 to name the field and pydantic cannot attach a location to a rule that
    spans fields or compares against the clock.
    """
    with request.app.state.sessions() as db:
        patient = _patient(patient_no, user, db)
        if body.recorded_at > datetime.now(UTC):
            raise HTTPException(422, "Invalid request: recorded_at")
        if body.sign_type is contract.VitalType.bp and body.value_secondary is None:
            # A blood pressure without its diastolic half cannot be judged: the
            # range has two bounds per side, and half a reading is not a reading.
            raise HTTPException(422, "Invalid request: value_secondary")

        threshold = _threshold(db, body.sign_type.value)
        row = VitalSign(
            patient_id=patient.id,
            sign_type=body.sign_type.value,
            value=body.value,
            value_secondary=body.value_secondary,
            unit=threshold.unit,
            recorded_at=body.recorded_at,
            source=body.source.value,
            is_abnormal=_is_abnormal(threshold, body.value, body.value_secondary),
            recorded_by=user.id,
        )
        db.add(row)
        db.flush()
        mark_audit(
            request,
            "vital.create",
            "vital_sign",
            row.id,
            patient_id=patient.id,
            detail={
                "sign_type": row.sign_type,
                "is_abnormal": row.is_abnormal,
                # The reading itself is clinical data, not a request body, and
                # the trail is append-only -- so it stays out.
                "source": row.source,
            },
        )
        db.commit()
        return ok(_vital(row))


@router.get(
    "/api/patients/{patient_no}/vitals/trend",
    response_model=contract.VitalTrendResponse,
)
def vital_trend(
    request: Request,
    user: Actor,
    patient_no: str,
    sign_type: Annotated[contract.VitalType, Query()],
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
):
    """趋势图数据 / Time-series data for one metric, shaped for ECharts.

    Returns `{recorded_at, value}` pairs rather than table rows, so the client
    draws without reshaping. Each point carries the threshold that produced its
    verdict, because the chart colours the point and shows the bounds in the
    tooltip -- recomputing them client-side is exactly how a chart and a record
    start disagreeing. An empty range is `points: []`, an empty state rather than
    a blank canvas.
    """
    with request.app.state.sessions() as db:
        patient = _patient(patient_no, user, db)
        threshold = _threshold(db, sign_type.value)
        # `to` is inclusive of the whole day, so the range is a half-open instant
        # interval. Comparing against `to` as midnight would silently drop
        # everything recorded on the last day the user picked.
        start = datetime.combine(from_, time.min, tzinfo=UTC)
        end = datetime.combine(to + timedelta(days=1), time.min, tzinfo=UTC)
        rows = list(
            db.scalars(
                select(VitalSign)
                .where(
                    VitalSign.patient_id == patient.id,
                    VitalSign.sign_type == sign_type.value,
                    VitalSign.recorded_at >= start,
                    VitalSign.recorded_at < end,
                )
                .order_by(VitalSign.recorded_at, VitalSign.id)
            )
        )
        bounds = contract.VitalTrendThreshold(
            min=threshold.min_value,
            max=threshold.max_value,
            min_secondary=threshold.min_secondary,
            max_secondary=threshold.max_secondary,
        )
        return ok(
            contract.VitalTrendData(
                sign_type=sign_type,
                unit=threshold.unit,
                threshold=bounds,
                points=[
                    contract.VitalTrendPoint(
                        recorded_at=_utc(row.recorded_at),
                        value=row.value,
                        value_secondary=row.value_secondary,
                        is_abnormal=row.is_abnormal,
                        threshold=bounds,
                    )
                    for row in rows
                ],
            )
        )


# ------------------------------------------------------------------ reminders


@router.get("/api/reminder-rules", response_model=contract.ReminderRuleListResponse)
def list_reminder_rules(
    request: Request,
    user: Actor,
    patient_no: Annotated[str, Query(max_length=20)] = "",
):
    """提醒规则列表 / List reminder rules, scoped by department."""
    with request.app.state.sessions() as db:
        query = (
            select(ReminderRule)
            .join(Patient, ReminderRule.patient_id == Patient.id)
            .where(Patient.deleted_at.is_(None), patient_scope(user))
        )
        if patient_no:
            query = query.where(Patient.patient_no == patient_no)
        return ok([_rule(row) for row in db.scalars(query.order_by(ReminderRule.id))])


@router.post(
    "/api/reminder-rules",
    response_model=contract.ReminderRuleResponse,
    dependencies=WRITE,
)
def create_reminder_rule(request: Request, user: Actor, body: contract.ReminderRuleWriteRequest):
    """新建提醒规则 / Create a reminder rule."""
    with request.app.state.sessions() as db:
        patient = _patient(body.patient_no, user, db)
        plan = None
        if body.health_plan_id is not None:
            plan = _plan_row(db, user, body.health_plan_id)
            if plan.patient_id != patient.id:
                raise HTTPException(404, "Health plan not found")
        rule = _new_rule(db, patient, body, plan, user)
        mark_audit(
            request,
            "reminder_rule.create",
            "reminder_rule",
            rule.id,
            patient_id=patient.id,
            detail={"rtype": rule.rtype, "cron_expr": rule.cron_expr},
        )
        db.commit()
        return ok(_rule(rule))


@router.patch(
    "/api/reminder-rules/{rule_id}",
    response_model=contract.ReminderRuleResponse,
    dependencies=WRITE,
)
def update_reminder_rule(
    request: Request, user: Actor, rule_id: int, body: contract.ReminderRuleUpdateRequest
):
    """更新提醒规则 / Update a reminder rule.

    Partial by design: T36 §4 and scenario S2 deactivate a rule with
    ``{"active": false}`` and nothing else. Deactivating stops **new** reminders;
    the entries already logged stay exactly where they are.
    """
    with request.app.state.sessions() as db:
        rule = _rule_for(db, user, rule_id)
        changed = body.model_dump(exclude_unset=True, exclude_none=True)
        # Same reasoning as the plan update: a rule moved to another patient would
        # move out of the department that owns it. Popped rather than applied, so
        # it never reaches `setattr` -- `patient_no` is not a column here, it is
        # the patient row's business key.
        named = changed.pop("patient_no", None)
        if named is not None and named != rule.patient.patient_no:
            raise HTTPException(404, "Reminder rule not found")
        if "rtype" in changed:
            changed["rtype"] = changed["rtype"].value
        for field, value in changed.items():
            setattr(rule, field, value)
        mark_audit(
            request,
            "reminder_rule.update",
            "reminder_rule",
            rule.id,
            patient_id=rule.patient_id,
            detail={key: str(value) for key, value in changed.items()},
        )
        db.commit()
        return ok(_rule(rule))


@router.get("/api/reminders", response_model=contract.ReminderLogListResponse)
def list_reminders(
    request: Request,
    user: Actor,
    pagination: Annotated[Pagination, Depends()],
    patient_no: Annotated[str, Query(max_length=20)] = "",
    done: Annotated[bool | None, Query()] = None,
    unread_only: Annotated[bool, Query()] = False,
):
    """已触发提醒 / List fired reminders.

    **Opening this list clears the red dot**, so the returned entries are marked
    read. `unread_only=true` is the caller that wants the dot's contents without
    consuming them, which is what the counting endpoint uses.

    `unread` is counted after the clear, so the same response that shows the user
    their reminders is the one that tells the shell the dot is now empty. The
    count is deliberately not the pre-clear number: that would leave the bell
    lit over a list the user is looking at.
    """
    with request.app.state.sessions() as db:
        conditions = [Patient.deleted_at.is_(None), patient_scope(user)]
        if patient_no:
            conditions.append(Patient.patient_no == patient_no)
        if done is not None:
            conditions.append(ReminderLog.done.is_(done))
        if unread_only:
            conditions.append(ReminderLog.read.is_(False))
        query = (
            select(ReminderLog)
            .join(Patient, ReminderLog.patient_id == Patient.id)
            .where(*conditions)
        )
        total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = list(
            db.scalars(
                query.order_by(ReminderLog.due_at.desc(), ReminderLog.id.desc())
                .offset(pagination.offset)
                .limit(pagination.size)
            )
        )
        if not unread_only:
            for row in rows:
                row.read = True
        unread = _unread(db, user)
        db.commit()
        return ok(
            contract.ReminderLogData(
                items=[_log(row) for row in rows],
                total=total,
                page=pagination.page,
                size=pagination.size,
                unread=unread,
            )
        )


def _unread(db, user: User) -> int:
    """The number behind the red dot: unread entries for patients in scope."""
    return (
        db.scalar(
            select(func.count())
            .select_from(ReminderLog)
            .join(Patient, ReminderLog.patient_id == Patient.id)
            .where(
                ReminderLog.read.is_(False),
                Patient.deleted_at.is_(None),
                patient_scope(user),
            )
        )
        or 0
    )


@router.get("/api/reminders/unread-count", response_model=contract.UnreadCountResponse)
def get_unread_reminder_count(request: Request, user: Actor):
    """未读提醒数 / The single number behind the workspace red dot.

    A cheap poll for the shell, so the bell does not have to fetch the list to
    decide whether to light up. It answers without side effects -- unlike
    `GET /api/reminders`, which clears the dot as a side effect of being read.
    """
    with request.app.state.sessions() as db:
        return ok(contract.UnreadCount(unread=_unread(db, user)))


@router.post(
    "/api/reminders/{reminder_id}/done",
    response_model=contract.ReminderLogResponse,
    dependencies=WRITE,
)
def mark_reminder_done(request: Request, user: Actor, reminder_id: int):
    """标记提醒已处理 / Mark a reminder as actioned.

    Marking it done also marks it read: an entry the user has just acted on
    cannot sensibly be the thing lighting the red dot.
    """
    with request.app.state.sessions() as db:
        row = db.scalar(
            select(ReminderLog)
            .join(Patient, ReminderLog.patient_id == Patient.id)
            .where(
                ReminderLog.id == reminder_id,
                Patient.deleted_at.is_(None),
                patient_scope(user),
            )
        )
        if row is None:
            raise HTTPException(404, "Reminder not found")
        row.done = True
        row.done_at = datetime.now(UTC)
        row.read = True
        mark_audit(
            request,
            "reminder.done",
            "reminder",
            row.id,
            patient_id=row.patient_id,
        )
        db.commit()
        return ok(_log(row))


# ---------------------------------------------------------------- assessments


@router.get(
    "/api/patients/{patient_no}/assessments",
    response_model=contract.HealthAssessmentListResponse,
)
def list_assessments(request: Request, user: Actor, patient_no: str):
    """评估记录 / Periodic assessments, newest first.

    Not paginated: the contract's `HealthAssessmentListResponse.data` is a plain
    array, and the list feeds one section of the patient detail page. A revision
    is a new row, so one period may appear more than once -- that is the revision
    trail, newest first.
    """
    with request.app.state.sessions() as db:
        patient = _patient(patient_no, user, db)
        rows = db.scalars(
            select(HealthAssessment)
            .where(HealthAssessment.patient_id == patient.id)
            .order_by(HealthAssessment.assessed_at.desc(), HealthAssessment.id.desc())
        )
        return ok([_assessment(row) for row in rows])


@router.post(
    "/api/patients/{patient_no}/assessments",
    response_model=contract.HealthAssessmentResponse,
    dependencies=WRITE,
)
def create_assessment(
    request: Request, user: Actor, patient_no: str, body: contract.HealthAssessmentWriteRequest
):
    """录入定期评估 / Record a periodic assessment."""
    with request.app.state.sessions() as db:
        patient = _patient(patient_no, user, db)
        assessed_at = body.assessed_at or datetime.now(UTC)
        if assessed_at > datetime.now(UTC):
            # T37 §5's date validation. A future assessment date makes the
            # newest-first trail read as though a later revision already exists.
            raise HTTPException(422, "Invalid request: assessed_at")
        row = HealthAssessment(
            patient_id=patient.id,
            period=body.period,
            conclusion=body.conclusion,
            plan_adjustment=body.plan_adjustment,
            assessed_by=user.id,
            assessed_at=assessed_at,
            version=1,
        )
        db.add(row)
        db.flush()
        mark_audit(
            request,
            "assessment.create",
            "assessment",
            row.id,
            patient_id=patient.id,
            detail={"period": row.period, "version": row.version},
        )
        db.commit()
        return ok(_assessment(row))


def _assessment_row(db, user: User, assessment_id: int) -> HealthAssessment:
    row = db.scalar(
        select(HealthAssessment)
        .join(Patient, HealthAssessment.patient_id == Patient.id)
        .where(
            HealthAssessment.id == assessment_id,
            Patient.deleted_at.is_(None),
            patient_scope(user),
        )
    )
    if row is None:
        raise HTTPException(404, "Assessment not found")
    return row


@router.get(
    "/api/assessments/{assessment_id}",
    response_model=contract.HealthAssessmentResponse,
)
def get_assessment(request: Request, user: Actor, assessment_id: int):
    """评估详情 / Read a periodic assessment."""
    with request.app.state.sessions() as db:
        return ok(_assessment(_assessment_row(db, user, assessment_id)))


@router.patch(
    "/api/assessments/{assessment_id}",
    response_model=contract.HealthAssessmentResponse,
    dependencies=WRITE,
)
def update_assessment(
    request: Request,
    user: Actor,
    assessment_id: int,
    body: contract.HealthAssessmentWriteRequest,
):
    """修订评估 / Revise a periodic assessment.

    **Only the assessing physician may revise their own assessment** -- T37
    scenario S2 has another doctor attempt it and requires 403. An assessment is
    an attributed clinical opinion, not a shared document.

    The revision is a new row with `version + 1`, so the conclusion it replaces
    stays readable exactly as it was written; the earlier one is never edited.
    """
    with request.app.state.sessions() as db:
        original = _assessment_row(db, user, assessment_id)
        if original.assessed_by != user.id:
            raise HTTPException(403, "Only the assessing physician may revise this assessment")
        assessed_at = body.assessed_at or datetime.now(UTC)
        if assessed_at > datetime.now(UTC):
            raise HTTPException(422, "Invalid request: assessed_at")
        latest = (
            db.scalar(
                select(func.max(HealthAssessment.version)).where(
                    HealthAssessment.patient_id == original.patient_id,
                    HealthAssessment.period == body.period,
                )
            )
            or 0
        )
        row = HealthAssessment(
            patient_id=original.patient_id,
            period=body.period,
            conclusion=body.conclusion,
            plan_adjustment=body.plan_adjustment,
            assessed_by=user.id,
            assessed_at=assessed_at,
            version=latest + 1,
            updated_at=datetime.now(UTC),
        )
        db.add(row)
        db.flush()
        mark_audit(
            request,
            "assessment.update",
            "assessment",
            row.id,
            patient_id=row.patient_id,
            detail={"period": row.period, "version": row.version, "revises": original.id},
        )
        db.commit()
        return ok(_assessment(row))


# ------------------------------------------------------------------ scheduler


def due_this_minute(cron_expr: str, minute: datetime) -> datetime | None:
    """The instant this rule fires at, if it fires in `minute`; otherwise None.

    APScheduler can tell you the *next* fire time of a trigger but not whether a
    given minute is one, so the question is asked from just before the minute: if
    the next fire after `minute - 1s` is `minute` itself, this rule fires now.

    A malformed expression returns None rather than raising. The write path
    rejects one with a 422, so a row that fails here could only come from a direct
    database edit, and one bad row must not stop every other reminder.
    """
    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone="UTC")
    except (ValueError, TypeError):
        return None
    fired = trigger.get_next_fire_time(None, minute - timedelta(seconds=1))
    return minute if fired == minute else None


def generate_reminders(sessions):
    """Materialise a log entry for every rule that fires in the minute just ended.

    **Idempotency is the whole difficulty.** The job re-evaluates the same minute
    after every restart, and T36 scenario S2 restarts twice and requires no
    duplicates. Two things make that safe: the lookup below, so the ordinary case
    writes nothing, and the unique key on `(rule_id, due_at)`, so a race between
    two workers loses the insert instead of duplicating it.

    Registered once at start-up, by `register_jobs`. Under several worker
    processes each would register its own scheduler and therefore evaluate every
    rule N times; that is survivable *because* of the key above, which is the
    reason it is stated in the database rather than only in this function.
    """
    now = datetime.now(UTC)
    minute = now.replace(second=0, microsecond=0)
    with sessions() as db:
        rules = list(db.scalars(select(ReminderRule).where(ReminderRule.active.is_(True))))
        for rule in rules:
            due = due_this_minute(rule.cron_expr, minute)
            if due is None:
                continue
            already = db.scalar(
                select(ReminderLog.id).where(
                    ReminderLog.rule_id == rule.id, ReminderLog.due_at == due
                )
            )
            if already is not None:
                continue
            db.add(
                ReminderLog(
                    rule_id=rule.id,
                    patient_id=rule.patient_id,
                    title=rule.title,
                    due_at=due,
                    fired_at=now,
                )
            )
        try:
            db.commit()
        except IntegrityError:
            # Another worker got there first. The entries it wrote are the ones
            # that should exist, so there is nothing to repair.
            db.rollback()


def register_jobs(scheduler, sessions):
    """Attach the reminder job to the application's one scheduler."""
    scheduler.add_job(
        generate_reminders,
        "interval",
        minutes=1,
        args=[sessions],
        id="generate_reminders",
        max_instances=1,
        coalesce=True,
    )
