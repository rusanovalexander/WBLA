# Deep Project Audit Report — Credit Pack Multi-Agent PoC (WBLA-feature-autonomous-agents)

**Audit date:** 2026-02-24  
**Scope:** Full codebase analysis, architecture, security, testing, and alignment with prior audits  
**Branch/context:** feature/autonomous-agents, no git repo detected

---

## 1. Executive Summary

| Area | Score | Status |
|------|--------|--------|
| **Architecture** | 8.5/10 | ✅ Modular, clear separation (config, models, agents, core, tools, ui) |
| **Code quality** | 7/10 | ⚠️ Good typing and structure; a few bare `except`, one type-hint bug |
| **Testing** | 4/10 | ❌ Single unit module; no parser/orchestration/integration tests |
| **Security** | 6/10 | ⚠️ Env/secrets OK; no input sanitization, RBAC, or file upload limits |
| **Documentation** | 8/10 | ✅ Rich docs; some drift (main.py, .env comments) |
| **Production readiness** | 5/10 | ⚠️ No timeouts, TraceStore unbounded, CI allows test/lint failures |

**Overall:** The project is a well-structured multi-agent credit-pack drafting system with a conversational UI (Streamlit), Gemini-based agents, RAG (Vertex AI Search), and optional Vertex/Langfuse tracing. Several previously reported critical issues (C1, C2) have been addressed in code. Remaining gaps are concentrated in testing, operational hardening, and consistency (entrypoints, env, and a few code quality items).

---

## 2. Project Overview

- **Purpose:** Automated credit pack drafting via multi-agent AI (Orchestrator, Process Analyst, Compliance Advisor, Writer) with human-in-the-loop.
- **Primary UI:** `ui/chat_app.py` (ConversationalOrchestratorV2).
- **Legacy UI:** `ui/legacy/app.py` (phase-based workflow).
- **Stack:** Python 3.10+, Streamlit, Google GenAI/Vertex, Pydantic, tenacity, python-docx, PyMuPDF, etc.

---

## 3. Architecture Audit

### 3.1 Layout and Boundaries

