"""Channel definitions for the Agent Communication Bus."""

from __future__ import annotations

from enum import Enum


class Channel(str, Enum):
    """All communication channels between agents."""
    MODULE_UPDATES = "module_updates"
    PROMPT_READY = "prompt_ready"
    GENERATION_STATUS = "generation_status"
    VALIDATION_RESULTS = "validation_results"
    REVIEW_FEEDBACK = "review_feedback"
    HITL_REQUESTS = "hitl_requests"
    HITL_RESPONSES = "hitl_responses"
    PIPELINE_EVENTS = "pipeline_events"
    ERROR_ALERTS = "error_alerts"
    AGENT_HEARTBEATS = "agent_heartbeats"
    # Phase 4 — dedicated raw terminal output stream (stdout/stderr from Codex)
    TERMINAL_OUTPUT = "terminal_output"
