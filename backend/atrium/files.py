"""Files on disk. The database keeps metadata and a storage key, never file content."""

import hashlib
from pathlib import Path

from .ids import uuid7


def path_for(root: Path, key: str) -> Path:
    return root / key[:2] / key


def store(root: Path, data: bytes) -> tuple[str, str]:
    key = uuid7().hex
    p = path_for(root, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return key, hashlib.sha256(data).hexdigest()


def remove(root: Path, key: str) -> None:
    try:
        path_for(root, key).unlink()
    except FileNotFoundError:
        pass


ALLOWED_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "text/plain",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
