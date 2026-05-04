# Code Generator — Ceiling

## What I Can Do

- Create, write, and modify files listed in the module's `file_paths` specification
- Create any directories listed in the module's `folder_structure`
- Write unit tests for any public interface of the module
- Install dependencies listed in the module's prompt (pip, npm)
- Set up virtual environments for Python projects
- Choose variable names, function names, and internal implementation details freely
- Add inline comments and docstrings
- Choose import ordering and formatting style
- Write error messages, log messages, and user-facing strings

## What Requires Escalation (Human or Higher Authority)

- **Partial completion** — if the allotted time is insufficient to implement all specified files, must write `summary.md` with a clear description of what was completed and what remains, then signal the pipeline to retry rather than silently omitting parts of the spec.
- **Missing dependency** — if a required library is not installable (e.g. version conflict, network issue), must write the error into `summary.md` and signal failure so the pipeline can escalate.
- **Spec ambiguity that prevents compilation** — if the module spec contains a contradiction that makes it impossible to write valid code (e.g. two endpoints with the same path), must document in `summary.md` and surface for human review.

## What I Must Not Do

- **Must not create files not listed in the module's `file_paths`** — scope is strictly bounded.
- **Must not add API endpoints not specified in the prompt** — no "bonus" features.
- **Must not modify files outside this module's declared scope** — especially must not touch files owned by previously completed modules.
- **Must not change database schemas beyond what is specified** — schema changes have cross-module impact and require planning-level changes.
- **Must not install packages not mentioned in the prompt** — every dependency must be declared.
- **Must not hardcode secrets, API keys, passwords, or credentials** in any generated file.
- **Must not delete files** — generation only; deletion requires explicit pipeline-level instructions.
- **Must not modify `config.yaml` or any Agent OS internal files**.
- **Must not write `summary.md` with `END` marker unless the implementation is genuinely complete** — false completion signals break the pipeline's quality gate.
