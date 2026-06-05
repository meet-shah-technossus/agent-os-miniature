"""Authentication service — unified Copilot/GitHub token resolution.

Consolidates the duplicated 'gh auth token' + env fallback logic that was
previously copy-pasted in api_adapter.py and code_reviewer/runner.py.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

from ..constants import GH_CLI_TIMEOUT

logger = logging.getLogger(__name__)


def get_copilot_token(config_token: str = "") -> str:
    """Return a GitHub OAuth token suitable for the Copilot API.

    Priority:
    1. ``gh auth token`` — the OAuth token stored by the gh CLI (preferred,
       works with the Copilot API which rejects PATs).
    2. ``config_token`` — token passed from config (AI Tools UI or secrets).
    3. ``GITHUB_TOKEN`` env var.

    IMPORTANT: ``gh`` echoes back GITHUB_TOKEN/GH_TOKEN if they are present
    in its environment instead of reading the stored OAuth credential. We
    must strip those vars before invoking ``gh auth token``.
    """
    # 1. Try gh CLI OAuth token
    gh_token = _get_gh_cli_token()
    if gh_token:
        return gh_token

    # 2. Config-provided token
    if config_token:
        return config_token

    # 3. Environment variable
    return os.environ.get("GITHUB_TOKEN", "")


def _get_gh_cli_token() -> Optional[str]:
    """Attempt to get token from gh CLI. Returns None on failure."""
    try:
        clean_env = {
            k: v for k, v in os.environ.items()
            if k not in ("GITHUB_TOKEN", "GH_TOKEN")
        }
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=GH_CLI_TIMEOUT,
            env=clean_env,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
            if token:
                return token
    except Exception:
        pass
    return None
