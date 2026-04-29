# Agent OS — Autonomous SDLC Engine: Implementation Plan

## Vision

An autonomous, module-by-module software development lifecycle engine that takes structured requirements (epics → features → stories → acceptance criteria) and produces production-ready Python web-application codebases through iterative code generation and code review cycles, with human oversight at every critical decision point.

---

## System Architecture Overview

### Components

| # | Component | Type | Role |
|---|-----------|------|------|
| 1 | **Orchestrator** | Python process | Central brain — controls flow, state, retries, iteration caps, module sequencing |
| 2 | **Module Maker** | Codex CLI session | Decomposes requirements into structured module definitions (JSON/YAML) with dependency DAG |
| 3 | **Prompt Generator** | Codex CLI session | Converts a single module definition into a detailed, framework-based prompt |
| 4 | **Code Generator** | Codex CLI session | Executes the prompt to produce code in the project directory |
| 5 | **Validation Layer** | Python subprocess | Runs lint, type-check, tests, security scans on generated code |
| 6 | **Code Reviewer** | Codex CLI session | Reviews code using validation outputs + diff + ACs, produces structured JSON |
| 7 | **Backend API** | FastAPI server | REST + WebSocket API powering the frontend dashboard |
| 8 | **Frontend** | React + Tailwind | Dashboard: streaming terminals, module/iteration status, controls |
| 9 | **Storage** | SQLite + JSON files | Persists modules, prompts, review JSONs, iteration state, token usage |

### Data Flow

```
Requirements (docs + epics/features/stories/ACs)
        │
        ▼
┌─────────────────┐
│  Module Maker    │──→ Structured module definitions (JSON) + dependency DAG
└─────────────────┘
        │
        ▼  [HUMAN GATE 1: Review/edit module definitions]
        │
┌─────────────────┐
│ Prompt Generator │──→ Detailed prompt (.md file, iteration-stamped)
└─────────────────┘
        │
        ▼  [HUMAN GATE 2: Review/edit generated prompt]
        │
┌─────────────────┐
│ Code Generator   │──→ Code in project directory + summary.md (with END marker)
└─────────────────┘
        │
        ▼
┌─────────────────┐
│ Validation Layer │──→ lint/type/test/security results (structured JSON)
└─────────────────┘
        │
        ▼
┌─────────────────┐
│ Code Reviewer    │──→ Review JSON (per-file actions: regenerate/patch/accept)
└─────────────────┘
        │
        ▼  [HUMAN GATE 3: Review/override reviewer decisions]
        │
┌─────────────────┐
│  Orchestrator    │──→ Decision: refine prompt → loop back │ accept → next module
└─────────────────┘
        │
        ▼
   Git commit to feature branch
   (on module complete: PR → dev → main)
```

### Human-in-the-Loop (HITL) Gates

| Gate | Location | What the Human Can Do | Default if Skipped |
|------|----------|----------------------|-------------------|
| **HITL-1** | After Module Maker output | Edit module JSON, reorder modules, adjust dependency graph, modify API/schema definitions | Auto-approve after timeout or if auto-mode enabled |
| **HITL-2** | After Prompt Generator output | Edit the generated prompt .md, add/remove instructions, refine details | Auto-approve |
| **HITL-3** | After Code Reviewer JSON | Override severity, change regenerate→patch, force-accept files, add notes | Auto-approve |
| **HITL-4** | After max iterations reached | Decide: force-accept, manually fix, or abort module | Require human decision (no auto) |
| **HITL-5** | After module completion | Review PR before merge, trigger integration tests | Require human decision |

The frontend provides UI for all gates. The orchestrator pauses pipeline execution at each gate, emits a WebSocket event, and waits for human response (or auto-timeout in auto-pilot mode).

---

## Phase-by-Phase Implementation Plan

---

## PHASE 1: Foundation & Orchestrator Core

**Goal**: Build the skeleton — orchestrator state machine, file/folder conventions, storage layer, and one manual end-to-end run.

**Duration Estimate**: Foundation sprint

### 1.1 Project Scaffolding

