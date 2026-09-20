"""Optional M3 smoke check against an already running local API, Vite and Redis.

Run from backend: uv run python ../scripts/verify_m3_runtime.py
Creates one consultation and one message in the local demo database.
"""

import asyncio
import json
import sys
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import select
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.auth import issue_token  # noqa: E402
from app.config import Settings  # noqa: E402
from app.database import make_engine, session_factory  # noqa: E402
from app.models import User  # noqa: E402


async def main():
    settings = Settings()
    if not settings.database_url.startswith("sqlite:///"):
        raise RuntimeError("Only local demo SQLite is supported")
    engine = make_engine(settings.database_url)
    try:
        with session_factory(engine)() as db:
            tokens = {
                name: issue_token(db.scalar(select(User).where(User.username == name)), settings.jwt_secret)
                for name in ("dr_wang", "dr_li", "admin_zhang")
            }
    finally:
        engine.dispose()
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5173", timeout=15) as http:
        async def request(name, method, path, body=None):
            response = await http.request(method, path, json=body, headers={"Authorization": f"Bearer {tokens[name]}"})
            response.raise_for_status()
            return response.json()["data"]

        sockets = []
        room_id = None
        try:
            health = (await http.get("/api/health/ready")).json()["data"]
            assert health == {"db": "ok", "redis": "ok"}
            room_id = (await request("dr_wang", "POST", "/api/consultations", {"patient_no": "P20260001"}))["id"]
            await request("dr_li", "POST", f"/api/consultations/{room_id}/accept", {})
            url = f"ws://127.0.0.1:5173/ws/chat/{room_id}"
            for suffix in ("", f"?token={tokens['admin_zhang']}"):
                try:
                    async with connect(url + suffix):
                        raise AssertionError("Unexpected upgrade for anonymous/nonparticipant")
                except InvalidStatus as error:
                    assert error.response.status_code == 403
            for _ in range(20):
                sockets.append(await connect(url + f"?token={tokens['dr_wang']}"))

            async def message(ws):
                while True:
                    event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                    if event["type"] == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    if event["type"] == "message":
                        return event["data"]

            start = perf_counter()
            await sockets[0].send(json.dumps({"type": "message", "data": {"content": "M3 real Redis broadcast check"}}))
            messages = await asyncio.gather(*(message(ws) for ws in sockets))
            elapsed = (perf_counter() - start) * 1000
            assert len({row["id"] for row in messages}) == 1
            assert (await request("dr_wang", "GET", f"/api/consultations/{room_id}/messages"))["total"] == 1
            print(json.dumps({"health": health, "unauthorized_handshake": 403, "nonparticipant_handshake": 403, "connections": 20, "persisted_broadcast_ms": round(elapsed, 1), "under_500ms": elapsed < 500}))
        finally:
            await asyncio.gather(*(ws.close() for ws in sockets))
            if room_id:
                await request("dr_wang", "POST", f"/api/consultations/{room_id}/end", {})
            for name in tokens:
                await request(name, "POST", "/api/auth/logout", {})


if __name__ == "__main__":
    asyncio.run(main())
