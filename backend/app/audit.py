"""T11 independent audit transactions. Never retain bodies, credentials or queries."""

import logging

from starlette.concurrency import run_in_threadpool

from app.models import AuditLog

logger = logging.getLogger(__name__)
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
ACTIONS = {
    "create_patient": "patient.create",
    "update_patient": "patient.update",
    "delete_patient": "patient.delete",
    "create_allergy": "allergy.create",
    "update_allergy": "allergy.update",
    "delete_allergy": "allergy.delete",
    "login": "auth.login",
    "send_code": "auth.send_code",
    "verify_code": "auth.verify_code",
    "face_login": "auth.face_login",
    "logout": "auth.logout",
    "create_grant": "temp_grant.create",
    "revoke_grant": "temp_grant.revoke",
    "create_user": "user.create",
    "update_user": "user.update",
    "create_meeting": "meeting.create",
    "accept_meeting": "meeting.accept",
    "decline_meeting": "meeting.decline",
    "start_meeting": "meeting.start",
    "complete_meeting": "meeting.complete",
    "upload_meeting_material": "meeting.material.upload",
}


# The action strings marked by hand, for the screens that publish a filter over
# them: `frontend/src/views/AuditLogView.vue`'s dropdown and nothing else. The
# middleware falls back to `<route name>.<method>`, so an action missing here is
# still recorded -- it only prints as a raw key such as `list_patient_groups.get`.
MARKED = {
    "forum.post.create",
    "forum.reply.create",
    "patient.view",
    "patient.allergies.view",
    "allergy.create",
    "allergy.update",
    "allergy.delete",
    "temp_grant.expire",
    "audit.export",
    "patient_group.create",
    "patient_group.update",
    "patient_group.delete",
    "patient_group.members.add",
    "patient_group.members.remove",
    "history.create",
    "history.update",
    "history.delete",
    # M5's room, which reuses M3's chat: the socket read, the message write and the
    # call it ends, named for the meeting rather than for a consultation.
    "meeting.messages.view",
    "meeting.message",
    "meeting.call.end",
}


def mark_audit(request, action, object_type, object_id=None, *, patient_id=None, detail=None):
    request.state.audit = {
        "action": action,
        "object_type": object_type,
        "object_id": str(object_id) if object_id is not None else None,
        "patient_id": patient_id,
        "detail": detail,
    }


def persist_audit(sessions, values):
    try:
        with sessions() as session:
            session.add(AuditLog(**values))
            session.commit()
    except Exception:  # noqa: BLE001 -- audit must never abort the business response
        logger.error("Audit persistence failed; business response preserved")


async def audit_request(request, call_next):
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        marked = getattr(request.state, "audit", None)
        if request.method in WRITE_METHODS or marked:
            route = request.scope.get("route")
            route_path = getattr(route, "path", "/unmatched")
            name = getattr(route, "name", "request")
            identity = getattr(request.state, "identity", None)
            values = marked or {
                "action": ACTIONS.get(name, name + "." + request.method.lower())[:50],
                "object_type": "request",
            }
            await run_in_threadpool(
                persist_audit,
                request.app.state.sessions,
                {
                    **values,
                    "user_id": identity.id if identity else None,
                    # T12 lists the actor by name. Snapshotted here rather than
                    # joined at read time, so a later rename cannot rewrite what
                    # the log says happened.
                    "username": identity.username if identity else None,
                    "ip": request.client.host[:45] if request.client else None,
                    "method": request.method,
                    "path": route_path[:500],
                    "result": "success" if status < 400 else "failure",
                    "status_code": status,
                },
            )
