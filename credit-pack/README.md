# Credit Pack Agent (ADK Samples Style)

Credit Pack orchestration agent following the [Google ADK Samples](https://github.com/google/adk-samples/tree/main/python/agents) structure. Handles deal analysis, requirements discovery, compliance, structure generation, and section drafting.

## Structure

- `credit_pack/` — core package
  - `agent.py` — root agent
  - `prompt.py` — instructions
  - `tools.py` — root-level tools (including AgentTools for sub-agents)
  - `sub_agents/` — process_analyst, compliance, writer
- `deployment/` — Vertex AI Agent Engine deploy
- `eval/` — evaluation scripts and data
- `tests/` — unit tests

## Setup

1. Copy `.env.example` to `.env` and set `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`.
2. Run from **repo root** (runner and tools use `agents`, `core`, `config` from the repo):
   ```bash
   PYTHONPATH=. uv run --project credit-pack adk web --port 8000
   ```
3. Open http://127.0.0.1:8000 and select the `credit_pack` agent.

## Migration plan

See `docs/ADK_SAMPLES_FULL_MIGRATION_PLAN.md` for the full transition plan and phases.
