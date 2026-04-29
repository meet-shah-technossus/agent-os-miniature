"""Dependency manager — venv creation and pip install for generated projects."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..config.schema import DependencyConfig

logger = logging.getLogger(__name__)


class DependencyInstallResult:
    """Outcome of a pip install attempt."""

    def __init__(
        self, success: bool, output: str = "", errors: str = ""
    ) -> None:
        self.success = success
        self.output = output
        self.errors = errors


class DependencyManager:
    """Manages virtual environment creation and dependency installation
    for the generated project directory."""

    def __init__(self, config: DependencyConfig, project_root: str) -> None:
        self._config = config
        self._root = Path(project_root)
        self._venv_path = self._root / config.venv_name

    @property
    def venv_python(self) -> str:
        """Path to the venv's Python interpreter."""
        return str(self._venv_path / "bin" / "python")

    @property
    def venv_exists(self) -> bool:
        return (self._venv_path / "bin" / "python").exists()

    def ensure_venv(self) -> bool:
        """Create the virtual environment if it doesn't exist.

        Returns True on success, False on failure.
        """
        if not self._config.auto_create_venv:
            return True

        if self.venv_exists:
            logger.debug("Venv already exists: %s", self._venv_path)
            return True

        logger.info("Creating venv at: %s", self._venv_path)
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", str(self._venv_path)],
                capture_output=True, text=True, timeout=120,
                cwd=str(self._root),
            )
            return self.venv_exists
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error("Failed to create venv: %s", exc)
            return False

    def install_requirements(self) -> DependencyInstallResult:
        """Run ``pip install -r requirements.txt`` inside the project venv.

        Returns a DependencyInstallResult with success flag and output.
        """
        if not self._config.auto_install:
            return DependencyInstallResult(success=True, output="auto_install disabled")

        req_file = self._root / "requirements.txt"
        if not req_file.exists():
            return DependencyInstallResult(success=True, output="no requirements.txt found")

        self.ensure_venv()
        pip = str(self._venv_path / "bin" / "pip")
        if not Path(pip).exists():
            pip = self.venv_python

        cmd = [pip, "install", "-r", str(req_file)]
        logger.info("Installing dependencies: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True, text=True, timeout=300,
                cwd=str(self._root),
            )
            return DependencyInstallResult(
                success=result.returncode == 0,
                output=result.stdout[-2000:] if result.stdout else "",
                errors=result.stderr[-2000:] if result.stderr else "",
            )
        except subprocess.TimeoutExpired:
            return DependencyInstallResult(success=False, errors="pip install timed out")
        except FileNotFoundError:
            return DependencyInstallResult(success=False, errors="pip not found")

    def dry_run_install(self) -> DependencyInstallResult:
        """Check dependencies without installing (dry-run)."""
        req_file = self._root / "requirements.txt"
        if not req_file.exists():
            return DependencyInstallResult(success=True, output="no requirements.txt found")

        pip = str(self._venv_path / "bin" / "pip") if self.venv_exists else "pip"
        cmd = [pip, "install", "--dry-run", "-r", str(req_file)]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                cwd=str(self._root),
            )
            return DependencyInstallResult(
                success=result.returncode == 0,
                output=result.stdout[-2000:] if result.stdout else "",
                errors=result.stderr[-2000:] if result.stderr else "",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return DependencyInstallResult(success=False, errors=str(exc))
