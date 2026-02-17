# Migration Plan: Current Credit Pack Flow → ADK Data-Science Style

This document summarizes how the [Google ADK Data Science multi-agent sample](https://github.com/google/adk-samples/tree/main/python/agents/data-science) is implemented (UI, agents, tools) and outlines a concrete plan to migrate the current credit-pack orchestrator to an ADK-based approach.

---

## 1. How the ADK Data Science Agent Is Implemented

### 1.1 UI

| Aspect | ADK Data Science |
|--------|-------------------|
| **Primary UI** | **ADK Web GUI**: `uv run adk web`, then select the agent from a dropdown. No custom Streamlit/React app in the sample. |
| **Alternative** | **CLI**: `uv run adk run data_science` for terminal interaction. |
| **Deployment** | **FastAPI + Uvicorn**: `main.py` uses `get_fast_api_app()` from `google.adk.cli.fast_api` with `agents_dir` and optional `web=True` to serve the same agent behind a FastAPI app (e.g. for Cloud Run). So the “UI” is either ADK’s built-in web UI or a custom front end talking to the FastAPI session/query API. |
| **Session** | Session service can be in-memory or external (`SESSION_SERVICE_URI`). |

So in the sample: **no custom UI code**; the “UI” is ADK’s own web interface or CLI, plus an optional FastAPI wrapper for deployment.

### 1.2 Agent Architecture

- **Single root agent** (`LlmAgent`), defined in `data_science/agent.py` and exposed as `root_agent`.
- **Sub-agents** are **not** direct children of the root; they are **invoked as tools** via `AgentTool(agent=...)`:
  - **Root** has **tools**: `call_analytics_agent`, and optionally `call_bigquery_agent` and/or `call_alloydb_agent`.
  - **Sub-agents**: `bqml_agent` (BQML), `bigquery_agent` (NL2SQL), `alloydb_agent` (NL2SQL), `analytics_agent` (NL2Py + Code Interpreter).
- **Orchestration**: The root LLM decides when to call which tool. Each “tool” is an async function that uses `AgentTool(agent=sub_agent).run_async(args=..., tool_context=tool_context)`. So the **orchestrator is the root agent’s LLM + its tool list**; there is no separate Python orchestrator class.
- **State**: `tool_context.state` is used to pass data between tools (e.g. `bigquery_query_result`, `alloydb_query_result`) and to the next tool (e.g. analytics gets “question + data” from state).
- **Callbacks**: `before_agent_callback`, `after_tool_callback` on the root/bigquery agent for loading DB settings and storing query results in context.

### 1.3 Tools

| Tool type | Where | Purpose |
|-----------|--------|---------|
| **AgentTool (sub-agent as tool)** | `data_science/tools.py` | `call_bigquery_agent`, `call_alloydb_agent`, `call_analytics_agent`: each is an async function that wraps a sub-agent with `AgentTool(agent=...)` and `run_async(...)`. |
| **ADK built-in BigQuery** | `sub_agents/bigquery/agent.py` | `BigQueryToolset` + `BigQueryToolConfig` (execute_sql, etc.). |
| **Custom NL2SQL** | `sub_agents/bigquery/` | `bigquery_nl2sql` or Chase-SQL–based tools for generating SQL from natural language. |
| **MCP Toolbox (AlloyDB)** | AlloyDB sub-agent | MCP Toolbox for Databases (external process / Cloud Run) for AlloyDB access. |
| **Code execution** | Analytics agent | `VertexAiCodeExecutor` for running generated Python (NL2Py). |
| **RAG** | BQML agent | Vertex AI RAG (e.g. BQML reference guide). |

So: **tools = AgentTools (wrapping sub-agents) + ADK built-in tools (BigQuery) + custom tools (NL2SQL, MCP, code executor, RAG)**.

### 1.4 Summary Table

| Dimension | ADK Data Science |
|-----------|-------------------|
| **UI** | ADK Web GUI or CLI; optional FastAPI app for deploy. |
| **Orchestration** | Single root `LlmAgent` with tools; no separate orchestrator class. |
| **Sub-agents** | Implemented as agents, exposed to root as tools via `AgentTool`. |
| **State** | `CallbackContext.state` / `ToolContext.state` (e.g. query results, DB settings). |
| **Session** | ADK session service (in-memory or `SESSION_SERVICE_URI`). |
| **Tools** | AgentTools, BigQueryToolset, custom NL2SQL, MCP, Code Executor, RAG. |

---

## 2. Current Credit Pack Approach (High Level)

| Dimension | Current project |
|-----------|------------------|
| **UI** | Custom **Streamlit** app (`ui/chat_app.py`): file upload, chat, thinking, process timeline, export. |
| **Orchestration** | **ConversationalOrchestratorV2** (Python class): intent detection (LLM), then hand-off to handlers that call agents. |
| **Agents** | **ProcessAnalyst**, **ComplianceAdvisor**, **Writer** (and optional others); called directly by orchestrator, not as ADK tools. |
| **State** | In-memory `persistent_context`, `conversation_history`, `step_history` inside the orchestrator. |
| **Session** | Streamlit `st.session_state` (orchestrator, messages, uploaded_files, etc.). |
| **Tools** | RAG (`tool_search_procedure`, `tool_search_guidelines`), LLM client (`call_llm` / `call_llm_streaming`), no ADK. |

So the current stack is **custom orchestrator + custom agents + Streamlit**, with **no ADK**.

---

## 3. Migration Plan: From Current Approach to ADK Data-Science Style

Goal: move to a **single root ADK agent** that uses **tools** (including AgentTools wrapping today’s “agents”) so that orchestration is driven by the root LLM and ADK’s session/tool context, while keeping credit-pack capabilities (analysis, requirements, compliance, structure, drafting, export).

### Phase 1: ADK Setup and Root Agent Shell

1. **Add ADK and dependencies**
   - Add `google-adk` (and optionally `google-cloud-aiplatform[adk,agent-engines]`) to the project (e.g. `pyproject.toml` or `requirements.txt`).
   - Align Python version with ADK (e.g. 3.12+ as in the sample).

2. **Create an ADK agent package**
   - Introduce a package that will be the ADK entry point (e.g. `credit_pack_agent/` or keep `data_science`-style layout under something like `agents/adk/`).
   - In that package:
     - `agent.py`: define a single **root** `LlmAgent` with:
       - `instruction`: high-level credit-pack workflow (analyze deal → requirements → compliance → structure → draft sections; when to ask for files/examples; when to export).
       - `tools=[]` initially (to be filled in Phase 2).
       - `model`, `name`, `generate_content_config` as needed.
     - Expose `root_agent` so that `adk run <package_name>` and `adk web` work.

3. **Run and verify**
   - `uv run adk run <package_name>` or `uv run adk web` and confirm the root agent responds (even if it only says it can’t do credit-pack steps yet).

**Deliverable:** One ADK root agent that loads and runs under ADK CLI/Web, with no custom tools yet.

---

### Phase 2: Expose Current Agents as ADK Tools (AgentTools)

1. **Wrap each current “agent” as an ADK agent**
   - **ProcessAnalyst** → one ADK agent (e.g. `LlmAgent` or `Agent` with instruction + tools for RAG). Implement in the ADK package (e.g. `sub_agents/process_analyst/agent.py`). It should accept “request” (or similar) and use existing RAG/LLM logic (reuse or refactor from `agents/process_analyst.py`).
   - **ComplianceAdvisor** → one ADK agent (e.g. `sub_agents/compliance/agent.py`), again with instruction + any tools it needs.
   - **Writer** → one ADK agent (e.g. `sub_agents/writer/agent.py`) for structure generation and section drafting.

2. **Implement AgentTools that call these agents**
   - In a `tools.py` (or equivalent) in the ADK package:
     - `call_process_analyst(teaser_text: str, ...)` → `AgentTool(agent=process_analyst_agent).run_async(args={"request": ...}, tool_context=tool_context)`.
     - `call_compliance_advisor(...)` → same pattern.
     - `call_writer_structure(...)` and `call_writer_draft_section(...)` (or one writer tool that takes an “action” and payload).
   - Each tool should read/write `tool_context.state` so the root agent can pass teaser text, analysis, requirements, compliance result, structure, and drafts between steps.

3. **Attach tools to the root agent**
   - Set `root_agent.tools = [call_process_analyst, call_compliance_advisor, call_writer_structure, call_writer_draft_section, ...]` (or a single writer tool that handles both structure and drafting).
   - Root instruction must describe when to call which tool, what to pass, and how to use the results (e.g. “after analysis, call requirements discovery with analysis text and process path”).

4. **State and context**
   - Use `tool_context.state` (and optionally `callback_context.state`) for:
     - `teaser_text`, `analysis`, `requirements`, `structure`, `drafts`, `compliance_result`, `example_text`, etc.
   - Mirror current `persistent_context` and step flow in the root agent’s instruction and in the tools’ read/write of state.

**Deliverable:** Root ADK agent that can perform the same logical steps as the current orchestrator by calling AgentTools that wrap ProcessAnalyst, ComplianceAdvisor, and Writer.

---

### Phase 3: RAG and Existing Tools in ADK

1. **RAG as ADK tools**
   - Current RAG: `tool_search_procedure`, `tool_search_guidelines`. Implement these as ADK tools (async functions with `ToolContext`) that call the existing search logic.
   - Either:
     - Attach RAG tools to the **root** agent (so it can fetch procedure/guidelines when needed), or
     - Attach them to the **ProcessAnalyst** (and others) sub-agents so they use RAG internally. The data-science sample attaches DB schema to the root and gives sub-agents their own tools; we can do the same (RAG on sub-agents and/or root).

2. **File upload and “session” data**
   - Today: teaser and example text come from Streamlit uploads and are stored in orchestrator context.
   - In ADK: store in `tool_context.state` or in session-backed state (e.g. first user message: “Use this teaser: <content>” and a tool that stores it in state; or integrate file upload into the ADK app so that the first message includes file content or a reference). Optionally add a small “ingest_uploaded_document” tool that the root agent can call when the user says they’re uploading a teaser/example.

**Deliverable:** RAG and upload/teaser data available inside ADK via tools and state.

---

### Phase 4: UI Options (Keep Streamlit vs. ADK Web)

**Option A – Use ADK Web only**
   - Use `adk web` (and optionally FastAPI deploy) as the only UI. No Streamlit. Customize only via ADK’s configuration and prompts. Easiest migration from a code perspective; less control over layout, process timeline, and export UX.

**Option B – Keep Streamlit as front end, ADK as engine**
   - Run the root ADK agent in the backend (e.g. via ADK’s programmatic API or a thin FastAPI app that creates a session and sends user messages to the agent).
   - Streamlit app:
     - Keeps file upload, chat, and “thinking”/process timeline if the API exposes step or stream events.
     - Sends each user message to the ADK session and displays the final response and any streaming/thinking the backend provides.
   - This preserves the current UX while moving orchestration into ADK.

**Option C – Hybrid**
   - Use ADK Web for internal/testing; keep a separate Streamlit (or other) app for production that talks to the same ADK agent via API.

**Recommendation:** Phase 4 should start with **Option B** (Streamlit + ADK backend) so that existing features (timeline, export, file upload) remain, then optionally add **Option A** for quick testing with `adk web`.

---

### Phase 5: Session, Memory, and Process Timeline

1. **Session**
   - Use ADK’s session service (in-memory for dev; optional `SESSION_SERVICE_URI` for production) so that conversation and state are tied to a session ID. Streamlit would pass the same session ID when talking to the backend.

2. **Memory**
   - Current: conversation history and step history in the orchestrator. In ADK, conversation is managed by the session; for “process timeline” (Cursor-like steps), either:
     - Use `tool_context.state` to append a list of “steps” (e.g. `[{ "phase": "analyze_deal", "label": "...", "thinking": [...], "response": "..." }]`) each time a tool completes, and expose this via an API for the Streamlit timeline, or
     - Rely on ADK’s own event/history API if it exposes tool calls and responses in order.

3. **Re-run from step**
   - Current: “Re-run from here” with optional extra instruction. In ADK, this could be implemented by:
     - Storing in state the context at each step (e.g. analysis, requirements, structure, drafts up to that point); then a dedicated tool or a special user message like “Re-run from step 3 with: <instruction>” that the root agent interprets by restoring that context and re-invoking tools from that step. This likely requires a custom tool or a small “replay” sub-flow in the root instruction.

**Deliverable:** Session and state aligned with ADK; process timeline and re-run available either via state + custom API or via ADK events.

---

### Phase 6: Streaming and “Thinking” in ADK

- ADK and Vertex typically support streaming responses. Configure the root (and sub-agents) for streaming and ensure the FastAPI/Streamlit backend forwards streamed chunks and (if available) “thinking” or tool-call progress to the UI so that “Model output (live)” and status steps still work.

---

### Phase 7: Export and Sidebar

- **Export (DOCX)** and **sidebar** (e.g. “Export” button, download link) stay in the Streamlit app (if Option B). The backend (ADK) can expose a tool like `export_credit_pack(structure, drafts)` that returns a URL or bytes, or the Streamlit app can call the existing `core/export.py` with structure and drafts taken from the last response or from an API that returns current state. State for “current structure and drafts” should be in `tool_context.state` (or session) so the backend can return it for export.

---

## 4. Dependency and Structure Sketch

**New/updated dependencies (example):**
- `google-adk>=1.14`
- `google-cloud-aiplatform[adk,agent-engines]>=1.93.0` (or as required by ADK docs)

**Suggested directory layout (example):**
```
credit_pack_agent/           # or agents/adk_credit_pack/
  __init__.py
  agent.py                   # root_agent, get_root_agent()
  prompts.py                 # root + sub-agent instructions
  tools.py                   # call_process_analyst, call_compliance, call_writer_*, RAG tools
  sub_agents/
    __init__.py
    process_analyst/agent.py
    compliance/agent.py
    writer/agent.py
```

Existing `agents/process_analyst.py`, `agents/compliance_advisor.py`, `agents/writer.py` can be refactored into the ADK sub-agents (reusing core logic and RAG) so that the ADK agents are thin wrappers around the same LLM/RAG calls.

---

## 5. Risks and Mitigations

| Risk | Mitigation |
|------|-------------|
| ADK API differs from current flow (e.g. no “intent” step) | Model intent as the root agent’s tool choices; refine root instruction so it follows the same sequence (analyze → requirements → compliance → structure → draft). |
| Losing process timeline / re-run | Implement step history in state + optional custom “replay” tool or message handling. |
| Streaming/thinking UX regresses | Use ADK/Vertex streaming and map events to the existing “thinking” and “Model output (live)” UI. |
| File upload and “session” context | Represent uploads via state (e.g. “teaser_text”, “example_text”) and a tool or first message that sets them. |

---

## 6. Summary

- **ADK Data Science** uses a **single root `LlmAgent`** with **tools**; sub-agents are invoked via **AgentTool**; **UI** is ADK Web or CLI, with optional **FastAPI** for deployment; **state** is in **ToolContext/CallbackContext**.
- **Migration** means: (1) Add ADK and a root agent shell, (2) Expose ProcessAnalyst, ComplianceAdvisor, and Writer as ADK sub-agents and call them from the root via AgentTools, (3) Move RAG and upload/teaser into ADK tools and state, (4) Keep Streamlit as front end talking to ADK backend (recommended), (5) Implement session, timeline, and re-run on top of ADK state/events, (6) Preserve streaming and export in the UI/backend.

This plan aligns the credit pack flow with the [ADK data-science multi-agent pattern](https://github.com/google/adk-samples/tree/main/python/agents/data-science) while preserving current behavior and UX as much as possible.
