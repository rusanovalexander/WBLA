# Credit Pack ADK Web Project

Separate project for migrating the Credit Pack flow to **ADK Web**. Lives on branch `feature/adk-web-migration`. The main app (Streamlit) remains in the repo root; this folder is self-contained for running the agent with ADK’s built-in UI.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) or pip + venv

## Setup

1. From this directory (`adk_web_project/`):

   ```bash
   uv sync
   ```

   Or with pip:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -e .
   ```

2. Copy `.env.example` to `.env` and set at least:
   - `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` for Vertex, or
   - `GOOGLE_API_KEY` for Gemini API

## Run with ADK Web

**Recommended:** From the **repo root** (parent of `adk_web_project/`) so the agent can import `agents`, `core`, `config`, `tools`:

```bash
cd <repo_root>
PYTHONPATH=. uv run --project adk_web_project adk web --port 8000
```

Or from this directory if the repo root is on `PYTHONPATH`:

```bash
cd adk_web_project
PYTHONPATH=.. uv run adk web --port 8000
```

Open http://localhost:8000, select **adk_credit_pack** in the dropdown, and chat.

## Run with CLI

```bash
uv run adk run adk_credit_pack
```

## Current state (Phase 2)

- **Root agent with tools**: `set_teaser`, `set_example`, `analyze_deal`, `discover_requirements`, `check_compliance`, `generate_structure`, `draft_section`.
- Tools call the existing Credit Pack agents (ProcessAnalyst, ComplianceAdvisor, Writer) via `runner.py`; state is shared in `tool_context.state` or a fallback dict.
- Run from repo root with `PYTHONPATH=.` so that `agents`, `core`, `config`, `tools` resolve.

## Branch

This project is developed on **`feature/adk-web-migration`**. Merge to main/autonomous-agents when the migration is ready.
