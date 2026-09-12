"""T05 authentication and the Redis hand-off for B's T06 email sender."""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, field_validator
from redis.exceptions import WatchError
from sqlalchemy import select

from app import auth_schemas as contract
from app.models import User

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def ok(data):
    return {"code": 0, "message": "ok", "data": data}


def hash_password(password: str) -> str:
    raw = password.encode()
    if not 1 <= len(raw) <= 72:
        raise ValueError("Password must contain 1–72 UTF-8 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), stored.encode())
    except (ValueError, TypeError):
        return False


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def cache_for(request: Request):
    cache = request.app.state.cache
    if cache is None:
        raise HTTPException(503, "Authentication requires Redis")
    return cache


def ticket_key(ticket: str) -> str:
    return "auth:ticket:" + hashlib.sha256(ticket.encode()).hexdigest()


def code_key(user_id: int) -> str:
    return f"auth:code:{user_id}"


def code_digest(secret: str, ticket: str, code: str) -> str:
    return hmac.new(secret.encode(), f"{ticket}:{code}".encode(), hashlib.sha256).hexdigest()


def store_verification_code(cache, secret: str, ticket: str, code: str) -> None:
    """T06 calls after SMTP succeeds; never store/log the plaintext code.

    Codes are bound to the password-verified ticket and expire after 300 seconds.
    The sender owns delivery, resend throttling and daily limits.
    """
    user_id = cache.get(ticket_key(ticket))
    if user_id is None:
        raise HTTPException(401, "Login ticket has expired")
    cache.set(code_key(int(user_id)), code_digest(secret, ticket, code), ex=300)


def user_data(user):
    return {
        "id": user.id,
        "username": user.username,
        "name": user.name,
        "title": user.role.name,
        "department": user.department.name,
    }


def issue_token(user, secret: str):
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "user_id": user.id,
            "title": user.role.name,
            "department": user.department.name,
            "jti": secrets.token_urlsafe(32),
            "iat": now,
            "exp": now + timedelta(hours=2),
        },
        secret,
        algorithm="HS256",
    )


def current_user(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
):
    if credentials is None:
        raise HTTPException(401, "Missing access token")
    try:
        claims = jwt.decode(
            credentials.credentials,
            request.app.state.settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "jti", "user_id", "title", "department"]},
        )
        if not isinstance(claims["user_id"], int) or not isinstance(claims["jti"], str):
            raise jwt.InvalidTokenError()
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Access token has expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid access token") from None
    if cache_for(request).exists(f"auth:blacklist:{claims['jti']}"):
        raise HTTPException(401, "Access token was invalidated by logout")
    with request.app.state.sessions() as db:
        user = db.get(User, claims["user_id"])
        if user is None or user.status != "active":
            raise HTTPException(401, "User is unavailable or disabled")
        if user.role.name not in {"admin", "senior", "junior"}:
            raise HTTPException(403, "Unknown role")
        request.state.claims = claims
        return user


CurrentUser = Annotated[User, Depends(current_user)]


class LoginRequest(contract.LoginRequest):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode()) > 72:
            raise ValueError("Password exceeds 72 UTF-8 bytes")
        return value


class VerifyCodeRequest(contract.VerifyCodeRequest):
    ticket: str = Field(min_length=1, max_length=200)
    code: str = Field(pattern=r"^[0-9]{6}$")


@router.post("/api/auth/login", response_model=contract.LoginResponse)
def login(body: LoginRequest, request: Request):
    cache = cache_for(request)
    failures = "auth:failures:" + hashlib.sha256(body.username.encode()).hexdigest()
    if int(cache.get(failures) or 0) >= 5:
        raise HTTPException(429, "Too many attempts; retry after 300 seconds")
    with request.app.state.sessions() as db:
        user = db.scalar(select(User).where(User.username == body.username))
        valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if not valid or user is None or user.status != "active":
            with cache.pipeline() as pipe:
                count, _ = pipe.incr(failures).expire(failures, 300).execute()
            raise HTTPException(
                429 if count >= 5 else 401,
                "Too many attempts; retry after 300 seconds"
                if count >= 5
                else "Invalid username or password",
            )
        cache.delete(failures)
        ticket = secrets.token_urlsafe(32)
        cache.set(ticket_key(ticket), user.id, ex=300)
        return ok({"ticket": ticket, "expires_in": 300})


