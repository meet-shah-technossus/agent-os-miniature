# Agent OS — Frontend & Architecture Overhaul Plan

> **Status**: Planning only — no implementation yet  
> **Scope**: 7 major areas across frontend + backend  
> **Phases**: 10 phases, ordered by dependency and risk

---

## Table of Contents

1. [Phase 1 — Settings: Decouple VCS from Requirements Source](#phase-1)
2. [Phase 2 — Settings: Remove Agent-Tool Routing Section](#phase-2)
3. [Phase 3 — CLI Tool Architecture: Backend Parity](#phase-3)
4. [Phase 4 — Command Center: Terminal Grid & Tool Wiring](#phase-4)
5. [Phase 5 — Command Center: Editable Review JSON & Approve Fix](#phase-5)
6. [Phase 6 — Dashboard: Diagram Refinements](#phase-6)
7. [Phase 7 — Workflow: Enhanced Diagram & Layout](#phase-7)
8. [Phase 8 — Agents Page: Remove Module Maker & Inline Editing](#phase-8)
9. [Phase 9 — Git & History: PR Comments, Iterations, CI Details](#phase-9)
10. [Phase 10 — Polish & Cross-Cutting Fixes](#phase-10)

---

<a id="phase-1"></a>
## Phase 1 — Settings: Decouple VCS from Requirements Source

### Problem
`vcs/factory.py` uses `config.requirements.source` to decide GitHub vs ADO for **all** VCS operations. Users cannot pull requirements from ADO while pushing code to GitHub or vice versa.

### Current State
- `factory.py:make_vcs_client()` → checks `config.requirements.source == "ado"` → returns ADO or GitHub client
- `SettingsView.tsx` Requirements tab: radio group for source (device / jira / asana / ado)
- No separate VCS provider selector exists anywhere in UI or config

### Plan

#### Backend (config + factory)
1. **`agent_os/config/schema.py`** — Add a new `VCSConfig` model:
   ```python
   class VCSConfig(BaseModel):
       provider: str = "github"  # "github" | "ado"
   ```
   Add `vcs: VCSConfig = VCSConfig()` to `AgentOSConfig`.

2. **`agent_os/vcs/factory.py`** — Change `make_vcs_client()` to read `config.vcs.provider` instead of `config.requirements.source`. Keep the existing `_make_github_client()` / `_make_ado_client()` helpers untouched.

3. **Migration**: On config load, if `vcs.provider` is missing but `requirements.source == "ado"`, default `vcs.provider` to `"ado"` for backward compatibility.

#### Frontend (SettingsView)
4. **Settings → new "VCS" section** (inside GitHub tab or as a new sub-section):
   - Radio group: "VCS Target" → GitHub | Azure DevOps
   - Conditionally show GitHub fields (owner, repo, token) or ADO fields (org, project, token)
   - This is **independent** of the Requirements Source radio

5. **Requirements tab** — Keep as-is (device / jira / asana / ado), but remove any implication that choosing ADO here affects git operations.

#### Files Changed
| File | Change |
|------|--------|
| `agent_os/config/schema.py` | Add `VCSConfig`, add `vcs` field to root config |
| `agent_os/vcs/factory.py` | Read `config.vcs.provider` instead of `config.requirements.source` |
| `agent_os/api/routes/settings.py` | Expose new VCS config in GET/PUT |
| `frontend/src/types.ts` | Add `vcs` to Settings type |
| `frontend/src/components/SettingsView.tsx` | Add VCS provider radio + conditional fields |

#### Risk: Low
Both VCS clients fully implement the same `VCSClient` interface. No runner changes needed.

---

<a id="phase-2"></a>
## Phase 2 — Settings: Remove Agent-Tool Routing Section

### Problem
The CLI routing JSON editor in Settings (mapping posts → tool keys) duplicates what CommandCenter's dropdown does. It also still references `MODULE_MAKER`.

### Current State
- `SettingsView.tsx` has a collapsible "CLI Routing" JSON section at the bottom of the AI Tools tab
- It shows `{ "MODULE_MAKER": "codex", "PROMPT_GENERATOR": "codex", "CODE_GENERATOR": "codex", "CODE_REVIEWER": "codex" }`
- Users can edit raw JSON, but this is error-prone and confusing

### Plan
1. **Remove the CLI Routing section** from `SettingsView.tsx` entirely (the collapsible panel + JSON editor + save button).
2. **Remove `MODULE_MAKER`** from `cli_routing` default in `schema.py` and from any references in `session.py`.
3. **Keep `cli_routing` in config** — it's still used by the backend wrapper. It will be updated programmatically via CommandCenter's tool selection (Phase 4).

#### Files Changed
| File | Change |
|------|--------|
| `frontend/src/components/SettingsView.tsx` | Remove CLI routing section (~50 lines) |
| `agent_os/config/schema.py` | Remove `MODULE_MAKER` from `cli_routing` default dict |
| `agent_os/codex/session.py` | Remove `MODULE_MAKER` from `SessionType` enum |

#### Risk: Low
Purely removal work. No new features.

---

<a id="phase-3"></a>
## Phase 3 — CLI Tool Architecture: Backend Parity

### Problem
Only 3 tools (codex, aider, claude) have backend command builders. The UI shows 6 tools (codex, claude, gemini, qwen, deepseek, copilot). Selecting an unsupported tool silently falls back to codex.

### Current State
- `cli_adapter.py:build_command()` → only handles codex, aider, claude; unknown tools fall back to codex
- `cli_tools.py` API route has metadata for 7 tools but no validation
- Code Reviewer always uses OpenAI API directly (ignores CLI routing)
- Prompt Generator always uses OpenAI API directly

### Plan

#### Step 1: Expand `cli_adapter.py` with new tool command builders
Add command builders for tools that have CLI interfaces:

| Tool | CLI Command Pattern | Feasibility |
|------|-------------------|-------------|
| **gemini** | `gemini` CLI (Google AI Studio) or API-based | Needs investigation — may not have a mature CLI. Consider wrapping via API adapter script. |
| **copilot** | `github-copilot-cli` or VS Code extension commands | VS Code extension only — likely needs an API adapter, not a direct CLI. |
| **qwen** | No official CLI | API-only. Need a thin CLI wrapper script. |
| **deepseek** | No official CLI | API-only. Need a thin CLI wrapper script. |

**Recommended approach**: For tools without native CLIs, create a unified `api_adapter.py` that wraps any OpenAI-compatible endpoint (Gemini, Qwen, DeepSeek all offer OpenAI-compatible APIs) and emits output to stdout the same way CLI tools do. This keeps the subprocess streaming architecture consistent.

#### Step 2: Add tool availability validation
- `cli_adapter.py:is_tool_available(tool: str) -> bool` — Check if the tool's binary exists on `$PATH` or if API credentials are configured.
- `wrapper.py:execute()` — Raise explicit error if selected tool is unavailable, instead of silent fallback.
- API route `GET /api/cli-tools` — return `available: bool` per tool based on actual backend support (not just metadata).

#### Step 3: Code Reviewer architectural decision
**Option A (Recommended)**: Keep Code Reviewer on OpenAI API. It needs structured JSON output and 15-point checklist — CLI tools aren't great for this. Document this clearly.  
**Option B**: Make Code Reviewer pluggable via CLI tools too (requires parsing structured output from arbitrary LLMs, high risk).

**Decision**: Go with Option A. The reviewer's system prompt + streaming JSON parsing is tightly coupled to the OpenAI chat completions API. Making it tool-agnostic would require significant prompt engineering per tool with no clear benefit.

#### Files Changed
| File | Change |
|------|--------|
| `agent_os/codex/cli_adapter.py` | Add command builders for new tools, add `is_tool_available()` |
| `agent_os/codex/wrapper.py` | Explicit error on unsupported tool, remove silent fallback |
| `agent_os/api/routes/cli_tools.py` | Return `available` based on actual backend support |
| New: `agent_os/codex/api_adapter.py` | Thin wrapper for OpenAI-compatible API tools (gemini, qwen, deepseek) |

#### Risk: Medium
Depends on each tool's CLI maturity. Some may need API adapter scripts. The unified OpenAI-compatible adapter approach reduces per-tool effort.

---

<a id="phase-4"></a>
## Phase 4 — Command Center: Terminal Grid & Tool Wiring

### Problem
1. Tool selection in UI doesn't actually update backend `cli_routing` config
2. No code reviewer terminals (reviewer streams to backend but no terminal UI)
3. Only authenticated tools should appear in the dropdown
4. Terminal windows are unequal sizes
5. Need a prompt generator terminal with streaming output

### Current State
- `CommandCenter.tsx:CLI_TOOL_KEYS` = 6 tools, all mapped to `CODE_GENERATOR` post
- `CliGrid` shows compact cards (80px collapsed) and expanded terminal (60vh)
- Tool dropdown selects tool locally but never calls backend
- `ReviewViewer` is read-only Monaco editor showing review JSON
- No terminal for code reviewer or prompt generator output

### Plan

#### Step 1: Wire tool selection to backend
1. **New API endpoint**: `PUT /api/pipeline/cli-tool` → `{ post: "CODE_GENERATOR", tool: "claude" }`
   - Updates `config.codex.cli_routing["CODE_GENERATOR"]` in memory
   - Persists to config file
2. **CommandCenter.tsx** → on tool dropdown change, call `api.setCliTool(post, tool)`
3. **Filter dropdown** — only show tools where `status == "authenticated"` (from `GET /api/cli-tools`)

#### Step 2: Add Code Reviewer terminal
1. **New WebSocket channel** or extend existing terminal WS to carry reviewer output
2. Code Reviewer runner already streams chunks — needs to emit them to a WS channel
3. Add a dedicated terminal card in `CliGrid` for "Code Reviewer" (always present, not in tool dropdown since it's OpenAI-based)
4. Show streaming review text in real-time, then formatted JSON at completion

#### Step 3: Add Prompt Generator terminal
1. Prompt Generator runner streams prompt text — emit to WS channel
2. Add terminal card for "Prompt Generator" in `CliGrid`
3. Show streaming prompt generation output

#### Step 4: Equal-sized terminal windows
1. Replace current variable-height layout with CSS Grid:
   - When collapsed: uniform compact cards in a grid (2-3 columns)
   - When expanded: selected terminal takes equal share of viewport (not 60vh fixed)
   - Multiple terminals can be expanded simultaneously (equal splits)

#### Step 5: Fix approve button for all AI tools
- **Investigate**: Currently `Approve & Trigger` may only work for the default codex tool
- Ensure the approve action uses the currently selected CLI tool from the dropdown
- The approve gate should pass the selected tool key to the backend pipeline

#### Files Changed
| File | Change |
|------|--------|
| `agent_os/api/routes/pipeline.py` or `cli_tools.py` | New `PUT /api/pipeline/cli-tool` endpoint |
| `agent_os/code_reviewer/runner.py` | Emit streaming chunks to WS channel |
| `agent_os/prompt_generator/runner.py` | Emit streaming chunks to WS channel |
| `frontend/src/hooks/api.ts` | Add `setCliTool()`, update `getCliTools()` |
| `frontend/src/components/CommandCenter.tsx` | Filter dropdown, wire selection, add reviewer/prompt terminals, equalize grid, fix approve |

#### Risk: Medium-High
Multiple interacting changes. WS channel wiring for reviewer/prompt generator needs careful coordination with the existing terminal architecture.

---

<a id="phase-5"></a>
## Phase 5 — Command Center: Editable Review JSON & Approve Fix

### Problem
Review JSON is displayed read-only. Users want to edit review decisions before approving.

### Current State
- `ReviewViewer` uses Monaco editor with `readOnly: true`
- Shows pretty-printed review JSON from `GET /api/review`
- "Approve Review" button only visible when `isHITLReview` status
- Approve calls `api.approveGate()` which doesn't send any modified review data

### Plan

#### Step 1: Make ReviewViewer editable
1. Remove `readOnly: true` from Monaco editor config
2. Track local edits in state (diff against original)
3. Add "Reset" button to revert to original reviewer output
4. Add JSON validation — show error indicator if JSON is malformed

#### Step 2: Send edited review on approve
1. **New API endpoint**: `PUT /api/review` → accepts modified ReviewJSON body
   - Overwrites the review file on disk
   - Updates PR comments if user changed them
2. **Approve button** → sends the (potentially edited) review JSON to backend before triggering gate approval
3. Show confirmation if user changed the verdict (e.g., changed "needs_work" to "accepted")

#### Step 3: Visual feedback
- Highlight changed fields in the Monaco editor (yellow gutter markers)
- Show "Modified" badge on ReviewViewer when edits differ from original

#### Files Changed
| File | Change |
|------|--------|
| `frontend/src/components/CommandCenter.tsx` | Make ReviewViewer editable, add reset/validation, send edits on approve |
| `agent_os/api/routes/review.py` or `orchestrator.py` | New `PUT /api/review` endpoint |
| `agent_os/code_reviewer/runner.py` | Accept override review JSON, re-post comments if changed |

#### Risk: Medium
Need to handle the case where user edits break the expected JSON schema. Backend must validate before acting on it.

---

<a id="phase-6"></a>
## Phase 6 — Dashboard: Diagram Refinements

### Problem
1. Shimmer animation plays continuously, not just during active pipeline transfer
2. Diagram is too small in compact mode
3. Text overflows node boxes
4. Danger Zone (Reset) is at the bottom of the sidebar — should be below controls

### Current State
- `PipelineFlowDiagram.tsx`: compact=480×260 (node 112×88), full=660×340 (node 140×110)
- `ShimmerEdge` always renders animated dot when `active` prop is true
- `statusToActiveEdge()` returns active edges based on pipeline status
- Text in nodes uses `foreignObject` with truncation, but long status labels overflow
- `DashboardView.tsx`: Danger Zone is a separate section at sidebar bottom

### Plan

#### Step 1: Conditional shimmer — only during active transfer
1. `ShimmerEdge` component — only show animated dot when pipeline is actively transitioning (not just when a node is active)
2. Add a `transferring` prop or derive from status:
   - Shimmer ON: status is in a "running" state (LOADING_REQUIREMENTS, PROMPT_GENERATION, CODE_GENERATION, CODE_REVIEW)
   - Shimmer OFF: status is in a "waiting" state (IDLE, HITL_PROMPT_REVIEW, HITL_REVIEW_DECISION, PIPELINE_COMPLETE, FAILED)
3. When shimmer is OFF, show static colored lines (no animation) for active edges

#### Step 2: Bigger diagram
1. Increase compact dimensions: 480×260 → 640×320 (node 140×100)
2. Make diagram responsive — use `viewBox` on SVG with percentage-based container width
3. On Dashboard, let the diagram fill the available right pane (flex-grow)

#### Step 3: Fix text overflow
1. Reduce font sizes in `foreignObject` text
2. Add `text-overflow: ellipsis` + `overflow: hidden` on node labels
3. Use tooltip on hover to show full text for truncated labels
4. Compute text width and auto-scale font-size if needed

#### Step 4: Move Danger Zone
1. Move the "Danger Zone" section from sidebar bottom to directly below the action buttons section
2. Keep the confirmation modal behavior

#### Files Changed
| File | Change |
|------|--------|
| `frontend/src/components/PipelineFlowDiagram.tsx` | Conditional shimmer, bigger dimensions, text overflow fixes |
| `frontend/src/components/DashboardView.tsx` | Reorder Danger Zone below controls |
| `frontend/src/hooks/usePipelineFlow.ts` | Add `isTransferring` derived state |

#### Risk: Low
Purely frontend visual changes. No backend impact.

---

<a id="phase-7"></a>
## Phase 7 — Workflow: Enhanced Diagram & Layout

### Problem
1. Same diagram issues as Dashboard (shimmer, text overflow)
2. Diagram should look "crazier" — more visual impact
3. Event feed is below the diagram — should be on the right side

### Current State
- `WorkflowView.tsx`: ~75 lines, header + diagram (full mode) + event feed (vertical scroll)
- Event feed shows last 50 events with icon + text + timestamp
- Diagram uses full mode: 660×340

### Plan

#### Step 1: Layout change — event feed to the right
1. Change from vertical stack (diagram above, feed below) to horizontal split:
   - Left: Diagram (flex-grow, ~65% width)
   - Right: Event feed (fixed-width sidebar, ~35% width, full height scroll)
2. Keep the auto-scroll-to-top behavior on new events

#### Step 2: Make the diagram "crazier"
Ideas for enhanced visual impact:
1. **Particle effects on active edges**: Instead of a single shimmer dot, use multiple particles flowing along edges with varying speeds and sizes
2. **Gradient glow on active nodes**: Animated radial gradient that pulses in sync with processing
3. **Connection line styles**: Curved bezier paths instead of straight lines, with animated dash arrays
4. **Background grid**: Subtle dot grid or circuit-board pattern behind the diagram
5. **Status transition animations**: Nodes flash/pulse when transitioning between states
6. **Data flow visualization**: Show small "data packet" icons flowing along edges (e.g., document icon flowing from Prompt Generator to Code Generator)
7. **Color theme**: Shift from subtle indigo to more vivid gradients (indigo → purple → blue flowing)
8. **Node shadows**: Dynamic drop shadows that intensify when node is active

#### Step 3: Apply Phase 6 fixes
- Same conditional shimmer logic
- Same text overflow fixes
- Apply bigger node sizes (full mode already 140×110, may go to 160×130)

#### Files Changed
| File | Change |
|------|--------|
| `frontend/src/components/WorkflowView.tsx` | Horizontal layout, event feed to right |
| `frontend/src/components/PipelineFlowDiagram.tsx` | Enhanced visuals (particles, curves, gradients, grid) |

#### Risk: Low-Medium
Visual-heavy work. Risk is mainly in getting the animations performant and not janky. Use `will-change` and `transform` for GPU acceleration.

---

<a id="phase-8"></a>
## Phase 8 — Agents Page: Remove Module Maker & Inline Editing

### Problem
1. Module Maker still appears in post assignments and model routing dropdowns
2. Editing .md files opens a popup modal — should be inline

### Current State
- `AgentsView.tsx` (~750 lines):
  - `AssignmentPanel` → post dropdowns include MODULE_MAKER
  - Model routing → includes MODULE_MAKER input field
  - File editing → click file pill → opens modal with Monaco editor → save/close
  - Preview pane shows rendered markdown
- The popup modal provides Monaco editor with dark theme, 70vh height

### Plan

#### Step 1: Remove Module Maker references
1. Remove `MODULE_MAKER` from the posts array in `AssignmentPanel`
2. Remove `MODULE_MAKER` from model routing section
3. Update any validation or save logic that references MODULE_MAKER

#### Step 2: Inline .md editing instead of popup
1. **Replace the preview pane with an inline editor/preview toggle**:
   - Default: preview mode (rendered markdown, as current)
   - Toggle button: "Edit" → switches to Monaco editor in the same pane
   - Toggle button: "Preview" → switches back to rendered markdown
2. **Remove the popup modal entirely**
3. **Inline editor features**:
   - Monaco editor fills the preview pane area
   - Save/Revert buttons appear in the editor toolbar (top-right)
   - Unsaved changes indicator (dot on the file pill)
   - Auto-save on tab/file switch with confirmation if unsaved changes exist
4. **Split view option** (stretch goal): Side-by-side editor + preview for larger screens

#### Files Changed
| File | Change |
|------|--------|
| `frontend/src/components/AgentsView.tsx` | Remove MODULE_MAKER from posts, replace modal with inline editor toggle |

#### Risk: Low
Straightforward UI restructuring. The Monaco editor integration already exists — just needs to move from modal to inline.

---

<a id="phase-9"></a>
## Phase 9 — Git & History: PR Comments, Iterations, CI Details

### Problem
1. Not enough iteration information shown
2. PR comments are displayed as flat lists — want GitHub-style rendering with inline code vs global separation
3. CI result details are too shallow (just pass/fail)

### Current State
- `GitHistory.tsx` (~370 lines):
  - **Timeline tab**: Shows iteration #, status, token usage, review indicator, duration
  - **PR Comments tab**: Verdict strip + inline comments (file/line/severity) + global comments (category/severity)
  - **CI Results tab**: Collapsible rows with pass/fail icon, expandable for failure details

### Plan

#### Step 1: Enhanced iteration information
1. Add to each timeline entry:
   - **Files changed count** (additions/deletions)
   - **CLI tool used** for that iteration
   - **Model used** for that iteration
   - **Prompt summary** (first 100 chars of the prompt)
   - **Code generation exit code** and duration
   - **Review verdict** inline (accepted/rejected/needs_work + score)
2. Backend: Ensure iteration data includes all the above in `GET /api/iterations` or `GET /api/pipeline/history`

#### Step 2: GitHub-style PR comment rendering
1. **Inline comments section**:
   - Group by file path (collapsible file sections)
   - Show code context: display the actual code line(s) around each comment
   - Comment appears below the code line, GitHub-style (with reply thread UI)
   - Color-coded severity border (critical=red, high=orange, medium=yellow, low=gray)
   - Show checklist item tag (e.g., "security", "performance")
2. **Global comments section**:
   - Separate card/panel from inline comments
   - Each comment as a discussion thread card
   - Severity badge + category tag
3. **Visual diff context**:
   - If PR diff is available, show the actual diff hunk around each inline comment
   - Use syntax highlighting (Monaco or Prism)

#### Step 3: Deeper CI result details
1. **Expand CI result entries** to show:
   - Full test output (collapsible, syntax highlighted)
   - Test name, duration, assertion details
   - Stack trace for failures (formatted, collapsible)
   - Test file path (linked)
2. **Summary bar**: Total tests, passed, failed, skipped (with progress bar visualization)
3. **Backend**: `GET /api/ci-results/{iteration}` should return structured test data, not just pass/fail

#### Files Changed
| File | Change |
|------|--------|
| `frontend/src/components/GitHistory.tsx` | Enhanced timeline entries, GitHub-style PR comments, deeper CI details |
| `frontend/src/types.ts` | Extended iteration and CI result types |
| `agent_os/api/routes/` | Enhanced iteration/CI data endpoints |
| `agent_os/storage/` | Store richer iteration metadata |

#### Risk: Medium
Depends on what data the backend actually stores vs. what's available at query time. May need to enhance data capture in runners during pipeline execution.

---

<a id="phase-10"></a>
## Phase 10 — Polish & Cross-Cutting Fixes

### Remaining items that span multiple areas

#### 10a: Cursor tool
- Currently listed in `cli_tools.py` metadata but not in `CLI_TOOL_KEYS` in CommandCenter
- Decision: Include or exclude? Cursor is an IDE, not a CLI tool — likely exclude from terminal grid

#### 10b: Aider tool
- Has backend support (command builder in `cli_adapter.py`) but not shown in UI
- Decision: Add to `CLI_TOOL_KEYS` in CommandCenter? Or keep hidden?

#### 10c: Error handling unification
- Silent fallback to codex for unknown tools must be replaced with explicit errors (Phase 3)
- API responses should include meaningful error messages for tool unavailability

#### 10d: Config persistence
- Currently, CommandCenter tool selection needs to persist to config file
- Ensure `PUT /api/settings` handles `cli_routing` updates atomically
- Handle concurrent pipeline runs reading stale config

#### 10e: WebSocket channel cleanup
- Adding reviewer + prompt generator terminals (Phase 4) means more WS channels
- Ensure channels are properly cleaned up on disconnect
- Consider channel naming convention: `terminal:code_generator`, `terminal:code_reviewer`, `terminal:prompt_generator`

---

## Dependency Graph

```
Phase 1 (VCS Decoupling) ─────────────────────────────────────┐
Phase 2 (Remove CLI Routing UI) ──────┐                       │
                                       ├──→ Phase 3 (CLI Backend Parity)
                                       │         │
                                       │         ▼
                                       │    Phase 4 (Command Center Terminals)
                                       │         │
                                       │         ▼
                                       │    Phase 5 (Editable Review JSON)
                                       │
Phase 6 (Dashboard Diagram) ───────────┼──→ Phase 7 (Workflow Diagram)
                                       │
Phase 8 (Agents Page) ────────────────┘
Phase 9 (Git & History) ──── (independent)
Phase 10 (Polish) ─────────── runs last
```

### Recommended Execution Order
1. **Phase 1 + Phase 2** (Settings cleanup — foundation for Phase 3-4)
2. **Phase 6** (Dashboard diagram — establishes shared component changes)
3. **Phase 8** (Agents page — fully independent, quick win)
4. **Phase 3** (CLI backend parity — needed before Phase 4)
5. **Phase 4 + Phase 5** (Command Center — depends on Phase 3)
6. **Phase 7** (Workflow — reuses Phase 6 diagram changes)
7. **Phase 9** (Git & History — independent, can be parallelized)
8. **Phase 10** (Polish — final pass)

---

## Effort Estimates (T-Shirt Sizing)

| Phase | Size | Complexity |
|-------|------|------------|
| Phase 1 — VCS Decoupling | **S** | Config + factory change + UI radio |
| Phase 2 — Remove Routing UI | **XS** | Pure deletion |
| Phase 3 — CLI Backend Parity | **L** | New tool adapters, validation, API adapter |
| Phase 4 — Command Center Terminals | **L** | WS channels, terminal grid, wiring |
| Phase 5 — Editable Review JSON | **M** | Monaco editing + backend save |
| Phase 6 — Dashboard Diagram | **M** | SVG animation + layout |
| Phase 7 — Workflow Diagram | **M** | Layout + enhanced visuals |
| Phase 8 — Agents Page | **S** | Remove + restructure |
| Phase 9 — Git & History | **L** | GitHub-style UI + backend data |
| Phase 10 — Polish | **S** | Cleanup |

---

## Key Architectural Decisions to Make Before Starting

1. **Gemini / Qwen / DeepSeek / Copilot**: Build individual CLI command builders or create a unified OpenAI-compatible API adapter? (Recommended: unified adapter)

2. **Code Reviewer**: Keep on OpenAI API or make pluggable? (Recommended: keep on OpenAI)

3. **Cursor tool**: Include in terminal grid or exclude? (Recommended: exclude — it's an IDE, not a CLI)

4. **Aider tool**: Show in UI or keep as a backend-only option? (Recommended: show — it has full backend support)

5. **VCS decoupling granularity**: Single `vcs.provider` field or per-operation provider support? (Recommended: single field — simple, covers the use case)
