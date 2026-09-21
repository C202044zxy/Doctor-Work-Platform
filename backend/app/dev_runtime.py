"""Shared local startup checks for Windows and POSIX."""

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import time
from collections.abc import Sequence
from typing import NamedTuple
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

DEFAULT_PORTS = (8000, 5173)
ROLE_BY_PORT = {8000: "api", 5173: "web"}

# Windows reports kernel-reserved listeners (Hyper-V/WSL2 excluded port ranges,
# http.sys) as PID 0 or PID 4. Killing either is never right.
RESERVED_PIDS = frozenset({0, 1, 2, 3, 4})


class PortHolder(NamedTuple):
    port: int
    pid: int
    name: str
    cmdline: str


class HolderUnknown(RuntimeError):
    """The operating system could not name the process holding a port.

    Raised for a missing lookup tool, a timeout, or unparseable output. Keeping
    the three together matters: none of them is evidence that the port is free,
    so none of them may be treated as permission to go on.
    """


class PortConflict(RuntimeError):
    """A port is held by something that is not provably this project's own server."""

    def __init__(self, refused: Sequence[PortHolder], unknown_ports: Sequence[int]) -> None:
        self.refused = list(refused)
        self.unknown_ports = list(unknown_ports)
        super().__init__(_describe_conflict(self.refused, self.unknown_ports))


def _describe_conflict(refused: Sequence[PortHolder], unknown_ports: Sequence[int]) -> str:
    lines = ["Refusing to reclaim: these ports are not held by this project's own dev server."]
    for holder in refused:
        detail = holder.cmdline or "<command line not available>"
        lines.append(f"  port {holder.port}: pid {holder.pid} ({holder.name}) -- {detail}")
    for port in unknown_ports:
        lines.append(
            f"  port {port}: held, but nothing could be identified as listening on it. "
            "A server stopped seconds ago can still hold the address in TIME_WAIT; if so, retry."
        )
    lines.append(
        "Nothing was stopped. Inspect the holder with: python -m app.dev_runtime reclaim --dry-run"
    )
    return "\n".join(lines)


def _can_bind(port: int) -> bool:
    with socket.socket() as listener:
        if os.name == "posix":
            # POSIX-only. Here SO_REUSEADDR lets the probe succeed past a socket left
            # in TIME_WAIT by a server stopped seconds ago, and that is what we want:
            # nothing is listening, so the port is genuinely ours to take. On Windows
            # the same option lets the probe bind a port another process is actively
            # holding, which would silently disable this check -- hence the split.
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def occupied_ports(ports: Sequence[int] = DEFAULT_PORTS) -> list[int]:
    """The subset of `ports` that cannot be bound on 127.0.0.1, in the order given.

    Only these need looking up. A port we could bind is not in the way, whatever
    else on the machine happens to be listening on a different address.
    """
    return [port for port in ports if not _can_bind(port)]


def assert_ports_free(ports: Sequence[int] = DEFAULT_PORTS) -> None:
    """Raise unless every port can be bound. No side effects, no process lookups."""
    for port in occupied_ports(ports):
        raise RuntimeError(
            f"Port {port} is occupied. Stop the previous API/Vite or Docker stack first."
        )


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


# --------------------------------------------------------------------------
# Authorisation
#
# This is the whole safety policy, and it is the only place a process becomes
# eligible to be stopped. Everything below it gathers evidence; nothing below
# it may widen what counts as ours. Keep it pure so the truth table is testable.
# --------------------------------------------------------------------------


def _image_stem(name: str) -> str:
    """`/usr/local/bin/node` and `node.exe` both become `node`."""
    leaf = re.split(r"[\\/]", (name or "").strip())[-1]
    return leaf[:-4] if leaf.lower().endswith(".exe") else leaf


def _has_port_flag(cmdline: str, port: int) -> bool:
    # The trailing guard keeps `--port 51730` from matching a probe for 5173.
    return re.search(rf"--port[= ]{port}(?!\d)", cmdline) is not None


