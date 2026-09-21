"""Semantic validation layered over generated M1-07 contract models.

The generator emits both request models with `extra="forbid"` already, because the
contract declares `additionalProperties: false`; what it cannot carry across is the
password bound, which is why that one is restated here.
"""

from pydantic import Field, field_validator

from app import user_contract as contract

# bcrypt's own ceiling, not a policy choice: `app.auth.hash_password` refuses anything
# longer rather than truncating it, so a longer secret has to be a 422 and not a 500.
MAX_PASSWORD_BYTES = 72


class UserCreate(contract.UserCreateRequest):
    """`UserCreateRequest` with the checks the contract cannot express.

    `format: password` generates a `SecretStr`, whose validation drops the contract's
    `minLength` on the way through -- so the lower bound is restated here, on a plain
    `str`, beside the byte limit.
    """

    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_bytes(cls, value):
        if len(value.encode()) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Password exceeds {MAX_PASSWORD_BYTES} UTF-8 bytes")
        return value

    @field_validator("username", "name", "department")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value


class UserUpdate(contract.UserUpdateRequest):
    """`UserUpdateRequest` with the same non-blank rule on the fields that carry names.

    An explicit `null` is *not* handled here: `model_fields_set` is the only way to tell
    "sent as null" from "not sent", so that check lives in the endpoint where it can name
    the offending field in the message. See `app.users.update_user`.
    """

    @field_validator("name", "department")
    @classmethod
    def not_blank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Must not be blank")
        return value
