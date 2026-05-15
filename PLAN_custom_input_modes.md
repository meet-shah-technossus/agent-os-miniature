# Implementation Plan: Custom Input Modes

## Overview

Two new pipeline input modes to complement the existing hardcoded `requirements.yaml` flow:

| Mode | Input | Pipeline Start Point | Module Maker? |
|------|-------|---------------------|---------------|
| **Mode A** (existing) | Hardcoded `requirements.yaml` in config | Module Maker | Yes |
| **Mode B** (new) | User-selected local `requirements.yaml` | Module Maker | Yes |
| **Mode C** (new) | GitHub repo URL + user-selected `requirements.yaml` | Code Reviewer (fork → clone → review) | No |

---

## Phase 1 — Custom Requirements File Selection (Mode B)

**Goal**: Let the user pick any local `.yaml` file as requirements input from the UI, instead of only using the path hardcoded in `config.yaml`.

### 1.1 Backend — Requirements Upload/Select API

**File**: `agent_os/api/routes/requirements.py`

- Add `POST /api/requirements/upload` endpoint:
  - Accepts a YAML file via `UploadFile` (multipart form-data).
  - Saves the file to a canonical location: `data/requirements/<original_filename>` (inside the Agent OS data directory).
  - Validates the YAML using `RequirementsDocument.model_validate()` — returns 422 if invalid.
  - Updates `config.requirements.path` in-memory to point to the saved file.
  - Persists the new path to `config.yaml` via the existing `_write_config_yaml()` helper.
  - Returns `{ "success": true, "path": "<saved_path>", "stats": { epics, features, stories, acceptance_criteria } }`.

- Add `POST /api/requirements/select` endpoint:
  - Accepts `{ "path": "/absolute/or/relative/path.yaml" }` for selecting an already-existing local file.
  - Validates the file exists and is valid YAML.
  - Updates `config.requirements.path` and persists to `config.yaml`.
  - Returns same response shape as `/upload`.

### 1.2 Backend — Pipeline Start with Mode

**File**: `agent_os/api/routes/pipeline.py`

- Modify `POST /api/pipeline/start` to accept an optional `pipeline_mode` field in the request body:
  - `"standard"` (default) — current behavior: IDLE → LOADING_REQUIREMENTS → MODULE_PLANNING → ...
  - `"github_review"` — new Mode C flow (Phase 2).
- When `pipeline_mode` is `"standard"`, behavior is identical to today — it reads `config.requirements.path` (which the user may have changed via Phase 1.1).

### 1.3 Frontend — Requirements File Picker

**File**: `frontend/src/components/SettingsView.tsx` (or a new sub-component)

- Add a "Requirements File" section to the Settings page (or to a new "Pipeline Input" section on the Dashboard):
  - **File upload** button: opens a file picker, uploads `.yaml` file via `POST /api/requirements/upload`.
  - **File path input**: text field for entering/pasting a local path, calls `POST /api/requirements/select`.
  - Shows the currently configured path (from settings GET) and a validation status badge (valid/invalid/not-loaded).
  - On successful upload/select, show a brief summary: "4 epics, 12 features, 28 stories, 45 ACs".

### 1.4 Validation & Edge Cases

- If the user uploads a new `requirements.yaml` while the pipeline is running or paused at an HITL gate, the upload endpoints should return a 409 Conflict ("pipeline is active — reset or complete before changing requirements").
- File size limit: reject files > 1 MB.
- Only `.yaml` / `.yml` extensions accepted.

---

## Phase 2 — GitHub Repo + Requirements Review Mode (Mode C)

**Goal**: User provides a GitHub repo URL + a requirements YAML. The pipeline forks the repo, clones it locally, then enters a Code Review → Prompt Gen → Code Gen → Code Review loop (no Module Maker).

### 2.1 Config Schema — Pipeline Mode

**File**: `agent_os/config/schema.py`

- Add a `pipeline_mode` field to `AgentOSConfig` (or to `OrchestratorConfig`):
  ```python
  pipeline_mode: str = "standard"  # "standard" | "github_review"
  ```
- Add a `github_review` config section (new Pydantic model `GitHubReviewConfig`):
  ```python
  class GitHubReviewConfig(BaseModel):
      source_repo_url: str = ""        # e.g. "https://github.com/owner/repo"
      requirements_path: str = ""      # local path to requirements.yaml for this review
      fork_repo_name: str = ""         # override fork name (default: <repo>-agent-os)
      branch_name: str = "agent-os-fixes"  # branch for changes
  ```

