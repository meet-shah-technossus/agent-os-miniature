# Implementation Plan — Code Quality Hardening & Pipeline Robustness

**Date**: 2026-05-07  
**Scope**: 3 major areas across orchestrator, code reviewer, and identity injection.

---

## Summary of Issues

| # | Issue | Current State | Desired State |
|---|-------|--------------|---------------|
| 1 | Identity .md files injection | `build_preamble()` is called and prepended in **all 4 runners** ✅ | **Confirmed working.** No code change needed — soul, skills, tools, ceiling, brain are already injected. Prompt Generator uses `build_role_preamble()` (compact). Others use `build_preamble()` (full). |
| 2 | venv + requirements.txt in GitHub Review mode | `handle_github_fork_clone` clones repo but does NOT create venv or install deps | After clone, detect existing `requirements.txt`, create `.venv`, install deps before review/gen begins |
| 3 | Code Reviewer too lenient; syntax errors slip through | Prompt is generic "think step by step"; no mandatory testing gate at review time | Strict 15-point review checklist + mandatory functional testing by the reviewer before producing the JSON verdict |

---

## Issue 1 — Identity .md Files (Confirmed Working ✅)

**No implementation needed.** The identity context injection is already fully operational:

- `IdentityContextInjector` (in `agent_os/agents/context.py`) reads all 5 `.md` files
- `build_preamble()` produces a structured block with: Soul → Skills → Tools → Ceiling → Brain (memory)
- All 4 runners instantiate the injector with their pipeline post name and `_AGENTS_DIR`
- The preamble is prepended to system prompts / full prompts before LLM invocation
- `BrainUpdater` appends dated run summaries after each agent completes

**Recommendation**: If you want to verify/customize content, edit the files directly at:
```
agent_os/agents/code_reviewer/soul.md
agent_os/agents/code_reviewer/skills.md
agent_os/agents/code_reviewer/tools.md
agent_os/agents/code_reviewer/ceiling.md
```

---

## Issue 2 — venv + requirements.txt in GitHub Review Mode

### Problem

`handle_github_fork_clone` completes with:
1. Fork (or reuse existing fork)
2. Clone to local directory
3. Load requirements.yaml into DB
4. Create & checkout branch
5. Transition → `INITIAL_CODE_REVIEW`

Missing: **no venv creation, no dependency installation**. The standard pipeline has this via:
- `DependencyManager.ensure_venv()` + `install_requirements()` (called after code generation)
- Code Generator guardrails (instruct LLM to create venv)

But GitHub Review mode has a *pre-existing* codebase — dependencies should be installed **before** the first review so the validation step can run tests.

### Phase 2A — Post-Clone Environment Bootstrap

**File**: `agent_os/orchestrator/handlers.py` → `handle_github_fork_clone`

Insert between step 5 (Clone) and step 7 (Load requirements.yaml):

```
── 6.5. Bootstrap Python environment ──
1. Detect language (Python heuristic: presence of requirements.txt, setup.py, pyproject.toml)  
2. If Python project detected:
   a. Check if .venv exists in local_dest
   b. If not, create: `python3 -m venv <local_dest>/.venv`
   c. If requirements.txt exists, run: `.venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt`
   d. Emit progress messages on bus
3. If Node project detected (package.json exists):
   a. Run `npm install` in local_dest
4. Non-fatal: if venv creation or install fails, emit warning but continue
```

### Phase 2B — DependencyManager Integration

Reuse the existing `DependencyManager` class (in `agent_os/hardening/dependency_mgr.py`) rather than reimplementing. Call:

```python
from ..hardening.dependency_mgr import DependencyManager

dep_mgr = DependencyManager(ctx.config.dependencies, local_dest)
dep_mgr.ensure_venv()
dep_result = dep_mgr.install_requirements()
if dep_result.success:
    _emit(f"Dependencies installed ({dep_result.package_count} packages)")
else:
    _emit(f"Warning: dependency install failed — {dep_result.stderr[:200]}")
```

### Phase 2C — Config Flag

Add `dependencies.auto_install` and `dependencies.auto_create_venv` checks (already exist in config schema). Ensure the github_review flow respects them same as standard flow.

### Files Modified

| File | Change |
|------|--------|
| `agent_os/orchestrator/handlers.py` | Add venv bootstrap block in `handle_github_fork_clone` |
| (none else) | Reuses existing `DependencyManager` |

