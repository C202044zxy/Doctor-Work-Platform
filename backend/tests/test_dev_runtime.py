import os
import signal
import socket

import pytest

from app import dev_runtime, redis_bootstrap


def test_port_collision_reports_actionable_error():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(RuntimeError, match="occupied"):
            dev_runtime.assert_ports_free((listener.getsockname()[1],))


def test_redis_probe_uses_full_url_and_closes_client(monkeypatch):
    calls = []

    class Client:
        def ping(self):
            calls.append("ping")

        def close(self):
            calls.append("close")

    def from_url(url, **kwargs):
        calls.append(url)
        return Client()

    monkeypatch.setattr(redis_bootstrap.Redis, "from_url", from_url)
    url = "rediss://user:test-password@example.test:6380/2"
    assert redis_bootstrap.ping(url)
    assert calls == [url, "ping", "close"]


def test_readiness_requires_redis_and_database(monkeypatch):
    from io import BytesIO

    class Opener:
        def open(self, *args, **kwargs):
            return BytesIO(b'{"data":{"db":"ok","redis":"disabled"}}')

    monkeypatch.setattr(dev_runtime, "build_opener", lambda *args: Opener())
    monkeypatch.setattr(dev_runtime.time, "sleep", lambda *args: None)
    with pytest.raises(RuntimeError, match="dependencies are not ready"):
        dev_runtime.wait_ready(timeout=0.001)


# --------------------------------------------------------------------------
# Reclaiming a port may only ever stop this project's own leftover dev server.
# The truth table below *is* the safety policy; the autouse fixture is the
# guardrail that keeps a test from reaching a real taskkill or os.kill.
# --------------------------------------------------------------------------

# Verbatim from the orphan this feature was written for (PID 14900).
OUR_VITE = (
    r'"D:\work\node.js\node.exe" node_modules/vite/bin/vite.js '
    "--host 127.0.0.1 --port 5173 --strictPort"
)
OUR_API = "python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"


@pytest.fixture(autouse=True)
def _no_real_processes(monkeypatch):
    def forbid(what):
        def _fail(*args, **kwargs):
            pytest.fail(f"a test tried to {what}")

        return _fail

    monkeypatch.setattr(dev_runtime, "_run", forbid("run a real command"))
    monkeypatch.setattr(dev_runtime, "_signal", forbid("signal a real process"))


def _holder(port, pid=1234, name="node.exe", cmdline=OUR_VITE):
    return dev_runtime.PortHolder(port, pid, name, cmdline)


@pytest.fixture
def killed(monkeypatch):
    """Records terminate_holder calls instead of performing them."""
    calls = []

    def record(holder, port, **kwargs):
        calls.append((holder.pid, port))

    monkeypatch.setattr(dev_runtime, "terminate_holder", record)
    return calls


@pytest.fixture
def holders(monkeypatch):
    """Stubs discovery with a fixed set of port holders."""

    def install(*found):
        by_port = {holder.port: holder for holder in found}
        monkeypatch.setattr(dev_runtime, "occupied_ports", lambda ports=(): [h.port for h in found])
        monkeypatch.setattr(dev_runtime, "lookup_holder", lambda port: by_port.get(port))

    return install


@pytest.mark.parametrize(
    ("port", "name", "cmdline"),
    [
        (5173, "node.exe", OUR_VITE),
        (5173, "node", 'node "node_modules/vite/bin/vite.js" --port 5173 --strictPort'),
        (5173, "node.exe", r"node_modules\vite\bin\vite.js --port=5173 --strictPort"),
        (5173, "node.exe", OUR_VITE.replace("--strictPort", "--STRICTPORT")),
        (5173, "/usr/local/bin/node", "node_modules/vite/bin/vite.js --port 5173 --strictPort"),
        (8000, "python.exe", OUR_API),
        (8000, "/usr/local/bin/python", "uv run uvicorn app.main:app --port 8000"),
        (8000, "uvicorn", "uvicorn app.main:app --port 8000"),
    ],
)
def test_classify_holder_recognises_our_own_servers(port, name, cmdline):
    assert dev_runtime.classify_holder(port, name, cmdline) == dev_runtime.ROLE_BY_PORT[port]