def _is_api_cmdline(text: str) -> bool:
    """`uvicorn` plus this project's ASGI target.

    The boundary before `app` is load-bearing: a plain substring test would let
    `some_other_app.main:app` through, which is a different application entirely.
    """
    if "uvicorn" not in text:
        return False
    return re.search(r"(?:^|[\s\"'])app\.main:app(?!\w)", text) is not None


def classify_holder(port: int, name: str, cmdline: str) -> str:
    """Return "api", "web", or "" for a process holding `port`.

    Pure: no I/O, no globals beyond the table above. A process may only be
    stopped when this returns the role that port belongs to.
    """
    role = ROLE_BY_PORT.get(port)
    if role is None:
        return ""
    stem = _image_stem(name)
    text = (cmdline or "").lower()
    normalized = text.replace("\\", "/")

    if role == "api":
        # `app.main:app` is the discriminating token here; the image name is only
        # a second lock, so `uvicorn` is allowed alongside `python` because a
        # console-script launch is not always distinguishable from an interpreter.
        if stem not in {"python", "uvicorn"}:
            return ""
        return "api" if _is_api_cmdline(text) else ""

    if stem != "node":
        return ""
    # Four independent positive signals. --strictport is the load-bearing one: it
    # is not a Vite default, so a foreign project has to ask for it explicitly.
    if "node_modules" not in normalized:
        return ""
    if "vite/bin/vite.js" not in normalized:
        return ""
    if not _has_port_flag(text, port):
        return ""
    return "web" if "--strictport" in text else ""


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def _run(command: Sequence[str], timeout: float = 15.0) -> str:
    """The single subprocess choke point; tests monkeypatch this and nothing else."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HolderUnknown(f"could not run {command[0]}: {exc}") from None
    if completed.returncode != 0:
        raise HolderUnknown(f"{command[0]} exited with {completed.returncode}")
    return completed.stdout


def _windows_holder(port: int) -> PortHolder | None:
    pids = _run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f"Get-NetTCPConnection -State Listen -LocalPort {int(port)} "
                "-ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"
            ),
        ]
    ).split()
    if not pids:
        return None
    pid = int(pids[0])
    detail = _run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                f'$p = Get-CimInstance Win32_Process -Filter "ProcessId={pid}" '
                "-ErrorAction SilentlyContinue;"
                "if ($p) { Write-Output $p.Name; Write-Output $p.CommandLine }"
            ),
        ]
    ).splitlines()
    name = detail[0].strip() if detail else ""
    cmdline = detail[1].strip() if len(detail) > 1 else ""
    return PortHolder(port, pid, name, cmdline)


def _posix_listening_pid(port: int) -> int | None:
    """PID listening on `port`, or None when a tool ran and named nobody."""
    try:
        # ss is Linux-only; lsof covers macOS. Both are asked before giving up.
        output = _run(["ss", "-lptnH", f"sport = :{int(port)}"])
    except HolderUnknown:
        pass
    else:
        # Only `users:(("node",pid=123,fd=20))` names a process, and reading it
        # needs privileges. Without it ss still prints the socket, whose counters
        # are bare digits -- so a digit-scraping fallback here would return 0.
        match = re.search(r"pid=(\d+)", output)
        return int(match.group(1)) if match else None
    # lsof -t prints bare PIDs, one per line.
    output = _run(["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-t"])
    for token in output.split():
        if token.isdigit():
            return int(token)
    return None


def _posix_holder(port: int) -> PortHolder | None:
    pid = _posix_listening_pid(port)
    if pid is None:
        return None
    name = _run(["ps", "-o", "comm=", "-p", str(pid)]).strip()
    cmdline = _run(["ps", "-o", "command=", "-p", str(pid)]).strip()
    return PortHolder(port, pid, name, cmdline)


def lookup_holder(port: int) -> PortHolder | None:
    """Who is listening on `port`.

    None means a tool ran and found nobody. Anything that stops us finding out
    raises HolderUnknown, which callers must treat as "not ours", never as "free".
    """
    if os.name == "nt":
        return _windows_holder(port)
    return _posix_holder(port)


# --------------------------------------------------------------------------
# Termination
# --------------------------------------------------------------------------


def _assert_terminable(pid: int) -> None:
    if pid in RESERVED_PIDS:
        raise RuntimeError(
            f"Refusing to stop pid {pid}: on Windows that is a kernel-reserved listener "
            "(Hyper-V/WSL2 excluded port range). Check `netsh interface ipv4 show "
            "excludedportrange protocol=tcp`, or restart winnat."
        )
    if pid in (os.getpid(), os.getppid()):
        raise RuntimeError(f"Refusing to stop pid {pid}: it is this process or its parent.")


def _signal(pid: int, sig: int) -> None:
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _descendants(pid: int) -> list[int]:
    """Every descendant, deepest first, so children die before their parents."""
    try:
        output = _run(["pgrep", "-P", str(pid)])
    except HolderUnknown:
        return []
    found: list[int] = []
    for token in output.split():
        child = int(token)
        found.extend(_descendants(child))
        found.append(child)
    return found


def _terminate_posix(pid: int, timeout: float) -> None:
    # No `setsid` + `kill -- -PGID`: setsid is util-linux and macOS does not ship
    # it, while start.sh explicitly supports macOS.
    descendants = _descendants(pid)
    for target in [*descendants, pid]:
        _signal(target, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            break
        time.sleep(0.2)
    for target in [*descendants, pid]:
        if _alive(target):
            _signal(target, signal.SIGKILL)


def terminate_holder(holder: PortHolder, port: int, *, timeout: float = 5.0) -> None:
    """Stop the holder and its descendants, then verify the port really is free."""
    _assert_terminable(holder.pid)
    if os.name == "nt":
        # /T covers uvicorn --reload's worker child and Vite's esbuild child. /F is
        # used rather than a graceful-first pass: taskkill without /F posts
        # WM_CLOSE, and these servers run in hidden windows that cannot receive it.
        try:
            _run(["taskkill.exe", "/PID", str(holder.pid), "/T", "/F"])
        except HolderUnknown:
            pass  # It may have exited between discovery and now; the port check decides.
    else:
        _terminate_posix(holder.pid, timeout)
    if not _can_bind(port):
        raise RuntimeError(
            f"Tried to stop pid {holder.pid} ({holder.name}) but port {port} is still "
            "occupied. Stop it by hand; it may be running elevated."
        )


def reclaim_ports(
    ports: Sequence[int] = DEFAULT_PORTS, *, dry_run: bool = False
) -> list[PortHolder]:
    """Free ports held by this project's own leftover dev servers.

    Fail-closed and all-or-nothing: if any occupied port holds a process that
    cannot be proven ours, nothing is killed and PortConflict is raised. A
    half-applied reclaim would be harder to reason about than none at all.
    """
    planned: list[PortHolder] = []
    refused: list[PortHolder] = []
    unknown: list[int] = []

    for port in occupied_ports(ports):
        try:
            holder = lookup_holder(port)
        except HolderUnknown:
            holder = None
        if holder is None:
            unknown.append(port)
        elif classify_holder(port, holder.name, holder.cmdline) == ROLE_BY_PORT.get(port):
            planned.append(holder)
        else:
            refused.append(holder)

    if refused or unknown:
        raise PortConflict(refused, unknown)
    if dry_run:
        return planned
    for holder in planned:
        terminate_holder(holder, holder.port)
    return planned


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["ports", "reclaim", "ready"])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with reclaim: report what would be stopped, and stop nothing",
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "ports":
            assert_ports_free()
        elif args.command == "ready":
            wait_ready()
        else:
            for holder in reclaim_ports(dry_run=args.dry_run):
                verb = "would stop" if args.dry_run else "stopped"
                print(
                    f"{verb} pid {holder.pid} ({holder.name}) on port {holder.port}: {holder.cmdline}"
                )
    except RuntimeError as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
