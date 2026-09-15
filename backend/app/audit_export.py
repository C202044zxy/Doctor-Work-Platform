"""T12's CSV encoding, kept out of the routes so it can be tested directly.

`GET /api/audit-logs/export` is the first response in this codebase that is not
the `{code, message, data}` envelope. It has to be: a client that must unwrap JSON
to find a CSV is a client that can be handed a JSON error body and save it as
`audit.csv`. The route therefore returns a `Response` built here rather than
`_ok(...)`, and nothing in this module touches FastAPI.
"""

import csv
import io
import json
from datetime import UTC, datetime
from urllib.parse import quote

# Excel reads a BOM-less CSV as the system ANSI code page, which turns every
# Chinese name in the trail into mojibake. T12 criterion 2 asserts the BOM.
BOM = "﻿"

# The contract's `AuditLog` properties, in an order that reads well in a
# spreadsheet. `patient_id` and `status_code` are columns but not contract
# fields, so they are left out here for the same reason `AuditLogRead` leaves
# them out: the file and the API should describe the same object.
COLUMNS = (
    "id",
    "created_at",
    "user_id",
    "username",
    "action",
    "object_type",
    "object_id",
    "ip",
    "method",
    "path",
    "result",
    "detail",
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, dict):
        # `detail` is a structured summary, not prose. JSON keeps it inside one
        # cell without inventing a separator that a later reader has to guess at.
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def audit_csv(rows) -> str:
    """The BOM, the header, and one line per row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([_cell(getattr(row, column, None)) for column in COLUMNS])
    return BOM + buffer.getvalue()


def _day(value: datetime | None) -> str:
    return utc(value).strftime("%Y-%m-%d") if value is not None else "all"


def filename_range(rows, start: datetime | None, end: datetime | None) -> str:
    """`audit-<start>_<end>.csv`, covering the range the file actually spans.

    T12 criterion 2 wants the time range in the filename. When the caller filtered
    by a range that range is the honest answer. When they did not, the span of the
    rows that were exported is -- which keeps the claim true instead of naming a
    range the file does not contain.
    """
    if start is None or end is None:
        stamps = [utc(row.created_at) for row in rows if row.created_at is not None]
        if stamps:
            start = start or min(stamps)
            end = end or max(stamps)
    return f"audit-{_day(start)}_{_day(end)}.csv"


def content_disposition(filename: str) -> str:
    """Both spellings of the filename, because neither alone is enough.

    A bare `filename` cannot carry non-ASCII, and a bare `filename*` is ignored by
    older clients. The contract's example sends both, so both go out; when they
    agree the difference costs nothing.
    """
    return f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
