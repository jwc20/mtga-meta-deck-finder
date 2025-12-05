# MTGA Meta Deck Finder

Fork of [17lands mtga-log-client](https://github.com/rconroy293/mtga-log-client)

A tool for finding Magic The Gathering Arena decks uploaded to untapped.gg with a FastAPI backend and 17Lands log
follower.

https://github.com/user-attachments/assets/e83a4497-1c7b-46c3-ad75-88784dc640b2

## Prerequisites

- Python 3.10 or higher
- Git Bash (Windows only)

## Quick Start

### Windows

**PowerShell:**

```powershell
.\run.ps1
```

If you get an execution policy error, run this first:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Git Bash:**

```bash
./run.sh
```

### Linux / macOS

```bash
chmod +x run.sh
./run.sh
```

---

## Manual Setup

If you prefer to run the components manually:

### Setup the virtual environment

```bash
# Create venv
python -m venv .venv
# Install packages
python -m pip install -e .

# Or, if using uv
uv sync
```

### Run the applications

In separate terminals:

```bash
python seventeenlands/mtga_follower.py

# Or, if using uv
uv run seventeenlands/mtga_follower.py
```

```bash
uvicorn app.main:app --reload --host=0.0.0.0 --port=8765

# Or, if using uv
uv run fastapi run app/main.py --host 0.0.0.0 --port 8765
```
