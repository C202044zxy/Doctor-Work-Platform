"""T12 acceptance: the audit query endpoint and its CSV export.

`test_security.py` covers T11's writer. These cover the reader: who may call it,
whether each filter actually narrows, and whether the file says the same thing the
list does.
"""

import csv
import io
import re

from test_auth_grants import client as auth_client
from test_auth_grants import headers

client = auth_client

# The contract's `AuditLog` properties. `patient_id` and `status_code` are columns
# on the table but are not part of it, so the response model has to keep them out.
CONTRACT_FIELDS = {
    "id",
    "user_id",
    "action",
    "username",
    "object_type",
    "object_id",
    "ip",
    "method",
    "path",
    "result",
    "detail",
    "created_at",
}


def make_rows(client):
    """One patient, read by two accounts, so `user_id` has something to separate.

    Leaves three entries: `patient.create` by admin, then `patient.view` by admin
    and by senior.
    """
    number = client.post(
        "/api/patients",
        headers=headers(client, 1),
        json={
            "name": "Audit Subject",
            "gender": "unknown",
            "department": "Information Technology",
        },
    ).json()["data"]["patient_no"]
    for uid in (1, 2):
        assert (
            client.get(f"/api/patients/{number}", headers=headers(client, uid)).status_code == 200
        )
    return number


def count(client, query=""):
    body = client.get(f"/api/audit-logs{query}", headers=headers(client, 1)).json()["data"]
    return body["total"]


def csv_rows(response):
    # The BOM is not part of the first header cell; strip it before parsing.
    return list(csv.reader(io.StringIO(response.text.lstrip("﻿"))))


def test_list_is_admin_only(client):
    """Criterion 3 / scenario S2. A senior is refused too, and refused emptily.

    S2 will not sign off a build that merely hides the menu, so the assertion is on
    the body rather than the status code alone: the refusal must carry no log data
    for the browser's Network panel to show.
    """
    make_rows(client)
    for uid in (2, 3):
        response = client.get("/api/audit-logs", headers=headers(client, uid))
        assert response.status_code == 403
        assert response.json()["data"] is None
        for field in ("username", "object_type", "result", "created_at"):
            assert field not in response.text


def test_export_is_admin_only(client):
    make_rows(client)
    assert client.get("/api/audit-logs/export", headers=headers(client, 2)).status_code == 403
    assert client.get("/api/audit-logs/export").status_code == 401


def test_rows_match_the_contract_and_carry_detail(client):
    """Criterion 5, plus the response model standing in for the contract's fields."""
    make_rows(client)
    client.get("/api/audit-logs/export", headers=headers(client, 1))
    items = client.get("/api/audit-logs", headers=headers(client, 1)).json()["data"]["items"]

    assert items
    for row in items:
        assert set(row) == CONTRACT_FIELDS

    # `patient.view` is written with object_type and object_id, and the actor's name
    # is snapshotted rather than joined -- both accounts read the same patient, so
    # the two rows name different people.
    views = [row for row in items if row["action"] == "patient.view"]
    assert {row["username"] for row in views} == {"admin", "senior"}
    assert all(row["object_type"] == "patient" and row["method"] == "GET" for row in views)
    assert all(row["created_at"].endswith(("Z", "+00:00")) for row in views)  # never local time

    # Criterion 5 wants a row to expand in place. `patient.create` is recorded
    # without a detail, so the populated case here is the export's own entry --
    # which is also what T11 criterion 2 requires to exist at all.
    exported = next(row for row in items if row["action"] == "audit.export")
    assert exported["detail"]["rows"] >= 1
    assert exported["object_type"] == "audit_log"


def test_each_filter_narrows_the_result(client):
    """Criterion 1: the three conditions combine, and each one really filters."""
    make_rows(client)
    everything = count(client)
    assert everything >= 3

    by_user = client.get("/api/audit-logs?user_id=1", headers=headers(client, 1)).json()["data"]
    assert 0 < by_user["total"] < everything
    assert all(row["user_id"] == 1 for row in by_user["items"])

    by_action = client.get(
        "/api/audit-logs?action=patient.view", headers=headers(client, 1)
    ).json()["data"]
    assert by_action["total"] == 2
    assert {row["username"] for row in by_action["items"]} == {"admin", "senior"}

    # Every row here is patient-scoped, so this one keeps the whole set rather than
    # narrowing it -- which is the correct behaviour for a condition that matches.
    by_object = client.get(
        "/api/audit-logs?object_type=patient", headers=headers(client, 1)
    ).json()["data"]
    assert by_object["total"] == everything

    combined = count(client, "?user_id=1&action=patient.view&object_type=patient")
    assert combined == 1


