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

From **this directory** (`adk_web_project/`):

```bash
uv run adk web --port 8000
```

Or with pip:

```bash
adk web --port 8000
```

Open http://localhost:8000, select **adk_credit_pack** in the dropdown, and chat.

## Run with CLI

```bash
uv run adk run adk_credit_pack
```

## Current state (Phase 1)

- **Root agent only** — no tools yet. The agent explains that it is the Credit Pack agent and that tools will be added in the next phase.
- Next steps: add AgentTools for ProcessAnalyst, ComplianceAdvisor, Writer (see repo root `MIGRATION_PLAN_ADK_DATA_SCIENCE.md`).

## Branch

This project is developed on **`feature/adk-web-migration`**. Merge to main/autonomous-agents when the migration is ready.
