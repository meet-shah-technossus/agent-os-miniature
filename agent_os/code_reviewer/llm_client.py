"""LLM client abstraction for code review — extracted from CodeReviewerRunner (Phase 11.1).

Provides a ReviewLLMClient protocol and concrete implementations for:
  - OpenAI API (default)
  - GitHub Copilot (models.inference.ai.azure.com)
  - Ollama (local/remote)
"""
from __future__ import annotations

import logging
import os
from typing import Callable

from ..constants import (
    COPILOT_API_BASE,
    COPILOT_EDITOR_VERSION,
    COPILOT_INTEGRATION_ID,
    NO_TEMPERATURE_MODELS,
)

logger = logging.getLogger(__name__)


def stream_review(
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    system_prompt: str,
    user_message: str,
    emit: Callable[[str], None],
) -> str:
    """Stream a review from the LLM and return the full raw text.

    Args:
        provider:      One of "openai", "copilot", "ollama".
        model:         Model name to pass to the API.
        api_key:       API key / token.
        base_url:      API base URL.
        system_prompt: System prompt for the review.
        user_message:  User message (includes diff).
        emit:          Line-by-line streaming callback.

    Returns:
        Full raw text response from the LLM.
    """
    import openai

    extra_headers = {}
    if provider == "copilot":
        extra_headers = {
            "Copilot-Integration-Id": COPILOT_INTEGRATION_ID,
            "Editor-Version": COPILOT_EDITOR_VERSION,
            "Editor-Plugin-Version": COPILOT_EDITOR_VERSION,
        }

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        default_headers=extra_headers,
    )

    create_kwargs: dict = {
        "model": model,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    }
    if not any(model.startswith(p) for p in NO_TEMPERATURE_MODELS):
        create_kwargs["temperature"] = 0.2

    resp = client.chat.completions.create(**create_kwargs)

    full: list[str] = []
    buf: list[str] = []
    for chunk in resp:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content  # type: ignore[union-attr]
        if not delta:
            continue
        full.append(delta)
        buf.append(delta)
        combined = "".join(buf)
        while "\n" in combined:
            line, combined = combined.split("\n", 1)
            emit(line)
        buf = [combined] if combined else []
    if buf:
        rem = "".join(buf).strip()
        if rem:
            emit(rem)

    return "".join(full).strip()


def resolve_provider_config(
    config,
    code_reviewer_config,
    emit: Callable[[str], None],
) -> tuple[str, str, str, str]:
    """Resolve LLM provider settings from config.

    Returns:
        Tuple of (provider, base_url, api_key, model).
        If credentials are missing, returns empty api_key (caller should abort).
    """
    provider = (code_reviewer_config.provider if code_reviewer_config else None) or "openai"

    if provider == "copilot":
        base_url = COPILOT_API_BASE
        from ..services.auth_service import get_copilot_token
        _config_token = (
            (getattr(getattr(config, "ai_tools", None), "copilot", None)
                and config.ai_tools.copilot.api_key)
            or getattr(config.secrets, "github_token", "")
            or ""
        )
        api_key = get_copilot_token(config_token=_config_token)
        model = (code_reviewer_config.model if code_reviewer_config else "") or "gpt-4.1-mini"
        if not api_key:
            emit("[code-reviewer] No GITHUB_TOKEN — cannot run Copilot review")

    elif provider == "ollama":
        ollama_base = (
            getattr(config.ollama, "base_url", "") or "http://localhost:11434"
        )
        base_url = ollama_base.rstrip("/") + "/v1"
        api_key = "ollama"
        model = (code_reviewer_config.ollama_model if code_reviewer_config else "") or (
            getattr(config.ollama, "model", "") or "llama3.1:8b"
        )

    elif provider == "groq":
        base_url = "https://api.groq.com/openai/v1"
        api_key = (
            getattr(getattr(config, "groq", None), "api_key", "")
            or os.environ.get("GROQ_API_KEY", "")
        )
        model = (
            getattr(code_reviewer_config, "groq_model", "") if code_reviewer_config else ""
        ) or "llama-3.3-70b-versatile"
        if not api_key:
            emit("[code-reviewer] No GROQ_API_KEY — cannot run Groq review")

    else:  # "openai" (default)
        base_url = "https://api.openai.com/v1"
        api_key = (
            getattr(config.secrets, "openai_api_key", "") or ""
            or os.environ.get("OPENAI_API_KEY", "")
        )
        model = (
            (code_reviewer_config.model if code_reviewer_config else "")
            or config.codex.model_routing.get("CODE_REVIEWER")
            or config.codex.model
            or "gpt-4.1-mini"
        )
        if not api_key:
            emit("[code-reviewer] No OpenAI API key — cannot run review")

    return provider, base_url, api_key, model