---

## Issue 3 — Strict Code Review + Functional Testing

### Problem

1. The current review system prompt (`_REVIEW_SYSTEM_PROMPT`) says "think step by step" and lists required JSON fields, but does NOT mandate a strict checklist or minimum quality bar.
2. The code reviewer never runs tests itself — it only *reads* validation results that were produced by the VALIDATION step (which runs pytest, linter, type checker). But the VALIDATION step uses a simple timeout-based pytest run that may not catch everything.
3. Syntax errors slipping through means either: (a) the linter/type checker in VALIDATION didn't catch them, or (b) the code reviewer ignored the validation failures.

### Proposed Solution — 3 Sub-Phases

---

### Phase 3A — Strict Review Prompt Overhaul

**File**: `agent_os/code_reviewer/runner.py` → `_REVIEW_SYSTEM_PROMPT`

Replace the generic "think step by step" instructions with a **mandatory 15-point checklist** the LLM must evaluate for every iteration. Each point adds a required `area_scores` entry:

```
Mandatory Assessment Checklist (you MUST evaluate each, no exceptions):

 1. Code Correctness — Does it do what it's supposed to? All edge cases handled?
 2. Readability & Clarity — Meaningful names, proper formatting, understandable at first glance?
 3. Code Structure & Design — Modular, reusable, separation of concerns?
 4. Performance & Efficiency — Time/space complexity, unnecessary operations?
 5. Security — No hardcoded secrets, input validation, OWASP Top 10?
 6. Error Handling — Proper try-catch, meaningful messages, graceful failures?
 7. Code Standards — PEP8/language style guide, consistent naming, no duplication?
 8. Testing & Coverage — Unit tests written, edge cases covered, all passing?
 9. Documentation — Comments where needed, function descriptions, README updated?
10. Maintainability — Easy to extend, no tight coupling, clean modular logic?
11. Dependencies & Imports — No unnecessary libraries, versions pinned, secure?
12. Logging & Monitoring — Useful logs, not too noisy, aids debugging?
13. Version Control — Clean changes, no unrelated modifications?
14. UI/UX (if frontend) — Responsive, consistent design, no broken flows?
15. Overall Impact — Breaks nothing existing, aligned with project goals, production-ready?
```

**Failure enforcement**: Add explicit rule:
```
STRICT RULES:
- If ANY file has a syntax error → overall_status MUST be "rejected" (not "needs_work")
- If tests fail or are absent for new functionality → convergence_score cannot exceed 40
- If critical security issues exist → overall_status MUST be "rejected"
- Convergence score 80+ requires ALL items 1-7 clean with no critical/high issues
```

### Phase 3B — Mandatory Functional Testing by Code Reviewer

Currently: VALIDATION → CODE_REVIEW (validation runs tests, reviewer sees results).

Problem: The reviewer treats test failures as "informational" rather than blocking.

**Solution — Two-prong approach:**

#### 3B.1 — Strengthen validation result handling in review prompt

In `_fill_context_parts` / `_build_user_content`, change how validation results are presented:

**Before:**
```
## Validation Results
Linter: PASSED
Tests: FAILED (3 failures)
```

**After:**
```
## VALIDATION GATE (BLOCKING)
⚠️ THE FOLLOWING FAILURES MUST BE ADDRESSED — DO NOT ACCEPT IF ANY CRITICAL FAILURE EXISTS:

Tests: FAILED — 3 failures:
  - test_auth_login: AssertionError: expected 200 got 500
  - test_user_create: ModuleNotFoundError: No module named 'bcrypt'
  - test_endpoints: SyntaxError: unexpected EOF (app/routes.py line 45)

RULE: Any SyntaxError or ImportError in test output means overall_status="rejected"
```

#### 3B.2 — Post-review test verification (new)

After the code reviewer produces its JSON, add a **verification step** in `handle_code_review`:

```python
# If reviewer says "accepted" but validation had failures → downgrade to needs_work
if review.overall_status == "accepted" and validation_result and not validation_result.all_passed:
    logger.warning("Reviewer accepted but validation failed — downgrading to needs_work")
    review.overall_status = "needs_work"
    review.convergence_score = min(review.convergence_score, 60)
    review.summary += " [Auto-downgraded: validation failures still present]"
```