- Initialize Python project with `pyproject.toml` (or `setup.cfg`)
- Directory structure:
  ```
  agent_os/
  ├── orchestrator/          # Core state machine + flow control
  │   ├── __init__.py
  │   ├── engine.py          # Main orchestrator loop
  │   ├── state.py           # State persistence/recovery
  │   └── config.py          # All configurable parameters
  ├── module_maker/           # Module Maker wrapper
  │   ├── __init__.py
  │   ├── runner.py           # Codex CLI invocation
  │   └── schema.py           # Module definition JSON schema
  ├── prompt_generator/       # Prompt Generator wrapper
  │   ├── __init__.py
  │   ├── runner.py
  │   ├── templates/          # Prompt framework templates (RCTCF, etc.)
  │   └── schema.py
  ├── code_generator/         # Code Generator wrapper
  │   ├── __init__.py
  │   └── runner.py
  ├── validation/             # Validation layer
  │   ├── __init__.py
  │   ├── linter.py           # flake8/ruff
  │   ├── type_checker.py     # mypy
  │   ├── test_runner.py      # pytest
  │   └── security.py         # bandit
  ├── code_reviewer/          # Code Reviewer wrapper
  │   ├── __init__.py
  │   ├── runner.py
  │   └── schema.py           # Review JSON schema
  ├── git_ops/                # Git operations
  │   ├── __init__.py
  │   └── manager.py
  ├── storage/                # Persistence layer
  │   ├── __init__.py
  │   ├── db.py               # SQLite operations
  │   └── models.py           # Data models
  ├── api/                    # Backend API (Phase 3)
  │   └── ...
  ├── frontend/               # React frontend (Phase 3)
  │   └── ...
  ├── data/                   # Runtime data
  │   ├── modules/            # Module definitions (JSON)
  │   ├── prompts/            # Iteration-stamped prompts
  │   ├── reviews/            # Review JSONs per iteration
  │   ├── summaries/          # Code gen summaries
  │   └── state/              # Orchestrator checkpoints
  ├── config.yaml             # Runtime configuration
  └── requirements.txt
  ```
- Virtual environment setup + dependency pinning

### 1.2 Configuration System

Define `config.yaml`:
```yaml
project:
  name: ""
  root_path: ""                    # Where generated code lives
  language: "python"

orchestrator:
  max_iterations_per_module: 5
  auto_approve_hitl: false         # If true, skip human gates
  hitl_timeout_seconds: 0          # 0 = wait forever
  convergence_rule: "no_high_severity"

codex:
  model: "codex"                   # or specific model version
  timeout_seconds: 300

prompt_framework: "RCTCF"          # Dropdown: RCTCF | RISEN | COSTAR | CUSTOM

git:
  enabled: true
  remote: "origin"
  main_branch: "main"
  dev_branch: "dev"
  auto_create_feature_branches: true

validation:
  lint: true
  type_check: true
  tests: true
  security_scan: true

storage:
  db_path: "data/agent_os.db"

api:
  host: "0.0.0.0"
  port: 8000
```

### 1.3 Storage Layer (SQLite + JSON on disk)

**SQLite Tables:**

- `modules` — id, name, feature_name, status (pending/in_progress/completed/failed), dependency_ids, version, created_at, updated_at
- `iterations` — id, module_id, iteration_number, status, prompt_path, review_json_path, summary_path, started_at, completed_at, token_usage
- `requirements` — id, type (epic/feature/story/ac), parent_id, title, description, status
- `pipeline_state` — singleton row: current_module_id, current_iteration, pipeline_status, last_checkpoint

**JSON on disk:**
- `data/modules/module-{id}.json` — full module definition
- `data/prompts/module-{id}/iteration-{n}.md` — prompt per iteration
- `data/reviews/module-{id}/iteration-{n}.json` — review JSON per iteration
- `data/summaries/module-{id}/iteration-{n}.md` — code gen summary

### 1.4 Orchestrator State Machine

States:
```
IDLE
  → LOADING_REQUIREMENTS
  → MODULE_PLANNING
  → [HITL_1_MODULE_REVIEW]
  → PROMPT_GENERATION
  → [HITL_2_PROMPT_REVIEW]
  → CODE_GENERATION
  → VALIDATION
  → CODE_REVIEW
  → [HITL_3_REVIEW_DECISION]
  → DECISION (accept / iterate / max_reached)
      → iterate: back to PROMPT_GENERATION
      → accept: GIT_COMMIT → MODULE_COMPLETE
      → max_reached: [HITL_4_MAX_ITERATIONS]
  → MODULE_COMPLETE
  → [HITL_5_PR_REVIEW]
  → INTEGRATION_TEST
  → NEXT_MODULE (or PIPELINE_COMPLETE)
```

The orchestrator:
- Persists state to `pipeline_state` table after every transition
- On crash/restart: reads last state, resumes from that point
- Emits events (for frontend) on every state transition
- Enforces max iteration cap
- Tracks token usage per iteration

### 1.5 Codex CLI Wrapper

Build a Python wrapper (`codex_wrapper.py`) that:
- Spawns `codex exec <prompt>` as a subprocess
- Captures stdout/stderr in real-time (for streaming to frontend later)
- Tracks PID for process-level completion detection
- Returns exit code + captured output
- Implements timeout + retry logic (max 2 retries on crash)
- Does NOT rely solely on summary.md for completion — uses process exit as primary signal, summary.md as secondary validation

