"""Pipeline state repository — CRUD for the singleton pipeline_state row."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .models import PipelineState, PipelineStatus


class PipelineRepository:
    """Pipeline state persistence (singleton row with id=1)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_state(self) -> PipelineState:
        row = self._conn.execute("SELECT * FROM pipeline_state WHERE id = 1").fetchone()
        return PipelineState(
            current_module_id=row["current_module_id"],
            current_iteration=row["current_iteration"],
            pipeline_status=PipelineStatus(row["pipeline_status"]),
            last_checkpoint=datetime.fromisoformat(row["last_checkpoint"]),
            metadata=json.loads(row["metadata"]),
        )

    def save_state(self, state: PipelineState) -> None:
        self._conn.execute(
            """UPDATE pipeline_state SET
               current_module_id = ?, current_iteration = ?, pipeline_status = ?,
               last_checkpoint = ?, metadata = ? WHERE id = 1""",
            (
                state.current_module_id,
                state.current_iteration,
                state.pipeline_status.value,
                datetime.utcnow().isoformat(),
                json.dumps(state.metadata),
            ),
        )
        self._conn.commit()
