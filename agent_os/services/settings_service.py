"""Settings service — config read/write business logic.

Extracted from route handlers so the logic is testable without HTTP.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from ..config.env import mask_secret, resolve_secret

logger = logging.getLogger(__name__)


def get_masked_secrets(config: Any, db_conn: Any) -> dict[str, str]:
    """Resolve and mask secrets from config + DB, returning display values."""
    project_root = config.project.root_path or "."

    db_secrets: dict[str, str] = {}
    try:
        from ..storage.agent_config_repo import AgentConfigRepo
        db_secrets = AgentConfigRepo(db_conn).get_secrets()
    except Exception:
        logger.warning("Settings DB read failed, using empty defaults", exc_info=True)

    openai_resolved = resolve_secret(
        "openai_api_key",
        config.secrets.openai_api_key or db_secrets.get("openai_api_key", ""),
        project_root,
    )
    github_resolved = resolve_secret(
        "github_token",
        config.secrets.github_token or db_secrets.get("github_token", ""),
        project_root,
    )
    groq_resolved = resolve_secret(
        "groq_api_key",
        getattr(getattr(config, "groq", None), "api_key", "") or db_secrets.get("groq_api_key", ""),
        project_root,
    )
    return {
        "openai_api_key": mask_secret(openai_resolved),
        "github_token": mask_secret(github_resolved),
        "groq_api_key": mask_secret(groq_resolved),
    }


def is_masked_value(val: str) -> bool:
    """Return True if the value looks like a masked/redacted secret."""
    return (
        val.startswith("***")
        or (len(val) == 10 and val[3:6] == "...")
    )


def persist_env_file(
    agent_os_root: Path,
    openai_key: str = "",
    github_token: str = "",
) -> None:
    """Persist secrets to the .env file at agent_os_root."""
    env_path = agent_os_root / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    def _upsert(current_lines: list[str], key: str, val: str) -> list[str]:
        prefix = f"{key}="
        updated = False
        result = []
        for ln in current_lines:
            if ln.startswith(prefix):
                result.append(f'{key}="{val}"')
                updated = True
            else:
                result.append(ln)
        if not updated:
            result.append(f'{key}="{val}"')
        return result

    if openai_key:
        lines = _upsert(lines, "OPENAI_API_KEY", openai_key)
    if github_token:
        lines = _upsert(lines, "GITHUB_TOKEN", github_token)

    from ..utils.file_ops import atomic_write
    atomic_write(env_path, "\n".join(lines) + "\n")
    logger.info("Saved token(s) to %s", env_path)


def write_config_yaml(cfg: Any, config_path: Path | None = None) -> None:
    """Serialize user-editable settings back to the config YAML file.

    Delegates to the route-level implementation for backward compatibility.
    This is the canonical location; the route re-exports from here.
    """
    if config_path is None:
        return

    # Read existing file to preserve keys not managed by the Settings UI.
    existing: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}

    existing_storage = existing.get("storage", {})
    existing_model_routing = existing.get("codex", {}).get("model_routing", {})
    existing_cli_routing = existing.get("codex", {}).get("cli_routing", {})
    existing_budget = existing.get("budget", {})

    data: dict[str, Any] = {
        "project": {
            "name": cfg.project.name,
            "root_path": cfg.project.root_path,
            "language": cfg.project.language,
            "repo_name": getattr(cfg.project, "repo_name", ""),
            "feature_branch": getattr(cfg.project, "feature_branch", "dev"),
            "prompt_file_path": getattr(cfg.project, "prompt_file_path", ""),
        },
        "orchestrator": {
            "max_iterations": cfg.orchestrator.max_iterations,
            "auto_approve_hitl": cfg.orchestrator.auto_approve_hitl,
            "hitl_timeout_seconds": cfg.orchestrator.hitl_timeout_seconds,
            "convergence_rule": cfg.orchestrator.convergence_rule.value,
        },
        "codex": {
            "model": cfg.codex.model,
            "timeout_seconds": cfg.codex.timeout_seconds,
            "max_retries": cfg.codex.max_retries,
            **({"model_routing": existing_model_routing} if existing_model_routing else {}),
            "cli_routing": cfg.codex.cli_routing or existing_cli_routing or {},
        },
        "prompt_framework": cfg.prompt_framework.value,
        "git": {
            "auto_push": cfg.git.auto_push,
            "auto_commit": cfg.git.auto_commit,
        },
        "github": {
            "owner": cfg.github.owner,
            "repo": cfg.github.repo,
            "auto_push": cfg.github.auto_push,
            "auto_create_pr": cfg.github.auto_create_pr,
        },
        "requirements": {
            "path": cfg.requirements.path,
        },
        "secrets": {
            "openai_api_key": "",
            "github_token": "",
        },
    }

    # Preserve unmanaged keys
    if existing_storage:
        data["storage"] = existing_storage
    if existing_budget:
        data["budget"] = existing_budget

    from ..utils.file_ops import atomic_write
    atomic_write(config_path, yaml.dump(data, default_flow_style=False, sort_keys=False))
