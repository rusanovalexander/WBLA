# Bug Report: Post-C2 Fix Issues

**Reported By**: User comprehensive audit
**Date**: 2026-02-13
**Context**: After C2 fix implementation
**Status**: All critical issues now fixed

---

## Summary

User audit revealed that the C2 fix introduced **new bugs** and exposed **existing design gaps**. This report documents all findings and fixes.

---

## Bug 1: NameError - `top_k` Undefined in V2 Orchestrator ✅ FIXED

### Severity: 🔴 CRITICAL

### Location
- `core/conversational_orchestrator_v2.py` lines 161, 172

### Problem
When fixing parameter names from `top_k` → `num_results`, I updated the method signature and call to `tool_search_procedure`, but **forgot to update the tracking dictionary** that logs searches.

**Before C2 fix**:
```python
def search_procedure(self, query: str, top_k: int = 3):
    result = tool_search_procedure(query, num_results=top_k)
    self.persistent_context["rag_searches_done"].append({
        "type": "procedure",
        "query": query,
        "num_results": top_k  # ← Was correct
    })
```

**After C2 fix (BROKEN)**:
```python
def search_procedure(self, query: str, num_results: int = 3):  # ← Fixed
    result = tool_search_procedure(query, num_results=num_results)  # ← Fixed
    self.persistent_context["rag_searches_done"].append({
        "type": "procedure",
        "query": query,
        "num_results": top_k  # ← FORGOT TO UPDATE! NameError!
    })
```

### Impact
- **NameError at runtime** whenever `search_procedure()` or `search_guidelines()` called
- Crashes during `_handle_enhance_analysis` (line 503)
- Crashes when agents use orchestrator's search wrappers

### Root Cause
Incomplete refactoring - parameter renamed in signature but not in tracking code.

### Fix Applied
```python
def search_procedure(self, query: str, num_results: int = 3):
    result = tool_search_procedure(query, num_results=num_results)
    self.persistent_context["rag_searches_done"].append({
        "type": "procedure",
        "query": query,
        "num_results": num_results  # ← Fixed
    })
```

Applied to both `search_procedure()` and `search_guidelines()`.

### Files Modified
- `core/conversational_orchestrator_v2.py` (lines 161, 172)

---

## Bug 2: Responder LLM Calls Untraced ✅ FIXED

### Severity: 🟡 MEDIUM

### Location
- `agents/level3.py` line 135
- Both V1 and V2 orchestrators when creating responders

### Problem
Responder factories call `llm_caller` with only 5 positional arguments:
```python
result = llm_caller(prompt, model, 0.0, 1200, "ProcessAnalyst")
```

But `call_llm` signature has 7 parameters (with defaults):
```python
def call_llm(prompt, model, temperature, max_tokens, agent_name, tracer=None, thinking_budget=None)
```

This **works** because `tracer` and `thinking_budget` have defaults. But it means:
- Responder LLM calls use the **global singleton tracer** instead of orchestrator's session-specific tracer
- **Trace bleed** across Streamlit sessions
- **No observability** - responder calls invisible in session traces

### Impact
- Tracer pollution across sessions (Streamlit multi-user issue)
- Cannot see responder LLM calls in session trace logs
- Debugging agent communication is harder

### Root Cause
Responder factories don't receive `tracer` parameter and can't pass it to `llm_caller`.

### Fix Applied

Created tracer-aware wrapper in orchestrators before registering responders:

```python
# In both V1 and V2 orchestrators
def llm_with_tracer(prompt, model, temperature, max_tokens, agent_name):
    """Wrapper that passes the orchestrator's tracer to call_llm."""
    return call_llm(prompt, model, temperature, max_tokens, agent_name, tracer=self.tracer)

# Then use wrapper instead of call_llm directly
pa_responder = create_process_analyst_responder(
    llm_caller=llm_with_tracer,  # ← Now includes tracer
    model=MODEL_PRO,
    governance_context=self.governance_context,
)
```

### Files Modified
- `core/conversational_orchestrator.py` (lines 104-119)
- `core/conversational_orchestrator_v2.py` (lines 123-141)

### Alternative Fix Not Chosen
Could have modified responder factories to accept `tracer` parameter, but that would require:
- Changing factory signatures
- All callers to pass tracer
- More invasive change

Wrapper approach is **cleaner** - no signature changes needed.

---

## Bug 3: ComplianceAdvisor Missing Standalone Agent Class

### Severity: 🟡 MEDIUM (Design Gap, Not Bug)

### Location
- `agents/compliance_advisor.py` - Only has instruction template, no class

### Problem
Unlike `ProcessAnalyst` which has a full agent class with `analyze_deal()` method, **ComplianceAdvisor has no standalone agent class**. It only exists as:
- An instruction template (`get_compliance_advisor_instruction`)
- A responder factory (`create_compliance_advisor_responder`)
- Never instantiated as a standalone agent

### Current Usage
ComplianceAdvisor is **only used via agent bus responder**, never directly called by orchestrator.

