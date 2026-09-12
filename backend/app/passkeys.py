"""Device-verified, discoverable passkeys linked to existing accounts (M1/T05)."""

import hashlib
import json
import secrets

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app import auth
from app import auth_schemas as contract
from app.models import Passkey, User

router = APIRouter(prefix="/api/auth/passkeys", tags=["Auth"])


def challenge_key(ticket):
    return "auth:passkey:" + hashlib.sha256(ticket.encode()).hexdigest()


def options_response(request, options, purpose, user_id=None):
    cache = auth.cache_for(request)
    # Bound anonymous challenge creation without trusting spoofable forwarded headers.
    peer = request.client.host if request.client else "unknown"
    key = "auth:passkey:rate:" + hashlib.sha256(peer.encode()).hexdigest()
    with cache.pipeline() as pipe:
        count, _ = pipe.incr(key).expire(key, 60).execute()
    if count > 60:
        raise HTTPException(429, "Too many passkey attempts; retry later")
    ticket = secrets.token_urlsafe(32)
    public_key = json.loads(options_to_json(options))
    cache.set(
        challenge_key(ticket),
        json.dumps(
            {
                "challenge": public_key["challenge"],
                "purpose": purpose,
                "user_id": user_id,
            }
        ),
        ex=300,
    )
    return auth.ok({"ticket": ticket, "public_key": public_key})


def consume(request, ticket, purpose, user_id=None):
    # GETDEL prevents replay even across multiple API workers.
    raw = auth.cache_for(request).getdel(challenge_key(ticket))
    if raw is None:
        raise HTTPException(401, "Passkey challenge expired or already used")
    data = json.loads(raw)
    if data["purpose"] != purpose or data["user_id"] != user_id:
        raise HTTPException(401, "Passkey challenge does not match this session")
    return base64url_to_bytes(data["challenge"])


@router.post("/register/options", response_model=contract.PasskeyOptionsResponse)
def registration_options(request: Request, user: auth.CurrentUser):
    settings = request.app.state.settings
    with request.app.state.sessions() as db:
        credentials = list(db.scalars(select(Passkey).where(Passkey.user_id == user.id)))
    options = generate_registration_options(
        rp_id=settings.webauthn_rp_id,
        rp_name="Doctor Work Platform",
        user_id=hashlib.sha256(f"dwp-user:{user.id}".encode()).digest(),
        user_name=user.username,
        user_display_name=user.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=c.credential_id) for c in credentials
        ],
    )
    return options_response(request, options, "register", user.id)


@router.post("/register/verify", response_model=contract.OkData)
def registration_verify(
    body: contract.PasskeyVerifyRequest, request: Request, user: auth.CurrentUser
):
    challenge = consume(request, body.ticket, "register", user.id)
    settings = request.app.state.settings
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.webauthn_rp_id,
            expected_origin=settings.webauthn_origin,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, TypeError, KeyError):
        raise HTTPException(401, "Passkey registration could not be verified") from None
    with request.app.state.sessions() as db:
        db.add(
            Passkey(
                user_id=user.id,
                credential_id=verified.credential_id,
                credential_hash=hashlib.sha256(verified.credential_id).hexdigest(),
                public_key=verified.credential_public_key,
                sign_count=verified.sign_count,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Passkey is already registered") from None
    return auth.ok({"ok": True})


@router.post("/login/options", response_model=contract.PasskeyOptionsResponse)
def login_options(request: Request):
    return options_response(
        request,
        generate_authentication_options(
            rp_id=request.app.state.settings.webauthn_rp_id,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        "login",
    )


@router.post("/login/verify", response_model=contract.TokenResponse)
def login_verify(body: contract.PasskeyVerifyRequest, request: Request):
    challenge = consume(request, body.ticket, "login")
    settings = request.app.state.settings
    try:
        credential_id = base64url_to_bytes(body.credential["id"])
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "Invalid passkey") from None
    with request.app.state.sessions() as db:
        credential = db.scalar(
            select(Passkey)
            .where(Passkey.credential_hash == hashlib.sha256(credential_id).hexdigest())
            .with_for_update()
        )
        if credential is None or credential.credential_id != credential_id:
            raise HTTPException(401, "Invalid passkey")
        user = db.get(User, credential.user_id)
        if (
            user is None
            or user.status != "active"
            or user.role.name not in {"admin", "senior", "junior"}
        ):
            raise HTTPException(401, "User is unavailable or disabled")
        try:
            handle = body.credential["response"]["userHandle"]
            if handle != bytes_to_base64url(
                hashlib.sha256(f"dwp-user:{user.id}".encode()).digest()
            ):
                raise ValueError("Wrong user handle")
            verified = verify_authentication_response(
                credential=body.credential,
                expected_challenge=challenge,
                expected_rp_id=settings.webauthn_rp_id,
                expected_origin=settings.webauthn_origin,
                credential_public_key=credential.public_key,
                credential_current_sign_count=credential.sign_count,
                require_user_verification=True,
            )
        except (WebAuthnException, ValueError, TypeError, KeyError):
            raise HTTPException(401, "Passkey login could not be verified") from None
        result = db.execute(
            update(Passkey)
            .where(
                Passkey.id == credential.id,
                Passkey.sign_count == credential.sign_count,
            )
            .values(sign_count=verified.new_sign_count)
        )
        if result.rowcount != 1:
            raise HTTPException(401, "Passkey changed; retry login")
        data = auth.user_data(user)
        token = auth.issue_token(user, settings.jwt_secret)
        db.commit()
    return auth.ok(
        {"access_token": token, "token_type": "bearer", "expires_in": 7200, "user": data}
    )
