"""Exercise the running stack via the frontend's API proxy."""
import json
import os
from urllib.request import Request, urlopen

base = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:5173")


def request(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return json.load(response) if response.status != 204 else None


health = request("/api/health/ready")
assert health["checks"]["database"] == "ok", health
if os.environ.get("SMOKE_REQUIRE_REDIS", "1") == "1":
    assert health["checks"]["redis"] == "ok", health
with urlopen(base, timeout=10) as response:
    assert b'<div id="app">' in response.read()
department = request("/api/departments")["data"][0]
patient = request("/api/patients", "POST", {
    "name": "Smoke Test Synthetic Patient",
    "department_id": department["id"],
    "notes": "Temporary smoke test record",
})["data"]
try:
    assert request(f'/api/patients/{patient["id"]}')["data"] == patient
    assert request("/api/patients?q=Smoke%20Test")["total"] >= 1
finally:
    request(f'/api/patients/{patient["id"]}', "DELETE")
print("Stack smoke test passed: frontend, readiness, patient create/search/read/delete")
