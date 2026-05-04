"""Module Maker runner — decomposes requirements into module definitions.

Builds a prompt from stored requirements, invokes the Codex CLI,
parses the JSON output, validates and stores modules.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..codex.session import SessionType
from ..codex.wrapper import CodexWrapper
from ..config.schema import AgentOSConfig
from ..storage.database import Database
from ..storage.models import ModuleRecord, RequirementType
from ..storage.module_repo import ModuleRepository
from ..storage.requirement_repo import RequirementRepository
from .dependency_graph import build_execution_order, validate_no_cycles
from .schema import ModuleDefinition, ModulePlan

from typing import Callable

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a principal software architect creating an exhaustive, implementation-ready \
module decomposition. Your output is the SOLE blueprint that a code generator will use — \
it must contain every detail needed to write production code with ZERO ambiguity.

# Project Details
- Language: {language}
- Project name: {project_name}
- Project root: {project_root}

# Requirements
{requirements_text}

# Instructions

Produce a JSON object with TWO top-level keys:

1. `"project_folder_structure"`: A complete list of every directory and file path in the \
final project (e.g. `["src/", "src/main.py", "src/models/", "src/models/task.py", ...]`).

2. `"modules"`: An array where each element is a module object with ALL of the following \
fields filled in exhaustively.

**IMPORTANT — Module 0 (Foundation):**
You MUST generate a `"mod-0"` module as the FIRST module in the array with:
- `module_id`: `"mod-0"`
- `name`: `"Foundation"`
- `feature_name`: `"shared-infrastructure"`
- `dependencies`: `[]` (no dependencies)
- DETAILED `description` of all shared infrastructure it creates.
- DETAILED `technical_spec` with exact steps: directory creation, database connection \
factory, base models, configuration loading, logging, middleware, error handlers.
- Complete `folder_structure` listing EVERY directory in the project.
- Complete `file_paths` for all files it creates.
- `testing_notes` with named test cases.
- `constraints` listing edge cases.
- ALL dependent modules must include `"mod-0"` in their `dependencies` array.

## Required fields per module

| Field | Type | What to include |
|---|---|---|
| `module_id` | string | Sequential: "mod-0", "mod-1", "mod-2", ... |
| `name` | string | Descriptive name |
| `feature_name` | string | Which feature/epic this belongs to |
| `description` | string | 3-5 sentence detailed description of what this module does, \
its responsibilities, and how it fits into the overall system |
| `technical_spec` | string | Numbered step-by-step implementation plan. Include exact \
library imports, design patterns, error handling approach, and edge cases to handle. \
This must be detailed enough that a developer can implement without asking questions. |
| `folder_structure` | list[str] | Directories this module creates or uses |
| `file_paths` | list[str] | Every file this module creates or modifies (exact paths from project root) |
| `dependencies` | list[str] | module_ids this depends on (e.g. ["mod-1"]) |
| `apis` | list[object] | Every API endpoint (see schema below). Leave empty [] only if module has no endpoints. |
| `classes` | list[object] | Every class (see schema below). Leave empty [] only if no classes. |
| `functions` | list[object] | Every standalone function (see schema below). Leave empty [] only if no functions. |
| `db_schemas` | list[object] | Every DB table (see schema below). Leave empty [] only if no tables. |
| `testing_notes` | string | What tests to write: list each test case name and what it asserts. |
| `constraints` | list[str] | Edge cases, validation rules, security considerations, error scenarios. |

## Sub-object schemas

### ApiEndpoint
```json
{{
  "method": "POST",
  "path": "/tasks",
  "description": "Create a new task with the provided title",
  "request_body": "{{\\\"title\\\": \\\"string (required, non-empty)\\\"}}",
  "response_body": "{{\\\"id\\\": int, \\\"title\\\": str, \\\"done\\\": bool, \\\"created_at\\\": str}}",
  "status_codes": ["201 Created", "422 Validation Error"]
}}
```

### ClassSpec
```json
{{
  "name": "TaskRepository",
  "description": "Data access layer for the tasks table",
  "attributes": ["db: Connection — SQLite connection handle"],
  "methods": ["create(title: str) -> Task — inserts row and returns Task",
              "list_all() -> list[Task] — returns all tasks ordered by created_at DESC"]
}}
```

### FunctionSpec
```json
{{
  "name": "get_db_connection",
  "description": "Creates and returns a SQLite connection with WAL mode enabled",
  "params": ["db_path: str — path to the SQLite database file"],
  "returns": "sqlite3.Connection",
  "raises": ["sqlite3.OperationalError — if the file path is invalid"]
}}
```

### DbSchema
```json
{{
  "table_name": "tasks",
  "description": "Stores all user tasks",
  "columns": ["id INTEGER PRIMARY KEY AUTOINCREMENT",
               "title TEXT NOT NULL",
               "done BOOLEAN DEFAULT 0",
               "created_at TEXT NOT NULL DEFAULT (datetime('now'))"],
  "indexes": ["idx_tasks_created_at ON tasks(created_at DESC)"],
  "constraints": ["CHECK(length(title) > 0)"]
}}
```

## Critical rules
1. Output ONLY valid JSON — no markdown fences, no commentary, no text before or after the JSON.
2. Module "mod-0" (Foundation) MUST be the first module. All other root modules MUST depend on it.
3. Every field must be filled, not empty. If a module has no APIs, set `"apis": []` explicitly.
4. `technical_spec` must be detailed enough to write code from directly — include exact \
library calls, SQL statements, validation logic, error messages.
5. `file_paths` must list every file the module touches, with paths relative to project root.
6. `testing_notes` must list specific test function names and what they verify.
7. **Granularity**: Each module MUST have a single responsibility. Split by layer, NOT by \
feature. For a web app backend, ALWAYS produce these separate modules: (a) database \
connection & initialization, (b) data model definitions, (c) data access / repository layer, \
(d) API route handlers, (e) **application entry point** that wires everything together \
(registers routers, mounts static files, connects startup events). Do NOT combine these layers.
8. **App Entry Point module**: You MUST include a dedicated "App Entry Point" or "Application \
Wiring" module (e.g. `app/main.py`) that depends on ALL route modules AND the frontend static \
module. Its sole responsibility is: creating the FastAPI `app` instance, calling \
`app.include_router(...)` for every API router, mounting `StaticFiles`, and registering \
startup/shutdown event handlers. This module MUST depend on all modules whose routers it \
registers. Do NOT put router registration in mod-0 (Foundation) since those modules do not \
exist yet at that point.
9. Order dependencies so lower-level modules come first.
9. Order dependencies so lower-level modules come first.
10. `db_schemas` MUST be filled for ANY module that creates, defines, or modifies a database \
table. If a module has SQL CREATE TABLE or ALTER TABLE in its technical_spec, it MUST have a \
corresponding entry in `db_schemas` with all columns, indexes, and constraints. Do NOT leave \
`db_schemas` empty when the module touches database tables.
11. All `folder_structure` and `file_paths` across ALL modules must use CONSISTENT directory \
paths. If mod-0 creates `app/`, then ALL modules must use `app/` — never mix with `src/`.
12. **NO hallucination**: ONLY generate modules for features and stories listed in the \
requirements above. Do NOT invent features, dashboards, analytics, admin panels, \
or any functionality not explicitly described in the requirements. Every module MUST trace \
back to at least one requirement (epic, feature, story, or acceptance criterion). If a \
module's `feature_name` does not match a feature listed in the requirements, do NOT include it.
13. Aim for **6-8 modules** (excluding mod-0) for a typical small project. Each module \
should produce 1-3 files maximum.

# Output format
{{"project_folder_structure": [...], "modules": [...]}}
"""


