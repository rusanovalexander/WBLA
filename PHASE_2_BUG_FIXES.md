# Phase 2 Bug Fixes - Chat App Implementation

## Testing Environment

**Path:** `C:\Users\GV20FI\Documents\Mode Development\AI in WB lending process\Project Omni\WBLA-feature-autonomous-agents_v1/v2`

**Tested By:** External tester (GV20FI)

**Test Command:** `python -m streamlit run ui/chat_app.py`

---

## Bug #1: ImportError - discover_governance

### Error
```
ImportError: cannot import name 'discover_governance' from 'core.governance_discovery'
```

### Root Cause
- Used wrong function name in `core/conversational_orchestrator.py`
- Actual function: `run_governance_discovery()`
- Used function: `discover_governance()` (doesn't exist)

### Fix (Commit 1dc7886)
```python
# Before
from core.governance_discovery import discover_governance
result = discover_governance()

# After
from core.governance_discovery import run_governance_discovery
result = run_governance_discovery()
```

### Files Changed
- `core/conversational_orchestrator.py` (lines 21, 90)

---

## Bug #2: ImportError - search_procedure_documents

### Error
```
ImportError: cannot import name 'search_procedure_documents' from 'tools.rag_search'
```

### Root Cause
- Invented non-existent function names
- Actual functions: `tool_search_procedure()`, `tool_search_guidelines()`
- Used functions: `search_procedure_documents()`, `search_guidelines_documents()`

### Fix (Commit c7c741a)
```python
# Before
from tools.rag_search import search_procedure_documents, search_guidelines_documents

def search_procedure(self, query: str, top_k: int = 3) -> str:
    return search_procedure_documents(query, top_k=top_k)

# After
from tools.rag_search import tool_search_procedure, tool_search_guidelines

def search_procedure(self, query: str, top_k: int = 3):
    return tool_search_procedure(query, num_results=top_k)
```

### Additional Fixes
1. **Parameter names**: Changed `top_k` → `num_results` (correct parameter name)
2. **Return types**: Removed `-> str` annotations (functions return `Dict[str, Any]`)
3. **Wrapper simplification**: `_rag_search_guidelines()` now directly returns dict

### Files Changed
- `core/conversational_orchestrator.py` (lines 23, 119, 132, 136)

---

## Bug #3: ModuleNotFoundError - trace_store

### Error
```
ModuleNotFoundError: No module named 'core.trace_store'
```

### Root Cause
- Used wrong import path for trace_store module
- Actual location: `core/tracing/trace_store.py`
- Module should be imported via `core.tracing` package

### Fix (Commit 828147f)
```python
# Before
from core.trace_store import get_tracer, TraceStore

# After
from core.tracing import get_tracer, TraceStore
```

### Files Changed
- `core/conversational_orchestrator.py` (line 25)

### Pattern Verification
All existing code uses the correct pattern:
```python
# From agents/compliance_advisor.py
from core.tracing import TraceStore, get_tracer

# From core/orchestration.py
from core.tracing import TraceStore, get_tracer

# From ui/app.py
from core.tracing import TraceStore, set_tracer
```

---

## Bug #4: DefaultCredentialsError - Missing setup_environment()

### Error
```
google.auth.exceptions.DefaultCredentialsError: Your default credentials were not found.
To set up Application Default Credentials, see https://cloud.google.com/docs/authentication/external/set-up-adc
```

### Root Cause
- `chat_app.py` did NOT call `setup_environment()` from settings
- `app.py` DOES call it (line 33)
- `setup_environment()` sets the `GOOGLE_APPLICATION_CREDENTIALS` environment variable
- Without this env var, Google Cloud SDK cannot find credentials

### Why app.py Worked but chat_app.py Didn't

**app.py (Working):**
```python
from config.settings import setup_environment, validate_config
setup_environment()  # ← Sets GOOGLE_APPLICATION_CREDENTIALS
```

**chat_app.py (Broken):**
```python
# Missing setup_environment() call!
from core.conversational_orchestrator import ConversationalOrchestrator
```

### What setup_environment() Does (settings.py lines 216-224)
```python
def setup_environment():
    """Set up environment variables for Google Cloud."""
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = VERTEX_LOCATION
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

    if os.path.exists(KEY_PATH):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH  # ← Critical!
```

### Fix (Commit 69d7b5d)
```python
# Before
import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.conversational_orchestrator import ConversationalOrchestrator

# After
import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Google Cloud environment (MUST be called before importing orchestrator)
from config.settings import setup_environment, VERSION
setup_environment()  # ← Added this!

from core.conversational_orchestrator import ConversationalOrchestrator
```

### Files Changed
- `ui/chat_app.py` (lines 17-18, added setup call)

### Impact
This was a **critical bug** - the chat app could not work at all without credentials. Now it will use the same credential loading mechanism as the main app.

---

## Root Cause Analysis

### Why These Errors Occurred

1. **Insufficient API Review**
   - Did not check actual function names in `core/governance_discovery.py`
   - Did not check actual function names in `tools/rag_search.py`
   - Assumed function names without verification

2. **Incomplete Testing**
   - Did not run `streamlit run ui/chat_app.py` locally before committing
   - Relied on static analysis instead of runtime testing

3. **Lack of Reference Checking**
   - Did not examine how existing code (ui/app.py, ui/phases/*.py) imports these functions
   - Invented new names instead of using established patterns

### How to Prevent Future Errors

1. **Always Check Existing Imports**
   ```bash
   # Before creating new imports, check what exists:
   grep -rn "from tools.rag_search import" --include="*.py"
   grep -rn "from core.governance_discovery import" --include="*.py"
   ```

2. **Verify Function Signatures**
   ```bash
   # Check what functions are actually defined:
   grep -n "^def " tools/rag_search.py
   grep -n "^def " core/governance_discovery.py
   ```

3. **Test Before Committing**
   ```bash
   # Run the app to catch import errors:
   python -m streamlit run ui/chat_app.py
   ```

4. **Check Return Types**
   - Read function docstrings and return statements
   - Don't assume return types, verify them

---

## Current Status

### ✅ Fixed Issues
- [x] ImportError: `discover_governance` → `run_governance_discovery`
- [x] ImportError: `search_procedure_documents` → `tool_search_procedure`
- [x] ImportError: `search_guidelines_documents` → `tool_search_guidelines`
- [x] Parameter mismatch: `top_k` → `num_results`
- [x] Return type assumptions: `str` → `Dict[str, Any]`
- [x] ModuleNotFoundError: `core.trace_store` → `core.tracing`
- [x] **DefaultCredentialsError: Missing `setup_environment()` call (CRITICAL)**
- [x] Governance discovery: Missing RAG search function parameters
- [x] StreamlitDuplicateElementKey: Static approval button key

### 🧪 Next Testing Steps

1. **Run chat_app.py** to verify imports work
2. **Test full workflow**:
   - Upload teaser
   - Run analysis
   - Discover requirements
   - Check compliance
   - Generate structure
   - Draft sections
3. **Test agent communication**:
   - Verify Writer → ProcessAnalyst queries work
   - Verify Writer → ComplianceAdvisor queries work
   - Check communication log display

### 📝 Lessons Learned

1. **Don't invent API names** - Always check what exists first
2. **Test runtime, not just syntax** - Import errors only appear at runtime
3. **Follow established patterns** - Check how existing code does imports
4. **Read function signatures** - Don't assume parameter names or return types
5. **Use grep before coding** - Quick searches prevent mistakes

---

---

## Bug #5: Governance Discovery - Missing RAG Search Functions

### Warning
```
Governance discovery: no RAG results from either document
```

### Root Cause
- `_load_governance()` called `run_governance_discovery()` with NO parameters
- `run_governance_discovery()` requires `search_procedure_fn` and `search_guidelines_fn`
- Without these, it cannot query RAG to discover governance context
- Results in empty/failed governance discovery

### Fix (Commit 7eb4130)
```python
# Before
def _load_governance(self) -> dict[str, Any]:
    result = run_governance_discovery()  # ← No search functions!

# After
def _load_governance(self) -> dict[str, Any]:
    result = run_governance_discovery(
        search_procedure_fn=tool_search_procedure,  # ← Pass RAG functions
        search_guidelines_fn=tool_search_guidelines,
        tracer=self.tracer
    )
    return {
        "frameworks": result.get("frameworks", []),
        "summary": result.get("summary", ""),
        "full_context": result  # Store complete governance data
    }
```

### Files Changed
- `core/conversational_orchestrator.py` (lines 90-96)

### Impact
Without this fix, the governance context would be empty, meaning:
- Agents wouldn't have framework-specific terminology
- No compliance framework guidance
- No section templates from procedures
- Generic instructions instead of domain-adapted ones

Now governance discovery actually searches documents and populates the full context.

---

---

## Bug #6: StreamlitDuplicateElementKey - Approval Button

### Error
```
StreamlitDuplicateElementKey: There are multiple elements with the same
key='approve_button'
```

### Root Cause
- `render_approval_checkpoint()` used static button key: `"approve_button"`
- When approval checkpoint shown in message history, same button rendered multiple times
- Streamlit requires unique keys for ALL UI elements

### Fix (Commit 8298cfa)
```python
# Before
def render_approval_checkpoint(next_suggestion: str):
    if st.button("✅ Proceed", key="approve_button", ...):  # ← Static key!

# After
def render_approval_checkpoint(next_suggestion: str, message_idx: int):
    if st.button("✅ Proceed", key=f"approve_button_{message_idx}", ...):  # ← Unique key!
```

### Files Changed
- `ui/chat_app.py` (lines 162, 172, 199, 297)

### Impact
Without this fix, the chat app would crash when rendering message history with approval checkpoints.

---

## Commits

| Commit | Description | Files |
|--------|-------------|-------|
| `1dc7886` | Fix discover_governance import | conversational_orchestrator.py |
| `c7c741a` | Fix RAG search function imports | conversational_orchestrator.py |
| `828147f` | Fix trace_store import path | conversational_orchestrator.py |
| `69d7b5d` | **Fix missing setup_environment() call (CRITICAL)** | chat_app.py |
| `7eb4130` | Fix governance discovery RAG functions | conversational_orchestrator.py |
| `8298cfa` | Fix Streamlit duplicate button key | chat_app.py |

---

## Testing Checklist

### Import Tests
- [ ] `import core.conversational_orchestrator` - no errors
- [ ] `from core.conversational_orchestrator import ConversationalOrchestrator` - works
- [ ] `orchestrator = ConversationalOrchestrator()` - initializes without errors

### Functional Tests
- [ ] Upload teaser file
- [ ] Run "Analyze this deal"
- [ ] Agent communication logged
- [ ] All intents route correctly
- [ ] No more import errors

### Integration Tests
- [ ] ProcessAnalyst.analyze_deal() - calls tool_search_procedure
- [ ] ComplianceAdvisor.assess_compliance() - calls tool_search_guidelines
- [ ] Writer.draft_section() - agent bus queries work

---

## File Audit Summary

### Files Reviewed
- ✅ `core/governance_discovery.py` - has `run_governance_discovery()`
- ✅ `tools/rag_search.py` - has `tool_search_procedure()`, `tool_search_guidelines()`
- ✅ `core/conversational_orchestrator.py` - now uses correct imports
- ✅ `ui/chat_app.py` - imports ConversationalOrchestrator

### Functions Verified
| Module | Function | Return Type |
|--------|----------|-------------|
| governance_discovery | `run_governance_discovery()` | `dict` |
| rag_search | `tool_search_procedure(query, num_results)` | `Dict[str, Any]` |
| rag_search | `tool_search_guidelines(query, num_results)` | `Dict[str, Any]` |

### Import Patterns Used by Existing Code
```python
# ui/app.py
from tools.rag_search import tool_search_rag, tool_search_procedure, tool_search_guidelines

# ui/phases/setup.py
from tools.rag_search import test_rag_connection, tool_search_procedure, tool_search_guidelines

# agents/compliance_advisor.py (tool names in config)
"tools": ["tool_search_guidelines", "tool_search_procedure", "tool_load_document"]
```

**Pattern:** All use `tool_search_*` naming convention, NOT `search_*_documents`

---

## Conclusion

Both import errors were caused by **incorrect API assumptions**. The fixes align the conversational orchestrator with the existing codebase's import patterns and function signatures.

**Next:** Wait for external tester to run again and report any new errors.
