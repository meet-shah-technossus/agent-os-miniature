# Prompt Generator — Tools

## Available Tools

### 1. Module Definition Reader
**What it does:** Reads the `ModuleDefinition` JSON from the `modules` table for the current module being processed.
**Input:** Module ID, database connection
**Output:** `ModuleDefinition` object with all fields (APIs, classes, functions, db_schemas, file_paths, constraints, testing_notes, technical_spec)
**Used for:** Source material for all prompt sections

### 2. Prompt Framework Template Loader
**What it does:** Loads the Jinja/string template file for the selected framework (RCTCF, RISEN, COSTAR, or CUSTOM) from `agent_os/prompt_generator/templates/`.
**Input:** `PromptFramework` enum value
**Output:** Template string with named placeholders
**Used for:** Structural scaffold for the assembled prompt

### 3. Review Feedback Reader
**What it does:** Reads the `ReviewFeedback` object from the previous iteration's code review JSON file.
**Input:** Module ID, iteration number, data directory path
**Output:** `ReviewFeedback` with file verdicts, blocking issues, and AC failures
**Used for:** Building the revision section of iteration 2+ prompts

### 4. Prompt File Writer
**What it does:** Writes the assembled prompt string to a stamped Markdown file on disk.
**Input:** Prompt string, module ID, iteration number, data directory path
**Output:** Path object pointing to the written file (`data/prompts/{module_id}/iter-{n}.md`)
**Used for:** Persisting the prompt for HITL review, audit, and downstream consumption by Code Generator

### 5. Optional Chat Enrichment (OpenAI API)
**What it does:** Sends the template-filled prompt to an OpenAI chat model for natural language enrichment — making the prose more coherent while preserving all technical details.
**Input:** Filled template string, model name, API key
**Output:** Enriched prompt string
**Used for:** Higher-quality prompts when an API key is configured. Skipped gracefully if key is absent.
