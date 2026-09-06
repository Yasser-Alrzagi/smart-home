"""Validation and canonicalization only. Storage is atomic with the admission UoW."""

import hashlib
import os
from pathlib import PurePath
import subprocess
import sys

from app.core.config import BASE_DIR, settings
from app.core.errors import AppError

MIMES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def validate_document(data, filename, declared_type):
    if not data or len(data) > settings.DOCUMENT_MAX_BYTES:
        raise AppError(413, "Document is empty or exceeds the size limit.")
    kind = PurePath((filename or "").replace("\\", "/")).suffix.lower().lstrip(".")
    if kind not in MIMES or declared_type not in {
        MIMES[kind],
        "application/octet-stream",
    }:
        raise AppError(415, "Only PDF, JPEG and PNG documents are accepted.")
    # Do not pass signing/database credentials to the untrusted parsing process.
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.core.document_worker", kind],
            cwd=BASE_DIR,
            env=env,
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=7,
        )
    except (subprocess.TimeoutExpired, OSError):
        raise AppError(415, "Document validation failed or timed out.") from None
    if (
        proc.returncode != 0
        or not proc.stdout
        or len(proc.stdout) > settings.DOCUMENT_MAX_BYTES
    ):
        raise AppError(415, "Invalid, oversized, encrypted or active document content.")
    return proc.stdout, MIMES[kind], hashlib.sha256(proc.stdout).hexdigest()
