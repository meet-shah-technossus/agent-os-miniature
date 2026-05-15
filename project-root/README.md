# Clinic Dashboard

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
python scripts/seed.py
```

## Running the app

```bash
python app.py
```

## Tests

```bash
.venv/bin/pytest -q
```

## CI

```bash
python ci_check.py
```
