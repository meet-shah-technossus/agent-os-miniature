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
    PROMPT_GENERATION = "PROMPT_GENERATION"
    HITL_PROMPT_REVIEW = "HITL_PROMPT_REVIEW"
    CODE_GENERATION = "CODE_GENERATION"
    CODE_GEN_FAILED = "CODE_GEN_FAILED"
    CODE_REVIEW = "CODE_REVIEW"
    HITL_REVIEW_DECISION = "HITL_REVIEW_DECISION"
    PIPELINE_COMPLETE = "PIPELINE_COMPLETE"
    FAILED = "FAILED"


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

class IterationRecord(BaseModel):
    id: Optional[int] = None
    iteration_number: int
    status: IterationStatus = IterationStatus.IN_PROGRESS
    prompt_path: str = ""
    prompt_content: str = ""
    review_json_path: str = ""
    review_json_content: str = ""
    summary_path: str = ""
    token_usage: int = 0
    cli_tool_used: str = ""
    ci_result: str = ""  # "pass" | "fail" | ""
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
    current_iteration: int = 0
    pipeline_status: PipelineStatus = PipelineStatus.IDLE
    last_checkpoint: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)