- **config/** — Settings, env/secrets, paths, feature flags, model/tracing config. Clear and centralized.
- **models/** — Pydantic schemas and process steps. Used consistently at boundaries.
- **agents/** — Orchestrator, ProcessAnalyst, ComplianceAdvisor, Writer, level3 (agent bus). Good separation of prompts and behavior.
- **core/** — Orchestration (legacy phase-based), conversational orchestrator v1/v2, LLM client, parsers, export, governance discovery, tracing. Some files are large (e.g. `conversational_orchestrator_v2.py` ~1.5k lines) but responsibilities are identifiable.
- **tools/** — RAG search, document loader, function declarations (Gemini tools), change tracker, field discovery, phase manager. Clear tool vs orchestration split.
- **ui/** — Chat app, legacy app and phases, shared sidebar and agent dashboard. Clear primary vs legacy entrypoints.

### 3.2 Data and Control Flow

- Orchestrator holds conversation history, persistent context, and step history; passes callables (e.g. `search_procedure`, `search_guidelines`) and optional `agent_bus` into agents.
- Native tool calling: `get_agent_tools()` + `create_tool_executor()` map Gemini tool names (`search_procedure`, `search_guidelines`, `search_rag`) to Python implementations; executor receives `search_procedure_fn` etc. and is invoked from `core/llm_client.py` in the tool loop. C2-style name/parameter mismatches have been addressed (FIXES_C1_C2.md).
- Writer uses `agent_bus` in `draft_section` via `_query_agents_for_section` and `_run_compliance_review_subtask` (C1 fix confirmed in code).

### 3.3 Previous Critical Issues — Status

| Issue | Prior state | Current state |
|-------|-------------|----------------|
| **C1 – Agent bus unused** | Writer never called `agent_bus.query()` | **Fixed.** Writer calls `agent_bus.query()` in `_query_agents_for_section` and `_run_compliance_review_subtask`. |
| **C2 – Function name/param mismatch** | Declarations vs `tool_*` and `top_k` | **Fixed.** Aliases in `rag_search.py`; orchestrator wrappers use `num_results`; executor uses tool names `search_procedure` etc. |
| **Parsing / safe_extract_json** | Fragile JSON extraction | **Improved.** `core/parsers.py` uses `<json_output>` XML extraction, preamble stripping, bracket-aware parsing, truncation recovery, and `_try_parse_json` fixups. |

---

## 4. Code Quality Findings

### 4.1 Issues to Fix

1. **Bare `except:` (conversational_orchestrator_v2.py)**  
   - **Location:** ~584 (file upload decode).  
   - **Problem:** Catches `KeyboardInterrupt` and `BaseException`.  
   - **Recommendation:** Use `except UnicodeDecodeError:` (and optionally log).

2. **Return type in function_declarations.py**  
   - **Location:** `create_tool_executor(...) -> callable`.  
   - **Problem:** Lowercase `callable`; mypy/ruff may expect `Callable[[str, dict], str]`.  
   - **Recommendation:** `from typing import Callable` and return type `Callable[[str, dict], str]`.

3. **main.py entrypoint text**  
   - **Location:** `main.py` docstring and final print.  
   - **Problem:** Say "streamlit run ui/app.py" but primary app is `ui/chat_app.py`; legacy app is `ui/legacy/app.py`.  
   - **Recommendation:** Update to "streamlit run ui/chat_app.py" and optionally mention legacy app.

### 4.2 Positive Notes

- Pydantic used for schemas and boundaries.
- Retry and error handling in `core/llm_client.py` (tenacity, specific exceptions).
- Typing and `from __future__ import annotations` used in many modules.
- Parsers and LLM client avoid broad bare excepts (except the one above).

---

## 5. Security Audit

### 5.1 Current Practice

- **Credentials:** Env vars and Streamlit secrets; optional temp-file for GCP SA key; no credentials in repo.
- **Config:** `.env.example` documents required vars; no secrets in example.
- **Paths:** Data/output paths under project; directory creation is controlled.

### 5.2 Gaps

- **File uploads (chat_app.py):** No max file size or count; no content-type validation beyond extension; decode errors handled but not logged securely. Recommend: `MAX_FILE_SIZE_MB`, `MAX_FILES`, and explicit allowlist of MIME types.
- **Input sanitization:** User and file content are passed into prompts and context without sanitization (no stripping of control chars or prompt-injection patterns). At minimum: length limits and control-character stripping for user-facing text.
- **RBAC / auth:** No authentication or role-based access; any user with URL access can run full workflow. Acceptable for PoC; must be added for production.
- **Secrets:** For production, prefer Secret Manager over raw key files (as in COMPREHENSIVE_CODE_AUDIT.md).

---

## 6. Testing Audit

### 6.1 Existing Tests

- **tests/unit/test_section_draft.py:** SectionDraft schema and Writer `draft_section` return shape (mocked LLM). Valuable but isolated.

### 6.2 Gaps

- **Parsers:** No tests for `safe_extract_json` (markdown, XML tags, preambles, trailing commas, truncation). COMPREHENSIVE_CODE_AUDIT suggested tests; none present.
- **Orchestration / agents:** No integration tests for analysis, compliance, or drafting flows (with mocked RAG/LLM).
- **Agent bus:** No test that Writer actually calls `agent_bus.query()` under conditions that trigger analyst/compliance queries.
- **CI:** `.github/workflows/ci.yml` runs `pytest -q || true` and `pip-audit ... || true`, so failures do not fail the build. Lint (ruff) and mypy are not set to `|| true`, so they can fail CI.

**Recommendation:** Add `tests/unit/test_parsers.py` for `safe_extract_json` and key parser paths; add at least one integration test that runs a minimal orchestration path with mocks; then make pytest (and optionally pip-audit) fail the job on failure.

---

## 7. Operational and Robustness

### 7.1 TraceStore and Tracing

- **core/tracing/trace_store.py:** `self.entries` is an unbounded list. Long or busy sessions can grow memory. COMPREHENSIVE_CODE_AUDIT suggested a bounded deque (e.g. maxlen=10000) or time-based trim; not implemented.
- **Vertex / Langfuse:** Optional tracing is well separated; config in `config/settings.py` (e.g. `ENABLE_VERTEX_TRACE`, `TRACE_SAMPLING_RATE`) is clear.

### 7.2 LLM and External Calls

- **Timeouts:** No explicit timeout on Gemini calls in `core/llm_client.py`. Long-running or stuck calls can block. Recommend a configurable timeout (e.g. 120s) and map to SDK timeout/deadline where supported.
- **Token limits:** Various max-token values are set at call sites; some are hardcoded. Centralizing in config (as in COMPREHENSIVE_CODE_AUDIT) would help consistency and tuning.

### 7.3 Configuration and Entrypoints

- **Models:** `config/settings.py` uses stable-looking defaults (`gemini-2.5-pro`, `gemini-2.5-flash`). `.env.example` still references old preview model names in comments; worth updating to match current defaults.
- **main.py:** As above, should advertise `ui/chat_app.py` as the main Streamlit entrypoint.

---

## 8. Dependencies and Environment

- **requirements.txt vs pyproject.toml:** Mostly aligned; `python-pptx` is in requirements but not in `pyproject.toml` dependencies. Optional observability and dev deps are in pyproject only; fine if install path is `pip install -r requirements.txt`.
- **Python:** Requires 3.10+; CI uses 3.10. Consistent.
- **Ruff/mypy:** Configured in pyproject; CI runs both. Good for keeping style and types under check once tests are required to pass.

---

## 9. Documentation and Consistency

- **README:** Accurate for architecture, quick start, agents, and primary vs legacy UI. Main discrepancy is `main.py` still pointing to `ui/app.py`.
- **AUDIT_RESULTS.md / COMPREHENSIVE_CODE_AUDIT.md:** Describe C1/C2 and parsing; code shows C1/C2 fixes and improved parsers. FIXES_C1_C2.md correctly describes what was implemented.
- **AGENT_COMMUNICATION_ARCHITECTURE.md:** Now matches implementation (Writer uses agent_bus). No change needed for accuracy.

---

## 10. Priority Recommendations

### High (do soon)

1. Replace the bare `except:` in `conversational_orchestrator_v2.py` with `UnicodeDecodeError` (and log).
2. Fix `create_tool_executor` return type to `Callable[[str, dict], str]` in `tools/function_declarations.py`.
3. Update `main.py` to say `streamlit run ui/chat_app.py` (and optionally mention legacy).
4. Add unit tests for `safe_extract_json` and critical parser paths.
5. Cap TraceStore size (e.g. `collections.deque(maxlen=10000)` or similar) to avoid unbounded memory growth.

### Medium (next iteration)

6. Add file upload limits (size, count) and basic content-type checks in `ui/chat_app.py`.
7. Introduce a configurable timeout for LLM calls in `core/llm_client.py`.
8. Add at least one integration test (e.g. one full intent path with mocked LLM/RAG) and make CI fail on test failure.
9. Align `.env.example` comments with current model defaults in `config/settings.py`.

### Lower (hardening / production)

10. Input sanitization for user and file content used in prompts (length, control chars, optional prompt-injection patterns).
11. Consider Secret Manager for credentials in production.
12. Add authentication and RBAC if exposing to untrusted users.

---

## 11. Conclusion

The codebase is well-structured and the previously reported critical items (C1 agent bus, C2 function naming/parameters, and parsing robustness) are addressed in the current code. The main gaps are: **testing coverage** (especially parsers and integration), **operational hardening** (TraceStore cap, LLM timeouts, file upload limits), **one bare except and one type hint**, and **small doc/entrypoint inconsistencies**. Addressing the high-priority items above would materially improve reliability and maintainability without large refactors.

---

*End of Deep Audit Report*