### 2.2 Backend — GitHub Fork & Clone

**File**: `agent_os/github/client.py`

- Add `fork_repo(owner: str, repo: str) -> GitHubResult` method:
  - `POST /repos/{owner}/{repo}/forks` via GitHub API.
  - Returns the fork's full name (`<authenticated_user>/<repo>`).
  - Handles "fork already exists" (HTTP 202 with existing fork info).

**File**: `agent_os/git_ops/manager.py`

- Add `clone(url: str, dest: str, depth: int = 0) -> CommandResult` method:
  - Runs `git clone <url> <dest>` (with optional `--depth`).
  - Embeds the token in the URL for authentication: `https://x-access-token:{token}@github.com/...`.

### 2.3 Pipeline State Machine — New Entry Path

**File**: `agent_os/storage/models.py`

- Add new pipeline statuses:
  ```python
  GITHUB_FORK_CLONE = "github_fork_clone"       # Fork and clone the source repo
  INITIAL_CODE_REVIEW = "initial_code_review"    # First code review against requirements
  ```

**File**: `agent_os/orchestrator/state.py`

- Add transitions for the new states:
  ```
  IDLE → LOADING_REQUIREMENTS   (standard mode — existing)
  IDLE → GITHUB_FORK_CLONE      (github_review mode — new)

  GITHUB_FORK_CLONE → INITIAL_CODE_REVIEW | FAILED

  INITIAL_CODE_REVIEW → PROMPT_GENERATION | FAILED
  ```
- From `PROMPT_GENERATION` onward, the flow is identical to the existing pipeline — Code Gen → Validation → Code Review → Decision → iterate or complete.

### 2.4 Backend — New Handlers

**File**: `agent_os/orchestrator/handlers.py`

#### `handle_idle()` — Modify

- Check `ctx.config.pipeline_mode`:
  - `"standard"` → transition to `LOADING_REQUIREMENTS` (existing).
  - `"github_review"` → transition to `GITHUB_FORK_CLONE` (new).

#### `handle_github_fork_clone()` — New

This handler:
1. **Reads config**: `ctx.config.github_review.source_repo_url` — parse `owner/repo` from URL.
2. **Resolves GitHub token**: same pattern as `_ensure_remote_repo()`.
3. **Forks the repo**: call `GitHubClient.fork_repo(owner, repo)`.
4. **Determines local project folder**: Use the repo name (from the URL) as the folder name, e.g. `~/Projects/<repo-name>/`. Set `ctx.config.project.root_path` to this folder. Create the folder if it doesn't exist.
5. **Clones the fork locally**: `git clone https://x-access-token:{token}@github.com/{authenticated_user}/{fork_name}.git <local_folder>`.
6. **Sets `config.github.owner` and `config.github.repo`**: to the fork's owner/repo so that subsequent pushes go to the fork (not the original).
7. **Loads requirements**: Parses the requirements YAML (`ctx.config.github_review.requirements_path`) into the DB via `RequirementsParser.load_and_store()`.
8. **Creates branch**: `git checkout -b agent-os-fixes` (configurable branch name).
9. **Publishes events**: TerminalOutputMessage with fork/clone progress for Terminal Hub.
10. **Transitions to** `INITIAL_CODE_REVIEW`.

#### `handle_initial_code_review()` — New

This handler performs a requirements-aware code review of the entire forked codebase:

1. **Builds a synthetic "module" definition** that represents the entire codebase:
   - `module_id = "full-repo-review"`
   - `file_paths` = all source files in the cloned repo (filtered by common patterns, excluding `.git/`, `node_modules/`, etc.)
   - `description` = "Full repository code review against requirements"
   - `technical_spec` = loaded from the requirements YAML (epics/features/stories summary)
2. **Invokes `CodeReviewerRunner.run()`** with this synthetic module definition and an augmented system prompt that adds requirements-alignment review criteria:
   - Business logic alignment with requirements
   - Project structure / clean architecture
   - Missing features from requirements
   - Existing bugs / code quality issues
3. **Stores the review result** in `data/reviews/full-repo-review/iteration-1.json`.
4. **Converts the review into a `ReviewFeedback`** object (same schema the Prompt Generator expects).
5. **Sets pipeline state metadata**: 
   - `current_module_id = "full-repo-review"`
   - `current_iteration = 1`
   - Store the ReviewFeedback in metadata so Prompt Generator can consume it.
6. **Transitions to** `PROMPT_GENERATION`.

