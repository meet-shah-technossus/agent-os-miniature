"""Response schemas for the Agent OS API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class PipelineStatusResponse(BaseModel):
    pipeline_status: str
    current_module_id: Optional[str] = None
    current_iteration: int = 0
    last_checkpoint: datetime
    metadata: dict[str, Any] = {}
    is_hitl_gate: bool = False
    total_modules: int = 0


class ModuleResponse(BaseModel):
    id: str
    name: str
    feature_name: str
    status: str
    dependency_ids: list[str] = []
    version: int = 1
    execution_order: int = 0
    created_at: datetime
    updated_at: datetime
    pr_number: Optional[int] = None
    pr_url: str = ""


class IterationResponse(BaseModel):
    id: Optional[int] = None
    module_id: str
    iteration_number: int
    status: str
    prompt_path: str = ""
    review_json_path: str = ""
    summary_path: str = ""
    token_usage: int = 0
    started_at: datetime
    completed_at: Optional[datetime] = None


class RequirementResponse(BaseModel):
    id: str
    type: str
    parent_id: Optional[str] = None
    title: str
    description: str = ""
    status: str = "active"


class ApproveGateRequest(BaseModel):
    gate: Optional[str] = None


class ApproveGateResponse(BaseModel):
    approved: bool
    message: str


class BusMessageResponse(BaseModel):
    channel: str
    sender: str
    timestamp: datetime
    module_id: Optional[str] = None
    iteration: int = 0
    correlation_id: str = ""
    payload: dict[str, Any] = {}


class MetricsResponse(BaseModel):
    total_modules: int = 0
    completed_modules: int = 0
    failed_modules: int = 0
    total_iterations: int = 0
    total_token_usage: int = 0
    pipeline_status: str = "idle"
    total_cost: float = 0.0
    budget_per_module: int = 0


class ModuleBudgetResponse(BaseModel):
    module_id: str
    tokens_used: int = 0
    token_budget: int = 0
    usage_pct: float = 0.0
    cost: float = 0.0
    status: str = "ok"


# ── Settings schemas ──────────────────────────────────────────────


class SecretsSettingsResponse(BaseModel):
    openai_api_key: str = ""
    github_token: str = ""


class GitHubSettingsResponse(BaseModel):
    owner: str = ""
    repo: str = ""
    auto_push: bool = False
    auto_create_pr: bool = False


class ProjectSettingsResponse(BaseModel):
    name: str = ""
    root_path: str = ""
    language: str = "python"


class PipelineSettingsResponse(BaseModel):
    max_iterations_per_module: int = 5
    convergence_rule: str = "no_high_severity"
    auto_approve_hitl: bool = False


class SettingsResponse(BaseModel):
    secrets: SecretsSettingsResponse = SecretsSettingsResponse()
    github: GitHubSettingsResponse = GitHubSettingsResponse()
    project: ProjectSettingsResponse = ProjectSettingsResponse()
    pipeline: PipelineSettingsResponse = PipelineSettingsResponse()


class SettingsUpdateRequest(BaseModel):
    secrets: Optional[SecretsSettingsResponse] = None
    github: Optional[GitHubSettingsResponse] = None
    project: Optional[ProjectSettingsResponse] = None
    pipeline: Optional[PipelineSettingsResponse] = None


class TestGitHubResponse(BaseModel):
    valid: bool
    user: str = ""
    message: str = ""