@pytest.mark.parametrize(
    ("port", "name", "cmdline"),
    [
        # The same launcher without --strictPort: a foreign Vite on its default port.
        (5173, "node.exe", OUR_VITE.replace(" --strictPort", "")),
        (5173, "node.exe", OUR_VITE.replace("5173", "5174")),
        (5173, "node.exe", OUR_VITE.replace("5173", "51730")),
        (5173, "python.exe", "python -m http.server 5173"),
        (5173, "node.exe", "node server.js --port 5173 --strictPort"),
        # `vite` appearing only inside a path must not be enough.
        (5173, "node.exe", r'"D:\vite-projects\thing\node.exe" --port 5173 --strictPort'),
        (5173, "node.exe", ""),
        (5173, "docker-proxy", "docker-proxy -proto tcp -host-port 5173"),
        (5173, "com.docker.backend.exe", ""),
        # A substring of app.main:app must not pass for the real target.
        (8000, "python.exe", "python -m uvicorn some_other_app.main:app --port 8000"),
        (8000, "python.exe", "python -m http.server 8000"),
        (8000, "node.exe", OUR_VITE.replace("5173", "8000")),
        (9999, "node.exe", OUR_VITE),
    ],
)
def test_classify_holder_refuses_anything_not_provably_ours(port, name, cmdline):
    assert dev_runtime.classify_holder(port, name, cmdline) == ""


def test_reclaim_stops_only_our_own_leftovers(holders, killed):
    holders(_holder(5173, pid=14900))
    planned = dev_runtime.reclaim_ports((5173,))
    assert [holder.pid for holder in planned] == [14900]
    assert killed == [(14900, 5173)]


def test_reclaim_refuses_a_vite_that_is_not_ours(holders, killed):
    holders(_holder(5173, pid=8020, cmdline=OUR_VITE.replace(" --strictPort", "")))
    with pytest.raises(dev_runtime.PortConflict):
        dev_runtime.reclaim_ports((5173,))
    assert killed == []


def test_reclaim_stops_nothing_when_any_port_is_refused(holders, killed):
    holders(
        _holder(8000, pid=999, name="python.exe", cmdline="python -m http.server 8000"),
        _holder(5173, pid=14900),
    )
    with pytest.raises(dev_runtime.PortConflict):
        dev_runtime.reclaim_ports((8000, 5173))
    assert killed == []


def test_reclaim_reports_a_port_it_cannot_identify(monkeypatch, killed):
    monkeypatch.setattr(dev_runtime, "occupied_ports", lambda ports=(): [5173])
    monkeypatch.setattr(dev_runtime, "lookup_holder", lambda port: None)
    with pytest.raises(dev_runtime.PortConflict) as excinfo:
        dev_runtime.reclaim_ports((5173,))
    assert excinfo.value.unknown_ports == [5173]
    assert killed == []


def test_reclaim_treats_a_failed_lookup_as_unknown(monkeypatch, killed):
    def boom(port):
        raise dev_runtime.HolderUnknown("no lookup tool")

    monkeypatch.setattr(dev_runtime, "occupied_ports", lambda ports=(): [8000])
    monkeypatch.setattr(dev_runtime, "lookup_holder", boom)
    with pytest.raises(dev_runtime.PortConflict) as excinfo:
        dev_runtime.reclaim_ports((8000,))
    assert excinfo.value.unknown_ports == [8000]
    assert killed == []


def test_reclaim_dry_run_plans_without_stopping(holders, killed):
    holders(_holder(5173, pid=14900))
    planned = dev_runtime.reclaim_ports((5173,), dry_run=True)
    assert [holder.pid for holder in planned] == [14900]
    assert killed == []


