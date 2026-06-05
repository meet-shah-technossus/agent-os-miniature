"""Protocol definitions for Agent OS dependency injection.

These protocols enable:
1. Mocking in tests without monkey-patching
2. Future implementation swaps (e.g. different DB backends)
3. Structural typing — existing classes already satisfy these protocols
"""
from __future__ import annotations

import sqlite3
from typing import Any, Callable, Optional, Protocol, runtime_checkable
from pathlib import Path


@runtime_checkable
class DatabaseProtocol(Protocol):
    """Database access protocol."""

    @property
    def conn(self) -> sqlite3.Connection: ...

    def connect(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class StateManagerProtocol(Protocol):
    """Pipeline state management protocol."""

    @property
    def state(self) -> Any: ...

    @property
    def current_status(self) -> Any: ...

    def transition_to(self, status: Any, **kwargs: Any) -> None: ...

    def reset(self) -> Any: ...

    def update_metadata(self, metadata: dict[str, Any]) -> None: ...

    def on_transition(self, listener: Callable[..., Any]) -> None: ...

    def is_hitl_gate(self) -> bool: ...


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """Event broadcasting protocol."""

    def emit(self, event_type: str, data: dict[str, Any]) -> None: ...

    def emit_terminal(self, event: str, agent: str, session_id: str, **kwargs: Any) -> None: ...


@runtime_checkable
class CodeGeneratorProtocol(Protocol):
    """Code generation protocol."""

    def run(
        self,
        prompt_path: str | Path,
        working_dir: str | Path,
        iteration: int = 1,
        pr_number: Optional[int] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        story_context: Optional[dict[str, Any]] = None,
    ) -> Any: ...


@runtime_checkable
class CodeReviewerProtocol(Protocol):
    """Code review protocol."""

    def run(
        self,
        pr_number: int,
        iteration: int,
        feature_branch: Optional[str] = None,
        on_stdout: Optional[Callable[[str], None]] = None,
        story_context: Optional[dict[str, Any]] = None,
    ) -> Any: ...


@runtime_checkable
class VCSClientProtocol(Protocol):
    """Version control system protocol."""

    def create_pr(self, title: str, body: str, head: str, base: str) -> Any: ...

    def get_diff(self, pr_number: int) -> str: ...

    def post_comment(self, pr_number: int, body: str) -> None: ...


@runtime_checkable
class SubprocessRunnerProtocol(Protocol):
    """Subprocess execution protocol (enables mocking)."""

    def run(self, cmd: list[str], **kwargs: Any) -> Any: ...
