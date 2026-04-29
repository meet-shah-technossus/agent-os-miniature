# Agent OS — Autonomous SDLC Engine: Implementation Plan v2

## Vision

An autonomous, module-by-module software development lifecycle engine that takes structured requirements (epics → features → stories → acceptance criteria) and produces production-ready Python web-application codebases through iterative code generation and code review cycles, with human oversight at every critical decision point.

---

## Code Quality Standards (Enforced Throughout All Phases)

These rules apply to EVERY file written in this project. No exceptions.

1. **No god classes** — no single class that does everything. Each class has one clear responsibility.
2. **Max 200 lines per file** — if it exceeds, split into focused submodules immediately.
3. **Dedicated folders for each domain** — every new task area gets its own folder with subfolders as needed.
4. **Single-responsibility files** — each file does one thing. `db.py` doesn't also handle validation. `engine.py` doesn't also handle config.
5. **Reusable functions** — extract common logic into shared utilities. Never copy-paste.
6. **No hardcoded values** — all constants, strings, paths, limits go in `config.yaml` or database. Zero magic numbers in code.
7. **Clear naming** — classes, functions, variables named for what they do. `ModuleStatusUpdater`, not `Helper`. `process_review_json()`, not `do_stuff()`.
8. **Clean architecture** — dependency inversion, interface segregation. Inner layers don't know about outer layers.
9. **Folder structure is a feature** — organize by domain (orchestrator/, comms/, storage/), not by file type.
10. **Config-driven behavior** — anything that might change (timeouts, limits, paths, feature flags) lives in config, not in code.

---

## System Architecture Overview

### Components

| # | Component | Type | Role |
|---|-----------|------|------|
| 1 | **Orchestrator** | Python process | Central brain — controls flow, state, retries, iteration caps, module sequencing |
| 2 | **Agent Communication Bus** | Python (async) | Parallel message passing between all agents — pub/sub with channels |
| 3 | **Module Maker** | Codex CLI session | Decomposes requirements into structured module definitions (JSON) with dependency DAG |
| 4 | **Prompt Generator** | Codex CLI session | Converts a single module definition into a detailed, framework-based prompt |
| 5 | **Code Generator** | Codex CLI session | Executes the prompt to produce code in the project directory |
| 6 | **Validation Layer** | Python subprocess | Runs lint, type-check, tests, security scans on generated code |
| 7 | **Code Reviewer** | Codex CLI session | Reviews code using validation outputs + diff + ACs, produces structured JSON |
| 8 | **Backend API** | FastAPI server | REST + WebSocket API powering the frontend dashboard |
| 9 | **Frontend** | React + Tailwind | Dashboard: streaming terminals, module/iteration status, HITL editors, controls |
| 10 | **Storage** | SQLite + JSON files | Persists modules, prompts, review JSONs, iteration state, token usage |

---

## Agent-to-Agent Communication Architecture

### Problem with Sequential Pipeline

The v1 design was strictly sequential: Module Maker → Prompt Generator → Code Generator → Reviewer → back. Each agent only talked to the next one in line. This creates bottlenecks and prevents agents from sharing real-time context.

### Solution: Parallel Communication Bus

All agents communicate through a **shared message bus** with typed channels. Any agent can publish messages and any agent can subscribe to relevant channels. This runs **in parallel** alongside the main pipeline — agents don't block each other's messages.

```
┌──────────────┐     ┌──────────────────────────────┐     ┌──────────────┐
│ Module Maker │◄───►│                              │◄───►│ Code Generator│
└──────────────┘     │   Agent Communication Bus    │     └──────────────┘
                     │                              │
┌──────────────┐     │  Channels:                   │     ┌──────────────┐
│Prompt Genera-│◄───►│  - module_updates             │◄───►│ Code Reviewer│
│tor           │     │  - prompt_ready               │     └──────────────┘
└──────────────┘     │  - generation_status           │
                     │  - validation_results          │     ┌──────────────┐
┌──────────────┐     │  - review_feedback             │◄───►│ Validation   │
│ Orchestrator │◄───►│  - hitl_requests               │     │ Layer        │
└──────────────┘     │  - hitl_responses              │     └──────────────┘
                     │  - pipeline_events             │
                     │  - error_alerts                │     ┌──────────────┐
                     │  - agent_heartbeats            │◄───►│ Frontend     │
                     └──────────────────────────────┘     │ (via WS)     │
                                                          └──────────────┘
```

### Communication Channels

