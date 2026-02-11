# UI Refactor & Tracing Integration Plan

**Branch:** `feature/ui-refactor-and-tracing`  
**Status:** In Progress  
**Target:** Keep main branch stable, merge when fully tested

---

## Phase 1: UI Refactoring

### 1.1 Session State Management ✅ IN PROGRESS
**File:** `ui/utils/session_state.py`

Extract from `app.py` lines 89-147:
- `init_state()` - Initialize all session state defaults
- `get_tracer()` - Get current session tracer
- `_advance_phase()` - Phase transition logic

**Benefits:**
- Single source of truth for state structure
- Easier to test state initialization
- Clearer state dependencies

---

### 1.2 Reusable Components
**Files:**
- `ui/components/sidebar.py` - Navigation, RAG status, phase indicator
- `ui/components/file_upload.py` - Document upload widgets

Extract from `app.py`:
- Sidebar rendering (lines ~175-280)
- File upload sections (lines ~300-450)

---

### 1.3 Phase Modules
**Files:**
- `ui/phases/setup.py` - SETUP phase (RAG connection, governance discovery)
- `ui/phases/analysis.py` - ANALYSIS phase (teaser analysis, orchestrator decision)
- `ui/phases/process_gaps.py` - PROCESS_GAPS phase (requirements discovery)
- `ui/phases/compliance.py` - COMPLIANCE phase (compliance assessment)
- `ui/phases/drafting.py` - DRAFTING phase (section generation)
- `ui/phases/complete.py` - COMPLETE phase (export, download)

Each phase module exports:
```python
def render_phase_XXX():
    """Render the XXX phase UI."""
    pass
```

---

### 1.4 Main App Refactor
**File:** `ui/app.py` (slim down to ~200 lines)

New structure:
```python
# Imports
# Page config
# Session state init (from ui.utils.session_state)
# Sidebar (from ui.components.sidebar)
# Phase routing
if phase == "SETUP":
    from ui.phases.setup import render_phase_setup
    render_phase_setup()
elif phase == "ANALYSIS":
    from ui.phases.analysis import render_phase_analysis
    render_phase_analysis()
# ... etc
```

---

## Phase 2: Vertex AI Trace Integration

### 2.1 Trace Module
**File:** `core/tracing/vertex_trace.py`

Features:
- Initialize Vertex AI Trace client
- Trace context management
- Span creation for LLM calls
- Cost/token tracking per span
- Integration with existing TraceStore

```python
class VertexTraceManager:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.client = trace_client
        
    def create_span(self, name: str, attributes: dict):
        """Create a trace span for an operation."""
        pass
        
    def record_llm_call(self, model: str, prompt_tokens: int, output_tokens: int, cost: float):
        """Record LLM call metrics."""
        pass
```

---

### 2.2 LLM Client Integration
**File:** `core/llm_client.py`

Add tracing to:
- `call_llm()` - Wrap with span
- `call_llm_streaming()` - Wrap with span
- `call_llm_with_tools()` - Wrap with span + tool call sub-spans

Example:
```python
def call_llm(..., vertex_trace=True):
    if vertex_trace:
        with trace_manager.create_span(f"LLM:{agent_name}", {...}):
            # existing call logic
    else:
        # existing call logic
```

---

### 2.3 Configuration
**File:** `config/settings.py`

Add:
```python
# Vertex AI Trace
ENABLE_VERTEX_TRACE = os.getenv("ENABLE_VERTEX_TRACE", "false").lower() == "true"
TRACE_SAMPLE_RATE = float(os.getenv("TRACE_SAMPLE_RATE", "1.0"))  # 1.0 = 100%
```

---

## Testing Strategy

### Unit Tests
- Test session state initialization
- Test phase transitions
- Test trace span creation

### Integration Tests
- Test full workflow through all phases
- Verify trace data appears in Vertex AI console
- Test with/without tracing enabled

### Manual Testing
- Run app locally with new structure
- Verify all phases render correctly
- Check Vertex AI Trace dashboard

---

## Migration Path

1. ✅ Create new directory structure
2. 🔄 Extract modules one at a time
3. ⏳ Update imports in app.py progressively
4. ⏳ Test each module as it's extracted
5. ⏳ Add Vertex AI Trace integration
6. ⏳ Full regression test
7. ⏳ Merge to main when stable

---

## Rollback Plan

If issues arise:
```bash
git checkout main  # Revert to stable version
```

The feature branch preserves all work for later refinement.

---

## Estimated Timeline

- Session state extraction: 30 min
- Component extraction: 1 hour
- Phase extraction: 3-4 hours
- Main app refactor: 1 hour
- Vertex Trace integration: 2 hours
- Testing & debugging: 2-3 hours

**Total: 1-2 days**

---

## Success Criteria

- [ ] App runs without errors
- [ ] All phases function correctly
- [ ] No regression in functionality
- [ ] Code is more maintainable (smaller files)
- [ ] Traces visible in Vertex AI console
- [ ] Token/cost tracking works
- [ ] Documentation updated
- [ ] Git history clean with meaningful commits
