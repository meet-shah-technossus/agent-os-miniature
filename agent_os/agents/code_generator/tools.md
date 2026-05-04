# Code Generator — Tools

## Available Tools

### 1. File System — Read
**What it does:** Reads the contents of any file within the project root.
**Input:** Absolute or project-relative file path
**Output:** File contents as string
**Used for:** Reading existing code to understand conventions, reading config files, reading the prompt file

### 2. File System — Write
**What it does:** Creates a new file or overwrites an existing file at a specified path within the project root.
**Input:** File path, file contents
**Output:** Confirmation of write
**Used for:** Writing all generated source files, test files, and `summary.md`

### 3. File System — Create Directory
**What it does:** Creates a directory (and all parents) at the specified path.
**Input:** Directory path
**Output:** Confirmation of creation
**Used for:** Setting up the module's folder structure before writing files

### 4. Subprocess — Run Shell Command
**What it does:** Executes a shell command in the project root directory with a configurable timeout.
**Input:** Command string, working directory, timeout
**Output:** stdout, stderr, exit code
**Used for:** Running `pip install`, `npm install`, `python -m venv .venv`, and other setup commands

### 5. Python Package Installer (pip)
**What it does:** Installs Python packages into the project's `.venv` environment.
**Input:** List of package names or path to `requirements.txt`
**Output:** Installation success/failure
**Used for:** Installing dependencies declared by the module before generated code can run

### 6. Summary Writer
**What it does:** Writes the `summary.md` completion signal file to the working directory.
**Input:** Summary text describing what was implemented
**Output:** `summary.md` file ending with `END` marker
**Used for:** Signaling successful completion to the pipeline's completion detector
