"""Small file helpers."""

import hashlib
import os
import re
import shutil
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Dict

from gss import GssError


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_files(root: Path) -> Dict[str, Path]:
    """{relative posix path: path} for every file under root."""
    return {p.relative_to(root).as_posix(): p for p in sorted(root.rglob("*")) if p.is_file()}


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files."""

    def make_writable_and_retry(func, p, *_):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=make_writable_and_retry)


def safe_relpath(rel: str) -> str:
    """Reject paths that could point outside the folder they are extracted into."""
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or rel.startswith("/") or ":" in rel or "\\" in rel:
        raise GssError(f"Unsafe path in backup: {rel!r}")
    return p.as_posix()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def unique_path(path: Path) -> Path:
    """path, or path with _1, _2, ... added if it (or its .partial) exists."""
    candidate, n = path, 1
    while candidate.exists() or candidate.with_name(candidate.name + ".partial").exists():
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        n += 1
    return candidate