### 1.6 Deliverable for Phase 1

- Orchestrator can be run from CLI: `python -m agent_os.orchestrator.engine --config config.yaml`
- State machine transitions work (even if wired to stubs)
- Storage layer persists and recovers state
- Codex wrapper can invoke `codex exec` and capture output
- Config system loads and validates

---

## PHASE 2: Module Maker + Prompt Generator + HITL

**Goal**: Build the planning pipeline — from requirements to executable prompts, with human checkpoints.

### 2.1 Requirements Ingestion

- Accept requirements as:
  - A markdown document (requirements.md) describing the project
  - A structured YAML/JSON file defining the hierarchy:
    ```yaml
    epics:
      - id: E1
        title: "User Management"
        features:
          - id: F1
            title: "User Registration"
            stories:
              - id: S1
                title: "User can register with email"
                acceptance_criteria:
                  - id: AC1
                    description: "Given a valid email, when user submits..."
    ```
- Parse and store in `requirements` table with parent-child relationships
- Validate structure: every feature must have stories, every story must have ACs

### 2.2 Module Maker

**Input**: Requirements document + structured epic/feature/story/AC hierarchy

**Output**: Structured JSON per module + dependency DAG

**Module JSON Schema** (strict, validated):
```json
{
  "module_id": "M1",
  "module_name": "user_registration",
  "feature_id": "F1",
  "feature_title": "User Registration",
  "version": 1,
  "dependencies": [],
  "stories": [
    {
      "story_id": "S1",
      "title": "User can register with email",
      "acceptance_criteria": ["AC1", "AC2"]
    }
  ],
  "technical_spec": {
    "folder_structure": {
      "app/api/": ["auth.py"],
      "app/models/": ["user.py"],
      "app/services/": ["auth_service.py"],
      "app/schemas/": ["user_schema.py"],
      "tests/": ["test_auth.py"]
    },
    "apis": [
      {
        "endpoint": "/api/v1/auth/register",
        "method": "POST",
        "handler_function": "register_user",
        "file": "app/api/auth.py",
        "request_schema": "UserRegisterRequest",
        "response_schema": "UserRegisterResponse"
      }
    ],
    "database_schemas": [
      {
        "table": "users",
        "columns": [
          {"name": "id", "type": "UUID", "primary_key": true},
          {"name": "email", "type": "VARCHAR(255)", "unique": true}
        ]
      }
    ],
    "classes": [
      {
        "name": "AuthService",
        "file": "app/services/auth_service.py",
        "methods": ["register_user", "validate_email"]
      }
    ],
    "functions": [
      {
        "name": "register_user",
        "file": "app/api/auth.py",
        "purpose": "Handle POST /register, validate input, call AuthService"
      }
    ]
  }
}
```

**Module Maker also generates:**
- `module_0_foundation.json` — shared infra (DB connection, base models, middleware, config, logging)
- A `dependency_graph.json`:
  ```json
  {
    "execution_order": ["M0", "M1", "M2", "M3"],
    "dependencies": {
      "M0": [],
      "M1": ["M0"],
      "M2": ["M0", "M1"],
      "M3": ["M0"]
    }
  }
  ```

**Codex CLI prompt for Module Maker** includes:
- Full requirements document
- Structured epics/features/stories/ACs
- Strict instruction to output JSON matching the schema above
- Instruction to NOT generate code, only plan
- The target project root path
- The project tech stack

**Post-processing**: Orchestrator validates Module Maker output against JSON schema. If invalid → retry (max 2).

### 2.3 HITL Gate 1: Module Review

Orchestrator:
1. Saves all module JSONs to `data/modules/`
2. Sets state to `HITL_1_MODULE_REVIEW`
3. Emits WebSocket event with module data
4. **Waits** for human action (or auto-approves if config says so)

Human can (via frontend or direct file edit):
- Edit any module JSON
- Reorder modules in the dependency graph
- Add/remove APIs, classes, schema columns
- Split or merge modules
- Add notes/instructions

On approval → state moves to `PROMPT_GENERATION` for first module in execution order.

### 2.4 Prompt Generator

**Input**: Single module JSON (the current one only)

**Output**: A detailed prompt in `.md` format, stamped as `data/prompts/module-{id}/iteration-{n}.md`

**Framework selection** (configurable in config.yaml):

| Framework | Structure |
|-----------|-----------|
| **RCTCF** | Role → Context → Task → Constraints → Format |
| **RISEN** | Role → Instructions → Steps → End goal → Narrowing |
| **COSTAR** | Context → Objective → Style → Tone → Audience → Response |
| **CUSTOM** | User-defined template in `prompt_generator/templates/custom.md` |

