# Code Generator — Skills

## Core Capabilities

1. **Full-Stack Code Generation** — Writes complete, production-ready source code for a module from a structured prompt. Capable of generating Python (FastAPI, SQLAlchemy, Pydantic), TypeScript/React, SQL schemas, configuration files, and test files.

2. **File System Operations** — Creates directories, writes new files, and modifies existing files within the project root. All writes are bounded to the module's declared `file_paths`.

3. **Dependency Installation** — Detects `requirements.txt` or `package.json` changes introduced by the module and runs the appropriate installer (`pip install`, `npm install`) within the project's virtual environment.

4. **Virtual Environment Management** — Creates a Python `.venv` if one does not exist, and installs project dependencies automatically before running code.

5. **Completion Signaling** — Writes a `summary.md` file with an `END` marker on successful completion, enabling the pipeline to reliably detect successful generation vs. partial or timed-out runs.

6. **Partial Completion Recovery** — If a generation run is interrupted or incomplete, automatically retries with a "continue from where you left off" prompt variant, preserving any work already done.

7. **Test File Generation** — Writes unit tests for all public interfaces of the module, matching the testing framework used by the project (pytest for Python, Jest/Vitest for TypeScript).

8. **Code Style Adherence** — Follows existing project conventions including import ordering, docstring style, error handling patterns, and type annotation usage.
