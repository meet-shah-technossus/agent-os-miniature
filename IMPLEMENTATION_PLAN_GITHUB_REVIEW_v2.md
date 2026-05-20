# Implementation Plan: GitHub Review Mode Pipeline Overhaul

## Current State Assessment

### What Exists Today
- **GitHub Review Mode** is a **configuration stub only** — the UI collects repo URL, fork name, branch name, and requirements path, but the orchestrator treats it identically to standard mode.
- **No orchestrator involvement** — the orchestrator doesn't manage story queuing, dependency ordering, or per-story iteration loops.
- **Code generator creates new repos** — iteration 1 uses `create_repo()` + orphan baseline. There is no fork-based workflow.
- **No story queue UI** — the dashboard shows only pipeline status, iteration count, and HITL controls.
- **Requirements ingestion (Pipeline tab)** — only supports local file upload (Browse button). Unlike the Requirements tab, it doesn't offer ADO/Jira/Asana sources.
- **`__pycache__` bug** — `agent_os/agents/store.py:list_agents()` iterates `self._root.iterdir()` but only skips `"custom"` directories, so `__pycache__/` appears as an agent card in the UI.

### Corrected Current GitHub Review Workflow (what actually runs today)
1. User sets `pipeline_mode = "github_review"` in Settings → Pipeline tab.
2. User provides source repo URL, fork name, branch name.
3. User provides requirements file (local upload only).
4. Pipeline starts — **but runs identically to standard mode**:
   - `LOADING_REQUIREMENTS` → reads from `config.requirements.path` (ignores `github_review.requirements_path`).
   - `PROMPT_GENERATION` → generates implementation prompt from requirements.
   - `CODE_GENERATION` → creates a **new** repo (not a fork), orphan baseline, feature branch, PR.
   - `CODE_REVIEW` → reviews the PR diff, generates ReviewJSON.
   - Loop continues until acceptance.
5. The `github_input/cloner.py` utility exists but is **never called** by the orchestrator or code generator.

---

## Target Architecture

### New GitHub Review Pipeline Flow