@router.post("/api/auth/verify-code", response_model=contract.TokenResponse)
def verify_code(body: VerifyCodeRequest, request: Request):
    cache = cache_for(request)
    key = ticket_key(body.ticket)
    # WATCH makes consumption atomic across workers, including simultaneous retries.
    try:
        with cache.pipeline() as pipe:
            pipe.watch(key)
            uid = pipe.get(key)
            if uid is None:
                raise HTTPException(401, "Login ticket has expired or was already used")
            ck = code_key(int(uid))
            attempts = key + ":attempts"
            pipe.watch(ck, attempts)
            stored = pipe.get(ck)
            if stored is None:
                raise HTTPException(401, "The code has expired")
            expected = code_digest(request.app.state.settings.jwt_secret, body.ticket, body.code)
            if not hmac.compare_digest(
                stored.decode() if isinstance(stored, bytes) else stored, expected
            ):
                count = int(pipe.get(attempts) or 0) + 1
                pipe.multi()
                pipe.set(attempts, count, ex=300)
                if count >= 5:
                    pipe.delete(key, ck)
                pipe.execute()
                raise HTTPException(401, "Invalid verification code")
            with request.app.state.sessions() as db:
                user = db.get(User, int(uid))
                if user is None or user.status != "active":
                    raise HTTPException(401, "User is unavailable or disabled")
                token = issue_token(user, request.app.state.settings.jwt_secret)
                data = user_data(user)
            pipe.multi()
            pipe.delete(key, ck, attempts)
            pipe.execute()
    except WatchError:
        raise HTTPException(401, "Login ticket or code was already used; retry login") from None
    return ok({"access_token": token, "token_type": "bearer", "expires_in": 7200, "user": data})


@router.get("/api/me", response_model=contract.CurrentUserResponse)
def me(user: CurrentUser):
    return ok(user_data(user))


@router.post("/api/auth/logout", response_model=contract.OkData)
def logout(request: Request, user: CurrentUser):
    claims = request.state.claims
    remaining = max(1, int(claims["exp"] - datetime.now(UTC).timestamp()))
    cache_for(request).set(f"auth:blacklist:{claims['jti']}", "1", ex=remaining)
    return ok({"ok": True})


@router.post("/api/auth/send-code", response_model=contract.OkData)
def send_code(body: contract.SendCodeRequest, request: Request):
    import smtplib
    import ssl
    from email.message import EmailMessage

    cache = cache_for(request)
    settings = request.app.state.settings
    uid = cache.get(ticket_key(body.ticket))
    if uid is None:
        raise HTTPException(401, "Login ticket has expired")
    if not settings.smtp_host:
        raise HTTPException(503, "Email delivery is not configured")
    with request.app.state.sessions() as db:
        user = db.get(User, int(uid))
        if user is None or user.status != "active":
            raise HTTPException(401, "User is unavailable or disabled")
        address = user.email
    cooldown = f"auth:send:cooldown:{int(uid)}"
    if not cache.set(cooldown, "1", nx=True, ex=60):
        raise HTTPException(429, f"Please retry in about {max(1, cache.ttl(cooldown))} seconds")
    daily = f"auth:send:daily:{int(uid)}:{datetime.now(UTC).date()}"
    with cache.pipeline() as pipe:
        count, _ = pipe.incr(daily).expire(daily, 86400).execute()
    if count > 20:
        raise HTTPException(429, "Daily email limit reached; retry tomorrow")
    code = f"{secrets.randbelow(1000000):06d}"
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = address
    message["Subject"] = "Doctor Work Platform sign-in code"
    message.set_content(f"Your sign-in code is {code}. It expires in 5 minutes.")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(502, "Email delivery failed; please retry later") from None
    store_verification_code(cache, settings.jwt_secret, body.ticket, code)
    return ok({"ok": True})
