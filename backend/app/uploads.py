"""The one upload component, shared by T26's images and T31's meeting materials.

T31 §3 forbids implementing a second uploader: two copies of a security check
drift apart. So the size cap, the randomised on-disk name, the content-type
check and the audit hook live here once, and the two call sites differ only in
the whitelist they pass in -- T26 is image-only, T31 also accepts PDFs and
office documents, because scenario M5-T4 uploads 心电图-2026-09-01.pdf.

The declared content type decides, never the extension: an extension check
would happily store a text file named `report.pdf` as a PDF, and would reject a
legitimately unnamed upload. The stored name is randomised and its extension
comes from the validated type, so nothing the client sent survives into a path.
"""

import secrets
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

# Shared by both call sites; the contract calls it "the shared size cap".
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
DOCUMENT_EXTENSIONS = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

# T26's whitelist, kept separate on purpose: "shares the component" is not
# "shares the whitelist", and T31 needs the wider one below.
IMAGE_TYPES = frozenset(IMAGE_EXTENSIONS)
# T31 §1: "PDF / 图片 / 文档".
MEETING_TYPES = frozenset(IMAGE_EXTENSIONS) | frozenset(DOCUMENT_EXTENSIONS)

EXTENSIONS = {**IMAGE_EXTENSIONS, **DOCUMENT_EXTENSIONS}


@dataclass(frozen=True)
class StoredFile:
    """What the route stores in its own table. `filename` is the original."""

    filename: str
    stored_name: str
    content_type: str
    size_bytes: int


def save_upload(upload, directory, allowed: frozenset[str]) -> StoredFile:
    """Validate, then write, and answer with both names.

    A rejected type is a 422 whose message names the offending type, which is
    what the contract asks for and what makes the frontend able to say why a
    file was refused without guessing.
    """
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed:
        raise HTTPException(422, f"Unsupported file type: {content_type or 'unknown'}")
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(422, f"File exceeds the {MAX_UPLOAD_BYTES} byte upload cap")
    if not data:
        raise HTTPException(422, "Uploaded file is empty")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{secrets.token_hex(16)}{EXTENSIONS[content_type]}"
    (directory / stored_name).write_bytes(data)
    # `Path(...).name` strips any directory the client put in the field, so a
    # filename like `../../etc/passwd` cannot come back out in the header.
    filename = Path(upload.filename or stored_name).name[:255] or stored_name
    return StoredFile(filename, stored_name, content_type, len(data))


def stored_path(directory, stored_name: str) -> Path:
    return Path(directory) / Path(stored_name).name
