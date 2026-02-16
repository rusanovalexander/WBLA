# PR: Agentic hardening and UX improvements (feature/autonomous-agents)

## Summary

This branch improves correctness, transparency, and agentic behavior of the credit pack multi-agent system: decision extraction is hardened, RAG/tool failures are tracked and surfaced to users, a typed workflow state (TaskState) is introduced, Writer runs an optional compliance review sub-task, the UI shows live phase/step status, and session/orchestrator context is stabilized.

## Changes

### Correctness & robustness
- **ProcessAnalyst decision extraction**: Added `_normalize_decision_dict()` and explicit tracing so process-path JSON from `<RESULT_JSON>` or LLM fallback is validated and normalized; failures are logged instead of silent `None`.
- **RAG error handling**: All procedure/guidelines search calls record status and error in `persistent_context["rag_searches_done"]`. Requirements discovery no longer swallows RAG exceptions — it records `RAG_ERROR` in the tracer and passes error entries into `format_rag_results`. Added `_get_rag_error_summary()` and `_rag_error_notice()`; analysis, requirements, compliance, and general responses now append a user-visible notice when any RAG searches failed.

### Architecture
- **TaskState**: New `models/task_state.py` with `TaskState` and `TaskStepState` (phase, steps, progress flags). Orchestrator exposes `get_task_state()` built from `persistent_context` and conversation length — no change to existing flow, only a typed snapshot for UI and future planners.
- **Writer compliance review sub-task**: After drafting a section that needs compliance input, Writer optionally calls ComplianceAdvisor with the draft content and appends “Compliance Review Notes (Agentic Sub-Task)” to the section when the advisor responds.

### UX
- **Workflow status in sidebar**: Chat UI shows current phase (Setup / Analysis / Requirements / Compliance / Drafting / Complete) and step checklist (✅/○) from `get_task_state()`.
- **Session/orchestrator stability**: Persistent context is initialized via `_init_persistent_context()`. Chat app recreates the orchestrator if the stored instance lacks `process_message` (e.g. after reload or version change).

## How to test

1. Run analysis with a teaser; confirm structured decision and, if RAG fails, that a “Data sources” notice appears in the response.
2. Run requirements discovery and compliance; again confirm RAG failure notice when Procedure/Guidelines search errors occur.
3. In the sidebar, confirm “Workflow Status” updates (phase + steps) as you progress.
4. Draft a compliance-related section and confirm optional “Compliance Review Notes” block when ComplianceAdvisor responds.

## Branch

- **Branch**: `feature/autonomous-agents`
- **Base**: current default (e.g. `main` or `master` as appropriate)

## Commits (summary)

1. Improve ProcessAnalyst decision JSON normalization and tracing  
2. Improve RAG error tracking and surfacing  
3. Add TaskState model and orchestrator task snapshot  
4. Add Writer compliance review sub-task via agent bus  
5. Show TaskState-based workflow status in sidebar  
6. Stabilize orchestrator context and session orchestrator instance  
7. Surface RAG errors to user in analysis, requirements, compliance and general responses  