def test_reclaim_does_not_look_up_a_port_that_is_free(monkeypatch, killed):
    monkeypatch.setattr(dev_runtime, "occupied_ports", lambda ports=(): [])
    monkeypatch.setattr(
        dev_runtime, "lookup_holder", lambda port: pytest.fail("looked up a free port")
    )
    assert dev_runtime.reclaim_ports((8000, 5173)) == []
    assert killed == []


def test_conflict_message_names_the_holder(holders, killed):
    holders(_holder(5173, pid=8020, cmdline="node some-other-project.js"))
    with pytest.raises(dev_runtime.PortConflict) as excinfo:
        dev_runtime.reclaim_ports((5173,))
    message = str(excinfo.value)
    assert "8020" in message
    assert "node.exe" in message
    assert "some-other-project.js" in message


def test_terminate_holder_refuses_reserved_pids():
    with pytest.raises(RuntimeError, match="kernel-reserved"):
        dev_runtime.terminate_holder(_holder(8000, pid=4, name="System", cmdline=""), 8000)


def test_terminate_holder_refuses_this_process():
    with pytest.raises(RuntimeError, match="this process"):
        dev_runtime.terminate_holder(_holder(8000, pid=os.getpid(), name="python.exe"), 8000)


def test_terminate_holder_windows_walks_the_tree(monkeypatch):
    monkeypatch.setattr(dev_runtime.os, "name", "nt")
    monkeypatch.setattr(dev_runtime, "_can_bind", lambda port: True)
    commands = []
    monkeypatch.setattr(
        dev_runtime, "_run", lambda command, **kwargs: commands.append(list(command)) or ""
    )
    dev_runtime.terminate_holder(_holder(5173, pid=14900), 5173)
    assert commands == [["taskkill.exe", "/PID", "14900", "/T", "/F"]]


def test_terminate_holder_reports_a_port_that_survived(monkeypatch):
    monkeypatch.setattr(dev_runtime.os, "name", "nt")
    monkeypatch.setattr(dev_runtime, "_can_bind", lambda port: False)
    monkeypatch.setattr(dev_runtime, "_run", lambda command, **kwargs: "")
    with pytest.raises(RuntimeError, match="still"):
        dev_runtime.terminate_holder(_holder(5173, pid=14900), 5173)


def test_terminate_holder_posix_signals_children_before_parent(monkeypatch):
    monkeypatch.setattr(dev_runtime.os, "name", "posix")
    monkeypatch.setattr(dev_runtime, "_can_bind", lambda port: True)
    monkeypatch.setattr(dev_runtime, "_descendants", lambda pid: [11, 12])
    monkeypatch.setattr(dev_runtime, "_alive", lambda pid: False)
    sent = []
    monkeypatch.setattr(dev_runtime, "_signal", lambda pid, sig: sent.append((pid, sig)))
    dev_runtime.terminate_holder(_holder(5173, pid=10), 5173)
    assert sent == [(11, signal.SIGTERM), (12, signal.SIGTERM), (10, signal.SIGTERM)]


def test_posix_lookup_does_not_mistake_ss_counters_for_a_pid(monkeypatch):
    """ss prints the socket even when it cannot name the owner; those fields are digits."""

    def fake_run(command, **kwargs):
        return "LISTEN 0 511 127.0.0.1:5173 0.0.0.0:*\n" if command[0] == "ss" else ""

    monkeypatch.setattr(dev_runtime, "_run", fake_run)
    assert dev_runtime._posix_listening_pid(5173) is None


def test_posix_lookup_falls_back_to_lsof_when_ss_is_unavailable(monkeypatch):
    def fake_run(command, **kwargs):
        if command[0] == "ss":
            raise dev_runtime.HolderUnknown("ss is not installed")
        return "4242\n"

    monkeypatch.setattr(dev_runtime, "_run", fake_run)
    assert dev_runtime._posix_listening_pid(5173) == 4242
