"""Settings routes — read/write config, test GitHub connection."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, Depends

from ...config.env import mask_secret, resolve_secret
from ..deps import get_orchestrator, orch_holder
from ..schemas import (
    GitHubSettingsResponse,
    PipelineSettingsResponse,
    ProjectSettingsResponse,
    SecretsSettingsResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    TestGitHubResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse)
def get_settings(orch=Depends(get_orchestrator)):
    """Return current settings with secrets masked."""
    cfg = orch.config
    project_root = cfg.project.root_path or "."

    # Supplement config-level secrets with DB-stored secrets as a fallback.
    # DB takes priority over .env / os.environ when the config value is empty.
    try:
        from ...storage.agent_config_repo import AgentConfigRepo
        _db_secrets = AgentConfigRepo(orch.db.conn).get_secrets()
    except Exception:
        _db_secrets = {}

    openai_resolved = resolve_secret(
        "openai_api_key",
        cfg.secrets.openai_api_key or _db_secrets.get("openai_api_key", ""),
        project_root,
    )
    github_resolved = resolve_secret(
        "github_token",
        cfg.secrets.github_token or _db_secrets.get("github_token", ""),
        project_root,
    )

    return SettingsResponse(
        secrets=SecretsSettingsResponse(
            openai_api_key=mask_secret(openai_resolved),
            github_token=mask_secret(github_resolved),
        ),
        github=GitHubSettingsResponse(
            owner=cfg.github.owner,
            repo=cfg.github.repo,
            auto_push=cfg.github.auto_push,
            auto_create_pr=cfg.github.auto_create_pr,
        ),
        project=ProjectSettingsResponse(
            name=cfg.project.name,
            root_path=cfg.project.root_path,
            language=cfg.project.language,
        ),
        pipeline=PipelineSettingsResponse(
            max_iterations_per_module=cfg.orchestrator.max_iterations_per_module,
            convergence_rule=cfg.orchestrator.convergence_rule.value,
            auto_approve_hitl=cfg.orchestrator.auto_approve_hitl,
        ),
    )


@router.put("", response_model=SettingsResponse)
def update_settings(body: SettingsUpdateRequest, orch=Depends(get_orchestrator)):
    """Update settings, write to config.yaml, and hot-reload into the orchestrator."""
    cfg = orch.config

    # Apply secrets (only overwrite non-empty, non-masked values)
    _new_openai = ""
    _new_github = ""
    if body.secrets is not None:
        if body.secrets.openai_api_key and not body.secrets.openai_api_key.startswith("***"):
            cfg.secrets.openai_api_key = body.secrets.openai_api_key
            _new_openai = body.secrets.openai_api_key
        if body.secrets.github_token and not body.secrets.github_token.startswith("***"):
            cfg.secrets.github_token = body.secrets.github_token
            _new_github = body.secrets.github_token

    if body.github is not None:
        cfg.github.owner = body.github.owner
        cfg.github.repo = body.github.repo
        cfg.github.auto_push = body.github.auto_push
        cfg.github.auto_create_pr = body.github.auto_create_pr

    if body.project is not None:
        cfg.project.name = body.project.name
        cfg.project.root_path = body.project.root_path
        cfg.project.language = body.project.language

    if body.pipeline is not None:
        cfg.orchestrator.max_iterations_per_module = body.pipeline.max_iterations_per_module
        cfg.orchestrator.auto_approve_hitl = body.pipeline.auto_approve_hitl
        from ...config.schema import ConvergenceRule
        cfg.orchestrator.convergence_rule = ConvergenceRule(body.pipeline.convergence_rule)

    # Persist to config.yaml (no-op when config_path is None, e.g. in tests)
    _write_config_yaml(cfg, orch_holder.config_path)

    # Mirror model_routing and secrets to DB so they survive process restarts.
    try:
        from ...storage.agent_config_repo import AgentConfigRepo
        _repo = AgentConfigRepo(orch.db.conn)
        if cfg.codex.model_routing:
            _repo.set_model_routing(dict(cfg.codex.model_routing))
        if _new_openai or _new_github:
            _repo.set_secrets(openai_api_key=_new_openai, github_token=_new_github)
            # Inject into this process's os.environ immediately — resolve_secret
            # will find it without needing a DB round-trip
            import os as _os
            if _new_openai:
                _os.environ["OPENAI_API_KEY"] = _new_openai
            if _new_github:
                _os.environ["GITHUB_TOKEN"] = _new_github
            # Also persist to .env at Agent OS root so the token survives
            # a uvicorn --reload restart (which kills the process)
            try:
                from pathlib import Path as _Path
                _env_path = _Path(".env").resolve()
                _lines: list[str] = []
                if _env_path.exists():
                    _lines = _env_path.read_text().splitlines()
                # Upsert each key
                def _upsert(lines: list[str], key: str, val: str) -> list[str]:
                    prefix = f"{key}="
                    updated = False
                    result = []
                    for ln in lines:
                        if ln.startswith(prefix):
                            result.append(f'{key}="{val}"')
                            updated = True
                        else:
                            result.append(ln)
                    if not updated:
                        result.append(f'{key}="{val}"')
                    return result
                if _new_openai:
                    _lines = _upsert(_lines, "OPENAI_API_KEY", _new_openai)
                if _new_github:
                    _lines = _upsert(_lines, "GITHUB_TOKEN", _new_github)
                _env_path.write_text("\n".join(_lines) + "\n")
                logger.info("Saved token(s) to %s", _env_path)
            except Exception as _env_err:
                logger.debug("Could not write .env file: %s", _env_err)
    except Exception as _e:
        logger.warning("Could not mirror settings to DB: %s", _e)

    logger.info("Settings updated and persisted to config.yaml")

    # Return the updated (masked) settings
    return get_settings(orch)


@router.post("/test-github", response_model=TestGitHubResponse)
def test_github_connection(orch=Depends(get_orchestrator)):
    """Test the GitHub token by calling the /user endpoint."""
    cfg = orch.config
    project_root = cfg.project.root_path or "."
    try:
        from ...storage.agent_config_repo import AgentConfigRepo
        _db_tok = AgentConfigRepo(orch.db.conn).get_secrets().get("github_token", "")
    except Exception:
        _db_tok = ""
    token = resolve_secret("github_token", cfg.secrets.github_token or _db_tok, project_root)

    if not token:
        return TestGitHubResponse(valid=False, message="No GitHub token configured")

    try:
        resp = httpx.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return TestGitHubResponse(
                valid=True,
                user=data.get("login", ""),
                message=f"Authenticated as {data.get('login', 'unknown')}",
            )
        return TestGitHubResponse(
            valid=False,
            message=f"GitHub API returned {resp.status_code}",
        )
    except httpx.HTTPError as exc:
        return TestGitHubResponse(valid=False, message=f"Connection error: {str(exc)[:200]}")


def _write_config_yaml(cfg, config_path: Path | None = None) -> None:
    """Serialize user-editable settings back to the config YAML file.

    If ``config_path`` is None (e.g. in-memory / test configurations) the
    function is a no-op — it will never write to the project's config.yaml.

    Keys that are not exposed via the Settings UI (``storage.db_path``,
    ``codex.model_routing``, ``budget.*``) are read from the existing file and
    preserved verbatim, so a test or a mis-configured in-memory object can
    never clobber values the user set manually.

    Secrets are always written as empty strings; real values should live in
    ``.env`` or environment variables, not in the YAML file.
    """
    if config_path is None:
        return  # no persistent file — skip (in-memory / test orchestrator)

    # Read the existing file to preserve keys not managed by the Settings UI.
    existing: dict = {}
    if config_path.exists():
        with open(config_path) as f:
            existing = yaml.safe_load(f) or {}

    # Preserve storage, model_routing and budget from the file on disk.
    existing_storage = existing.get("storage", {})
    existing_model_routing = existing.get("codex", {}).get("model_routing", {})
    existing_budget = existing.get("budget", {})

    data = {
        "project": {
            "name": cfg.project.name,
            "root_path": cfg.project.root_path,
            "language": cfg.project.language,
        },
        "orchestrator": {
            "max_iterations_per_module": cfg.orchestrator.max_iterations_per_module,
            "auto_approve_hitl": cfg.orchestrator.auto_approve_hitl,
            "hitl_timeout_seconds": cfg.orchestrator.hitl_timeout_seconds,
            "convergence_rule": cfg.orchestrator.convergence_rule.value,
        },
        "codex": {
            "model": cfg.codex.model,
            "timeout_seconds": cfg.codex.timeout_seconds,
            "max_retries": cfg.codex.max_retries,
            # Preserve model_routing exactly as the user wrote it in the file.
            **({
                "model_routing": existing_model_routing
            } if existing_model_routing else {}),
        },
        "prompt_framework": cfg.prompt_framework.value,
        "git": {
            "enabled": cfg.git.enabled,
            "remote": cfg.git.remote,
            "main_branch": cfg.git.main_branch,
            "dev_branch": cfg.git.dev_branch,
            "auto_create_feature_branches": cfg.git.auto_create_feature_branches,
        },
        "validation": {
            "lint": cfg.validation.lint,
            "type_check": cfg.validation.type_check,
            "tests": cfg.validation.tests,
            "security_scan": cfg.validation.security_scan,
        },
        "requirements": {"path": cfg.requirements.path},
        # Preserve db_path from the file — it is a deployment setting, not a
        # user-editable field exposed through the Settings UI.
        "storage": {
            "db_path": existing_storage.get("db_path", "data/agent_os.db"),
        },
        "api": {"host": cfg.api.host, "port": cfg.api.port},
        # Preserve budget from the file so the user's manual edits survive.
        "budget": {
            "token_budget_per_module": existing_budget.get(
                "token_budget_per_module", cfg.budget.token_budget_per_module
            ),
            "alert_threshold_pct": existing_budget.get(
                "alert_threshold_pct", cfg.budget.alert_threshold_pct
            ),
            "pause_at_limit": existing_budget.get(
                "pause_at_limit", cfg.budget.pause_at_limit
            ),
            "cost_per_1k_tokens": existing_budget.get(
                "cost_per_1k_tokens", cfg.budget.cost_per_1k_tokens
            ),
        },
        "dependencies": {
            "auto_create_venv": cfg.dependencies.auto_create_venv,
            "auto_install": cfg.dependencies.auto_install,
            "venv_name": cfg.dependencies.venv_name,
        },
        "error_handling": {
            "max_json_retries": cfg.error_handling.max_json_retries,
            "retry_backoff_base": cfg.error_handling.retry_backoff_base,
            "retry_backoff_max": cfg.error_handling.retry_backoff_max,
            "rollback_on_failure": cfg.error_handling.rollback_on_failure,
            "skip_failed_validators": cfg.error_handling.skip_failed_validators,
        },
        "github": {
            "owner": cfg.github.owner,
            "repo": cfg.github.repo,
            "auto_push": cfg.github.auto_push,
            "auto_create_pr": cfg.github.auto_create_pr,
        },
        "secrets": {
            "openai_api_key": "",
            "github_token": "",
        },
    }

    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
