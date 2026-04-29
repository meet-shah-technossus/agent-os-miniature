"""Database connection and schema initialization."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

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
    module_id TEXT NOT NULL,
    iteration_number INTEGER NOT NULL,
    status TEXT DEFAULT 'in_progress',
    prompt_path TEXT DEFAULT '',
    prompt_content TEXT DEFAULT '',
    review_json_path TEXT DEFAULT '',
    review_content TEXT DEFAULT '',
    summary_path TEXT DEFAULT '',
    token_usage INTEGER DEFAULT 0,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (module_id) REFERENCES modules(id),
    UNIQUE(module_id, iteration_number)
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
    current_module_id TEXT,
    current_iteration INTEGER DEFAULT 0,
    pipeline_status TEXT DEFAULT 'IDLE',
    last_checkpoint TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
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
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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
        self.conn.executescript(_SCHEMA_SQL)
        # Migrate existing DBs: add columns if missing
        self._migrate_add_column("modules", "definition_json", "TEXT DEFAULT ''")
        self._migrate_add_column("iterations", "prompt_content", "TEXT DEFAULT ''")
        self._migrate_add_column("iterations", "review_content", "TEXT DEFAULT ''")
        self.conn.execute(
            """INSERT OR IGNORE INTO pipeline_state (id, current_module_id, current_iteration,
               pipeline_status, last_checkpoint, metadata) VALUES (1, NULL, 0, 'IDLE', ?, '{}')""",
            (datetime.utcnow().isoformat(),),
        )
        self.conn.commit()

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

    def get_all_modules(self):
        from .module_repo import ModuleRepository
        return ModuleRepository(self.conn).get_all()

    def get_module(self, module_id: str):
        from .module_repo import ModuleRepository
        return ModuleRepository(self.conn).get(module_id)

    def upsert_module(self, module):
        from .module_repo import ModuleRepository
        ModuleRepository(self.conn).upsert(module)

    def update_module_status(self, module_id: str, status):
        from .module_repo import ModuleRepository
        ModuleRepository(self.conn).update_status(module_id, status)
