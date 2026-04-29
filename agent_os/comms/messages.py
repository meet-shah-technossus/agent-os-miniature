"""Message types for the Agent Communication Bus."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from .channels import Channel


class AgentMessage(BaseModel):
    """Base message for all agent-to-agent communication."""
    channel: Channel
    sender: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    module_id: Optional[str] = None
    iteration: int = 0
    correlation_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ModuleUpdateMessage(AgentMessage):
    channel: Channel = Channel.MODULE_UPDATES


class PromptReadyMessage(AgentMessage):
    channel: Channel = Channel.PROMPT_READY


class GenerationStatusMessage(AgentMessage):
    channel: Channel = Channel.GENERATION_STATUS


class ValidationResultMessage(AgentMessage):
    channel: Channel = Channel.VALIDATION_RESULTS


class ReviewFeedbackMessage(AgentMessage):
    channel: Channel = Channel.REVIEW_FEEDBACK


class HITLRequestMessage(AgentMessage):
    channel: Channel = Channel.HITL_REQUESTS


class HITLResponseMessage(AgentMessage):
    channel: Channel = Channel.HITL_RESPONSES


class PipelineEventMessage(AgentMessage):
    channel: Channel = Channel.PIPELINE_EVENTS


class ErrorAlertMessage(AgentMessage):
    channel: Channel = Channel.ERROR_ALERTS


class HeartbeatMessage(AgentMessage):
    channel: Channel = Channel.AGENT_HEARTBEATS
