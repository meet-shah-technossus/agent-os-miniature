"""File operations — extracted from CodeGeneratorRunner (Phase 9.2).

Handles LLM output parsing (FILE blocks) and path validation.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

_FILE_BLOCK_RE = re.compile(
    r'###\s+FILE:\s+(\S+)\s*\n```[^\n]*\n(.*?)```',
    re.DOTALL,
)


def apply_llm_file_output(
    stdout: str,
    working_dir: Path,
    emit: Callable[[str], None] | None = None,
) -> list[str]:
    """Parse FILE blocks from LLM stdout and write them to *working_dir*.

    Expects blocks of the form::

        ### FILE: relative/path/to/file.ext
        ```
        ...content...
        ```

    Returns a list of error strings (empty = all OK).
    """
    root = working_dir.resolve()
    errors: list[str] = []
    written: list[str] = []
    for m in _FILE_BLOCK_RE.finditer(stdout):
        rel_path = m.group(1).strip().lstrip("/\\").replace("\\", "/")
        content = m.group(2)
        target = (root / rel_path).resolve()
        # Security: never write outside working_dir
        try:
            target.relative_to(root)
        except ValueError:
            errors.append(f"Skipped unsafe path: {rel_path}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(rel_path)
        if emit:
            emit(f"[code-generator] wrote {rel_path}")
    if written:
        logger.info("[api-tool] Wrote %d file(s): %s", len(written), ", ".join(written))
    else:
        logger.warning("[api-tool] LLM output contained no ### FILE: blocks")
    return errors
