"""Database connection and schema initialization."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

# Serialises schema initialisation across all threads to prevent
# concurrent DDL/INSERT races that produce "database is locked" errors.
_schema_init_lock = threading.Lock()
# Tracks which DB paths have already been fully initialised.
_initialised_db_paths: set[str] = set()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS modules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    feature_name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    dependency_ids TEXT DEFAULT '[]',
    version INTEGER DEFAULT 1,
    execution_order INTEGER DEFAULT 0,
    definition_json TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS iterations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_number INTEGER NOT NULL,
    status TEXT DEFAULT 'in_progress',
    prompt_path TEXT DEFAULT '',
    prompt_content TEXT DEFAULT '',
    review_json_path TEXT DEFAULT '',
    review_json_content TEXT DEFAULT '',
    summary_path TEXT DEFAULT '',
    token_usage INTEGER DEFAULT 0,
    cli_tool_used TEXT DEFAULT '',
    ci_result TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    parent_id TEXT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS pipeline_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_iteration INTEGER DEFAULT 0,
    pipeline_status TEXT DEFAULT 'IDLE',
    last_checkpoint TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_files (
    agent_name TEXT NOT NULL,
    file_name TEXT NOT NULL,
    content TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (agent_name, file_name)
);
"""


class Database:
    """SQLite database manager for Agent OS.

    Provides the connection and schema init. CRUD operations are in
    dedicated repository modules (module_repo, iteration_repo, etc.).
    Also provides backward-compatible convenience methods that delegate
    to the repositories.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _new_conn(self) -> sqlite3.Connection:
        """Create a new SQLite connection for the calling thread."""
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Tell SQLite to retry busy/locked writes for up to 30 s before raising.
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def connect(self) -> None:
        self._local.conn = self._new_conn()
        self._init_schema()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # Auto-connect for threads that didn't call connect() (e.g. FastAPI worker threads).
            conn = self._new_conn()
            self._local.conn = conn
            self._init_schema()
        return conn

    def _init_schema(self) -> None:
        path_key = str(self._db_path)
        # Fast path: already initialised in a previous call from this process.
        if path_key in _initialised_db_paths:
            return
        with _schema_init_lock:
            # Double-checked: another thread may have finished while we waited.
            if path_key in _initialised_db_paths:
                return
            self.conn.executescript(_SCHEMA_SQL)
            # Migrate existing DBs: add columns if missing
            self._migrate_add_column("modules", "definition_json", "TEXT DEFAULT ''")
            self._migrate_add_column("iterations", "prompt_content", "TEXT DEFAULT ''")
            self._migrate_add_column("iterations", "review_json_content", "TEXT DEFAULT ''")
            self._migrate_add_column("iterations", "cli_tool_used", "TEXT DEFAULT ''")
            self._migrate_add_column("iterations", "ci_result", "TEXT DEFAULT ''")
            self._migrate_add_column("iterations", "ci_output", "TEXT DEFAULT ''")
            self.conn.execute(
                """INSERT OR IGNORE INTO pipeline_state (id, current_iteration,
                   pipeline_status, last_checkpoint, metadata) VALUES (1, 0, 'IDLE', ?, '{}')""",
                (datetime.utcnow().isoformat(),),
            )
            self.conn.commit()
            _initialised_db_paths.add(path_key)

    def _migrate_add_column(self, table: str, column: str, col_type: str) -> None:
        """Add a column if it doesn't already exist (safe migration)."""
        cols = [row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            self.conn.commit()

    # --- Convenience delegates (backward compat with Phase 1 callers) ---

    def get_pipeline_state(self):
        from .pipeline_repo import PipelineRepository
        return PipelineRepository(self.conn).get_state()

    def save_pipeline_state(self, state):
        from .pipeline_repo import PipelineRepository
        PipelineRepository(self.conn).save_state(state)

    def clear_run_data(self) -> None:
        """Delete all iteration rows and reset pipeline_state to IDLE.

        Called by the orchestrator reset() so that Projects, Code Insights,
        and Git History pages reflect a clean slate for the next run.
        """
        with self.conn:
            self.conn.execute("DELETE FROM iterations")
            self.conn.execute(
                "UPDATE pipeline_state SET "
                "current_iteration = 0, pipeline_status = 'IDLE', "
                "last_checkpoint = ?, metadata = '{}' "
                "WHERE id = 1",
                (datetime.utcnow().isoformat(),),
            )

    # module_repo methods removed in Phase 1 (module_maker deleted)
