"""S1: simulated SMS transport; Redis owns verification and delivery is local only."""

import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select

from app import auth_schemas as contract
from app.auth import (
    CurrentUser,
    VerifyCodeRequest,
    cache_for,
    code_digest,
    code_key,
    ok,
    store_verification_code,
    ticket_key,
    verify_code,
)
from app.models import NotifyOutbox, User
from app.otp import reserve_send

router = APIRouter()


class SmsProvider(Protocol):
    def send(self, sessions, phone: str, code: str, *, expose_code: bool) -> int: ...


class MockSmsProvider:
    def send(self, sessions, phone: str, code: str, *, expose_code: bool) -> int:
        with sessions() as db:
            row = NotifyOutbox(
                channel="sms",
                target=phone[:3] + "****" + phone[-4:],
                template="login_code",
                payload_json={"mock": True, "expires_in": 300},
                code=code if expose_code else None,
                status="sent(mock)",
            )
            db.add(row)
            db.commit()
            return row.id


def require_dev(request):
    if request.app.state.settings.app_env != "dev":
        raise HTTPException(404, "Simulated SMS login is available only in APP_ENV=dev")


def ticket_user(request, ticket):
    cache = cache_for(request)
    uid = cache.get(ticket_key(ticket))
    if uid is None:
        raise HTTPException(401, "Login ticket has expired or was already used")
    with request.app.state.sessions() as db:
        user = db.get(User, int(uid))
        if user is None or user.status != "active":
            raise HTTPException(401, "User is unavailable or disabled")
        request.state.identity = user
    return cache, int(uid)


@router.post("/api/auth/sms/send")
def sms_send(body: contract.SmsSendRequest, request: Request):
    require_dev(request)
    cache, uid = ticket_user(request, body.ticket)
    settings = request.app.state.settings
    reserve_send(cache, uid, settings.otp_daily_limit)
    code = f"{secrets.randbelow(1000000):06d}"
    store_verification_code(cache, settings.jwt_secret, body.ticket, code)
    provider: SmsProvider = getattr(request.app.state, "sms_provider", MockSmsProvider())
    try:
        outbox_id = provider.send(request.app.state.sessions, body.phone, code, expose_code=True)
    except Exception:  # noqa: BLE001 -- provider failures must not expose codes or internals
        cache.delete(code_key(uid))
        raise HTTPException(
            503, "Simulated SMS delivery failed; retry after the cooldown"
        ) from None
    # The login viewer reads only this ticket-scoped, expiring copy; never queries the table.
    cache.set(
        ticket_key(body.ticket) + ":sms",
        json.dumps(
            {
                "id": outbox_id,
                "code": code,
                "masked_phone": body.phone[:3] + "****" + body.phone[-4:],
            }
        ),
        ex=300,
    )
    return ok(
        {
            "mock": True,
            "status": "sent(mock)",
            "cooldown": 60,
            "expires_in": 300,
            "masked_phone": body.phone[:3] + "****" + body.phone[-4:],
        }
    )


@router.post("/api/auth/sms/preview")
def sms_preview(body: contract.SmsTicketRequest, request: Request, response: Response):
    require_dev(request)
    response.headers["Cache-Control"] = "no-store"
    cache, uid = ticket_user(request, body.ticket)
    raw = cache.get(ticket_key(body.ticket) + ":sms")
    if raw is None:
        raise HTTPException(404, "No active simulated SMS for this login ticket")
    data = json.loads(raw)
    stored = cache.get(code_key(uid))
    digest = code_digest(request.app.state.settings.jwt_secret, body.ticket, data["code"])
    if stored is None or not hmac.compare_digest(
        stored.decode() if isinstance(stored, bytes) else stored, digest
    ):
        raise HTTPException(404, "The simulated SMS has expired or was replaced")
    return ok(
        {
            **data,
            "mock": True,
            "status": "sent(mock)",
            "expires_in": min(cache.ttl(ticket_key(body.ticket)), cache.ttl(code_key(uid))),
        }
    )


@router.post("/api/auth/sms/verify")
def sms_verify(body: contract.SmsVerifyRequest, request: Request):
    require_dev(request)
    # Use the same digest, attempt counter and atomic ticket consumption as email.
    result = verify_code(VerifyCodeRequest(ticket=body.ticket, code=body.code), request)
    cache_for(request).delete(ticket_key(body.ticket) + ":sms")
    result["data"]["mock"] = True
    return result


@router.get("/api/notify-outbox")
def notify_outbox(
    request: Request, response: Response, user: CurrentUser, page: int = 1, size: int = 20
):
    if user.role.name != "admin":
        raise HTTPException(403, "Only administrators can view the simulated outbox")
    response.headers["Cache-Control"] = "no-store"
    if page < 1 or not 1 <= size <= 100:
        raise HTTPException(422, "Invalid pagination")
    with request.app.state.sessions() as db:
        rows = db.scalars(
            select(NotifyOutbox)
            .order_by(NotifyOutbox.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        ).all()
        cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=300)
        items = [
            {
                "id": row.id,
                "channel": row.channel,
                "target": row.target,
                "template": row.template,
                "status": row.status,
                "mock": True,
                "created_at": row.created_at,
                "code": row.code
                if request.app.state.settings.app_env == "dev"
                and row.created_at.replace(tzinfo=None) > cutoff
                else None,
            }
            for row in rows
        ]
        return ok(
            {
                "items": items,
                "total": db.scalar(select(func.count()).select_from(NotifyOutbox)),
                "page": page,
                "size": size,
            }
        )
