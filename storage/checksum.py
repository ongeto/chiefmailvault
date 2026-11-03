"""MD5 checksum utilities."""

import hashlib
from pathlib import Path


def compute_md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_md5(path: Path, expected: str) -> bool:
    if not path.exists():
        return False
    return compute_md5(path) == expected