From this point, the standard pipeline takes over:
- **Prompt Generator** (iteration 2+ path) sees the review feedback and generates a fixes-only prompt.
- **Code Generator** applies fixes to the locally cloned code.
- **Code Reviewer** reviews the changes (standard iteration review, not the initial full-repo review).
- **Decision** → iterate or accept.
- **Git Commit** → pushes to the fork.

### 2.5 Handler Registry Update

**File**: `agent_os/orchestrator/handlers.py`

Add the two new handlers to `HANDLER_REGISTRY`:

```python
HANDLER_REGISTRY = {
    ...
    PipelineStatus.GITHUB_FORK_CLONE: handle_github_fork_clone,
    PipelineStatus.INITIAL_CODE_REVIEW: handle_initial_code_review,
    ...
}
```

### 2.6 Frontend — GitHub Review Mode UI

**File**: `frontend/src/components/SettingsView.tsx` or `DashboardView.tsx`

- Add a "Pipeline Mode" selector (radio buttons or toggle):
  - **Standard** (default): "Generate code from requirements" — shows the requirements file picker (Phase 1).
  - **GitHub Review**: "Review & improve an existing repo" — shows:
    - GitHub repo URL text field.
    - Requirements file upload/select (same component from Phase 1).
    - Optional: fork name override, branch name.
- The "Start Pipeline" button sends `pipeline_mode` to `POST /api/pipeline/start`.

**File**: `frontend/src/components/WorkflowView.tsx`

- Update the pipeline visualization to show the new states (`GITHUB_FORK_CLONE`, `INITIAL_CODE_REVIEW`) when in `github_review` mode.

### 2.7 API Endpoint Updates

**File**: `agent_os/api/routes/pipeline.py`

- Modify `POST /api/pipeline/start` request body:
  ```python
  class StartPipelineRequest(BaseModel):
      pipeline_mode: str = "standard"           # "standard" | "github_review"
      requirements_path: str | None = None      # override for requirements file
      source_repo_url: str | None = None        # for github_review mode
  ```
- Before starting the pipeline thread:
  - If `pipeline_mode == "github_review"`, validate that `source_repo_url` is provided, GitHub token is configured, and requirements path is valid.
  - Update `config.pipeline_mode`, `config.github_review.*` in-memory.
  - Persist to `config.yaml`.

**File**: `agent_os/api/routes/settings.py`

- Extend `PUT /api/settings` to accept the new `github_review` config section.

---

## Phase 3 — Code Reviewer Enhancements for Initial Review

**Goal**: Extend the Code Reviewer to handle a full-repo requirements-alignment review (deeper than its current per-module review).

### 3.1 Initial Review System Prompt

**File**: `agent_os/code_reviewer/runner.py`

