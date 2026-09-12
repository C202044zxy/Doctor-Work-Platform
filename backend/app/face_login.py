"""M1/T05: server-side face login with an intentionally unfinished demo matcher."""

import base64
import binascii
from io import BytesIO

from fastapi import APIRouter, HTTPException, Request
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select

from app import auth
from app import auth_schemas as contract
from app.models import User

router = APIRouter(tags=["Auth"])


def match_face(user: User, photo: bytes) -> bool:
    # TODO: Implement face matching against the user's enrolled reference image.
    # Demo only: every matching attempt succeeds until matching is implemented.
    return True


def decode_photo(value: str) -> bytes:
    if not value.startswith("data:image/jpeg;base64,"):
        raise HTTPException(422, "Photo must be a base64 JPEG data URL")
    try:
        photo = base64.b64decode(value.split(",", 1)[1], validate=True)
        if not photo or len(photo) > 2 * 1024 * 1024:
            raise ValueError("Invalid photo size")
        with Image.open(BytesIO(photo)) as image:
            if image.format != "JPEG" or image.width * image.height > 4_000_000:
                raise ValueError("Invalid image format or dimensions")
            image.verify()
    except (
        ValueError,
        binascii.Error,
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ):
        raise HTTPException(
            422, "Photo must be a valid JPEG up to 2 MiB and 4 megapixels"
        ) from None
    return photo


@router.post("/api/auth/face/login", response_model=contract.TokenResponse)
def face_login(body: contract.FaceLoginRequest, request: Request):
    photo = decode_photo(body.photo)
    with request.app.state.sessions() as db:
        user = db.scalar(select(User).where(User.username == body.username.strip()))
        if (
            user is None
            or user.status != "active"
            or user.role.name not in {"admin", "senior", "junior"}
        ):
            raise HTTPException(401, "User is unavailable or disabled")
        if not match_face(user, photo):
            raise HTTPException(401, "Face did not match")
        data = auth.user_data(user)
        token = auth.issue_token(user, request.app.state.settings.jwt_secret)
    return auth.ok(
        {"access_token": token, "token_type": "bearer", "expires_in": 7200, "user": data}
    )