**Prompt Generator's own instructions** (meta-prompt):
- You are generating a prompt for a code generation AI
- Use ONLY the information in the provided module JSON
- Do NOT invent endpoints, classes, or functions not in the module
- Do NOT add features, optimizations, or patterns not specified
- The output prompt MUST include:
  - Project root path
  - Complete folder structure with file paths
  - Every API endpoint with method, route, handler, schemas
  - Every class with methods and purpose
  - Every function with parameters and return types
  - Database schema DDL or ORM model definitions
  - Instructions for clean architecture, SOLID principles
  - Instructions for meaningful comments in code
  - Instructions for generating tests (mapped to acceptance criteria)
  - Instructions that after ALL code is generated, create `data/summaries/module-{id}/iteration-{n}.md` containing:
    - All files created
    - All files modified
    - Summary of changes
    - Must end with exactly:
      ```
      ============================================
      END
      ============================================
      ```
  - Dependency context: actual interfaces exported by dependency modules (extracted from generated code, not from blueprint)

**Structured template approach**: The Prompt Generator receives the module JSON and fills a template programmatically. The Codex CLI is used to flesh out natural-language sections, but the structural elements (file paths, function names, schemas) are injected directly from JSON — not generated.

### 2.5 HITL Gate 2: Prompt Review

Orchestrator:
1. Saves prompt to stamped file
2. Sets state to `HITL_2_PROMPT_REVIEW`
3. Emits WebSocket event
4. Waits

Human can:
- Edit the .md prompt directly (frontend provides editor)
- Add context, constraints, or clarifications
- Remove sections that seem hallucinated
- Approve as-is

On approval → trigger Code Generator.

### 2.6 Deliverable for Phase 2

- Module Maker generates valid structured JSON modules from requirements
- Dependency graph is produced and respected
- Module 0 (foundation) is always generated first
- Prompt Generator fills framework-based templates from module JSON
- Both HITL gates pause the pipeline and allow human edits
- All artifacts stored on disk with iteration stamps

---

## PHASE 3: Code Generator + Validation Layer + Code Reviewer

**Goal**: Build the iterative generation-review loop with deterministic validation.

### 3.1 Code Generator

**Invocation**: Orchestrator calls Codex wrapper with:
- The prompt from `data/prompts/module-{id}/iteration-{n}.md`
- A system-level guardrail prompt (prepended) defining scope:
  ```
  SCOPE AND BOUNDARIES:
  - You are generating code for a Python web application
  - Generate ONLY the files specified in the prompt
  - Do NOT create files not mentioned in the prompt
  - Do NOT add endpoints, classes, or functions not specified
  - Do NOT install packages not specified
  - You MAY make tactical implementation decisions:
    - Variable naming within conventions
    - Loop vs comprehension choices
    - Error message wording
    - Import ordering
  - You MUST NOT make structural decisions:
    - No new files beyond what's specified
    - No new API endpoints
    - No schema changes
    - No architectural pattern changes
  - After generating ALL code, create the summary file at the exact path specified
  - The summary file MUST end with the END marker exactly as specified
  ```
- Working directory: the project root path

**Completion detection** (dual mechanism):
1. **Primary**: Process exit code from subprocess (PID tracking)
2. **Secondary**: Check for summary.md at expected path with END marker
3. If process exits 0 but no summary → flag as partial completion, retry once
4. If process exits non-0 → log error, retry once, then fail to HITL-4

**Post-generation**:
- Parse summary.md to extract list of created/modified files
- Store in `iterations` table
- Delete summary.md after parsing (data preserved in DB)

### 3.2 Validation Layer

Runs automatically after Code Generator completes. Each tool runs as subprocess:

| Tool | Purpose | Output |
|------|---------|--------|
| `ruff` (or `flake8`) | Linting + style | JSON list of violations |
| `mypy` | Type checking | JSON list of type errors |
| `pytest` | Run generated tests | JSON test results (pass/fail per test) |
| `bandit` | Security scan | JSON list of security findings |
| `pip install -r requirements.txt` | Dependency check | Success/failure |

**Output**: Aggregated validation JSON:
```json
{
  "lint": {"passed": false, "issues": [...]},
  "type_check": {"passed": true, "issues": []},
  "tests": {"passed": false, "results": [...]},
  "security": {"passed": true, "issues": []},
  "dependencies": {"passed": true}
}
```

This JSON is passed to the Code Reviewer alongside the code. The reviewer doesn't guess about lint or test failures — it has hard data.

### 3.3 Code Reviewer

**Input** (explicitly scoped):
- `git diff` of changes in this iteration (not full codebase)
- Validation layer JSON output
- Current module JSON (the spec)
- Acceptance criteria for current stories
- Previous review JSON (last iteration only, not full history)
- The prompt that was used for this iteration

