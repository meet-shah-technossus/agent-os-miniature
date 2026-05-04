# Module Maker — Tools

## Available Tools

### 1. Requirements Reader
**What it does:** Reads the structured requirements YAML file from disk and parses it into a hierarchical structure of epics → features → stories → acceptance criteria.
**Input:** File path to `requirements.yaml`
**Output:** Structured dict with all epics, features, stories, and ACs
**Used for:** Building the requirements context block injected into the planning prompt

### 2. Requirements Database Reader
**What it does:** Queries the Agent OS SQLite database for all stored requirements records loaded by the pipeline.
**Input:** Database connection
**Output:** List of `RequirementRecord` objects with type, parent_id, title, description
**Used for:** Cross-referencing stored requirements when building the module decomposition prompt

### 3. Codex CLI Invocation (via CodexWrapper)
**What it does:** Invokes the OpenAI Codex CLI as a subprocess with the assembled planning prompt. The CLI generates the complete JSON module plan.
**Input:** Assembled prompt string, working directory, session type `MODULE_MAKER`, model from `model_routing`
**Output:** Raw stdout from Codex containing the JSON plan
**Used for:** The actual AI-driven decomposition step

### 4. Module Database Writer
**What it does:** Parses the Codex JSON output and writes each `ModuleRecord` into the `modules` table in SQLite.
**Input:** Parsed `ModulePlan` object
**Output:** Persisted module records with execution order assigned
**Used for:** Making the plan durable so the pipeline can resume after failures

### 5. Dependency Graph Validator
**What it does:** Runs cycle detection on the dependency graph declared in the module plan.
**Input:** List of module IDs and their declared dependencies
**Output:** Topologically sorted execution order, or raises `CycleError`
**Used for:** Ensuring the plan is executable before handing off to downstream agents
