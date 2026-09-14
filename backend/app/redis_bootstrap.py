"""Redis reachability helper shared by the Windows and POSIX startup scripts.

The startup scripts differ only in how they *launch* a Redis server (PowerShell
versus bash). Deciding whether one is already reachable, and on which host and
port, is identical on both platforms, so it lives here instead of being written
twice and drifting apart.

Commands:
    endpoint  Print "<host> <port>" for REDIS_URL, for the shell to parse.
    probe     Exit 0 if Redis answers PING, exit 1 otherwise. Prints nothing
              unless --verbose is given.
    wait      Poll probe until it succeeds or --timeout expires.
"""

import argparse
import sys
import time
from urllib.parse import urlparse

from redis import Redis
from redis.exceptions import RedisError

DEFAULT_URL = "redis://127.0.0.1:6379/0"


def resolve(redis_url: str | None) -> tuple[str, int, int]:
    """Split a Redis URL into (host, port, database)."""
    parsed = urlparse(redis_url or DEFAULT_URL)
    return parsed.hostname or "127.0.0.1", parsed.port or 6379, int(parsed.path.strip("/") or 0)


def ping(redis_url: str | None) -> bool:
    """Return True when Redis is reachable at the URL."""
    host, port, database = resolve(redis_url)
    client = Redis(host=host, port=port, db=database, socket_timeout=2, socket_connect_timeout=2)
    try:
        client.ping()
        return True
    except (RedisError, OSError):
        return False
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["endpoint", "probe", "wait"])
    parser.add_argument("--url", default=DEFAULT_URL, help="Redis URL to use")
    parser.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.command == "endpoint":
        host, port, _ = resolve(args.url)
        print(f"{host} {port}")
        return 0

    if args.command == "probe":
        reachable = ping(args.url)
        if args.verbose:
            print(f"redis at {args.url}: {'reachable' if reachable else 'unreachable'}")
        return 0 if reachable else 1

    deadline = time.monotonic() + args.timeout
    while True:
        if ping(args.url):
            return 0
        if time.monotonic() >= deadline:
            print(
                f"Redis did not become reachable at {args.url} within {args.timeout:g}s.",
                file=sys.stderr,
            )
            return 1
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
