"""Project provisioner — extracted from Orchestrator (Phase 8.2).

Handles creating project directories, deriving names, and initializing
the folder for code generation.
"""
from __future__ import annotations

import logging
import re
import stat as _stat
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ProjectProvisioner:
    """Creates and configures project directories for pipeline runs."""

    def __init__(self, config: Any) -> None:
        self._config = config

    def provision(self) -> str:
        """Create (if needed) and return a project folder under ~/Desktop/agent-os/.

        The folder name is derived from ``config.project.name`` when set, or
        falls back to the first epic title from the requirements file, or
        finally to ``agent-os-project``.  Collision-safe: appends ``-2``,
        ``-3``, … if the preferred name is already taken.

        The resolved path is stored back in ``config.project.root_path`` so
        subsequent iterations reuse the same folder.
        """
        # Determine a slug for the folder name
        raw_name = (self._config.project.name or "").strip()
        if not raw_name:
            raw_name = self._derive_name_from_requirements()
        if not raw_name:
            raw_name = "agent-os-project"

        # Sanitise to a filesystem-safe slug
        slug = re.sub(r"[^a-zA-Z0-9_\-]", "-", raw_name).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)[:60] or "agent-os-project"

        agent_os_root = Path.home() / "Desktop" / "agent-os"
        agent_os_root.mkdir(parents=True, exist_ok=True)

        # Collision-safe: find an unused name
        candidate = agent_os_root / slug
        counter = 2
        while candidate.exists() and candidate != Path(getattr(self._config.project, "root_path", "")):
            candidate = agent_os_root / f"{slug}-{counter}"
            counter += 1

        # Reuse if the directory already exists (e.g. re-running the same project)
        if candidate.exists():
            logger.info("Reusing existing project directory: %s", candidate)
            self._config.project.root_path = str(candidate)
            if not self._config.project.name:
                self._config.project.name = slug
            return str(candidate)

        try:
            candidate.mkdir(parents=True, exist_ok=True)
            # Ensure owner has full read/write/execute on the directory
            candidate.chmod(
                _stat.S_IRWXU | _stat.S_IRGRP | _stat.S_IXGRP | _stat.S_IROTH | _stat.S_IXOTH
            )
            logger.info("Provisioned project directory: %s", candidate)
        except Exception as exc:
            logger.error("Failed to create project directory %s: %s", candidate, exc)
            raise

        # Persist so subsequent steps reuse it
        self._config.project.root_path = str(candidate)
        if not self._config.project.name:
            self._config.project.name = slug
        return str(candidate)

    def _derive_name_from_requirements(self) -> str:
        """Try to extract a project name from the requirements file."""
        try:
            import yaml as _yaml

            req_path = getattr(self._config.requirements, "path", "")
            if not req_path:
                return ""
            req_file = Path(req_path)
            if not req_file.exists():
                return ""
            text = req_file.read_text(encoding="utf-8")
            if req_file.suffix.lower() == ".md":
                match = re.search(r"```yaml\s*\n(.*?)\n```", text, re.DOTALL)
                raw = _yaml.safe_load(match.group(1)) if match else {}
            else:
                raw = _yaml.safe_load(text)
            epics = (raw or {}).get("epics", [])
            if epics:
                return (epics[0].get("title", "") or "").strip()
        except Exception:
            pass
        return ""
