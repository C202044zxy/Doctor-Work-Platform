"""Generate Docker-only environment settings without a host Python installation."""

import argparse
import secrets
from pathlib import Path


def initialize(root: Path):
    target = root / ".env.server"
    if target.exists():
        print(".env.server already exists; preserved without changes.")
        return
    content = (root / ".env.server.example").read_text(encoding="utf-8")
    for key in ("JWT_SECRET", "PATIENT_DATA_KEY"):
        content = content.replace(f"{key}=\n", f"{key}={secrets.token_hex(32)}\n", 1)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    target.chmod(0o600)
    print("Created .env.server with random secrets. Configure SMTP for email login.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    initialize(parser.parse_args().root)
