# Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React + Vite)                  │
│  Dashboard │ Pipeline │ Agents │ Settings │ Terminal Grid    │
└───────────────────────────┬─────────────────────────────────┘
                            │ REST + WebSocket
┌───────────────────────────▼─────────────────────────────────┐
│                    FastAPI Backend (api/)                     │
│  routes/  │  schemas.py  │  websocket.py  │  deps.py        │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   Orchestrator (orchestrator/)                │
│  engine.py ── state.py ── emitter.py ── story_queue.py      │
└──┬────────────┬────────────┬────────────┬───────────────────┘
   │            │            │            │
   ▼            ▼            ▼            ▼
┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
│ Prompt │ │   Code   │ │   Code   │ │  Git Ops /   │
│ Gen    │ │Generator │ │ Reviewer │ │  VCS Client  │
└────────┘ └──────────┘ └──────────┘ └──────────────┘
   │            │            │            │
   └────────────┴────────────┴────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     Codex Wrapper (codex/)                    │
│  wrapper.py ── session.py ── cli_adapter.py ── streaming.py │
└─────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                    Storage Layer (storage/)                   │
│  database.py ── models.py ── pipeline_repo ── iteration_repo│
└─────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

| Module | Purpose |
|--------|---------|
| `api/` | FastAPI routes, WebSocket broadcast, request schemas |
| `orchestrator/` | Pipeline state machine, event emission, story queue |
| `code_generator/` | Prompt → Codex CLI → file output, guardrails |
| `code_reviewer/` | LLM-based code review with structured JSON output |
| `prompt_generator/` | Builds iteration prompts from requirements + context |
| `codex/` | Wraps Codex CLI / API tools (copilot, gemini, etc.) |
| `storage/` | SQLite persistence, repository pattern, migrations |
| `config/` | YAML config loading, schema validation, env vars |
| `git_ops/` | Git commit, branch, push operations |
| `vcs/` | VCS abstraction (GitHub, Azure DevOps) |
| `agents/` | Agent registry, brain memory, agent store |
| `requirements/` | YAML requirements parsing and validation |
| `github_input/` | Clone repos from GitHub for analysis |

## Data Flow

1. **Requirements** → parsed from YAML → stored in SQLite
2. **Orchestrator** advances state machine through pipeline stages
3. **Prompt Generator** builds context-rich prompts per iteration
4. **Code Generator** invokes CLI tool (Codex/Copilot/Gemini)
5. **Code Reviewer** evaluates output, produces structured review
6. **Git Ops** commits changes, pushes branches, creates PRs
7. **WebSocket** streams real-time events to the frontend
