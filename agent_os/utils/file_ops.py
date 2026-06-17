"""Atomic file write utilities.

Prevents data corruption from partial writes (e.g. crash during config save).
Uses tempfile + os.replace for atomicity on both Unix and Windows.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    """Write *content* to *path* atomically.

    Creates a temporary file in the same directory, writes content, flushes
    to disk, then atomically replaces the target file.  This prevents
    half-written files if the process is interrupted.

    Args:
        path: Target file path.
        content: String content to write.
        encoding: File encoding (default utf-8).
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(target))
    except BaseException:
        # Clean up temp file on any failure
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
