# Contributing

## Development Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
cd frontend && npm install
```

## Running

```bash
# Backend
python -m agent_os

# Frontend
cd frontend && npm run dev
```

## Testing

```bash
# Backend (363+ tests)
python -m pytest tests/unit/ tests/integration/ tests/characterization/ -W ignore

# Frontend (Vitest)
cd frontend && npx vitest run

# TypeScript check
cd frontend && npx tsc -p tsconfig.app.json --noEmit
```

## Code Quality

- **Linter:** `ruff check agent_os/`
- **Formatter:** `ruff format agent_os/`
- **Coverage:** `pytest --cov=agent_os --cov-fail-under=38`

## Conventions

- Python 3.12+, type annotations on all public methods
- `from __future__ import annotations` in all modules
- Use `datetime.now(timezone.utc)` instead of `datetime.utcnow()`
- Use `sys.platform == "win32"` instead of `platform.system()`
- SQLite with WAL mode for concurrent access
- Pydantic models for data validation
- Repository pattern for database access
- FastAPI dependency injection via `deps.py`

## Branch Strategy

- `main` — stable, tested code
- Feature branches for new phases
- All tests must pass before merge