| Channel | Publisher(s) | Subscriber(s) | Message Type | Purpose |
|---------|-------------|---------------|-------------|---------|
| `module_updates` | Module Maker | Prompt Gen, Orchestrator, Frontend | ModuleDefinition | New/updated module definitions |
| `prompt_ready` | Prompt Generator | Code Generator, Orchestrator, Frontend | PromptReady | Prompt generated and ready for execution |
| `generation_status` | Code Generator | Orchestrator, Reviewer, Frontend | GenerationStatus | Real-time progress of code generation |
| `validation_results` | Validation Layer | Code Reviewer, Orchestrator, Frontend | ValidationResult | Lint/test/security scan results |
| `review_feedback` | Code Reviewer | Prompt Generator, Module Maker, Orchestrator, Frontend | ReviewFeedback | Review JSON with issues and suggested fixes |
| `hitl_requests` | Any agent | Frontend, Orchestrator | HITLRequest | Human review needed — pause and wait |
| `hitl_responses` | Frontend/CLI | Orchestrator, requesting agent | HITLResponse | Human approved/edited/rejected |
| `pipeline_events` | Orchestrator | All agents, Frontend | PipelineEvent | State transitions, module switches |
| `error_alerts` | Any agent | Orchestrator, Frontend | ErrorAlert | Failures, timeouts, retries |
| `agent_heartbeats` | All agents | Orchestrator | Heartbeat | Liveness check — detect stuck agents |

### How Parallel Communication Works

**Example: Code Reviewer feeds back to Module Maker in parallel**

In v1 (sequential): Reviewer → JSON → Prompt Gen → eventually Module Maker learns about issues.

In v2 (parallel): While Reviewer sends `review_feedback` to Prompt Generator for the current iteration, it **simultaneously** sends the same message to Module Maker. Module Maker can start updating downstream module definitions without waiting for the current module to finish. The Prompt Generator and Module Maker receive the message at the same time.

**Example: Validation Layer and Code Reviewer work simultaneously**

Validation Layer publishes `validation_results` as each tool finishes (ruff done → publish → mypy done → publish). Code Reviewer **subscribes and starts reviewing as results stream in**, not after all validation is complete. This overlaps their work.

**Example: Frontend gets real-time updates from all agents**

Frontend subscribes to ALL channels via WebSocket bridge. It sees Module Maker output, Prompt Generator output, Code Generator progress, Validation results, and Review feedback — all streaming in parallel. No polling needed.

### Message Format

```json
{
  "channel": "review_feedback",
  "sender": "code_reviewer",
  "timestamp": "2026-04-22T10:30:00Z",
  "module_id": "M1",
  "iteration": 2,
  "correlation_id": "uuid-here",
  "payload": { ... }
}
```

Every message has a `correlation_id` to trace the full lifecycle of a request across agents.

---

## CLI Integration Architecture

### How Everything Connects

```
┌──────────────────────────────────────────────────────────────────┐
│  agent-os CLI (python -m agent_os)                               │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Orchestrator (engine.py)                                  │  │
│  │    ├── reads config.yaml                                   │  │
│  │    ├── connects to SQLite (data/agent_os.db)               │  │
│  │    ├── starts Agent Communication Bus (async)              │  │
│  │    └── manages lifecycle of all agents                     │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │                                       │
│            ┌─────────────┼─────────────┐                        │
│            ▼             ▼             ▼                         │
│     ┌────────────┐ ┌──────────┐ ┌──────────┐                   │
│     │codex exec  │ │codex exec│ │codex exec│  (subprocesses)   │
│     │Module Maker│ │Code Gen  │ │Reviewer  │                   │
│     └────────────┘ └──────────┘ └──────────┘                   │
│            │             │             │                         │
│            ▼             ▼             ▼                         │
│     data/modules/  project_root/  data/reviews/                 │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  FastAPI Server (optional, --with-api)                     │  │
│  │    ├── REST endpoints → reads from SQLite + JSON files     │  │
│  │    ├── WebSocket → bridges Agent Comm Bus to frontend      │  │
│  │    └── serves React frontend (static build)                │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### CLI Commands

```bash
# Core pipeline
agent-os --config config.yaml              # Start pipeline (pauses at HITL gates)
agent-os --auto                            # Auto-approve all HITL gates
agent-os --status                          # Show current state
agent-os --approve                         # Approve current HITL gate
agent-os --reset                           # Reset to IDLE

# With frontend
agent-os --with-api                        # Start pipeline + FastAPI + frontend

