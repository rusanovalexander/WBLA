# Bug Report C1: Agent Communication Bus Not Functional

**Reported By**: Independent Audit
**Date**: 2026-02-12
**Severity**: 🔴 **CRITICAL** - Advertised feature completely non-functional
**Status**: CONFIRMED

---

## Summary

The Agent Communication Bus is completely non-functional. While the infrastructure exists and responders are registered, the Writer agent **never actually calls** `agent_bus.query()`, making all inter-agent communication dead code.

---

## Expected Behavior

According to documentation (AGENT_COMMUNICATION_ARCHITECTURE.md):

```
Writer (drafting Executive Summary):
  "I need to know the key risk for this deal"

  → Sends query to ProcessAnalyst via AgentCommunicationBus

ProcessAnalyst:
  [Searches procedure documents]
  [Analyzes teaser for risk factors]

  → Returns: "Primary risk is untested market segment"

Writer:
  [Incorporates risk into Executive Summary]
```

**UI Should Show**:
```
💬 Writer → ProcessAnalyst: "What's the key risk?"
💬 ProcessAnalyst → Writer: "Primary risk is untested market segment"
```

---

## Actual Behavior

Writer agent **never queries** other agents. The `agent_bus` is:
- ✅ Created correctly
- ✅ Passed to Writer's `__init__`
- ✅ Responders registered correctly
- ❌ **NEVER USED** by Writer

Result: **All agent-to-agent queries return "[Agent X not registered]" or never happen**

---

## Root Cause Analysis

### Code Investigation

**File**: `agents/writer.py`

**Line 364**: Writer stores the bus
```python
def __init__(self, ..., agent_bus: Any = None, ...):
    self.agent_bus = agent_bus  # Stored but never used
```

**Evidence**: Grepped entire `agents/writer.py`:
```bash
$ grep -n "self.agent_bus" agents/writer.py
364:        self.agent_bus = agent_bus
```

Only **ONE occurrence** - the assignment. No usage anywhere.

**Confirmed**: Writer never calls:
- `self.agent_bus.query()`
- Any agent communication methods

### Infrastructure IS Working

**File**: `agents/level3.py` - AgentCommunicationBus class is correct

**File**: `core/conversational_orchestrator.py` lines 101-138:
```python
def _register_agent_responders(self):
    """Register agent responder functions for inter-agent communication."""

    # Process Analyst responder
    pa_responder = create_process_analyst_responder(...)
    self.agent_bus.register_responder("ProcessAnalyst", pa_responder)

    # Compliance Advisor responder
    ca_responder = create_compliance_advisor_responder(...)
    self.agent_bus.register_responder("ComplianceAdvisor", ca_responder)
```

✅ Registration code is correct and being called in `__init__`

### The Missing Link

