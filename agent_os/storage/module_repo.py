"""Module repository — CRUD for the modules table."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Optional

from .models import ModuleRecord, ModuleStatus


class ModuleRepository:
    """Module persistence operations."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, module: ModuleRecord) -> None:
        self._conn.execute(
            """INSERT INTO modules (id, name, feature_name, status, dependency_ids,
               version, execution_order, definition_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, feature_name=excluded.feature_name,
               status=excluded.status, dependency_ids=excluded.dependency_ids,
               version=excluded.version, execution_order=excluded.execution_order,
               definition_json=excluded.definition_json,
               updated_at=excluded.updated_at""",
            (
                module.id,
                module.name,
                module.feature_name,
                module.status.value,
                json.dumps(module.dependency_ids),
                module.version,
                module.execution_order,
                module.definition_json,
                module.created_at.isoformat(),
                datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def get(self, module_id: str) -> Optional[ModuleRecord]:
        row = self._conn.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
        if not row:
            return None
        return self._row_to_record(row)

    def get_all(self) -> list[ModuleRecord]:
        rows = self._conn.execute("SELECT * FROM modules ORDER BY execution_order").fetchall()
        return [self._row_to_record(r) for r in rows]

    def update_status(self, module_id: str, status: ModuleStatus) -> None:
        self._conn.execute(
            "UPDATE modules SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, datetime.utcnow().isoformat(), module_id),
        )
        self._conn.commit()

    def delete_all(self) -> int:
        """Delete all module records (and their child iterations). Returns rows deleted."""
        self._conn.execute("DELETE FROM iterations")
        cursor = self._conn.execute("DELETE FROM modules")
        self._conn.commit()
        return cursor.rowcount

    @staticmethod
    def _row_to_record(row) -> ModuleRecord:
        return ModuleRecord(
            id=row["id"],
            name=row["name"],
            feature_name=row["feature_name"],
            status=ModuleStatus(row["status"]),
            dependency_ids=json.loads(row["dependency_ids"]),
            version=row["version"],
            execution_order=row["execution_order"],
            definition_json=row["definition_json"] if "definition_json" in row.keys() else "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