```
User provides:  GitHub Repo URL + Requirements (stories with acceptance criteria)
                ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR                                                            │
│                                                                          │
│  1. Ingest requirements (stories + ACs)                                  │
│  2. Analyse dependencies between stories                                 │
│  3. Build ordered queue (topological sort by dependency)                 │
│  4. Fork the source repo (once, at pipeline start)                      │
│  5. Clone fork locally (once, at pipeline start)                        │
│                                                                          │
│  FOR EACH STORY IN QUEUE:                                                │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  STORY LOOP (iteration 1…N per story)                              │  │
│  │                                                                    │  │
│  │  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐       │  │
│  │  │   PROMPT     │ ──→ │    CODE      │ ──→ │    CODE      │       │  │
│  │  │  GENERATOR   │     │  GENERATOR   │     │   REVIEWER   │       │  │
│  │  └──────────────┘     └──────────────┘     └──────────────┘       │  │
│  │        ↑                                          │                │  │
│  │        └──────── ReviewJSON (if needs_work) ──────┘                │  │
│  │                                                                    │  │
│  │  Exit condition: code reviewer merges PR (status=accepted)         │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  Dequeue next story → repeat                                             │
│  All stories done → PIPELINE_COMPLETE                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### Per-Story Git Behaviour

| Action | Iteration 1 | Iteration 2+ |
|--------|-------------|--------------|
| Fork repo | Already done at pipeline start | N/A |
| Clone | Already done at pipeline start | N/A |
| Create branch | `story-{id}-{short-desc}` from `main` | Reuse existing branch |
| Code changes | Make changes locally | Make changes locally |
| Push | Push branch | Push branch |
| Create PR | From story branch → main | Already exists |
| Resolve comments | N/A | Resolve all existing comments |
| Code review | Review PR diffs, add comments | Review PR diffs, add comments |
| Merge | When accepted → merge + delete branch | When accepted → merge + delete branch |

---

## Phase-by-Phase Implementation

---

### Phase 0: Bug Fix — `__pycache__` in Agents Page

**Files Modified:**
- `agent_os/agents/store.py`

**Changes:**
1. In `list_agents()`, update the `if` condition on the directory iterator to also skip `__pycache__` and other standard ignore patterns (`__pycache__`, `.git`, `.mypy_cache`, etc.).
2. Delete the existing `agent_os/agents/__pycache__/` directory.
3. Add a `.gitignore` inside `agent_os/agents/` with `__pycache__/` to prevent future occurrences.

**Estimated Scope:** ~5 lines changed.

---

### Phase 1: Story Queue Data Model & Dependency Analysis

**Files Modified/Created:**
- `agent_os/orchestrator/story_queue.py` (NEW)
- `agent_os/orchestrator/state.py` (MODIFY — add queue state)
- `agent_os/storage/models.py` (MODIFY — add StoryQueue table)
- `agent_os/storage/database.py` (MODIFY — create table)

**Changes:**

1. **StoryQueue model** — New SQLite table:
   ```
   story_queue:
     id (PK), pipeline_id, story_id, title, description, acceptance_criteria (JSON),
     position (int), status (queued/in_progress/completed/failed),
     branch_name, pr_number, pr_url, iteration_count,
     depends_on (JSON list of story_ids), created_at, completed_at
   ```

2. **StoryQueueManager class** (`story_queue.py`):
   - `build_queue(stories: list[dict]) -> list[StoryQueueItem]` — takes parsed requirements stories, sends them to LLM (OpenAI) with prompt asking to determine dependencies and ordering, returns ordered list.
   - `enqueue(story) / dequeue() / peek() / mark_complete() / mark_failed()`
   - `get_queue_state() -> list[StoryQueueItem]` — for UI consumption.

3. **LLM dependency analysis prompt** — System prompt that receives all stories with their ACs and outputs a JSON ordering with dependency reasoning.

4. **State extension** — Add `current_story_id`, `story_queue` reference to `PipelineState`.

---

### Phase 2: Orchestrator Engine — Story-Aware Loop

**Files Modified:**
- `agent_os/orchestrator/engine.py` (MAJOR changes)
- `agent_os/orchestrator/state.py` (extend state transitions)

**Changes:**

1. **New pipeline states** for GitHub Review mode:
   ```
   IDLE → LOADING_REQUIREMENTS → ANALYSING_DEPENDENCIES → QUEUE_READY →
   [per-story loop]:
     STORY_PROMPT_GENERATION → STORY_CODE_GENERATION → STORY_CODE_REVIEW →
     (HITL gates as needed) →
     STORY_COMPLETE
   → PIPELINE_COMPLETE
   ```

2. **New step handlers:**
   - `_step_analyse_dependencies()` — calls StoryQueueManager.build_queue() using LLM
   - `_step_queue_ready()` — dequeues next story, sets current_story context
   - `_step_story_prompt_generation()` — same as current `_step_prompt_generation` but scoped to single story's ACs + ReviewJSON from previous iteration
   - `_step_story_code_generation()` — fork-aware (see Phase 3)
   - `_step_story_code_review()` — PR-based review (see Phase 4)
   - `_step_story_complete()` — marks story done, dequeues next or completes pipeline

3. **Mode dispatch** — `_loop()` checks `config.pipeline_mode`:
   - `"standard"` → existing dispatch table (unchanged)
   - `"github_review"` → new dispatch table with story-aware states

4. **Per-story iteration tracking** — Each story has its own iteration counter (separate from global pipeline iteration). Stored in StoryQueue table.

---

### Phase 3: Code Generator — Fork-Based Workflow

**Files Modified:**
- `agent_os/code_generator/runner.py` (MODIFY — add fork mode)
- `agent_os/github_input/cloner.py` (MODIFY — make fork+clone reusable)
- `agent_os/github/client.py` (MODIFY — add `fork_repo()` method)
- `agent_os/vcs/github_client.py` (MODIFY — add fork support to VCS abstraction)
- `agent_os/git_ops/manager.py` (MODIFY — clone-from-URL support)

**Changes:**

1. **Fork + Clone (once at pipeline start, called by orchestrator):**
   - `GitHubVCSClient.fork_repo(source_owner, source_repo) -> fork_url` — POST /repos/{owner}/{repo}/forks
   - `GitOpsManager.clone_from_url(url, target_dir)` — git clone to local folder (named after repo)
   - Orchestrator calls these in `_step_queue_ready()` (first story only) or in a dedicated `_step_fork_and_clone()` state.

2. **Per-story iteration 1 (code generator):**
   - Create branch from `main`: `git checkout -b story-{id}-{short-desc}`
   - Run CLI with prompt (existing guardrails preserved)
   - `git add -A && git commit -m "feat(story-{id}): {summary}"`
   - `git push -u origin story-{id}-{short-desc}`
   - Create PR: title = `[Story {id}] {title}`, body = acceptance criteria, base = `main`, head = story branch

3. **Per-story iteration 2+ (code generator):**
   - `git checkout story-{id}-{short-desc}`
   - Run CLI with prompt (contains review feedback)
   - `git add -A && git commit -m "fix(story-{id}): address review comments"`
   - `git push`
   - Resolve all PR review comments (existing `resolve_all_pr_review_comments()`)

4. **Branch naming convention:** `story-{id}-{slugified-title-max-40-chars}`

---

### Phase 4: Code Reviewer — PR-Based Review (No Local Code Access)

**Files Modified:**
- `agent_os/code_reviewer/runner.py` (MODIFY — fork-aware review)
- `agent_os/code_reviewer/schema.py` (MODIFY — add pr_number, pr_url to ReviewJSON)

**Changes:**

1. **Review via PR diff only** (already the case today):
   - `get_pr_diff(pr_number)` — fetches diff from GitHub API (existing)
   - LLM reviews against the 15-point checklist (existing)
   - Checks alignment with requirements/ACs (pass story's ACs in system prompt)

2. **ReviewJSON extension:**
   ```python
   class ReviewResult:
       # ... existing fields ...
       pr_number: int          # NEW — which PR was reviewed
       pr_url: str             # NEW — full PR URL
       story_id: str           # NEW — which story this belongs to
   ```

3. **Comment posting** (existing, no change needed):
   - Inline comments: `add_pr_review_comment(pr_number, file, line, body)`
   - Global comments: `add_pr_comment(pr_number, body)`

4. **Merge on acceptance** (existing, no change needed):
   - When `overall_status == "accepted"`: `merge_pr(pr_number, strategy="squash")`
   - Delete branch after merge

5. **Pass requirements context to reviewer:**
   - Orchestrator passes current story's acceptance criteria to reviewer
   - Reviewer's system prompt includes: "Validate that the implementation satisfies these acceptance criteria: {ACs}"

---

### Phase 5: Prompt Generator — Story-Scoped Prompts

**Files Modified:**
- `agent_os/prompt_generator/runner.py` (MODIFY — story context)
- `agent_os/prompt_generator/schema.py` (MODIFY if needed)

**Changes:**

1. **Iteration 1 prompt** (per story):
   - Input: story title, description, acceptance criteria, repo structure context
   - Output: comprehensive implementation prompt for this specific story
   - Include: "You are working on a forked repository. The code already exists. Make only the changes required for this story."

2. **Iteration 2+ prompt** (per story):
   - Input: ReviewJSON from code reviewer (contains comments, scores, PR reference)
   - Output: targeted fix prompt addressing review comments
   - Include PR context: "The PR #{pr_number} has the following review comments. Address each one."

3. **Existing behaviour preserved** — same LLM call pattern, same fallback templates, same archive path structure. Only the content/context changes.

---

### Phase 6: Pipeline Settings UI — Requirements Source for GitHub Review Mode

**Files Modified:**
- `frontend/src/components/SettingsView.tsx` (MODIFY — Pipeline tab)

**Changes:**

1. **When `pipelineMode === 'github_review'`**, show the same requirements source options as the Requirements tab:
   - Source selector: Local File | Azure DevOps | Jira | Asana
   - ADO: org + PAT + project dropdown (reuse `fetchAdoProjects` + `getAdoProjects` API)
   - Jira: URL + email + API token + project key
   - Asana: PAT + project GID
   - Local: file upload (existing)

2. **Reuse existing components/logic:**
   - The ADO project dropdown with fetch + auto-select (already implemented)
   - The requirements preview modal (reuse from Requirements tab)
   - The ingestion API calls (same `/api/requirements/ingest/*` endpoints)

3. **Additional fields (existing, keep):**
   - Source Repository URL
   - Fork Name Override (optional)
   - Branch Name prefix (default: `story-`)

4. **Remove** the single "Branch Name" field (branches are now auto-generated per story).

---

### Phase 7: Dashboard UI — Story Queue Visualization

**Files Modified:**
- `frontend/src/components/DashboardView.tsx` (MODIFY)
- `frontend/src/hooks/api.ts` (MODIFY — add queue API)
- `agent_os/api/routes/orchestrator.py` or similar (MODIFY — add queue endpoint)

**Changes:**

1. **New API endpoint:** `GET /api/orchestrator/story-queue`
   - Returns: `{ stories: [{ id, title, position, status, branch_name, pr_url, iteration_count, depends_on }] }`

2. **Dashboard layout (when in github_review mode):**
   ```
   ┌─────────────────────────────────────────────────────────────────┐
   │  LEFT PANEL (existing)        │  RIGHT PANEL                    │
   │                                │                                 │
   │  Pipeline Status: IN_PROGRESS  │  ┌─── Story Queue ───────────┐ │
   │  Mode: GitHub Review           │  │                            │ │
   │  Current Story: STORY-42       │  │  ✅ STORY-12 (merged)     │ │
   │  Story Iteration: 2/5          │  │  🔄 STORY-42 (iter 2)     │ │
   │                                │  │  ⏳ STORY-55 (queued)     │ │
   │  [▶ Start] [⏸ Pause]          │  │  ⏳ STORY-78 (queued)     │ │
   │  [✓ Approve]                   │  │  ⏳ STORY-91 (queued)     │ │
   │                                │  │                            │ │
   │  Fork: user/repo-fork          │  └────────────────────────────┘ │
   │  PR: #42 (open)                │                                 │
   │                                │  PipelineFlowDiagram (existing) │
   └─────────────────────────────────────────────────────────────────┘
   ```

3. **Story Queue component:**
   - Vertical list/timeline of stories in queue order
   - Each card shows: position, story ID, title (truncated), status badge, iteration count, PR link (if exists)
   - Status badges: `queued` (gray), `in_progress` (blue pulse), `completed` (green check), `failed` (red)
   - Dependency arrows or indentation to show which stories depend on others
   - Auto-refreshes via polling (same pattern as existing pipeline status polling)

4. **Story detail expansion:** Click a story card to see:
   - Full title + acceptance criteria
   - Branch name + PR URL (clickable)
   - Iteration history (brief)
   - Dependencies (which stories must complete first)

---

### Phase 8: Backend API Extensions

**Files Modified/Created:**
- `agent_os/api/routes/orchestrator.py` (MODIFY — new endpoints)
- `agent_os/api/schemas.py` (MODIFY — new response models)

**Changes:**

1. **New endpoints:**
   - `GET /api/orchestrator/story-queue` — returns full queue state
   - `GET /api/orchestrator/story-queue/{story_id}` — returns single story detail
   - `POST /api/orchestrator/story-queue/reorder` — (optional) manual reorder

2. **Extend existing endpoints:**
   - `GET /api/orchestrator/status` — add `current_story`, `stories_completed`, `stories_total`, `mode`
   - `POST /api/orchestrator/start` — when mode is github_review, trigger fork+clone+dependency analysis before loop starts

3. **WebSocket events** (extend existing):
   - `story_started`, `story_completed`, `story_failed` events for real-time queue updates
   - `queue_built` event after dependency analysis completes

---

### Phase 9: Integration Testing & Edge Cases

**Files Created:**
- `tests/test_github_review_pipeline.py` (NEW)
- `tests/test_story_queue.py` (NEW)

**Test Scenarios:**

1. **Story queue building:**
   - Stories with no dependencies → alphabetical/ID order
   - Stories with linear dependencies (A→B→C)
   - Stories with diamond dependencies
   - Single story (queue of 1)

2. **Fork workflow:**
   - Fork already exists (idempotent)
   - Clone already exists locally (resume after crash)
   - Branch already exists (resume mid-story)
   - PR already exists (resume mid-story iteration 2+)

3. **Per-story iteration loop:**
   - Code reviewer accepts on first iteration → merge, next story
   - Code reviewer rejects → prompt gen gets ReviewJSON → code gen fixes → reviewer re-reviews
   - Max iterations reached per story → mark failed, move to next
   - All stories complete → PIPELINE_COMPLETE

4. **Edge cases:**
   - Empty requirements (no stories) → error
   - Fork API rate limit → retry with backoff
   - PR merge conflict → mark story failed with clear error
   - Network loss mid-push → retry mechanism

---

## Dependency Graph Between Phases

```
Phase 0 (bug fix)           → independent, do first
Phase 1 (data model)        → foundation for Phase 2
Phase 2 (orchestrator)      → depends on Phase 1
Phase 3 (code generator)    → depends on Phase 2 (needs story context)
Phase 4 (code reviewer)     → depends on Phase 2 (needs story context)
Phase 5 (prompt generator)  → depends on Phase 2 (needs story context)
Phase 6 (settings UI)       → independent of Phases 3-5, depends on Phase 1 schema
Phase 7 (dashboard UI)      → depends on Phase 8 (needs API)
Phase 8 (API extensions)    → depends on Phase 1 + Phase 2
Phase 9 (testing)           → depends on all above
```

**Recommended execution order:** 0 → 1 → 2 → 3 → 4 → 5 → 6 → 8 → 7 → 9

---

## Files Inventory

### New Files
| File | Purpose |
|------|---------|
| `agent_os/orchestrator/story_queue.py` | Story queue manager + LLM dependency analysis |
| `tests/test_github_review_pipeline.py` | Integration tests for new pipeline |
| `tests/test_story_queue.py` | Unit tests for queue logic |

### Modified Files
| File | Scope of Change |
|------|-----------------|
| `agent_os/agents/store.py` | 1-line filter fix for `__pycache__` |
| `agent_os/orchestrator/engine.py` | Major — new state machine branch for github_review mode |
| `agent_os/orchestrator/state.py` | Add new states + story context fields |
| `agent_os/storage/models.py` | Add StoryQueue table |
| `agent_os/storage/database.py` | Create StoryQueue table |
| `agent_os/code_generator/runner.py` | Fork-aware git workflow (skip create_repo, use existing clone) |
| `agent_os/github/client.py` | Add `fork_repo()` method |
| `agent_os/vcs/github_client.py` | Add fork to VCS abstraction |
| `agent_os/git_ops/manager.py` | Add `clone_from_url()` |
| `agent_os/github_input/cloner.py` | Refactor for reuse by orchestrator |
| `agent_os/code_reviewer/runner.py` | Accept story ACs as context, add story_id/pr to ReviewJSON |
| `agent_os/code_reviewer/schema.py` | Extend ReviewResult with pr_number, story_id |
| `agent_os/prompt_generator/runner.py` | Story-scoped prompt generation |
| `agent_os/api/routes/orchestrator.py` | New queue endpoints |
| `agent_os/api/schemas.py` | New response models |
| `frontend/src/components/SettingsView.tsx` | Pipeline tab requirements sources |
| `frontend/src/components/DashboardView.tsx` | Story queue visualization |
| `frontend/src/hooks/api.ts` | New API functions for queue |

---

## Key Design Decisions

1. **Fork once, branch per story** — The repo is forked and cloned at pipeline start. Each story gets its own branch + PR. This avoids repeated fork/clone overhead.

2. **LLM-driven dependency ordering** — Rather than asking users to manually order stories, the orchestrator uses an LLM call to analyse acceptance criteria and determine which stories logically depend on others.

3. **Per-story iteration counter** — Each story has its own max-iterations limit (configurable, default from pipeline settings). A story failing doesn't block the entire pipeline — it's marked failed and the next story is picked up.

4. **Code reviewer never accesses local code** — All review is PR-based (diff from GitHub API). This is already the current behaviour and is preserved.

5. **Existing ReviewJSON format preserved** — Extended with `pr_number`, `pr_url`, `story_id` fields but all existing fields remain the same.

6. **Standard mode completely untouched** — All new logic is gated behind `config.pipeline_mode == "github_review"`. The existing standard pipeline path is not modified.