- Add a new method `run_initial_review()` (or pass a `review_mode="initial"` flag to `run()`):
  - Uses a different system prompt (`_INITIAL_REVIEW_SYSTEM_PROMPT`) optimized for full-repo review:
    - **Requirements alignment**: Does the code implement what the requirements specify? What's missing?
    - **Architecture review**: Project structure, separation of concerns, clean architecture principles.
    - **Code quality**: Bugs, security issues, performance, test coverage.
    - **Improvement priorities**: Rank findings by impact — what should be fixed first?
  - The JSON output schema is the same `CodeReviewResult` (same downstream compatibility).
  - `files` array covers all files in the repo (not just a module's expected files).

### 3.2 Requirements Context in Review Prompt

- The initial review prompt includes the full requirements document (epics → features → stories → ACs) so the reviewer can check alignment.
- For subsequent iteration reviews (standard Code Review), the requirements context is NOT included (same as today) — the prompt generator has already incorporated them into the fix prompt.

---

## Phase 4 — Iteration Flow Adjustments for GitHub Review Mode

**Goal**: Make sure the Prompt Generator → Code Generator → Code Reviewer iteration loop works correctly when there's no Module Maker output.

### 4.1 Prompt Generator — Handle "full-repo-review" Module

**File**: `agent_os/prompt_generator/runner.py`

- When `module_def.module_id == "full-repo-review"` (or a flag indicates github_review mode):
  - Iteration 1: The "initial code review" has already happened. The prompt generator receives the review feedback and generates a comprehensive fix prompt (same as current iteration 2+ path — `_generate_fixes_prompt()`).
  - There is **no** iteration-1 "implementation prompt" in this mode since the code already exists.

### 4.2 Code Generator — Apply Fixes to Existing Code

- The code generator already applies changes to files in `working_dir`. No changes needed — it naturally modifies existing files when the prompt says "fix X in file Y".
- Verify that `working_dir` is set to the cloned repo path (`config.project.root_path`).

### 4.3 Subsequent Code Reviews

- After the code generator applies fixes, the standard `handle_code_review()` handler runs.
- It already reads files from `working_dir` and reviews them.
- The `module_def` for "full-repo-review" has `file_paths` = all repo files → reviewer sees all changes.

### 4.4 Decision Handler — No Module Completion in GitHub Mode

**File**: `agent_os/orchestrator/handlers.py` — `handle_decision()`

- In `github_review` mode, after the code is accepted:
  - Git commit & push to the fork.
  - Transition to `PIPELINE_COMPLETE` (not `NEXT_MODULE` — there's only one "module").
- If iterating, transition to `PROMPT_GENERATION` (same as today).

### 4.5 handle_next_module — Short-circuit for GitHub Mode

**File**: `agent_os/orchestrator/handlers.py` — `handle_next_module()`

- If `pipeline_mode == "github_review"`:
  - No more modules to pick — transition directly to `PIPELINE_COMPLETE`.

---

## Phase 5 — Testing & Polish

### 5.1 Unit Tests

- **Requirements upload**: Test file upload, validation, path persistence.
- **Fork & clone**: Mock `GitHubClient.fork_repo()` and `git clone` subprocess, verify local folder creation and config updates.
- **Initial code review**: Verify synthetic module definition construction, requirements-aware prompt, review result storage.
- **Pipeline flow**: End-to-end state transitions for `github_review` mode: IDLE → GITHUB_FORK_CLONE → INITIAL_CODE_REVIEW → PROMPT_GENERATION → CODE_GENERATION → ... → PIPELINE_COMPLETE.
- **Edge cases**: Fork already exists, clone fails, no GitHub token, invalid requirements YAML, empty repo.

### 5.2 Frontend Polish

- Pipeline mode selector: clear UX with descriptions for each mode.
- Progress indicators for fork/clone operations (streamed to Terminal Hub).
- Workflow visualization shows correct states for the active mode.

### 5.3 Config Persistence

- Ensure `pipeline_mode` and `github_review.*` survive backend restarts (written to `config.yaml`).
- Ensure switching back to `"standard"` mode works cleanly.

---

## Implementation Order

| Order | Phase | Description | Estimated Scope |
|-------|-------|-------------|-----------------|
| 1 | Phase 1 | Custom requirements file selection | 2 files backend, 1 file frontend |
| 2 | Phase 2.1–2.2 | Config schema + fork/clone capabilities | 3 files backend |
| 3 | Phase 2.3–2.5 | Pipeline states, handlers, registry | 3 files backend |
| 4 | Phase 3 | Code reviewer initial review enhancements | 1 file backend |
| 5 | Phase 4 | Iteration flow adjustments | 3 files backend |
| 6 | Phase 2.6–2.7 | Frontend UI + API updates | 2 files frontend, 1 file backend |
| 7 | Phase 5 | Testing & polish | Test files + UI refinements |

---

## Files Modified/Created Summary

### Modified Files
| File | Changes |
|------|---------|
| `agent_os/config/schema.py` | Add `GitHubReviewConfig`, `pipeline_mode` field |
| `agent_os/storage/models.py` | Add `GITHUB_FORK_CLONE`, `INITIAL_CODE_REVIEW` statuses |
| `agent_os/orchestrator/state.py` | Add transitions for new statuses |
| `agent_os/orchestrator/handlers.py` | Modify `handle_idle()`, add `handle_github_fork_clone()`, `handle_initial_code_review()`, update `HANDLER_REGISTRY`, adjust `handle_decision()` and `handle_next_module()` |
| `agent_os/github/client.py` | Add `fork_repo()` method |
| `agent_os/git_ops/manager.py` | Add `clone()` method |
| `agent_os/code_reviewer/runner.py` | Add `run_initial_review()` with requirements-aware prompt |
| `agent_os/api/routes/pipeline.py` | Add `StartPipelineRequest`, mode handling |
| `agent_os/api/routes/requirements.py` | Add upload/select endpoints |
| `agent_os/api/routes/settings.py` | Support `github_review` config section |
| `agent_os/prompt_generator/runner.py` | Handle "full-repo-review" module (minor) |
| `frontend/src/components/SettingsView.tsx` | Pipeline mode selector, requirements file picker |
| `frontend/src/components/WorkflowView.tsx` | Show new pipeline states |

### New Files
| File | Purpose |
|------|---------|
| (none — all changes fit into existing files) | |
