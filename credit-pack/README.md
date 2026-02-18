# Credit Pack (clean ADK project)

Single, self-contained Credit Pack agent following the [Google ADK Samples](https://github.com/google/adk-samples/tree/main/python/agents) layout. No dependency on the rest of the repo.

## Layout

- `credit_pack/` — package
  - `agent.py` — root ADK agent
  - `prompt.py` — instructions
  - `tools.py` — ADK tools (set_teaser, analyze_deal, discover_requirements, check_compliance, generate_structure, draft_section, export_credit_pack)
  - `llm.py` — Vertex AI (google-genai) client
  - `config.py` — env-based config
  - `governance.py` — RAG-query Procedure & Guidelines, LLM extraction, cached context
  - `rag.py` — Vertex AI Search (Discovery Engine): procedure and guidelines search
  - `analyst.py`, `compliance.py`, `writer.py` — analysis, compliance, structure/draft
  - `export_docx.py` — DOCX export (python-docx)
- `deployment/`, `eval/`, `tests/` — for deploy, eval, tests
- `pyproject.toml`, `.env.example`

## Setup

1. From the **credit-pack** directory:
   ```bash
   cd credit-pack
   uv sync
   ```
2. Copy `.env.example` to `.env` and set:
   - `GOOGLE_CLOUD_PROJECT`
   - `GOOGLE_CLOUD_LOCATION` (e.g. us-central1)
   - `DATA_STORE_ID` — Vertex AI Search data store for procedure/guidelines RAG
   - `SEARCH_LOCATION` (e.g. global) if not using default
   - Optionally `GOOGLE_APPLICATION_CREDENTIALS` for a service account key
3. Run:
   ```bash
   uv run adk web --port 8000
   ```
4. Open http://127.0.0.1:8000 and select the `credit_pack` agent.

No `PYTHONPATH` or repo root required; the project is self-contained.
