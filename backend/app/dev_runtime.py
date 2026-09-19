"""Shared local startup checks for Windows and POSIX."""

import argparse
import json
import socket
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def assert_ports_free(ports=(8000, 5173)):
    for port in ports:
        with socket.socket() as listener:
            try:
                listener.bind(("127.0.0.1", port))
            except OSError:
                raise RuntimeError(
                    f"Port {port} is occupied. Stop the previous API/Vite or Docker stack first."
                ) from None


def wait_ready(timeout=30):
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open("http://127.0.0.1:8000/api/health/ready", timeout=2) as response:
                data = json.load(response)["data"]
                if data.get("db") == "ok" and data.get("redis") == "ok":
                    return
        except (URLError, OSError, ValueError, KeyError):
            pass
        time.sleep(0.5)
    raise RuntimeError(
        "API dependencies are not ready (SQLite and Redis must both be ok). "
        "Check /api/health/ready and backend/runtime/api-error.log. "
        "Development Redis must use redis://127.0.0.1:16379/0."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ports", "ready"])
    args = parser.parse_args()
    try:
        assert_ports_free() if args.command == "ports" else wait_ready()
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")