Writer agent should have code like this (but DOESN'T):

```python
def draft_section(self, section, context):
    # ... existing code ...

    # 🔴 THIS IS MISSING:
    if self.agent_bus and section_needs_risk_info(section):
        risk_info = self.agent_bus.query(
            from_agent="Writer",
            to_agent="ProcessAnalyst",
            query="What are the key risks for this deal?",
            context=context
        )
        # Use risk_info in drafting
```

---

## Impact Assessment

### User-Facing Impact
- **Severity**: CRITICAL (advertised feature completely broken)
- **Visibility**: HIGH (documented in multiple files)
- **User Expectations**: Users expect Writer to query other agents autonomously

### Affected Features
1. ❌ Writer cannot query ProcessAnalyst for clarifications
2. ❌ Writer cannot query ComplianceAdvisor for guideline context
3. ❌ "💬 Agent Comms" sidebar always shows 0 queries
4. ❌ Agent communication log always shows "(No agent communications)"
5. ❌ Documentation promises feature that doesn't work

### Misleading Documentation
**Files that promise this feature**:
- `AGENT_COMMUNICATION_ARCHITECTURE.md` - Detailed examples of agent queries
- `PHASE2_MODERN_IMPLEMENTATION.md` - Lists as implemented feature
- `TEST_CASES.md` - TC-6.1 and TC-6.2 test this feature
- `AUTONOMOUS_AGENT_MIGRATION.md` - Shows as key benefit
- UI sidebar has "💬 Agent Comms" section

**Reality**: None of this works

---

## Why This Wasn't Caught

### Design Assumption
The assumption was that Writer **would naturally use** the agent bus when needed. But:
1. Writer was never refactored to include agent queries
2. Original Writer implementation had no agent communication
3. Agent bus was added to infrastructure but not integrated into Writer logic

### Testing Gap
- No integration tests for agent communication
- Test cases exist (TC-6.1, TC-6.2) but were never run
- Manual testing would have revealed this immediately

---

## Reproduction Steps

1. Run `streamlit run ui/chat_app.py`
2. Complete full workflow: analyze → requirements → compliance → structure → drafting
3. Check sidebar "💬 Agent Comms" section
4. **Expected**: Shows query count > 0
5. **Actual**: Shows "No agent communications yet"

---

## Proposed Fix

### Option 1: Implement Agent Queries in Writer (RECOMMENDED)

Add logic to Writer to query other agents when needed:

```python
# In agents/writer.py, in draft_section() method

def draft_section(self, section, context):
    # ... existing setup code ...

    # 🆕 Query ProcessAnalyst for key risks if needed
    additional_context = ""
    if self.agent_bus:
        if self._section_needs_risk_info(section):
            risk_response = self.agent_bus.query(
                from_agent="Writer",
                to_agent="ProcessAnalyst",
                query="What are the 2-3 most critical risks for this deal?",
                context=context
            )
            additional_context += f"\n**Key Risks (from ProcessAnalyst):**\n{risk_response}\n"

        if self._section_needs_compliance_info(section):
            comp_response = self.agent_bus.query(
                from_agent="Writer",
                to_agent="ComplianceAdvisor",
                query="Are there any compliance considerations for this section?",
                context=context
            )
            additional_context += f"\n**Compliance Notes (from ComplianceAdvisor):**\n{comp_response}\n"

    # Add additional_context to prompt
    # ... rest of drafting code ...
```

**Helper methods needed**:
```python
def _section_needs_risk_info(self, section) -> bool:
    """Check if section should query for risk information."""
    risk_sections = ["executive summary", "risk assessment", "analysis"]
    return any(keyword in section['name'].lower() for keyword in risk_sections)

def _section_needs_compliance_info(self, section) -> bool:
    """Check if section should query for compliance information."""
    compliance_sections = ["compliance", "regulatory", "guidelines"]
    return any(keyword in section['name'].lower() for keyword in compliance_sections)
```

**Effort**: ~2 hours
**Risk**: Low (additive change)

---

### Option 2: Remove Agent Communication Feature

If agent communication is not actually needed:

1. Remove agent bus from Writer
2. Remove responder registration from orchestrators
3. Remove "💬 Agent Comms" from UI
4. Remove all documentation about agent communication
5. Update architecture docs to reflect reality

**Effort**: ~1 hour
**Risk**: Low (removes unused code)
**Downside**: Loses planned feature

---

### Option 3: Make Agent Communication Optional (COMPROMISE)

Document that agent communication is:
- Infrastructure ready (bus + responders work)
- Not yet used by Writer (future enhancement)
- Can be manually triggered via direct queries

Add to README:
```markdown
## Agent Communication (Experimental)

The agent communication bus is implemented but not yet fully integrated.
Currently:
- ✅ Infrastructure: AgentCommunicationBus + responders work
- ✅ Manual queries: Can query agents via orchestrator
- ⚠️ Autonomous queries: Writer doesn't auto-query other agents yet
```

**Effort**: 15 minutes
**Risk**: None
**Downside**: Feature remains incomplete

---

## Recommendations

### Immediate (Before Next Release)

1. **Choose fix option** (recommend Option 1: implement properly)
2. **Update documentation** to reflect current state
3. **Fix test cases** TC-6.1 and TC-6.2 or mark as "NOT IMPLEMENTED"
4. **Add integration test** for agent communication

### Short-term (Next Sprint)

1. Implement Writer agent queries (Option 1)
2. Test with real workflow
3. Verify sidebar shows agent communications

### Long-term (Future Consideration)

1. Make agent queries configurable (enable/disable)
2. Add query count limits (prevent infinite loops)
3. Add query cost tracking
4. Consider async agent queries for performance

---

## Test Plan

After implementing fix:

```python
# Test Case: Writer Queries ProcessAnalyst
def test_writer_queries_analyst():
    # Setup
    orchestrator = ConversationalOrchestrator()
    orchestrator.analyze_deal(teaser)

    # Draft a section
    section = {"name": "Risk Assessment", ...}
    draft = orchestrator.writer.draft_section(section, context)

    # Verify
    assert orchestrator.agent_bus.message_count > 0
    assert any("ProcessAnalyst" in msg.to_agent for msg in orchestrator.agent_bus.message_log)
    assert "key risk" in draft.content.lower()
```

---

## Related Issues

- None found (this is first report)

---

## References

**Code Files**:
- `agents/level3.py` - AgentCommunicationBus implementation
- `agents/writer.py` - Writer class (missing queries)
- `core/conversational_orchestrator.py` - Responder registration
- `ui/chat_app.py` - UI showing non-functional "Agent Comms"

**Documentation Files**:
- `AGENT_COMMUNICATION_ARCHITECTURE.md` - Promises this feature
- `PHASE2_MODERN_IMPLEMENTATION.md` - Claims feature implemented
- `TEST_CASES.md` - TC-6.1, TC-6.2 test this

---

## Conclusion

**Current State**: Feature is 90% implemented but 0% functional

**Infrastructure**: ✅ Working perfectly (bus, responders, registration)
**Integration**: ❌ Missing entirely (Writer never calls bus)

**Recommendation**: Implement Option 1 (add Writer queries) OR clearly document as "not yet implemented" (Option 3)

**Priority**: HIGH - This is advertised across documentation but doesn't work

---

**Report Status**: Submitted for review
**Next Action**: Awaiting decision on fix approach
