"""Centralized constants for the Agent OS codebase.

All magic strings and magic numbers throughout the codebase must be imported
from this module. Never repeat literals that are defined here.
"""
from __future__ import annotations

from enum import StrEnum

# ─── Pipeline Modes ──────────────────────────────────────────────────────────

class PipelineMode(StrEnum):
    STANDARD = "standard"
    GITHUB_REVIEW = "github_review"


# ─── Event Channels ──────────────────────────────────────────────────────────

class EventChannel(StrEnum):
    PIPELINE = "pipeline"
    REVIEW = "review"
    TERMINAL_PROMPT_GEN = "terminal:prompt_generator"
    TERMINAL_CODE_GEN = "terminal:code_generator"
    TERMINAL_CODE_REVIEW = "terminal:code_reviewer"


# ─── Event Types ─────────────────────────────────────────────────────────────

class EventType(StrEnum):
    RUN_STARTED = "run_started"
    STATE_CHANGED = "state_changed"
    LOADING_REQUIREMENTS = "loading_requirements"
    PROMPT_GENERATION_STARTED = "prompt_generation_started"
    PROMPT_GENERATION_COMPLETE = "prompt_generation_complete"
    PROMPT_TOKEN = "prompt_token"
    PROMPT_GEN_FAILED = "prompt_gen_failed"
    HITL_GATE = "hitl_gate"
    CODE_GENERATION_STARTED = "code_generation_started"
    CODE_GENERATION_COMPLETE = "code_generation_complete"
    CODEX_STDOUT = "codex_stdout"
    CODEX_STDERR = "codex_stderr"
    CODE_GEN_FAILED = "code_gen_failed"
    CODE_GEN_STOPPED = "code_gen_stopped"
    CODE_REVIEW_STARTED = "code_review_started"
    CODE_REVIEW_COMPLETE = "code_review_complete"
    PIPELINE_COMPLETE = "pipeline_complete"
    FAILED = "failed"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


# ─── Terminal Session Events ─────────────────────────────────────────────────

class TerminalEvent(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TOKEN = "token"
    LINE = "line"


# ─── Agent Names ─────────────────────────────────────────────────────────────

class AgentName(StrEnum):
    ORCHESTRATOR = "orchestrator"
    PROMPT_GENERATOR = "PROMPT_GENERATOR"
    CODE_GENERATOR = "CODE_GENERATOR"
    CODE_REVIEWER = "CODE_REVIEWER"


# ─── Git Constants ───────────────────────────────────────────────────────────

GIT_AUTHOR_NAME = "Agent OS Bot"
GIT_AUTHOR_EMAIL = "agent-os@noreply.github.com"
GIT_COMMIT_PREFIX = "[agent-os]"
SLUG_MAX_LENGTH = 60

# ─── Timeouts (seconds) ──────────────────────────────────────────────────────

DEFAULT_CODEX_TIMEOUT = 300
DEFAULT_MAX_RETRIES = 2
GH_CLI_TIMEOUT = 5
SQLITE_CONNECT_TIMEOUT = 30
SQLITE_BUSY_TIMEOUT_MS = 30_000
PTY_ROWS = 40
PTY_COLS = 120

# ─── Limits ──────────────────────────────────────────────────────────────────

FILE_LINE_LIMIT = 200
DIFF_CHAR_LIMIT = 50_000
WS_QUEUE_MAXSIZE = 1000
WS_MESSAGE_HISTORY = 500

# ─── Code Review Score Thresholds ────────────────────────────────────────────

REVIEW_SCORE_APPROVED = 80
REVIEW_SCORE_CONDITIONAL = 70
REVIEW_SCORE_REJECTED = 40

# ─── Default Gitignore Patterns ──────────────────────────────────────────────

DEFAULT_GITIGNORE_PATTERNS: tuple[str, ...] = (
    "__pycache__/",
    "*.pyc",
    "*.pyo",
    ".env",
    ".venv/",
    "venv/",
    "node_modules/",
    ".next/",
    "dist/",
    "build/",
    ".DS_Store",
    "Thumbs.db",
    "*.log",
    ".idea/",
    ".vscode/",
    "*.swp",
    "*.swo",
    "*.egg-info/",
    ".pytest_cache/",
)

# ─── Git Cleanup Patterns ────────────────────────────────────────────────────

GIT_CLEANUP_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "__pycache__",
    ".DS_Store",
)

# ─── Project Naming ──────────────────────────────────────────────────────────

PROJECT_NAME_STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
    "for", "of", "with", "by", "from", "as", "is", "was", "are",
    "were", "be", "been", "being", "have", "has", "had", "do",
    "does", "did", "will", "would", "could", "should", "may",
    "might", "shall", "can", "need", "must", "it", "its", "this",
    "that", "these", "those", "i", "we", "you", "they", "he",
    "she", "my", "our", "your", "their",
})

# ─── Code Reviewer ───────────────────────────────────────────────────────────

CODE_REVIEWER_LOG_PREFIX = "[code-reviewer]"
NO_TEMPERATURE_MODELS: frozenset[str] = frozenset({
    "o1-preview",
    "o1-mini",
    "o1",
    "o3-mini",
})

# ─── Copilot API ─────────────────────────────────────────────────────────────

COPILOT_API_BASE = "https://api.githubcopilot.com"
COPILOT_INTEGRATION_ID = "agent-os"
COPILOT_EDITOR_VERSION = "agent-os/1.0"
