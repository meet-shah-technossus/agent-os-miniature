"""Configuration schema — Pydantic models for Agent OS config."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class PromptFramework(str, Enum):
    RCTCF = "RCTCF"
    RISEN = "RISEN"
    COSTAR = "COSTAR"
    CUSTOM = "CUSTOM"


class ConvergenceRule(str, Enum):
    NO_HIGH_SEVERITY = "no_high_severity"
    NO_CRITICAL = "no_critical"
    ALL_ACCEPTED = "all_accepted"


class ProjectConfig(BaseModel):
    name: str = ""
    root_path: str = ""
    language: str = "python"


class OrchestratorConfig(BaseModel):
    max_iterations_per_module: int = Field(default=5, ge=1, le=20)
    auto_approve_hitl: bool = False
    hitl_timeout_seconds: int = Field(default=0, ge=0)
    convergence_rule: ConvergenceRule = ConvergenceRule.NO_HIGH_SEVERITY


class CodexConfig(BaseModel):
    model: str = "codex"
    timeout_seconds: int = Field(default=300, ge=30)
    max_retries: int = Field(default=2, ge=0, le=5)
    model_routing: dict[str, str] = Field(default_factory=lambda: {
        "MODULE_MAKER": "gpt-4.1-mini",
        "PROMPT_GENERATOR": "gpt-4.1-mini",
        "CODE_GENERATOR": "gpt-4.1",
        "CODE_REVIEWER": "gpt-4.1-mini",
    })


class GitConfig(BaseModel):
    enabled: bool = True
    remote: str = "origin"
    main_branch: str = "main"
    dev_branch: str = "dev"
    auto_create_feature_branches: bool = True


class ValidationConfig(BaseModel):
    lint: bool = True
    type_check: bool = True
    tests: bool = True
    security_scan: bool = True


class StorageConfig(BaseModel):
    db_path: str = "data/agent_os.db"

    @property
    def data_dir(self) -> "Path":
        """Return the absolute path to the data directory (parent of db_path)."""
        from pathlib import Path
        return Path(self.db_path).resolve().parent


class RequirementsConfig(BaseModel):
    path: str = "requirements.yaml"


class ApiConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1024, le=65535)


class BudgetConfig(BaseModel):
    token_budget_per_module: int = Field(default=20_000, ge=0)
    alert_threshold_pct: int = Field(default=80, ge=0, le=100)
    pause_at_limit: bool = True
    cost_per_1k_tokens: float = Field(default=0.01, ge=0)


class DependencyConfig(BaseModel):
    auto_create_venv: bool = True
    auto_install: bool = True
    venv_name: str = ".venv"


class ErrorHandlingConfig(BaseModel):
    max_json_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_base: float = Field(default=1.0, ge=0.1, le=30.0)
    retry_backoff_max: float = Field(default=30.0, ge=1.0, le=300.0)
    rollback_on_failure: bool = True
    skip_failed_validators: bool = True


class GitHubConfig(BaseModel):
    owner: str = ""
    repo: str = ""
    auto_push: bool = False
    auto_create_pr: bool = False


class SecretsConfig(BaseModel):
    openai_api_key: str = ""
    github_token: str = ""


class GitHubInputConfig(BaseModel):
    """Phase 5 — existing GitHub repo as read-only context for Module Maker."""

    enabled: bool = False
    source_repo_url: str = ""
    clone_depth: int = Field(default=1, ge=1, le=100)
    include_file_patterns: list[str] = Field(
        default_factory=lambda: ["**/*.py", "**/*.ts", "README.md"]
    )
    exclude_patterns: list[str] = Field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/.git/**",
            "**/__pycache__/**",
        ]
    )
    max_context_files: int = Field(default=50, ge=1, le=500)
    new_repo_suffix: str = "-agent-os-fork"


class AgentOSConfig(BaseModel):
    project: ProjectConfig = ProjectConfig()
    orchestrator: OrchestratorConfig = OrchestratorConfig()
    codex: CodexConfig = CodexConfig()
    prompt_framework: PromptFramework = PromptFramework.RCTCF
    git: GitConfig = GitConfig()
    validation: ValidationConfig = ValidationConfig()
    storage: StorageConfig = StorageConfig()
    requirements: RequirementsConfig = RequirementsConfig()
    api: ApiConfig = ApiConfig()
    budget: BudgetConfig = BudgetConfig()
    dependencies: DependencyConfig = DependencyConfig()
    error_handling: ErrorHandlingConfig = ErrorHandlingConfig()
    github: GitHubConfig = GitHubConfig()
    secrets: SecretsConfig = SecretsConfig()
    github_input: GitHubInputConfig = GitHubInputConfig()

    @field_validator("project")
    @classmethod
    def validate_project(cls, v: ProjectConfig) -> ProjectConfig:
        if v.root_path:
            path = Path(v.root_path).expanduser().resolve()
            v.root_path = str(path)
        return v

    @field_validator("storage")
    @classmethod
    def validate_storage(cls, v: StorageConfig) -> StorageConfig:
        db_dir = Path(v.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        return v
