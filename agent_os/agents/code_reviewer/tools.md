# Code Reviewer — Tools

## Available Tools

### 1. File Content Reader
**What it does:** Reads the full contents of all source files in the project directory that belong to the current module (as declared in `file_paths`).
**Input:** Module's `file_paths` list, project root path
**Output:** Dict mapping file path → file contents
**Used for:** The primary corpus for code review analysis

### 2. Validation Result Reader
**What it does:** Reads the structured `ValidationResult` JSON produced by the Validation step for the current module and iteration.
**Input:** Module ID, iteration number, data directory
**Output:** `ValidationResult` with per-tool results (lint, type-check, tests, security scan)
**Used for:** Incorporating automated tool findings into the review without redundant re-checking

### 3. Module Specification Reader
**What it does:** Reads the full `ModuleDefinition` for the current module from the database.
**Input:** Module ID, database connection
**Output:** `ModuleDefinition` with all APIs, classes, functions, db_schemas, constraints, acceptance_criteria
**Used for:** Spec-adherence checking — verifying all specified elements are present and correctly implemented

### 4. Codex CLI Invocation (via CodexWrapper)
**What it does:** Invokes the OpenAI Codex CLI as a subprocess with the assembled review prompt (code + spec + validation results). The CLI produces the structured JSON review.
**Input:** Review prompt string, working directory, session type `CODE_REVIEWER`, model from `model_routing`
**Output:** Raw stdout from Codex containing the JSON review
**Used for:** The actual AI-driven review analysis

### 5. Review JSON Writer
**What it does:** Writes the parsed review JSON to disk at `data/reviews/{module_id}/iteration-{n}.json`.
**Input:** Review JSON object, module ID, iteration number
**Output:** Persisted review file
**Used for:** Making the review durable for audit, HITL display, and Prompt Generator consumption
