"""Data models for Agent OS persistence layer."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- Enums ---

class PipelineStatus(str, Enum):
    IDLE = "IDLE"
    LOADING_REQUIREMENTS = "LOADING_REQUIREMENTS"
    MODULE_PLANNING = "MODULE_PLANNING"
    HITL_1_MODULE_REVIEW = "HITL_1_MODULE_REVIEW"
    PROMPT_GENERATION = "PROMPT_GENERATION"
    HITL_2_PROMPT_REVIEW = "HITL_2_PROMPT_REVIEW"
    CODE_GENERATION = "CODE_GENERATION"
    VALIDATION = "VALIDATION"
    CODE_REVIEW = "CODE_REVIEW"
    HITL_3_REVIEW_DECISION = "HITL_3_REVIEW_DECISION"
    DECISION = "DECISION"
    GIT_COMMIT = "GIT_COMMIT"
    MODULE_COMPLETE = "MODULE_COMPLETE"
    HITL_4_MAX_ITERATIONS = "HITL_4_MAX_ITERATIONS"
    HITL_5_PR_REVIEW = "HITL_5_PR_REVIEW"
    INTEGRATION_TEST = "INTEGRATION_TEST"
    NEXT_MODULE = "NEXT_MODULE"
    PIPELINE_COMPLETE = "PIPELINE_COMPLETE"
    FAILED = "FAILED"


class ModuleStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IterationStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class RequirementType(str, Enum):
    EPIC = "epic"
    FEATURE = "feature"
    STORY = "story"
    ACCEPTANCE_CRITERIA = "ac"


# --- Models ---

class ModuleRecord(BaseModel):
    id: str
    name: str
    feature_name: str = ""
    status: ModuleStatus = ModuleStatus.PENDING
    dependency_ids: list[str] = Field(default_factory=list)
    version: int = 1
    execution_order: int = 0
    definition_json: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class IterationRecord(BaseModel):
    id: Optional[int] = None
    module_id: str
    iteration_number: int
    status: IterationStatus = IterationStatus.IN_PROGRESS
    prompt_path: str = ""
    prompt_content: str = ""
    review_json_path: str = ""
    review_content: str = ""
    summary_path: str = ""
    token_usage: int = 0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class RequirementRecord(BaseModel):
    id: str
    type: RequirementType
    parent_id: Optional[str] = None
    title: str
    description: str = ""
    status: str = "active"


class PipelineState(BaseModel):
    current_module_id: Optional[str] = None
    current_iteration: int = 0
    pipeline_status: PipelineStatus = PipelineStatus.IDLE
    last_checkpoint: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
