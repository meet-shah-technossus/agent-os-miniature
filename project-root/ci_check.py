#!/usr/bin/env python3
"""CI sanity check driver for Agent OS."""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv_ci"


def run_in_env(command: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def create_venv() -> None:
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    pip_path = VENV_DIR / "bin" / "pip"
    run_in_env([str(pip_path), "install", "--upgrade", "pip"])
    run_in_env([str(pip_path), "install", "-r", str(ROOT / "requirements.txt")])


def run_pytest() -> int:
    result = run_in_env([str(VENV_DIR / "bin" / "pytest"), "-q"])
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def smoke_test() -> int:
    env = dict(**dict(**__import__("os").environ))
    env["PYTHONPATH"] = str(ROOT)
    result = run_in_env([
        str(VENV_DIR / "bin" / "python"),
        "-c",
        "import app; print('App import OK' if hasattr(app, 'create_app') else 'Missing create_app')",
    ], env=env)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def main() -> None:
    try:
        create_venv()
    except subprocess.CalledProcessError as exc:
        print("Failed to set up virtual environment", exc, file=sys.stderr)
        sys.exit(1)

    rc = run_pytest()
    if rc != 0:
        print("Pytest failed", file=sys.stderr)
        sys.exit(rc)

    rc = smoke_test()
    if rc != 0:
        print("Smoke test failed", file=sys.stderr)
        sys.exit(rc)

    print("CI OK")


if __name__ == "__main__":
    main()