### Is This a Bug?
**No** - This is actually the **intended design**:
- ProcessAnalyst: **Primary agent** - orchestrator calls directly for analysis
- ComplianceAdvisor: **Support agent** - only responds to queries from other agents
- Writer: **Primary agent** - orchestrator calls directly for drafting

### Why Not a Problem (Yet)
- The current workflow doesn't need standalone ComplianceAdvisor
- All compliance checks happen via Writer queries during drafting
- If we later need standalone compliance phase, we'd add the class then

### Recommendation
**Document but don't fix** - add to architecture docs that ComplianceAdvisor is query-only.

---

## Bug 4: Writer Doesn't Use Native Function Calling

### Severity: 🟢 LOW (Works As Designed)

### Location
- `agents/writer.py` - Uses text-based `<AGENT_QUERY>` syntax

### Problem
Writer's instructions reference `<AGENT_QUERY>` tag parsed by regex:
```python
# Writer instruction
"Use <AGENT_QUERY to=ProcessAnalyst>question</AGENT_QUERY> to query other agents"
```

This is **text-based parsing**, not native Gemini function calling.

### Why This Works
- Writer doesn't call RAG tools (ProcessAnalyst and ComplianceAdvisor do that)
- Writer only queries **other agents** via agent bus
- Agent queries are **inter-process communication**, not LLM tool calls
- Text-based syntax actually works fine for this use case

### Is Native Calling Better?
**Potentially**, but low priority:
- Agent queries work reliably with text parsing
- Native function calling for agent queries would require:
  - New function declaration for "query_agent" tool
  - Executor that routes to agent_bus.query()
  - More complex setup for marginal benefit

### Recommendation
**Low priority optimization** - current approach works, native calling would be cleaner but not necessary.

---

## Bug 5: Orchestrator Instructions Reference Wrong Tool Names

### Severity: 🟢 LOW (Cosmetic)

### Location
- `agents/orchestrator.py` lines 282-291

### Problem
Orchestrator instruction template lists tools:
```
<TOOLS>
- tool_load_document: Load any document
- tool_scan_data_folder: List available documents
- tool_search_rag: Search Procedure/Guidelines
</TOOLS>
```

But native function declarations use different names:
- `search_procedure` (not `tool_search_procedure`)
- `search_guidelines` (not `tool_search_guidelines`)
- `search_rag` (not `tool_search_rag`)

### Why This Doesn't Matter
**Orchestrator doesn't actually call tools in V2 flow** - it delegates to agents. The `<TOOLS>` section is informational context only, not used for parsing.

### Recommendation
**Low priority cleanup** - update documentation for consistency, but no functional impact.

---

## Summary Table

| Issue | Severity | Status | Impact |
|-------|----------|--------|--------|
| Bug 1: `top_k` NameError in V2 | 🔴 CRITICAL | ✅ FIXED | Runtime crash |
| Bug 2: Responder calls untraced | 🟡 MEDIUM | ✅ FIXED | Trace bleed, no observability |
| Bug 3: ComplianceAdvisor no class | 🟡 MEDIUM | 📝 DESIGN | Not needed yet |
| Bug 4: Writer text-based queries | 🟢 LOW | 📝 WORKS | Functional, not optimal |
| Bug 5: Orchestrator tool name docs | 🟢 LOW | 📝 COSMETIC | No functional impact |

---

## Testing After Fixes

### Test Bug 1 Fix (NameError)
```bash
streamlit run ui/chat_app.py
# Upload teaser
# Say: "start analysis"
# Should complete without NameError
```

### Test Bug 2 Fix (Tracer)
```python
# In code, check tracer after agent communication:
orchestrator.tracer.traces
# Should see responder LLM calls logged under session tracer, not global
```

### Expected Behavior
- Analysis completes without crashes ✅
- Responder calls visible in session trace ✅
- No trace bleed across sessions ✅

---

## Lessons Learned

### From Bug 1
**Refactoring checklist**:
- ✅ Update function signature
- ✅ Update function calls
- ✅ Update **all references to old variable name** (including logging, tracking, comments)

Use IDE "Rename Symbol" feature instead of manual find-replace to catch all references.

### From Bug 2
**Dependency injection pattern**:
- When creating factories, consider **closure over session state** (like tracer)
- Wrapper functions are cleaner than changing factory signatures
- Alternative: Make factories accept all dependencies explicitly

### General
**Multi-file refactoring risk**:
- Changing parameter names across multiple layers is high-risk
- Need comprehensive testing after such changes
- Consider pair of changes: first add new param, then deprecate old

---

## Files Modified (This Fix)

1. `core/conversational_orchestrator_v2.py`:
   - Lines 161, 172: Fixed `top_k` → `num_results` in tracking
   - Lines 123-127: Added tracer wrapper for responders

2. `core/conversational_orchestrator.py`:
   - Lines 104-109: Added tracer wrapper for responders

3. `BUG_REPORT_POST_C2_ISSUES.md`:
   - This comprehensive audit report

---

## Status: All Critical Issues Resolved

**Ready for testing** with all critical bugs fixed.

---

**Report Date**: 2026-02-13
**Priority**: CRITICAL fixes complete, MEDIUM fixes complete, LOW issues documented
