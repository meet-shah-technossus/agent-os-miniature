"""Project service — file listing and directory operations.

Extracted from route handlers for testability.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories to skip when building file trees.
IGNORE_DIRS: frozenset[str] = frozenset({
    ".git", "__pycache__", ".venv", "node_modules",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
})


def count_source_files(root: Path) -> int:
    """Count source files in root, excluding ignored directories."""
    count = 0
    if not root.exists():
        return 0
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if any(part in IGNORE_DIRS for part in f.parts):
            continue
        count += 1
    return count


def build_file_tree(
    current: Path,
    root: Path,
    max_depth: int = 6,
    depth: int = 0,
) -> list[dict[str, Any]]:
    """Recursively build a file tree, skipping ignored directories.

    Returns a list of dicts with keys: name, path, is_dir, children, size.
    """
    if depth > max_depth:
        return []

    nodes: list[dict[str, Any]] = []
    try:
        entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return []

    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env",):
            continue
        if entry.name in IGNORE_DIRS:
            continue

        rel = str(entry.relative_to(root))
        if entry.is_dir():
            children = build_file_tree(entry, root, max_depth, depth + 1)
            nodes.append({"name": entry.name, "path": rel, "is_dir": True, "children": children})
        else:
            nodes.append({"name": entry.name, "path": rel, "is_dir": False, "size": entry.stat().st_size})

    return nodes
