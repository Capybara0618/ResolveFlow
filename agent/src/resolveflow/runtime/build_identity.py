"""Credential-free identity for an unstamped checkout or installed source package."""
from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path


def source_identity(package: Path, lock: Path) -> str:
    code = hashlib.sha256()
    for path in sorted(package.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".sql"}:
            code.update(path.relative_to(package).as_posix().encode())
            code.update(b"\0")
            code.update(path.read_bytes())
            code.update(b"\0")
    if lock.is_file():
        dependency = hashlib.sha256(lock.read_bytes()).hexdigest()
        kind = "lock"
    else:
        # Wheels do not carry uv.lock: record the installed distributions explicitly.
        versions = sorted(f"{item.metadata['Name']}=={item.version}" for item in importlib.metadata.distributions())
        dependency = hashlib.sha256("\n".join(versions).encode()).hexdigest()
        kind = "deps"
    return f"source:{code.hexdigest()};{kind}:{dependency}"
