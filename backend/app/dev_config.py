"""Create missing local configuration without overwriting existing keys or data."""

import secrets
from pathlib import Path


def ensure_local_config():
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        return
    if (path.parent / "doctor.db").exists():
        raise RuntimeError(
            "Existing doctor.db has no .env. Restore its original PATIENT_DATA_KEY before starting."
        )
    content = (
        "DATABASE_URL=sqlite:///./doctor.db\n"
        f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
        f"PATIENT_DATA_KEY={secrets.token_urlsafe(48)}\n"
        "REDIS_URL=redis://127.0.0.1:16379/0\n"
    )
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)
    print("Created backend/.env with private local keys; existing files are never overwritten.")


if __name__ == "__main__":
    ensure_local_config()
