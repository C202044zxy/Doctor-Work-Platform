"""AES-256-GCM helpers for the patient identifiers added by task T13.

Phone numbers and national ID numbers are personal data, so the table stores
ciphertext in ``phone_enc`` and ``id_card_enc``, and the API only ever returns a
masked form. The key comes from ``PATIENT_DATA_KEY``; every process that reads
those columns must be configured with the same value.

GCM is authenticated: a tampered or truncated ciphertext raises instead of
returning garbage, and every encryption uses a fresh random nonce, so the same
phone number never produces the same ciphertext twice.
"""

import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings

_NONCE_BYTES = 12

# create_app() calls configure(). Falling back to Settings keeps the module
# usable from tests and scripts that import it without an application.
_secret: str | None = None


def configure(secret: str) -> None:
    global _secret
    _secret = secret


def _key() -> bytes:
    secret = _secret if _secret is not None else Settings().patient_data_key
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt(value: str) -> str:
    """Return base64(nonce || ciphertext) for a non-empty value."""
    nonce = os.urandom(_NONCE_BYTES)
    sealed = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce + sealed).decode("ascii")


def decrypt(token: str) -> str:
    """Reverse encrypt(). Raises InvalidTag when the key or the data is wrong."""
    raw = base64.b64decode(token)
    plaintext = AESGCM(_key()).decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], None)
    return plaintext.decode("utf-8")


def normalise(value: str) -> str:
    """`138 0000 1234` and `138-0000-1234` are one identifier.

    Shared by the blind index and the masks so the two cannot disagree about what
    a phone number is: the index has to compare the normalised form, and a mask
    built from the raw string would show `138******1234` for the same number whose
    stored form reads `138****1234`.
    """
    return "".join(ch for ch in value if not ch.isspace() and ch != "-").upper()


def blind_index(kind: str, value: str | None) -> str | None:
    """A deterministic, keyed digest of an identifier, for equality search.

    `phone_enc` and `id_card_enc` cannot be searched: GCM draws a fresh nonce per
    write, so the same number is a different token every time and the only way to
    find one would be to decrypt the whole table on every query. This is the
    usual answer -- store a keyed HMAC next to the ciphertext and compare that.
    The key is derived from `PATIENT_DATA_KEY` with a label per column, so a
    phone digest can never be compared against an ID-card digest, and a database
    dump without the key yields nothing but 64 hex characters per row.

    Normalisation is part of the contract: `138 0000 1234`, `138-0000-1234` and
    `13800001234` are one number, so the same patient is found whichever way the
    caller types it. `kind` names the column ("phone" / "id_card").
    """
    normalised = normalise(value) if value else ""
    if not normalised:
        return None
    key = hmac.new(_key(), f"blind-index:{kind}".encode(), hashlib.sha256).digest()
    return hmac.new(key, normalised.encode("utf-8"), hashlib.sha256).hexdigest()


def _mask(value: str, head: int, tail: int) -> str:
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}{'*' * (len(value) - head - tail)}{value[-tail:]}"


def mask_phone(phone: str | None) -> str | None:
    """13800001234 -> 138****1234. Shorter values degrade to all stars."""
    return _mask(normalise(phone), 3, 4) if phone else None


def mask_id_card(id_card: str | None) -> str | None:
    """110101199003071234 -> 110101********1234."""
    return _mask(normalise(id_card), 6, 4) if id_card else None
