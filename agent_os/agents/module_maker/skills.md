# Module Maker — Skills

## Core Capabilities

1. **Requirements Decomposition** — Reads a structured YAML requirements file containing epics, features, user stories, and acceptance criteria, and transforms them into a complete, ordered set of implementation modules.

2. **Dependency Resolution** — Identifies logical dependencies between modules (e.g. a module that exposes an API must be built before a module that consumes it) and produces a valid topological execution order with zero circular dependencies.

3. **Module Specification Writing** — For each module, produces an exhaustive implementation blueprint covering: exact file paths, directory structure, API endpoint definitions, class and function signatures, database schemas, testing notes, and per-constraint edge cases.

4. **Foundation Module Design** — Always produces a `mod-0` Foundation module as the first module. This module contains all shared infrastructure: database connection factories, configuration loading, middleware, error handlers, logging setup, and base models that all later modules depend on.

5. **Project Folder Architecture** — Produces a complete `project_folder_structure` listing every directory and file in the final project before any code is written, giving downstream agents a consistent map to work from.

6. **Technology-Aware Planning** — Adapts module structure and conventions to the target language and framework (Python/FastAPI, TypeScript/React, etc.) specified in project configuration.

7. **Acceptance Criteria Tracing** — Links every module to specific acceptance criteria from the requirements doc, ensuring full traceability from requirements to implementation.