**The reviewer does NOT**:
- Modify any code files
- Read unrelated modules
- Access full project history

**Output**: Structured review JSON:
```json
{
  "module_id": "M1",
  "iteration": 2,
  "overall_status": "needs_changes",
  "convergence_score": 72,
  "files": [
    {
      "path": "app/api/auth.py",
      "action": "patch",
      "issues": [
        {
          "id": "ISS-001",
          "severity": "high",
          "category": "security",
          "line_range": [45, 52],
          "issue": "Password stored in plaintext",
          "suggested_fix": "Use bcrypt hashing via passlib",
          "requires_regeneration": false
        }
      ]
    },
    {
      "path": "app/models/user.py",
      "action": "accept",
      "issues": []
    },
    {
      "path": "app/services/auth_service.py",
      "action": "regenerate",
      "issues": [
        {
          "id": "ISS-002",
          "severity": "critical",
          "category": "functionality",
          "issue": "Missing email validation entirely — does not fulfill AC1",
          "suggested_fix": "Implement email validation per acceptance criteria",
          "requires_regeneration": true
        }
      ]
    }
  ],
  "ac_verification": {
    "AC1": {"status": "fail", "reason": "Email validation not implemented"},
    "AC2": {"status": "pass"}
  },
  "review_areas": {
    "design_architecture": {"score": 7, "notes": "..."},
    "functionality": {"score": 5, "notes": "..."},
    "complexity": {"score": 8, "notes": "..."},
    "security": {"score": 3, "notes": "..."},
    "naming_readability": {"score": 8, "notes": "..."},
    "tests": {"score": 6, "notes": "..."},
    "performance": {"score": 7, "notes": "..."}
  }
}
```

Stored at: `data/reviews/module-{id}/iteration-{n}.json`

### 3.4 HITL Gate 3: Review Decision

Orchestrator:
1. Presents review JSON in frontend
2. Human can:
   - Override any `action` (e.g., change `regenerate` → `accept`)
   - Lower/raise severity
   - Add notes for next iteration
   - Force-accept entire module (skip further iterations)
3. On approve → Orchestrator decides next step

### 3.5 Orchestrator Decision Logic

```python
def decide_next_step(review_json, iteration_number, config):
    if review_json["overall_status"] == "accepted":
        return "MODULE_COMPLETE"
    
    if iteration_number >= config["max_iterations_per_module"]:
        return "HITL_4_MAX_ITERATIONS"  # Human must decide
    
    has_critical = any(
        issue["severity"] == "critical"
        for f in review_json["files"]
        for issue in f["issues"]
    )
    has_high = any(
        issue["severity"] == "high"
        for f in review_json["files"]
        for issue in f["issues"]
    )
    
    if not has_critical and not has_high:
        # Only low/medium issues remain — convergence reached
        return "MODULE_COMPLETE"
    
    # Needs another iteration
    return "PROMPT_GENERATION"
```

### 3.6 Prompt Generator — Iteration Mode

When called for iteration > 1, Prompt Generator receives:
- Review JSON from Code Reviewer
- Original module JSON

Behavior depends on per-file `action`:
- `regenerate` files: rebuild full prompt section for those files
- `patch` files: generate targeted fix instructions with specific issue IDs
- `accept` files: explicitly tell Code Generator "do not modify these files"

This prompt replaces the previous iteration's prompt in a new stamped file.

### 3.7 Deliverable for Phase 3

- Full generate → validate → review → iterate loop working
- Validation layer produces hard data for reviewer
- Review JSON is structured and per-file
- Convergence logic terminates loops
- HITL gates at review decisions
- All artifacts persisted per iteration

---

## PHASE 4: Git Integration + Module Sequencing

**Goal**: Proper Git workflow, multi-module pipeline, integration testing.

### 4.1 Git Strategy

```
main (stable, production-ready)
  └── dev (integration branch)
       ├── feature/module-M0-foundation
       ├── feature/module-M1-user-registration
       ├── feature/module-M2-user-profile
       └── ...
```

**Per-iteration**: Commit to `feature/module-{id}` branch with message:
```
[Agent OS] Module {id} - Iteration {n}: {summary}
```

**On module complete**:
1. Squash-merge or regular merge `feature/module-{id}` → `dev`
2. Tag: `module-{id}-complete`

**On all modules complete**:
1. PR from `dev` → `main`
2. HITL Gate 5: Human reviews full PR before merge

**Git ops**: All via GitHub MCP plugin connected to Codex CLI (as specified in requirements).

### 4.2 Multi-Module Sequencing

