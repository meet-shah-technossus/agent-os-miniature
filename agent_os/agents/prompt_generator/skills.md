# Prompt Generator — Skills

## Core Capabilities

1. **Framework-Based Prompt Construction** — Builds structured prompts using established prompt engineering frameworks: RCTCF (Role/Context/Task/Constraints/Format), RISEN, COSTAR, or a custom template. Framework is selected via project configuration.

2. **Module Spec Serialization** — Translates a structured `ModuleDefinition` (APIs, classes, functions, DB schemas, file paths, constraints) into rich natural-language prompt sections with full technical detail.

3. **Review Feedback Integration** — On iteration 2 and beyond, incorporates `ReviewFeedback` from the Code Reviewer into the prompt. Formats blocking issues, per-file verdicts, and acceptance criteria failures as targeted fix instructions for the Code Generator.

4. **First-Pass vs. Revision Prompting** — Distinguishes between an initial generation prompt (full spec, no prior context) and a revision prompt (focused on specific issues identified by the Code Reviewer), producing different prompt structures for each case.

5. **Context Injection** — Injects project-level context (project name, language, root path, dependencies on other modules) into every prompt so the Code Generator never works without full situational awareness.

6. **Prompt Persistence** — Writes the final prompt to a stamped file (`data/prompts/{module_id}/iter-{n}.md`) for auditability, HITL review, and replay.

7. **Optional LLM Enrichment** — When an OpenAI API key is available, can call a chat model to enrich and naturalize the template-filled prompt before passing it to the Code Generator.