# Individual agent testing
agent-os run-module-maker --requirements requirements.yaml
agent-os run-prompt-gen --module data/modules/module-M1.json
agent-os run-code-gen --prompt data/prompts/module-M1/iteration-1.md
agent-os run-reviewer --module M1 --iteration 1
```

### Folder-to-CLI Mapping

| Folder | Connected via | Purpose |
|--------|-------------|---------|
| `agent_os/orchestrator/` | CLI entry point (`engine.py:main()`) | State machine, decision logic |
| `agent_os/comms/` | Started by Orchestrator at boot | Agent Communication Bus |
| `agent_os/module_maker/` | Called by Orchestrator via Codex wrapper | Module planning |
| `agent_os/prompt_generator/` | Called by Orchestrator via Codex wrapper | Prompt building |
| `agent_os/code_generator/` | Called by Orchestrator via Codex wrapper | Code generation |
| `agent_os/validation/` | Called by Orchestrator as subprocess | Lint/test/security |
| `agent_os/code_reviewer/` | Called by Orchestrator via Codex wrapper | Code review |
| `agent_os/git_ops/` | Called by Orchestrator | Branch/commit/PR management |
| `agent_os/storage/` | Imported by all components | SQLite + file I/O |
| `agent_os/api/` | Started by CLI with `--with-api` | REST + WebSocket server |
| `config.yaml` | Loaded at startup | All configurable parameters |
| `data/` | Read/written by all components | Runtime artifacts |

---

## GitHub MCP Integration

### When: Phase 4 (Git Integration)

### How Codex CLI Connects to GitHub MCP

GitHub MCP is added as a plugin to the Codex CLI configuration. Each Codex CLI session (Module Maker, Code Gen, Reviewer) can use GitHub MCP tools when needed.

**Codex CLI config** (`~/.codex/config.json` or project-level):
```json
{
  "plugins": {
    "github": {
      "type": "mcp",
      "server": "github-mcp-server",
      "config": {
        "token": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

**What each agent uses GitHub MCP for**:

| Agent | GitHub MCP Actions |
|-------|-------------------|
| Code Generator | Create/update files, commit to feature branch |
| Code Reviewer | Read diffs, read PR contents, add PR comments |
| Orchestrator (via git_ops/) | Create branches, create PRs, merge PRs, manage tags |

**Setup steps** (done in Phase 4):
1. Install `github-mcp-server` npm package globally
2. Configure Codex CLI to load it as plugin
3. Set `GITHUB_TOKEN` env var (stored in config, never hardcoded)
4. Orchestrator's `git_ops/manager.py` wraps all GitHub operations

---

## Human-in-the-Loop (HITL) Gates

| Gate | Location | What Human Can Do | Frontend UI Element | Default if Skipped |
|------|----------|------------------|--------------------|--------------------|
| **HITL-1** | After Module Maker | Edit module JSON, reorder modules, adjust dependency graph | Monaco JSON Editor + dependency DAG visualizer | Auto-approve or timeout |
| **HITL-2** | After Prompt Generator | Edit the generated prompt, add/remove instructions | Monaco Markdown Editor with diff view | Auto-approve |
| **HITL-3** | After Code Reviewer | Override severity, change actions, force-accept files | Review panel with inline editing + override buttons | Auto-approve |
| **HITL-4** | Max iterations reached | Force-accept, manually fix, abort module | Decision dialog with options | **Requires human** (no auto) |
| **HITL-5** | Module completion | Review PR, trigger integration tests | Git panel with PR diff viewer | **Requires human** |

**Frontend HITL Flow**:
1. Agent publishes `hitl_requests` message on Comm Bus
2. Orchestrator sets state to HITL gate, pauses pipeline
3. WebSocket bridge pushes notification to frontend
4. Frontend shows notification banner + opens relevant editor tab
5. User edits content using Monaco Editor (JSON for modules, Markdown for prompts, review panel for reviews)
6. User clicks [Approve] / [Edit & Approve] / [Reject]
7. Frontend sends `hitl_responses` via WebSocket → Comm Bus → Orchestrator
8. Pipeline resumes

---

## Phase-by-Phase Implementation Plan (15 Phases)

---

## PHASE 1: Project Foundation

**Goal**: Project scaffolding, configuration system, data models.

### 1.1 Project Scaffolding

- `pyproject.toml` with all dependency groups
- Directory structure (every domain gets its own folder):
  ```
  agent_os/
  ├── orchestrator/
  │   ├── __init__.py
  │   ├── engine.py          # Main loop only (<200 lines)
  │   ├── handlers.py        # Step handler functions
  │   ├── decision.py        # Convergence + decision logic
  │   └── cli.py             # Argument parsing + CLI entry
  ├── comms/                  # Agent Communication Bus
  │   ├── __init__.py
  │   ├── bus.py              # Core pub/sub bus
  │   ├── channels.py         # Channel definitions + enums
  │   └── messages.py         # Message types (Pydantic models)
  ├── config/                 # Configuration (separated from orchestrator)
  │   ├── __init__.py
  │   ├── loader.py           # YAML loading + validation
  │   └── schema.py           # Pydantic config models
  ├── module_maker/
  │   ├── __init__.py
  │   ├── runner.py
  │   └── schema.py
  ├── prompt_generator/
  │   ├── __init__.py
  │   ├── runner.py
  │   ├── frameworks.py       # Framework selection logic
  │   ├── templates/
  │   └── schema.py
  ├── code_generator/
  │   ├── __init__.py
  │   ├── runner.py
  │   └── guardrails.py       # Scope enforcement prompts
  ├── validation/
  │   ├── __init__.py
  │   ├── runner.py            # Validation orchestrator
  │   ├── linter.py
  │   ├── type_checker.py
  │   ├── test_runner.py
  │   └── security.py
  ├── code_reviewer/
  │   ├── __init__.py
  │   ├── runner.py
  │   └── schema.py
  ├── git_ops/
  │   ├── __init__.py
  │   ├── branch_manager.py
  │   ├── commit_manager.py
  │   └── pr_manager.py
  ├── codex/                   # Codex CLI wrapper (own domain)
  │   ├── __init__.py
  │   ├── wrapper.py           # Core subprocess management
  │   ├── session.py           # Session tracking
  │   └── streaming.py         # Output streaming helpers
  ├── storage/
  │   ├── __init__.py
  │   ├── database.py          # Connection + schema init
  │   ├── module_repo.py       # Module CRUD
  │   ├── iteration_repo.py    # Iteration CRUD
  │   ├── requirement_repo.py  # Requirement CRUD
  │   ├── pipeline_repo.py     # Pipeline state CRUD
  │   └── models.py            # Pydantic data models
  ├── api/
  │   └── ...
  ├── frontend/
  │   └── ...
  ├── data/
  │   ├── modules/
  │   ├── prompts/
  │   ├── reviews/
  │   ├── summaries/
  │   └── state/
  └── __main__.py
  ```
- Virtual environment setup

### 1.2 Configuration System

- `config/schema.py` — Pydantic models for all config sections
- `config/loader.py` — YAML file loading with validation
- `config.yaml` — default configuration file
- All values that could change live here. Zero hardcoded values in code.

### 1.3 Data Models

- `storage/models.py` — Pydantic models and enums:
  - `PipelineStatus` (17 states)
  - `ModuleStatus`, `IterationStatus`, `RequirementType`
  - `ModuleRecord`, `IterationRecord`, `RequirementRecord`, `PipelineState`

### 1.4 Deliverables

- Project installable via `pip install -e .`
- Config loads and validates from YAML
- All data models defined
- Directory structure in place

---

## PHASE 2: Storage Layer

**Goal**: SQLite persistence with clean repository pattern — one file per domain.

### 2.1 Database Connection

- `storage/database.py` — connection management, schema initialization, WAL mode
- Singleton pipeline_state row auto-created

### 2.2 Repository Classes (one per table)

- `storage/module_repo.py` — `ModuleRepository` class: upsert, get, get_all, update_status
- `storage/iteration_repo.py` — `IterationRepository` class: create, update, get, get_for_module
- `storage/requirement_repo.py` — `RequirementRepository` class: upsert, get_all, get_by_type
- `storage/pipeline_repo.py` — `PipelineRepository` class: get_state, save_state

Each repository takes a `sqlite3.Connection` and does ONLY its own table's operations.

### 2.3 Deliverables

- All 4 SQLite tables created
- Full CRUD for each table via clean repository classes
- Each repo file < 100 lines
- State persists across process restarts

---

## PHASE 3: Agent Communication Bus

**Goal**: Build the parallel message-passing system that all agents use.

### 3.1 Core Bus

- `comms/bus.py` — `AgentCommBus` class:
  - `publish(channel, message)` — send message to a channel
  - `subscribe(channel, callback)` — register listener
  - `unsubscribe(channel, callback)` — remove listener
  - Uses `asyncio.Queue` per subscriber for non-blocking delivery
  - Thread-safe (agents run in threads/subprocesses)

### 3.2 Channel Definitions

- `comms/channels.py` — `Channel` enum with all channel names
- Type-safe channel → message type mapping

### 3.3 Message Types

- `comms/messages.py` — Pydantic models for each message type:
  - `AgentMessage` (base: channel, sender, timestamp, module_id, iteration, correlation_id, payload)
  - `ModuleUpdateMessage`, `PromptReadyMessage`, `GenerationStatusMessage`
  - `ValidationResultMessage`, `ReviewFeedbackMessage`
  - `HITLRequestMessage`, `HITLResponseMessage`
  - `PipelineEventMessage`, `ErrorAlertMessage`, `HeartbeatMessage`

### 3.4 Deliverables

- Comm Bus runs in background thread
- Agents can publish/subscribe without blocking each other
- Messages are typed and validated
- All messages logged for debugging

---

## PHASE 4: Orchestrator State Machine

**Goal**: The central brain — state transitions, handler dispatch, crash recovery.

### 4.1 State Machine

- `orchestrator/engine.py` — `Orchestrator` class:
  - Owns: config, db, state_manager, comm_bus, codex_wrapper
  - `run()` — main loop, dispatches to handlers
  - < 200 lines — delegates to handlers.py

### 4.2 State Management

- State transitions with validation (allowed transitions map)
- Persistence to DB after every transition
- Crash recovery: read last state on startup, resume
- Event emission on every transition (via Comm Bus)
- HITL gate detection

### 4.3 Step Handlers

- `orchestrator/handlers.py` — one function per state:
  - `handle_idle()`, `handle_loading_requirements()`, etc.
  - Each handler is a standalone function, not a method on a god class
  - Handlers receive a context object with references to db, bus, codex, config

### 4.4 Decision Logic

- `orchestrator/decision.py` — convergence rules:
  - Max iteration cap
  - Severity-based convergence (no high/critical = accept)
  - Per-file action aggregation

### 4.5 CLI Entry Point

- `orchestrator/cli.py` — argument parsing separated from engine logic
- Commands: `--status`, `--auto`, `--approve`, `--reset`, `--with-api`
- `__main__.py` delegates to `cli.py`

### 4.6 Deliverables

- Full state machine with 17 states
- All transitions validated
- Crash recovery from any state
- HITL gates pause the pipeline
- `--approve` resumes from HITL gate
- `--auto` bypasses HITL gates
- All handlers are stubs (wired in later phases)

---

## PHASE 5: Codex CLI Wrapper

**Goal**: Robust subprocess management for Codex CLI invocations.

### 5.1 Core Wrapper

- `codex/wrapper.py` — `CodexWrapper` class:
  - `execute(prompt, working_dir, session_type)` → `CodexResult`
  - Retry logic (configurable max retries)
  - Timeout management (kill PID on timeout)
  - Process exit code as primary completion signal

### 5.2 Session Management

- `codex/session.py` — `CodexSession` dataclass:
  - Tracks PID, process handle, session type
  - Active sessions registry
  - Kill session by type

### 5.3 Output Streaming

- `codex/streaming.py` — streaming helpers:
  - Pipe stdout/stderr to line buffers in threads
  - Callback hooks for real-time streaming (to Comm Bus and frontend)
  - Thread-safe line collection

### 5.4 Deliverables

- Codex wrapper can spawn `codex exec <prompt>`
- Captures output in real-time with callbacks
- Timeout kills the process cleanly
- Retry on failure (configurable)
- Each file < 150 lines

---

## PHASE 6: Requirements Ingestion

**Goal**: Parse requirements documents and structured epic/feature/story/AC files.

### 6.1 Requirements Parser

- `requirements/` (new folder):
  - `parser.py` — parse requirements.md + requirements.yaml
  - `validator.py` — validate structure (features have stories, stories have ACs)
  - `schema.py` — Pydantic models for epic/feature/story/AC hierarchy

### 6.2 Requirements Storage

- Store parsed requirements in `requirements` table via `RequirementRepository`
- Parent-child relationships (epic → feature → story → AC)

### 6.3 Deliverables

- YAML/JSON requirements file parsed and validated
- Stored in DB with hierarchy
- Can query: "What ACs belong to story S1?"

---

## PHASE 7: Module Maker

**Goal**: Codex CLI agent that decomposes requirements into structured module definitions.

### 7.1 Module Maker Runner

- `module_maker/runner.py` — `ModuleMakerRunner`:
  - Builds prompt from requirements + structured hierarchy
  - Invokes Codex wrapper
  - Parses output as JSON
  - Validates against module schema

### 7.2 Module Schema

- `module_maker/schema.py` — JSON schema for module definitions
- Validates: module_id, technical_spec, APIs, classes, functions, DB schemas

### 7.3 Dependency Graph

- `module_maker/dependency_graph.py`:
  - Generates `dependency_graph.json`
  - Topological sort for execution order
  - Validates no circular dependencies

### 7.4 Module 0 (Foundation)

- Automatically generates shared infrastructure module (DB, base models, middleware, config, logging)

### 7.5 HITL Gate 1

- Publishes module definitions on Comm Bus
- Pauses pipeline for human review
- Human can edit module JSONs via frontend Monaco Editor

### 7.6 Deliverables

- Module Maker produces valid structured JSON from requirements
- Dependency DAG generated and validated
- Module 0 always generated first
- HITL gate pauses for human module editing

---

## PHASE 8: Prompt Generator

**Goal**: Convert module definitions into detailed, framework-based prompts.

### 8.1 Framework Templates

- `prompt_generator/templates/` — one template per framework:
  - `rctcf.md`, `risen.md`, `costar.md`, `custom.md`
- `prompt_generator/frameworks.py` — framework selection + template loading (from config dropdown)

### 8.2 Prompt Builder

- `prompt_generator/runner.py` — `PromptGeneratorRunner`:
  - Receives single module JSON (never multiple)
  - Fills template programmatically (file paths, function names, schemas from JSON — not LLM-generated)
  - Uses Codex CLI to flesh out natural-language sections only
  - Produces stamped `.md` file: `data/prompts/module-{id}/iteration-{n}.md`

### 8.3 Iteration Mode

- First iteration: full prompt from module JSON
- Subsequent iterations: receives review JSON from Comm Bus
  - `regenerate` files → rebuild full section
  - `patch` files → targeted fix instructions
  - `accept` files → "do not modify"

### 8.4 HITL Gate 2

- Publishes prompt on Comm Bus
- Frontend shows Monaco Markdown Editor with diff view (vs previous iteration)
- Human can edit prompt directly before approving

### 8.5 Deliverables

- Prompt Generator produces framework-based prompts
- Template-driven (switchable via config)
- Iteration mode handles review feedback
- HITL gate with frontend editor

---

## PHASE 9: Code Generator + Completion Detection

**Goal**: Code generation from prompts with robust completion detection.

### 9.1 Code Generator Runner

- `code_generator/runner.py` — `CodeGeneratorRunner`:
  - Reads prompt from stamped file
  - Prepends guardrail prompt (from `code_generator/guardrails.py`)
  - Invokes Codex wrapper in project root directory
  - Bounded autonomy: tactical decisions allowed, structural decisions forbidden

### 9.2 Guardrails

- `code_generator/guardrails.py`:
  - System prompt defining scope and boundaries
  - What Code Generator MAY do (naming, error messages, minor implementation choices)
  - What Code Generator MUST NOT do (new files, new endpoints, schema changes)

### 9.3 Completion Detection

- **Primary**: Process exit code (PID tracking)
- **Secondary**: Check summary.md at expected path with END marker
- **Fallback**: Process exits 0 but no summary → partial completion → retry once
- Parse summary.md → store in DB → delete file

### 9.4 Deliverables

- Code Generator produces code in project directory
- Guardrails enforced
- Dual completion detection
- Summary parsed and stored

---

## PHASE 10: Validation Layer

**Goal**: Deterministic validation — hard data before code review.

### 10.1 Validation Orchestrator

- `validation/runner.py` — `ValidationRunner`:
  - Runs each tool as subprocess
  - Collects results into structured JSON
  - Publishes results on Comm Bus (streaming — each tool result published as completed)

### 10.2 Individual Validators

- `validation/linter.py` — ruff/flake8 wrapper → JSON output
- `validation/type_checker.py` — mypy wrapper → JSON output
- `validation/test_runner.py` — pytest wrapper → JSON output
- `validation/security.py` — bandit wrapper → JSON output
- `validation/dependency_checker.py` — pip install check

### 10.3 Deliverables

- All validators run and produce structured JSON
- Results published on Comm Bus for Code Reviewer to consume in parallel
- Aggregated validation JSON stored per iteration

---

## PHASE 11: Code Reviewer

**Goal**: Structured code review using validation data + diff + acceptance criteria.

### 11.1 Code Reviewer Runner

- `code_reviewer/runner.py` — `CodeReviewerRunner`:
  - Receives via Comm Bus: validation results, git diff, module spec, ACs, previous review
  - Does NOT modify code files — produces structured JSON only
  - Invokes Codex CLI with scoped input

### 11.2 Review Schema

- `code_reviewer/schema.py`:
  - Per-file actions: `accept`, `patch`, `regenerate`
  - Per-issue: id, severity, category, line_range, issue, suggested_fix
  - AC verification: pass/fail per acceptance criteria
  - Review area scores (design, security, tests, performance, etc.)
  - Convergence score (0-100)

### 11.3 Review Feedback on Comm Bus

- Publishes `review_feedback` to ALL agents simultaneously:
  - Prompt Generator → for next iteration prompt
  - Module Maker → for downstream module updates
  - Orchestrator → for decision logic
  - Frontend → for display

### 11.4 HITL Gate 3

- Review panel in frontend:
  - Severity badges (color-coded)
  - Per-file issue breakdown
  - AC pass/fail status
  - Override buttons (change severity, change action)
  - [Approve] / [Force Accept] / [Request More Iterations]

### 11.5 Deliverables

- Code Reviewer produces structured JSON per iteration
- Feedback sent to all agents in parallel via Comm Bus
- HITL gate with interactive review panel in frontend
- Review JSONs stored: `data/reviews/module-{id}/iteration-{n}.json`

---

## PHASE 12: Iteration Loop + Decision Logic

**Goal**: Wire the full generate → validate → review → iterate cycle.

### 12.1 Full Loop Wiring

- Orchestrator handles:
  - DECISION state → check convergence → iterate or accept
  - PROMPT_GENERATION on iteration > 1 → Prompt Generator in iteration mode
  - Max iterations → HITL Gate 4

### 12.2 Decision Logic

```python
# orchestrator/decision.py
def decide(review_json, iteration, max_iterations, convergence_rule):
    if review_json["overall_status"] == "accepted":
        return "MODULE_COMPLETE"
    if iteration >= max_iterations:
        return "HITL_4_MAX_ITERATIONS"
    has_blocking = any(
        issue["severity"] in ("critical", "high")
        for f in review_json["files"]
        for issue in f.get("issues", [])
    )
    if not has_blocking:
        return "MODULE_COMPLETE"
    return "ITERATE"
```

### 12.3 Deliverables

- Full iteration loop functional
- Convergence detection works
- Max iteration cap enforced
- Single module can go through generate → validate → review → iterate → accept

---

## PHASE 13: Git Integration + Module Sequencing

**Goal**: Proper Git workflow and multi-module pipeline.

### 13.1 Git Strategy

```
main (stable)
  └── dev (integration)
       ├── feature/module-M0-foundation
       ├── feature/module-M1-user-registration
       └── ...
```

### 13.2 Git Operations (via GitHub MCP)

- `git_ops/branch_manager.py` — create, switch, delete branches
- `git_ops/commit_manager.py` — commit per iteration, tag per module
- `git_ops/pr_manager.py` — create PRs, merge, add comments

### 13.3 GitHub MCP Setup

- Configure Codex CLI with GitHub MCP plugin
- `GITHUB_TOKEN` from environment (set in config, never hardcoded)
- Orchestrator's git_ops/ wraps all GitHub operations

### 13.4 Multi-Module Sequencing

- Read `dependency_graph.json`
- Process in topological order
- Before starting Module N:
  - Verify all dependencies completed
  - Extract actual interfaces from completed code
  - Pass as dependency context to Prompt Generator

### 13.5 Integration Testing

- After module completes: regression tests, import checks, API contract validation
- Integration failure → route back to prompt generation

### 13.6 HITL Gate 5

- PR review in frontend before merge
- Git panel with branch visualization, commit history, PR diff

### 13.7 Deliverables

- Feature branches per module
- Commits per iteration, PRs per module
- GitHub MCP plugin configured and functional
- Multi-module sequencing with dependency awareness
- Integration tests run between modules

---

## PHASE 14: Backend API + Frontend Dashboard

**Goal**: Full visibility and control via web interface.

### 14.1 Backend API (FastAPI)

REST endpoints for: requirements, modules, iterations, prompts, reviews, pipeline state, metrics.
WebSocket endpoints for: terminal streaming, pipeline events, HITL notifications.

**WebSocket-to-CommBus Bridge**: All Comm Bus messages forwarded to WebSocket clients. Frontend subscribes to channels it cares about.

### 14.2 Frontend (React + Tailwind + Framer Motion)

**Tech Stack**: React 18+, Tailwind, Framer Motion, xterm.js, Monaco Editor, Recharts, React Router.

**Tabs**:
1. **Pipeline View** — module cards, iteration progress, convergence trends
2. **Terminal Streams** — 4 xterm.js panels (Module Maker, Prompt Gen, Code Gen, Reviewer)
3. **Code Insights** — review JSON rendered, severity badges, AC pass/fail
4. **Prompt Editor (HITL)** — Monaco Markdown Editor with diff view, approve/edit buttons
5. **Module Editor (HITL)** — Monaco JSON Editor with schema validation
6. **Review Editor (HITL)** — interactive review panel with override controls
7. **Git & History** — branch viz, commit log, PR status
8. **Metrics** — token usage, time per iteration, cost tracking

**HITL in Frontend**: When pipeline pauses at any HITL gate, frontend shows:
- Notification banner (which gate, which module)
- Auto-opens relevant editor tab
- User edits using Monaco Editor (JSON for modules, Markdown for prompts)
- [Approve] / [Edit & Approve] / [Reject] buttons
- On approve → WebSocket message → Comm Bus → orchestrator resumes

**Design**: Dark theme, glass-morphism cards, Framer Motion animations, gradient accents.

### 14.3 Deliverables

- FastAPI backend with REST + WebSocket
- React frontend with 8 tabs
- Real-time terminal streaming
- HITL gates fully interactive with Monaco editors
- Metrics dashboard

---

## PHASE 15: Hardening, Error Handling, Optimization

**Goal**: Production readiness.

### 15.1 Error Handling

| Failure | Detection | Response |
|---------|-----------|----------|
| Codex CLI crash | Non-zero exit | Retry (configurable), then HITL-4 |
| Codex CLI hang | Timeout | Kill PID, retry |
| Partial generation | Exit 0, no summary | Retry once |
| Validation tool error | Subprocess error | Skip tool, note in context |
| Git conflict | Merge failure | Pause, HITL notification |
| Network error | HTTP error | Retry with backoff |
| Invalid JSON from reviewer | Parse error | Retry with "output must be valid JSON" |

### 15.2 Rollback

- Git commit checkpoint at each iteration start
- Catastrophic failure → `git reset --hard` to last clean commit
- DB state ensures no orphaned state

### 15.3 Token/Cost Budget

- Track per-iteration token usage
- Budget caps per module (configurable)
- Alert at 80%, pause at 100%
- Cumulative cost chart in frontend

### 15.4 Dependency Management

- Auto-create venv for generated project
- `pip install -r requirements.txt` after each iteration
- Install failure → add to reviewer context

### 15.5 Optimization

- Prompt framework A/B testing
- Reviewer self-improvement (historical accuracy tracking)
- Module parallelization for independent modules (future)

### 15.6 Deliverables

- All error modes handled with retry/rollback
- Token tracking + budget enforcement
- Dependency management automated
- System stable for real-world usage

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
CONSTRAINTS: Do not create files not listed, follow SOLID...
FORMAT: Generate code files at specified paths. After completion, generate summary.md...
```

### RISEN (Role, Instructions, Steps, End goal, Narrowing)
```
ROLE: Senior Python developer
INSTRUCTIONS: Build the user registration feature...
STEPS: 1. Create app/models/user.py... 2. Create app/api/auth.py...
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

## Appendix D: Agent Communication Message Examples

### ModuleUpdateMessage
```json
{
  "channel": "module_updates",
  "sender": "module_maker",
  "timestamp": "2026-04-22T10:00:00Z",
  "module_id": "M1",
  "iteration": 0,
  "correlation_id": "abc-123",
  "payload": {
    "action": "created",
    "module_definition": { ... }
  }
}
```

### ReviewFeedbackMessage (sent to ALL agents simultaneously)
```json
{
  "channel": "review_feedback",
  "sender": "code_reviewer",
  "timestamp": "2026-04-22T11:30:00Z",
  "module_id": "M1",
  "iteration": 2,
  "correlation_id": "def-456",
  "payload": {
    "overall_status": "needs_changes",
    "convergence_score": 72,
    "files": [ ... ],
    "ac_verification": { ... }
  }
}
```

### HITLRequestMessage
```json
{
  "channel": "hitl_requests",
  "sender": "orchestrator",
  "timestamp": "2026-04-22T10:05:00Z",
  "module_id": "M1",
  "iteration": 1,
  "correlation_id": "ghi-789",
  "payload": {
    "gate": "HITL_2_PROMPT_REVIEW",
    "artifact_path": "data/prompts/module-M1/iteration-1.md",
    "artifact_type": "prompt",
    "message": "Prompt for Module M1 ready for review"
  }
}
```