def test_time_range_filter_actually_binds(client):
    """The one that fails if a datetime is bound wrongly.

    `created_at` is stored as a naive UTC string. A range wide enough to cover
    everything has to return everything; a comparison that never matched would come
    back as zero instead and the page would simply look empty, which is the kind of
    failure that survives a demo.
    """
    make_rows(client)
    everything = count(client)
    assert count(client, "?from=2000-01-01T00:00:00&to=2999-01-01T00:00:00") == everything
    assert count(client, "?from=2999-01-01T00:00:00&to=2999-01-02T00:00:00") == 0

    # A narrower range than "everything" but still covering the rows, to prove the
    # bounds are compared rather than ignored.
    assert count(client, "?from=2000-01-01T00:00:00") == everything
    assert count(client, "?to=2000-01-01T00:00:00") == 0


def test_a_filter_that_is_not_a_timestamp_is_rejected(client):
    assert (
        client.get("/api/audit-logs?from=yesterday", headers=headers(client, 1)).status_code == 422
    )


def test_pagination_splits_the_result_and_counts_all_of_it(client):
    """Criterion 1: `total` is the number of matches, not the rows on the page."""
    make_rows(client)
    first = client.get("/api/audit-logs?size=1&page=1", headers=headers(client, 1)).json()["data"]
    second = client.get("/api/audit-logs?size=1&page=2", headers=headers(client, 1)).json()["data"]

    assert first["total"] == second["total"] >= 3
    assert (first["page"], first["size"]) == (1, 1)
    assert len(first["items"]) == len(second["items"]) == 1
    # The `id` tie-break is what keeps a row off both pages when two entries share
    # a timestamp, which they do whenever a test writes them in the same second.
    assert first["items"][0]["id"] != second["items"][0]["id"]


def test_export_agrees_with_the_list(client):
    """Criterion 2 / scenario S1, all four halves of it."""
    make_rows(client)
    query = "action=patient.view"
    total = count(client, f"?{query}")

    response = client.get(f"/api/audit-logs/export?{query}", headers=headers(client, 1))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    # The bytes, not the decoded text, are what Excel reads.
    assert response.content.startswith(b"\xef\xbb\xbf")

    disposition = response.headers["content-disposition"]
    assert "attachment;" in disposition
    # Both spellings, per the contract's example: a bare `filename` cannot carry
    # non-ASCII and a bare `filename*` is ignored by older clients.
    assert "filename=" in disposition and "filename*=UTF-8''" in disposition

    rows = csv_rows(response)
    assert rows[0][:3] == ["id", "created_at", "user_id"]
    # S1's own judgement: the export honours the filter rather than dumping the table.
    assert len(rows) - 1 == total

    everything = csv_rows(client.get("/api/audit-logs/export", headers=headers(client, 1)))
    assert len(everything) - 1 > total


def test_export_filename_carries_the_range(client):
    """Criterion 2: the filename has to say which range the file covers."""
    make_rows(client)
    bounded = client.get(
        "/api/audit-logs/export?from=2026-01-01T00:00:00&to=2026-01-02T00:00:00",
        headers=headers(client, 1),
    )
    assert 'filename="audit-2026-01-01_2026-01-02.csv"' in bounded.headers["content-disposition"]

    # Unfiltered, the name falls back to the span of what was exported rather than
    # claiming a range the file does not contain.
    unfiltered = client.get("/api/audit-logs/export", headers=headers(client, 1))
    assert re.search(
        r'filename="audit-\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv"',
        unfiltered.headers["content-disposition"],
    )


def test_export_records_itself(client):
    """T11 criterion 2: the export is a sensitive read the middleware cannot see.

    The middleware records writes only, so an unmarked export hands the entire trail
    to a file and leaves nothing behind saying who took it.
    """
    make_rows(client)
    assert count(client, "?action=audit.export") == 0

    export = client.get("/api/audit-logs/export?action=patient.view", headers=headers(client, 1))
    assert export.status_code == 200

    exported = client.get("/api/audit-logs?action=audit.export", headers=headers(client, 1))
    body = exported.json()["data"]
    assert body["total"] == 1
    entry = body["items"][0]
    assert (entry["username"], entry["object_type"]) == ("admin", "audit_log")
    # The recorded summary is a JSON column, so it has to survive the insert: a
    # datetime in there raises and `persist_audit` swallows the whole entry, which
    # would make this row disappear rather than fail loudly.
    assert entry["detail"]["filters"]["action"] == "patient.view"
    assert entry["detail"]["rows"] == len(csv_rows(export)) - 1