Orchestrator reads `dependency_graph.json` and:
1. Processes modules in topological order
2. Before starting Module N:
   - Verifies all dependencies are in `completed` state
   - Extracts actual exported interfaces from completed dependency code:
     - Public function signatures
     - Class definitions
     - API endpoint routes
     - Schema definitions
   - Passes these as "dependency context" to Prompt Generator

### 4.3 Integration Testing

After each module completes (before merge to dev):
1. Run all tests from previously completed modules (regression)
2. Run import checks across modules
3. Validate API contract consistency (if Module 2 calls Module 1's endpoint, does the schema match?)

If integration tests fail → route back to prompt generation with integration failure context.

### 4.4 Module Maker Refinement (Evolving Plan)

After Module N is complete, the Module Maker can receive feedback:
- "Module N's actual implementation deviated from plan in X ways"
- Used to update module definitions for downstream modules

This is NOT automatic regeneration — it's a structured update triggered when the orchestrator detects interface mismatches.

### 4.5 Deliverable for Phase 4

- Git branches created/managed automatically
- Commits per iteration, merges per module
- Dependency-aware module sequencing
- Integration tests between modules
- Module definitions evolve based on actual code

---

## PHASE 5: Backend API + Frontend Dashboard

**Goal**: Full visibility and control via web interface.

### 5.1 Backend API (FastAPI)

**REST Endpoints**:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/requirements` | Full epic/feature/story/AC tree |
| GET | `/api/modules` | All modules with status |
| GET | `/api/modules/{id}` | Single module definition |
| PUT | `/api/modules/{id}` | HITL edit module |
| GET | `/api/modules/{id}/iterations` | All iterations for module |
| GET | `/api/modules/{id}/iterations/{n}/prompt` | Prompt for iteration |
| PUT | `/api/modules/{id}/iterations/{n}/prompt` | HITL edit prompt |
| GET | `/api/modules/{id}/iterations/{n}/review` | Review JSON |
| PUT | `/api/modules/{id}/iterations/{n}/review` | HITL override review |
| GET | `/api/pipeline/state` | Current pipeline state |
| POST | `/api/pipeline/start` | Start pipeline |
| POST | `/api/pipeline/pause` | Pause at next gate |
| POST | `/api/pipeline/approve-gate` | Approve current HITL gate |
| POST | `/api/pipeline/force-next-module` | Skip to next module |
| GET | `/api/metrics` | Token usage, iteration counts, cost |

**WebSocket Endpoints**:

| Path | Purpose |
|------|---------|
| `/ws/terminal/{session}` | Real-time terminal output streaming (per agent session) |
| `/ws/pipeline` | Pipeline state change events |
| `/ws/hitl` | HITL gate notifications |

**Terminal Streaming Implementation**:
- Each Codex CLI session (module maker, prompt gen, code gen, reviewer) runs as a subprocess
- stdout/stderr piped through a PTY (using `pty` module or `pexpect`)
- Each byte/token written to PTY is broadcast via WebSocket to connected frontend clients
- Sessions identified by `session_type` enum: `MODULE_MAKER | PROMPT_GENERATOR | CODE_GENERATOR | CODE_REVIEWER`

### 5.2 Frontend (React + Tailwind + Framer Motion)

**Tech Stack**:
- React 18+ (with hooks)
- Tailwind CSS (utility-first styling)
- Framer Motion (animations, transitions, layout animations)
- xterm.js (terminal rendering in browser)
- Monaco Editor (for prompt/module JSON editing in HITL gates)
- Recharts or Nivo (for metrics charts)
- React Router (SPA routing)

**Layout** (single-page dashboard with panels):

```
┌────────────────────────────────────────────────────────────────┐
│  Header: Agent OS — Pipeline Status: [Running ● / Paused ◯]   │
│  Controls: [Start] [Pause] [Approve Gate] [Force Next Module]  │
├──────────────┬─────────────────────────────────────────────────┤
│              │                                                  │
│  Left Sidebar│  Main Content Area                               │
│              │                                                  │
│  Requirements│  Tab 1: Pipeline View                            │
│  Tree View   │    - Module cards with status                    │
│              │    - Current iteration indicator                  │
│  Epics       │    - Progress bars                               │
│   └Features  │    - Convergence score trend                     │
│     └Stories │                                                  │
│       └ACs   │  Tab 2: Terminal Streams                         │
│              │    - 4 terminal panels (Module Maker,            │
│  Currently   │      Prompt Gen, Code Gen, Reviewer)             │
│  Working:    │    - Token-by-token streaming via xterm.js        │
│  [Feature X] │                                                  │
│  ────────────│  Tab 3: Code Insights                            │
│  Modules     │    - Current review JSON rendered                │
│  [M0] ✅     │    - Severity badges (color-coded)              │
│  [M1] 🔄 i3 │    - Per-file issue breakdown                   │
│  [M2] ⏳     │    - AC pass/fail status                        │
│  [M3] ⏳     │                                                  │
│              │  Tab 4: Prompt Editor (HITL)                      │
│              │    - Monaco editor with current prompt            │
│              │    - Diff view (previous vs current)              │
│              │    - [Approve] [Edit & Approve] buttons           │
│              │                                                  │
│              │  Tab 5: Module Editor (HITL)                      │
│              │    - JSON editor for module definition            │
│              │    - Schema validation indicators                 │
│              │                                                  │
│              │  Tab 6: Git & History                             │
│              │    - Branch visualization                         │
│              │    - Commit log per module                        │
│              │    - PR status                                    │
│              │                                                  │
│              │  Tab 7: Metrics                                   │
│              │    - Token usage per module/iteration             │
│              │    - Time per iteration                           │
│              │    - Issue severity distribution                  │
│              │    - Convergence trend chart                      │
├──────────────┴─────────────────────────────────────────────────┤
│  Footer: Iteration 3/5 │ Module M1 │ Tokens Used: 45.2k       │
└────────────────────────────────────────────────────────────────┘
```

**Design System**:
- Dark theme primary (gradient: deep navy → charcoal)
- Accent: electric blue gradient (#3B82F6 → #8B5CF6)
- Status colors: green (success), amber (warning), red (critical), blue (info)
- Cards with subtle glass-morphism (backdrop-blur + semi-transparent bg)
- Framer Motion: page transitions (slide), card animations (spring), progress bar animations
- Smooth depth via shadows and layering — NOT Three.js (saves complexity, achieves same visual impact)
- Responsive: works on 1440p+ screens primarily (developer tool, not mobile)

**HITL UX Flow**:
1. Pipeline pauses at gate
2. Frontend shows a notification banner: "Human review required: Module M1 prompt ready"
3. User clicks banner → opens Prompt Editor tab
4. Monaco editor pre-loaded with prompt
5. User edits (or not)
6. Clicks [Approve] → API call to `/api/pipeline/approve-gate`
7. Pipeline resumes

### 5.3 Deliverable for Phase 5

- FastAPI backend serving REST + WebSocket
- React frontend with all 7 tabs
- Real-time terminal streaming from all 4 agent sessions
- HITL gates interactive in UI
- Metrics dashboard functional

---

## PHASE 6: Hardening, Error Handling, Token Budget

**Goal**: Make it robust for real-world usage.

### 6.1 Error Handling & Recovery

| Failure | Detection | Response |
|---------|-----------|----------|
| Codex CLI crashes | Non-zero exit + no summary | Retry once, then HITL-4 |
| Codex CLI hangs | Timeout (configurable) | Kill PID, retry once |
| Partial code generation | Process exits but missing files | Log + retry with note in prompt |
| Validation fails to run | Subprocess error | Skip that validator, note in review context |
| Git conflict | Merge failure on branch | Pause, notify via HITL |
| Network error (API) | HTTP error from GitHub MCP | Retry with backoff, 3 attempts |
| JSON parse failure (review) | Invalid reviewer output | Retry review with "output must be valid JSON" appended |
| Module dependency not met | DB check | Block module, log, notify |

**Rollback strategy**:
- Every iteration starts with a Git commit (even if empty, as a checkpoint)
- On catastrophic failure: `git reset --hard` to last clean commit on feature branch
- Orchestrator state in DB ensures no orphaned state

### 6.2 Token/Cost Budget

- Track per-iteration: prompt tokens, completion tokens, total cost
- Set per-module budget cap (configurable)
- Alert at 80% of budget → show warning in frontend
- At 100% → pause pipeline, HITL required
- Dashboard shows cumulative cost chart

### 6.3 Dependency & Environment Management

Before first code generation:
1. Create virtual environment in project root
2. After each iteration that adds dependencies:
   - Parse generated `requirements.txt`
   - Run `pip install -r requirements.txt` in venv
   - If install fails → add to reviewer context

### 6.4 Deliverable for Phase 6

- Retry/rollback logic for all failure modes
- Token tracking + budget enforcement
- Dependency auto-installation
- All error states visible in frontend

---

## PHASE 7: Optimization & Scaling

**Goal**: Improve quality and prepare for scaling.

### 7.1 Prompt Quality Improvement

- A/B test prompt frameworks (RCTCF vs RISEN vs COSTAR) on same module
- Track which framework produces fewest iterations to convergence
- Store winner per project type

### 7.2 Reviewer Quality Improvement

- Feed reviewer its own historical accuracy:
  - "Last iteration you flagged X, code generator couldn't fix it — rephrase"
- Add reviewer self-correction: if same issue appears 3 iterations → escalate severity

### 7.3 Module Parallelization (Future)

- If dependency graph allows, run independent modules in parallel
- Requires: separate feature branches, no shared file conflicts
- Only enable after single-module pipeline is battle-tested

### 7.4 Database Migration (If Needed)

- If multi-user or team usage required → migrate SQLite → PostgreSQL
- Add user auth to API
- Add role-based access (viewer, operator, admin)

### 7.5 Deliverable for Phase 7

- Prompt framework benchmarking
- Smarter reviewer with historical context
- Architecture ready for parallelization
- Migration path to production DB

---

## Appendix A: Full Review JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["module_id", "iteration", "overall_status", "files", "ac_verification"],
  "properties": {
    "module_id": {"type": "string"},
    "iteration": {"type": "integer"},
    "overall_status": {"enum": ["accepted", "needs_changes", "needs_regeneration"]},
    "convergence_score": {"type": "integer", "minimum": 0, "maximum": 100},
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "action"],
        "properties": {
          "path": {"type": "string"},
          "action": {"enum": ["accept", "patch", "regenerate"]},
          "issues": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["id", "severity", "category", "issue"],
              "properties": {
                "id": {"type": "string"},
                "severity": {"enum": ["critical", "high", "medium", "low"]},
                "category": {"enum": ["security", "functionality", "architecture", "performance", "complexity", "naming", "tests", "style"]},
                "line_range": {"type": "array", "items": {"type": "integer"}},
                "issue": {"type": "string"},
                "suggested_fix": {"type": "string"},
                "requires_regeneration": {"type": "boolean"}
              }
            }
          }
        }
      }
    },
    "ac_verification": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "status": {"enum": ["pass", "fail", "not_tested"]},
          "reason": {"type": "string"}
        }
      }
    },
    "review_areas": {
      "type": "object",
      "properties": {
        "design_architecture": {"$ref": "#/definitions/area_score"},
        "functionality": {"$ref": "#/definitions/area_score"},
        "complexity": {"$ref": "#/definitions/area_score"},
        "security": {"$ref": "#/definitions/area_score"},
        "naming_readability": {"$ref": "#/definitions/area_score"},
        "tests": {"$ref": "#/definitions/area_score"},
        "performance": {"$ref": "#/definitions/area_score"}
      }
    }
  },
  "definitions": {
    "area_score": {
      "type": "object",
      "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 10},
        "notes": {"type": "string"}
      }
    }
  }
}
```

## Appendix B: Module Definition JSON Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["module_id", "module_name", "feature_id", "version", "dependencies", "stories", "technical_spec"],
  "properties": {
    "module_id": {"type": "string"},
    "module_name": {"type": "string"},
    "feature_id": {"type": "string"},
    "feature_title": {"type": "string"},
    "version": {"type": "integer", "minimum": 1},
    "dependencies": {"type": "array", "items": {"type": "string"}},
    "stories": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["story_id", "title", "acceptance_criteria"],
        "properties": {
          "story_id": {"type": "string"},
          "title": {"type": "string"},
          "acceptance_criteria": {"type": "array", "items": {"type": "string"}}
        }
      }
    },
    "technical_spec": {
      "type": "object",
      "required": ["folder_structure", "apis", "database_schemas", "classes", "functions"],
      "properties": {
        "folder_structure": {"type": "object"},
        "apis": {"type": "array"},
        "database_schemas": {"type": "array"},
        "classes": {"type": "array"},
        "functions": {"type": "array"}
      }
    }
  }
}
```

## Appendix C: Prompt Frameworks Reference

### RCTCF (Role, Context, Task, Constraints, Format)

```
ROLE: You are a senior Python backend developer...
CONTEXT: You are building module M1 (User Registration) of...
TASK: Generate the following files with exact specifications...
CONSTRAINTS:
- Do not create files not listed
- Follow SOLID principles
- ...
FORMAT: Generate code files at specified paths. After completion, generate summary.md...
```

### RISEN (Role, Instructions, Steps, End goal, Narrowing)

```
ROLE: Senior Python developer
INSTRUCTIONS: Build the user registration feature...
STEPS:
1. Create app/models/user.py with...
2. Create app/api/auth.py with...
END GOAL: Fully functional registration API passing all ACs
NARROWING: Only create specified files, no external dependencies...
```

### COSTAR (Context, Objective, Style, Tone, Audience, Response)

```
CONTEXT: Module M1 of an e-commerce platform...
OBJECTIVE: Generate production-ready user registration code...
STYLE: Clean architecture, well-commented
TONE: Professional, enterprise-grade
AUDIENCE: The code will be reviewed by senior engineers
RESPONSE: Python files at specified paths + summary.md
```