class ModuleMakerRunner:
    """Decompose requirements into modules via Codex CLI."""

    def __init__(self, db: Database, config: AgentOSConfig, identity_ctx=None) -> None:
        self._db = db
        self._config = config
        self._identity_ctx = identity_ctx
        self._req_repo = RequirementRepository(db.conn)
        self._mod_repo = ModuleRepository(db.conn)
        self._codex = CodexWrapper(
            timeout_seconds=config.codex.timeout_seconds,
            max_retries=config.codex.max_retries,
            openai_api_key=config.secrets.openai_api_key,
            project_root=config.project.root_path or ".",
            model_routing=config.codex.model_routing,
            default_model=config.codex.model,
        )

    def run(self, on_stdout: Callable[[str], None] | None = None) -> ModulePlan:
        """Execute the full module-making pipeline and return the plan."""
        prompt = self._build_prompt()
        raw_json = self._invoke_codex(prompt, on_stdout=on_stdout)
        plan = self._parse_and_validate(raw_json)
        self._ensure_module_0_dependencies(plan)
        self._assign_execution_order(plan)
        self._store_modules(plan)
        return plan

    # --- Prompt building ---

    def _build_prompt(self) -> str:
        lines: list[str] = []
        epics = self._req_repo.get_by_type(RequirementType.EPIC.value)
        for epic in epics:
            lines.append(f"## Epic: {epic.title}")
            if epic.description:
                lines.append(epic.description)
            features = self._req_repo.get_children(epic.id)
            for feat in features:
                lines.append(f"### Feature: {feat.title}")
                if feat.description:
                    lines.append(feat.description)
                stories = self._req_repo.get_children(feat.id)
                for story in stories:
                    lines.append(f"- Story: {story.title}")
                    if story.description:
                        lines.append(f"  {story.description}")
                    acs = self._req_repo.get_children(story.id)
                    for ac in acs:
                        lines.append(f"  - AC: {ac.title}")
                        if ac.description:
                            lines.append(f"    {ac.description}")

        req_text = "\n".join(lines)
        base = _PROMPT_TEMPLATE.format(
            requirements_text=req_text,
            language=self._config.project.language or "python",
            project_name=self._config.project.name or "Target Project",
            project_root=self._config.project.root_path or ".",
        )
        if self._identity_ctx:
            preamble = self._identity_ctx.build_preamble()
            if preamble:
                return preamble + base
        return base

    # --- Codex invocation ---

    def _invoke_codex(self, prompt: str, *, on_stdout: Callable[[str], None] | None = None) -> str:
        working_dir = self._config.project.root_path or "."
        result = self._codex.execute(
            prompt=prompt,
            working_dir=working_dir,
            session_type=SessionType.MODULE_MAKER,
            on_stdout=on_stdout,
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"Module Maker Codex call failed (exit {result.exit_code}): "
                f"{result.stderr[:500]}"
            )
        return result.stdout

    # --- Parsing & validation ---

    @staticmethod
    def _normalize_llm_output(data: dict) -> dict:
        """Coerce common LLM output variations into the expected schema shape."""
        # First pass: extract any modules that the LLM mistakenly nested
        # inside apis/modules arrays of other modules.
        data = ModuleMakerRunner._flatten_nested_modules(data)

        for mod in data.get("modules", []):
            # functions: accept plain strings → {"name": s}
            if "functions" in mod:
                mod["functions"] = [
                    {"name": f} if isinstance(f, str) else f
                    for f in mod["functions"]
                ]
            # classes: accept plain strings → {"name": s}
            if "classes" in mod:
                mod["classes"] = [
                    {"name": c} if isinstance(c, str) else c
                    for c in mod["classes"]
                ]
            # db_schemas: accept plain strings, "name" as alias for
            # "table_name", and column dicts → flatten to "name type" strings
            if "db_schemas" in mod:
                normalised_schemas: list[dict] = []
                for schema in mod["db_schemas"]:
                    if isinstance(schema, str):
                        schema = ModuleMakerRunner._parse_db_schema_string(schema)
                    if isinstance(schema, dict):
                        if "table_name" not in schema and "name" in schema:
                            schema["table_name"] = schema.pop("name")
                        if "columns" in schema:
                            schema["columns"] = [
                                col if isinstance(col, str)
                                else " ".join(
                                    filter(None, [col.get("name", ""), col.get("type", "")])
                                )
                                for col in schema["columns"]
                            ]
                    normalised_schemas.append(schema)
                mod["db_schemas"] = normalised_schemas
            # apis: accept plain strings → {"path": s}
            if "apis" in mod:
                mod["apis"] = [
                    {"path": a} if isinstance(a, str) else a
                    for a in mod["apis"]
                ]
        return data

    @staticmethod
    def _flatten_nested_modules(data: dict) -> dict:
        """Extract module-like objects that the LLM nested inside apis/modules arrays."""
        modules = data.get("modules", [])
        extracted: list[dict] = []
        seen_ids: set[str] = set()

        def _is_module(obj: dict) -> bool:
            return isinstance(obj, dict) and "module_id" in obj and "name" in obj

        def _extract_from_module(mod: dict) -> None:
            # Check 'apis' array for nested modules
            if "apis" in mod and isinstance(mod["apis"], list):
                real_apis = []
                for item in mod["apis"]:
                    if isinstance(item, dict) and _is_module(item):
                        extracted.append(item)
                    else:
                        real_apis.append(item)
                mod["apis"] = real_apis
            # Check 'modules' key accidentally placed inside a module
            if "modules" in mod and isinstance(mod["modules"], list):
                for item in mod["modules"]:
                    if isinstance(item, dict) and _is_module(item):
                        extracted.append(item)
                del mod["modules"]

        for mod in modules:
            if isinstance(mod, dict):
                seen_ids.add(mod.get("module_id", ""))
                _extract_from_module(mod)

        # Recursively check extracted modules too
        for ext_mod in list(extracted):
            _extract_from_module(ext_mod)

        # Add extracted modules that aren't duplicates
        for ext_mod in extracted:
            mid = ext_mod.get("module_id", "")
            if mid and mid not in seen_ids:
                modules.append(ext_mod)
                seen_ids.add(mid)

        data["modules"] = modules
        return data

    @staticmethod
    def _parse_db_schema_string(s: str) -> dict:
        """Parse a compact string like 'Task(id: int PK, title: str, ...)' into a DbSchema dict."""
        import re
        m = re.match(r"^(\w+)\s*\((.+)\)\s*$", s, re.DOTALL)
        if m:
            table_name = m.group(1)
            cols_raw = m.group(2)
            columns = [c.strip() for c in cols_raw.split(",") if c.strip()]
            return {"table_name": table_name, "columns": columns}
        # If it doesn't match the pattern, treat the whole string as table name
        return {"table_name": s, "columns": []}

    def _parse_and_validate(self, raw: str) -> ModulePlan:
        raw = raw.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            raw = "\n".join(lines)

        # Find the first '{' to skip any preamble text
        brace_idx = raw.find("{")
        if brace_idx == -1:
            raise ValueError(
                f"Module Maker output contains no JSON object.\n"
                f"Raw output (first 500 chars): {raw[:500]}"
            )
        raw = raw[brace_idx:]

        try:
            # Use raw_decode to parse just the first JSON object,
            # ignoring any trailing text the LLM may have appended
            decoder = json.JSONDecoder()
            data, _ = decoder.raw_decode(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Module Maker output is not valid JSON: {exc}\n"
                f"Raw output (first 500 chars): {raw[:500]}"
            ) from exc

        data = self._normalize_llm_output(data)
        plan = ModulePlan.model_validate(data)

        cycle_errors = validate_no_cycles(plan.modules)
        if cycle_errors:
            raise ValueError(
                "Module dependency errors:\n"
                + "\n".join(f"  - {e}" for e in cycle_errors)
            )

        return plan

    # --- Module 0 dependency enforcement ---

    @staticmethod
    def _ensure_module_0_dependencies(plan: ModulePlan) -> ModulePlan:
        """Ensure all root modules (no dependencies) depend on mod-0,
        and that mod-0 itself has no dependencies."""
        ids = {m.module_id for m in plan.modules}
        if "mod-0" not in ids:
            logger.warning("LLM did not generate mod-0; plan may lack Foundation module")
            return plan
        for m in plan.modules:
            if m.module_id == "mod-0":
                m.dependencies = []  # Foundation never depends on anything
            elif not m.dependencies:
                m.dependencies.append("mod-0")
        return plan

    # --- Ordering & storage ---

    def _assign_execution_order(self, plan: ModulePlan) -> None:
        order = build_execution_order(plan.modules)
        order_map = {mid: idx for idx, mid in enumerate(order)}
        for m in plan.modules:
            m.dependencies = [
                d for d in m.dependencies if d in order_map
            ]

    def _store_modules(self, plan: ModulePlan) -> None:
        order = build_execution_order(plan.modules)
        order_map = {mid: idx for idx, mid in enumerate(order)}

        # Clean up stale modules from previous generations
        self._mod_repo.delete_all()

        # Use absolute path derived from config so it works regardless of CWD
        out_dir = self._config.storage.data_dir / "modules"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Clean up stale JSON definition files
        new_ids = {m.module_id for m in plan.modules}
        for existing_file in out_dir.glob("mod-*.json"):
            mod_id = existing_file.stem  # e.g. "mod-5"
            if mod_id not in new_ids:
                existing_file.unlink()
                logger.info("Removed stale module file: %s", existing_file.name)

        for mod_def in plan.modules:
            definition_text = mod_def.model_dump_json(indent=2)
            record = ModuleRecord(
                id=mod_def.module_id,
                name=mod_def.name,
                feature_name=mod_def.feature_name,
                dependency_ids=mod_def.dependencies,
                execution_order=order_map.get(mod_def.module_id, 0),
                definition_json=definition_text,
            )
            self._mod_repo.upsert(record)

            # Write JSON alongside DB upsert so they stay in sync
            path = out_dir / f"{mod_def.module_id}.json"
            path.write_text(definition_text, encoding="utf-8")

        # Persist project folder structure if provided
        if plan.project_folder_structure:
            meta_path = out_dir / "_project_structure.json"
            meta_path.write_text(
                json.dumps(plan.project_folder_structure, indent=2),
                encoding="utf-8",
            )

        logger.info(
            "Stored %d modules (execution order: %s)",
            len(plan.modules),
            [m.module_id for m in sorted(
                plan.modules,
                key=lambda x: order_map.get(x.module_id, 0),
            )],
        )
