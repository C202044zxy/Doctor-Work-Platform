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
