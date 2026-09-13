"""Email-verified enrollment; patient access requires local administrator activation."""

import hashlib
import hmac
import json
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import auth
from app import auth_schemas as contract
from app.models import Department, Role, User

router = APIRouter()


class SignupRequest(contract.SignupRequest):
    @field_validator("username", "name", "department", "email")
    @classmethod
    def trim(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode()) > 72:
            raise ValueError("Password exceeds 72 UTF-8 bytes")
        return value


def signup_key(ticket):
    return "signup:ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


def limit(cache, key, maximum, ttl):
    with cache.pipeline() as pipe:
        count, _ = pipe.incr(key).expire(key, ttl).execute()
    if count > maximum:
        raise HTTPException(429, "Too many signup attempts; please retry later")


@router.post("/api/auth/signup", response_model=contract.LoginResponse)
def signup(body: SignupRequest, request: Request):
    cache = auth.cache_for(request)
    settings = request.app.state.settings
    if not settings.smtp_host:
        raise HTTPException(503, "Email delivery is not configured")
    ip = request.client.host if request.client else "unknown"
    limit(cache, "signup:ip:" + hashlib.sha256(ip.encode()).hexdigest(), 20, 3600)
    address_key = "signup:email:" + hashlib.sha256(body.email.encode()).hexdigest()
    if not cache.set(address_key + ":cooldown", "1", nx=True, ex=60):
        raise HTTPException(429, "Please wait 60 seconds before requesting another signup code")
    limit(cache, address_key + ":daily", 20, 86400)
    with request.app.state.sessions() as db:
        if db.scalar(
            select(User.id).where(
                (func.lower(User.username) == body.username.lower())
                | (func.lower(User.email) == body.email)
            )
        ):
            raise HTTPException(409, "Username or email already registered")
        department = db.scalar(select(Department).where(Department.name == body.department))
        role = db.scalar(select(Role).where(Role.name == "junior"))
        if department is None:
            raise HTTPException(422, "Unknown department")
        if role is None:
            raise HTTPException(503, "Seed roles before accepting registrations")
        data = body.model_dump(exclude={"password", "department"})
        data.update(
            password_hash=auth.hash_password(body.password),
            department_id=department.id,
            role_id=role.id,
        )
    ticket = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1000000):06d}"
    data["digest"] = auth.code_digest(settings.jwt_secret, ticket, code)
    auth.deliver_code(settings, body.email, code)
    cache.set(signup_key(ticket), json.dumps(data), ex=300)
    return auth.ok({"ticket": ticket, "expires_in": 300})


@router.post("/api/auth/signup/verify", response_model=contract.OkData)
def verify_signup(body: auth.VerifyCodeRequest, request: Request):
    cache = auth.cache_for(request)
    key = signup_key(body.ticket)
    # Atomic attempt counting and GETDEL bound retries and consumption across workers.
    limit(cache, key + ":attempts", 5, 300)
    raw = cache.get(key)
    if raw is None:
        raise HTTPException(401, "Signup ticket expired or was already used")
    data = json.loads(raw)
    expected = auth.code_digest(request.app.state.settings.jwt_secret, body.ticket, body.code)
    if not hmac.compare_digest(data["digest"], expected):
        if int(cache.get(key + ":attempts") or 0) >= 5:
            cache.delete(key)
        raise HTTPException(401, "Invalid verification code")
    if cache.getdel(key) is None:
        raise HTTPException(401, "Signup ticket was already used")
    del data["digest"]
    with request.app.state.sessions() as db:
        if db.scalar(
            select(User.id).where(
                (func.lower(User.username) == data["username"].lower())
                | (func.lower(User.email) == data["email"])
            )
        ):
            raise HTTPException(409, "Username or email already registered")
        db.add(User(**data, status="pending"))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Username or email already registered") from None
    return auth.ok({"ok": True})
