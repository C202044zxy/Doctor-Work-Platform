"""Self-service profile changes; role and department remain administrator-owned."""

import hashlib
import hmac
import json
import secrets
from datetime import UTC

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from redis.exceptions import WatchError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import auth
from app.audit import mark_audit
from app.models import User
from app.otp import reserve_send

router = APIRouter(tags=["Profile"])
EMAIL_PATTERN = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    current_password: str | None = Field(default=None, repr=False, max_length=72)
    email_code: str | None = Field(default=None, pattern=r"^\d{6}$", repr=False)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value.strip()


class EmailCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254, pattern=EMAIL_PATTERN)
    current_password: str = Field(min_length=1, max_length=72, repr=False)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=72, repr=False)
    new_password: str = Field(min_length=8, max_length=72, repr=False)

    @field_validator("new_password", "current_password")
    @classmethod
    def byte_limit(cls, value):
        if len(value.encode()) > 72:
            raise ValueError("Password exceeds 72 UTF-8 bytes")
        return value


def data(user):
    return {
        **auth.user_data(user),
        "email": user.email,
        "status": user.status,
        "created_at": user.created_at
        if user.created_at.tzinfo
        else user.created_at.replace(tzinfo=UTC),
    }


def password_check(request, user, password):
    cache = auth.cache_for(request)
    key = f"profile:password-failures:{user.id}"
    if int(cache.get(key) or 0) >= 5:
        raise HTTPException(429, "Too many attempts; retry after 300 seconds")
    if not password or not auth.verify_password(password, user.password_hash):
        with cache.pipeline() as pipe:
            pipe.incr(key).expire(key, 300).execute()
        raise HTTPException(403, "Current password is incorrect")
    cache.delete(key)


def available(db, email, user_id):
    if db.scalar(
        select(User.id).where(func.lower(User.email) == email.lower(), User.id != user_id)
    ):
        raise HTTPException(409, "Email is already registered")


def digest(request, user_id, email, code):
    return hmac.new(
        request.app.state.settings.jwt_secret.encode(),
        f"profile:{user_id}:{email}:{code}".encode(),
        hashlib.sha256,
    ).hexdigest()


def consume_code(request, user_id, email, code):
    cache = auth.cache_for(request)
    key = f"profile:email:{user_id}"
    while True:
        try:
            with cache.pipeline() as pipe:
                pipe.watch(key)
                raw = pipe.get(key)
                if not raw:
                    raise HTTPException(422, "Email verification code expired; request a new code")
                record = json.loads(raw)
                valid = record["email"] == email and hmac.compare_digest(
                    record["digest"], digest(request, user_id, email, code or "")
                )
                remaining = max(1, pipe.ttl(key))
                pipe.multi()
                if valid or record["attempts"] >= 4:
                    pipe.delete(key)
                else:
                    record["attempts"] += 1
                    pipe.set(key, json.dumps(record), ex=remaining)
                pipe.execute()
                if not valid:
                    raise HTTPException(422, "Invalid email verification code")
                return
        except WatchError:
            continue


@router.get("/api/profile")
def get_profile(user: auth.CurrentUser):
    return auth.ok(data(user))


@router.post("/api/profile/email-code")
def email_code(body: EmailCodeRequest, request: Request, user: auth.CurrentUser):
    password_check(request, user, body.current_password)
    email = body.email.lower()
    with request.app.state.sessions() as db:
        available(db, email, user.id)
    settings = request.app.state.settings
    if not settings.smtp_host:
        raise HTTPException(503, "Email delivery is not configured")
    cache = auth.cache_for(request)
    reserve_send(cache, user.id, settings.otp_daily_limit)
    code = f"{secrets.randbelow(1000000):06d}"
    auth.deliver_code(settings, email, code)
    cache.set(
        f"profile:email:{user.id}",
        json.dumps(
            {"email": email, "digest": digest(request, user.id, email, code), "attempts": 0}
        ),
        ex=300,
    )
    return auth.ok({"ok": True})


@router.patch("/api/profile")
def update_profile(body: ProfileUpdate, request: Request, user: auth.CurrentUser):
    email = body.email.lower()
    changed = []
    with request.app.state.sessions() as db:
        target = db.get(User, user.id)
        if target.email.lower() != email:
            password_check(request, target, body.current_password)
            available(db, email, user.id)
            consume_code(request, user.id, email, body.email_code)
            target.email = email
            changed.append("email")
        if target.name != body.name:
            target.name = body.name
            changed.append("name")
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Email is already registered") from None
        result = data(target)
    mark_audit(request, "profile.update", "user", user.id, detail={"changed": changed})
    return auth.ok(result)


@router.put("/api/profile/password")
def change_password(body: PasswordChange, request: Request, user: auth.CurrentUser):
    with request.app.state.sessions() as db:
        target = db.get(User, user.id)
        password_check(request, target, body.current_password)
        target.password_hash = auth.hash_password(body.new_password)
        target.session_version += 1
        db.commit()
    mark_audit(request, "profile.password", "user", user.id)
    return auth.ok({"ok": True})