This acts as a hard safety net — the code reviewer cannot "accept" code that has failing linter/tests.

#### 3B.3 — Run targeted syntax check before review

In `handle_validation` (the VALIDATION handler), add a **syntax-only fast pass** at the very start:

```python
# Fast syntax check — catch SyntaxErrors immediately
from ..validation.syntax_check import quick_syntax_scan
syntax_errors = quick_syntax_scan(working_dir, file_paths)
if syntax_errors:
    # Add these as critical issues to validation result
    for err in syntax_errors:
        validation_result.add_issue("syntax", "critical", err)
```

New file: `agent_os/validation/syntax_check.py`
- Python files: `py_compile.compile()` or `ast.parse()`
- JS/TS files: check for basic parse with `node --check` or esbuild
- Returns list of `{file, line, error}` dicts

### Phase 3C — Review Schema Enhancement

**File**: `agent_os/code_reviewer/schema.py`

Add to `CodeReviewResult`:
```python
class CodeReviewResult(BaseModel):
    ...
    checklist_scores: dict[str, int] = Field(default_factory=dict)
    # Maps each of the 15 checklist items to a 0-100 score
    # e.g. {"code_correctness": 85, "security": 70, ...}
    
    syntax_errors_found: list[str] = Field(default_factory=list)
    # Explicit list of syntax errors the reviewer identified
    
    test_failures_acknowledged: bool = False
    # Whether the reviewer explicitly addressed test failures
```

Update `_parse_review` to extract these new fields (with graceful defaults if LLM omits them).

---

## Phase Summary & Dependencies

```
Phase 2A ──→ Phase 2B ──→ Phase 2C     (venv in github_review: sequential)
     │
     │  (independent)
     ▼
Phase 3A ──→ Phase 3B ──→ Phase 3C     (strict review: sequential)
```

| Phase | Effort | Files Modified |
|-------|--------|----------------|
| 2A | Small | `handlers.py` — add venv bootstrap in `handle_github_fork_clone` |
| 2B | Tiny | Same — call `DependencyManager` |
| 2C | Tiny | Verify config flags are respected |
| 3A | Medium | `code_reviewer/runner.py` — rewrite `_REVIEW_SYSTEM_PROMPT` |
| 3B.1 | Small | `code_reviewer/runner.py` — change validation presentation in prompt |
| 3B.2 | Small | `handlers.py` — add post-review safety net in `handle_code_review` |
| 3B.3 | Medium | New file `validation/syntax_check.py` + integrate in `handle_validation` |
| 3C | Small | `code_reviewer/schema.py` — add fields + update parser |

---

## Implementation Order

1. **Phase 2A+2B** — Quick win. Add `DependencyManager` call in `handle_github_fork_clone` after clone completes. ~20 lines of code.

2. **Phase 3A** — Rewrite `_REVIEW_SYSTEM_PROMPT` with strict 15-point checklist and failure rules. Pure prompt engineering, no logic changes.

3. **Phase 3B.3** — Create `syntax_check.py`. Fast syntax validation catches the class of bugs (SyntaxErrors) that were slipping through.

4. **Phase 3B.1** — Change how validation failures are presented to the reviewer (make them BLOCKING in the prompt).

5. **Phase 3B.2** — Add the hard safety net: override reviewer's "accepted" if validation still fails.

6. **Phase 3C** — Schema enhancement + parser update for the new checklist fields.

7. **Phase 2C** — Verify config integration (trivial).

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Strict prompt causes reviewer to reject everything | Include calibration: "convergence_score 50-79 = needs_work, 80+ = accepted candidate" |
| Syntax check false positives (e.g. template files) | Only check files in `module_def.file_paths`, skip templates/configs |
| LLM doesn't produce all 15 checklist scores | Default missing scores to 0 in parser, trigger re-review if >5 missing |
| venv creation fails on unusual Python setups | Non-fatal: emit warning, continue pipeline |
| Large repos take too long for full syntax scan | Cap at 200 files; parallelize with `concurrent.futures` |

---

## Testing Plan

- Unit test: `syntax_check.py` with intentional SyntaxError files
- Unit test: post-review safety net (mock reviewer "accepted" + validation failed → downgrade)
- Integration test: GitHub review mode pipeline with repo missing `.venv` → verify venv created
- Manual test: Run pipeline on the Dataset-Generator repo end-to-end
