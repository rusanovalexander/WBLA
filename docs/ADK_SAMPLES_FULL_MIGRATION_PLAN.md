# Full Migration Plan: Credit Pack → Google ADK Samples Platform

This document defines the **full transition** of the Credit Pack project to the same **logic, structure, and platform** used in [Google ADK Samples — Python Agents](https://github.com/google/adk-samples/tree/main/python/agents). It covers target structure, phases, and how we will execute the migration on a **new branch** with a **new project layout**.

---

## 1. Reference: ADK Samples Standard

### 1.1 Official structure (from [agents README](https://github.com/google/adk-samples/tree/main/python/agents))

Each agent in the repo follows this layout:

```
agent-name/                          # Folder: hyphenated (e.g. credit-pack, data-science)
├── agent_name/                     # Package: underscores (e.g. credit_pack, data_science)
│   ├── __init__.py                 # Exposes root_agent / package
│   ├── agent.py                    # Root agent + get_root_agent() if dynamic
│   ├── prompt.py                   # Root (and optionally sub-agent) prompts
│   ├── tools.py                    # Root-level tools (including AgentTools)
│   ├── shared_libraries/           # Optional: helpers shared by sub-agents
│   └── sub_agents/                 # Sub-agents (each = agent + tools + prompt)
│       ├── sub_agent_one/
│       │   ├── agent.py
│       │   ├── prompt.py
│       │   └── tools/              # Optional
│       └── sub_agent_two/
│           ├── agent.py
│           ├── prompt.py
│           └── tools/
├── deployment/                     # Deploy to Vertex AI Agent Engine
├── eval/                           # Evaluation scripts and data
├── tests/                          # Unit/integration tests
├── .env.example
├── pyproject.toml                  # Poetry or uv; Python 3.9+ (samples use 3.12+)
└── README.md
```

- **Run from agent root**: `adk web` or `adk run .` (often from `agent_name/` for CLI).
- **Stack**: [Python ADK](https://github.com/google/adk-python), Poetry or **uv**, Vertex AI and/or Gemini API.

### 1.2 Patterns we adopt (from Data Science + others)

| Aspect | Pattern |
|--------|--------|
| **Root agent** | Single `LlmAgent` in `agent.py`; `instruction` from `prompt.py`; `tools` + optional `sub_agents`. |
| **Sub-agents as tools** | Wrapped with `AgentTool(agent=sub_agent)`; root calls them via async tools that use `tool_context.state`. |
| **State** | `ToolContext.state` / `CallbackContext.state` for passing data between tools and steps. |
| **Config** | `.env` from `.env.example`; optional JSON/config files (e.g. dataset config in data-science). |
| **Callbacks** | `before_agent_callback` / `after_tool_callback` for loading context (e.g. DB settings, governance). |

---

## 2. Target: Credit Pack as an ADK Sample–Style Project

### 2.1 New project location and branch

- **Branch**: `feature/adk-samples-full-migration`
- **New project root**: `credit-pack/` at repository root (alongside existing `adk_web_project/` and `agents/`).
- **Package name**: `credit_pack` (underscores), so the core code lives under `credit-pack/credit_pack/`.

This keeps the current codebase intact while we build the new layout; later we can deprecate `adk_web_project/` or merge its working pieces into `credit-pack/`.

### 2.2 Target directory structure

```
credit-pack/
├── credit_pack/
│   ├── __init__.py                 # from .agent import root_agent
│   ├── agent.py                    # Root LlmAgent; tools = [AgentTools + helpers]
│   ├── prompt.py                   # get_root_instruction(), get_* for sub-agents
│   ├── tools.py                    # call_process_analyst, call_compliance_advisor,
│   │                               # call_writer_*, set_teaser, export_credit_pack, etc.
│   ├── shared_libraries/          # Shared helpers (e.g. governance load, RAG client)
│   │   └── ...
│   └── sub_agents/
│       ├── __init__.py
│       ├── process_analyst/
│       │   ├── agent.py            # LlmAgent for deal analysis + RAG
│       │   ├── prompt.py
│       │   └── tools/              # RAG tools (procedure, guidelines)
│       ├── compliance/
│       │   ├── agent.py            # LlmAgent for compliance check
│       │   ├── prompt.py
│       │   └── tools/             # Optional
│       └── writer/
│           ├── agent.py            # LlmAgent for structure + section drafting
│           ├── prompt.py
│           └── tools/
├── deployment/
│   └── (deploy.py + config for Vertex AI Agent Engine)
├── eval/
│   └── (eval data + scripts)
├── tests/
│   └── (unit tests for tools and agents)
├── .env.example
├── pyproject.toml                  # uv or Poetry; deps: google-adk, vertex, etc.
└── README.md
```

### 2.3 Mapping current code → new layout

| Current | New location |
|--------|----------------|
| `adk_web_project/adk_credit_pack/agent.py` (root) | `credit-pack/credit_pack/agent.py` |
| `adk_web_project/adk_credit_pack/prompts.py` | `credit-pack/credit_pack/prompt.py` |
| `adk_web_project/adk_credit_pack/tools.py` | `credit-pack/credit_pack/tools.py` |
| `adk_web_project/adk_credit_pack/runner.py` (governance, agents) | `credit-pack/credit_pack/shared_libraries/` + sub_agents |
| `agents/process_analyst.py` | `credit-pack/credit_pack/sub_agents/process_analyst/` (ADK agent wrapping same logic) |
| `agents/compliance_advisor.py` | `credit-pack/credit_pack/sub_agents/compliance/` |
| `agents/writer.py` | `credit-pack/credit_pack/sub_agents/writer/` |
| RAG / governance / `core/` | Reused via path or package dependency; shared code in `shared_libraries/` |

---

## 3. Phased Transition Plan

### Phase 1: Branch and skeleton (immediate)

1. Create branch `feature/adk-samples-full-migration`.
2. Create `credit-pack/` with:
   - `credit_pack/__init__.py`, `agent.py`, `prompt.py`, `tools.py` (stubs or minimal).
   - `credit_pack/sub_agents/` with `process_analyst/`, `compliance/`, `writer/` (each with `agent.py`, `prompt.py`).
   - `credit-pack/pyproject.toml` (name `credit-pack`, package `credit_pack`), `.env.example`, `README.md`.
   - Empty `deployment/`, `eval/`, `tests/`.
3. Ensure `adk web` runs from `credit-pack/` and selects the credit_pack agent.

**Deliverable:** New structure on new branch; ADK Web loads the agent (minimal behavior).

---

### Phase 2: Root agent and AgentTools (sub-agents as tools)

1. Implement root agent in `credit_pack/agent.py`:
   - `instruction` from `prompt.py` (workflow: set_teaser → analyze → requirements → compliance → structure → draft → export).
   - Tools: `set_teaser`, `analyze_deal`, `discover_requirements`, `check_compliance`, `generate_structure`, `draft_section`, `export_credit_pack`.
2. Implement each tool in `credit_pack/tools.py`:
   - **Analyze / requirements / compliance / structure / draft**: use `AgentTool(agent=<sub_agent>).run_async(args=..., tool_context=tool_context)` and read/write `tool_context.state`.
   - **set_teaser** / **export_credit_pack**: function tools that update state or call shared export logic.
3. Implement sub-agents in `credit_pack/sub_agents/*/agent.py`:
   - Process Analyst, Compliance, Writer as `LlmAgent` with their own instructions and tools (RAG where needed).
4. Reuse existing logic (ProcessAnalyst, ComplianceAdvisor, Writer) either by:
   - Importing from repo root (e.g. `PYTHONPATH` or path dependency in `pyproject.toml`), or
   - Copying/refactoring into `shared_libraries/` and sub_agents so `credit-pack` is self-contained.

**Deliverable:** Full workflow runnable via ADK Web: user says “analyze this teaser” → root calls tools → sub-agents run; state persists in `tool_context.state`.

---

### Phase 3: RAG, governance, and config

1. **RAG**: Expose procedure/guidelines search as tools on the Process Analyst sub-agent (or root). Use existing RAG implementation; config (e.g. project, corpus) from `.env` or config file.
2. **Governance**: Load governance once (e.g. in `before_agent_callback` or at startup) and inject into `tool_context.state` or sub-agent context so compliance and structure use it.
3. **Config**: Align with samples: `.env.example` lists all required vars; optional JSON/YAML for governance or feature flags if needed.

**Deliverable:** Credit pack behavior matches current app: RAG-backed analysis, governance-aware compliance and structure.

---

### Phase 4: Deployment, eval, and tests

1. **deployment/**: Add `deploy.py` (and config) for Vertex AI Agent Engine, following [ADK samples deployment pattern](https://github.com/google/adk-samples/tree/main/python/agents) (e.g. as in FOMC Research or Data Science).
2. **eval/**: Add evaluation dataset and script (e.g. sample teasers + expected process_path/origination) to run regression.
3. **tests/**: Unit tests for tools and sub-agents (e.g. pytest), as in the samples.

**Deliverable:** One-command deploy, repeatable eval, and CI-friendly tests.

---

### Phase 5: UI and production options

1. **Option A – ADK Web only**: Use `adk web` (and optional FastAPI) as the only UI; no Streamlit.
2. **Option B – Streamlit + ADK backend**: Keep Streamlit; backend runs the root agent (session + message API) and Streamlit displays responses and timeline (from state or ADK events).
3. **Option C – Hybrid**: ADK Web for dev/test; Streamlit or custom front end for production.

Recommendation: Start with **Option A** for the new `credit-pack/` so the migration stays aligned with ADK samples; add Option B in a later phase if product requires the current Streamlit UX.

---

### Phase 6: Deprecate or merge old ADK project

1. Once `credit-pack/` is stable and feature-complete:
   - Document that `adk_web_project/` is deprecated in favor of `credit-pack/`.
   - Optionally remove or archive `adk_web_project/` and point all docs/README to `credit-pack/`.

**Deliverable:** Single ADK-based entry point for Credit Pack, aligned with adk-samples layout.

---

## 4. Technical Details

### 4.1 Dependencies (`credit-pack/pyproject.toml`)

- **Python**: 3.12+ (match data-science and ADK).
- **Core**: `google-adk`, `google-genai`, `google-cloud-aiplatform[adk]`, `python-dotenv`, `pydantic`, `tenacity`.
- **Existing Credit Pack**: Either path dependency to repo root (e.g. `agents`, `core`, `config`) or copy minimal code into `credit_pack/shared_libraries/` and sub_agents.

### 4.2 Running

From repo root (with path dependency) or from `credit-pack/`:

```bash
# From credit-pack/
uv sync
uv run adk web
# Or: adk run credit_pack
```

If the project uses the parent repo for `agents`/`core`/`config`:

```bash
PYTHONPATH=. uv run --project credit-pack adk web --port 8000
```

### 4.3 State contract (tool_context.state)

- `teaser_text`, `example_text`
- `analysis` (output of analyze_deal)
- `requirements`, `compliance_result`, `structure`, `drafts`
- Optional: `governance_context`, `last_step`, `thinking` (for UI)

---

## 5. Success criteria

- [ ] New branch `feature/adk-samples-full-migration` exists with `credit-pack/` layout.
- [ ] Structure matches adk-samples (agent_name/, sub_agents/, deployment/, eval/, tests/, .env.example, pyproject.toml, README).
- [ ] Root agent runs under `adk web` and executes full workflow via tools and sub-agents.
- [ ] RAG and governance integrated; behavior matches current app.
- [ ] Deployment and eval and tests in place; README documents run/deploy/eval/test.

---

## 6. References

- [ADK Samples — Python Agents](https://github.com/google/adk-samples/tree/main/python/agents)
- [ADK Samples — Agents README (structure)](https://github.com/google/adk-samples/blob/main/python/agents/README.md)
- [Data Science Agent](https://github.com/google/adk-samples/tree/main/python/agents/data-science) — multi-agent, AgentTool, state, callbacks
- [ADK Quickstart](https://google.github.io/adk-docs/get-started/quickstart/)
- Existing: `MIGRATION_PLAN_ADK_DATA_SCIENCE.md` (Phase 1–2 detail, UI options)
