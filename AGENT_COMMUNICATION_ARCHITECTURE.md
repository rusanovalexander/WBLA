# Agent Communication Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                          │
│                      (ui/chat_app.py)                           │
│                                                                 │
│  ┌──────────────┬─────────────────────────────────────────┐   │
│  │  📁 Sidebar  │         💬 Chat Messages                │   │
│  │              │                                         │   │
│  │  [+ Upload]  │  User: Analyze this deal               │   │
│  │              │                                         │   │
│  │  📄 teaser   │  🤖 Assistant                          │   │
│  │  📋 example  │  ⏳ Processing...                      │   │
│  │              │    ✓ Reading teaser                    │   │
│  │  🔍 Gov      │    ⏳ Running ProcessAnalyst           │   │
│  │  ✓ IFRS 9    │    💬 Writer → ProcessAnalyst         │   │
│  │              │                                         │   │
│  │  💬 Comms: 3 │  💡 Next: Discover requirements?       │   │
│  │  [View Log]  │  [✅ Proceed]                          │   │
│  │              │                                         │   │
│  └──────────────┴─────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ user message + uploaded files
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              CONVERSATIONAL ORCHESTRATOR                        │
│            (core/conversational_orchestrator.py)                │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 1. Intent Detection                                     │  │
│  │    - analyze_deal                                       │  │
│  │    - discover_requirements                              │  │
│  │    - check_compliance                                   │  │
│  │    - generate_structure                                 │  │
│  │    - draft_section                                      │  │
│  │    - query_agent                                        │  │
│  │    - show_communication                                 │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 2. File Context Update                                  │  │
│  │    - Extract teaser text                                │  │
│  │    - Extract example pack                               │  │
│  │    - Update context dict                                │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 3. Route to Agent                                       │  │
│  │    - Call appropriate agent method                      │  │
│  │    - Pass context                                       │  │
│  │    - Track thinking steps                               │  │
│  └─────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 4. Format Response                                      │  │
│  │    - Build response text                                │  │
│  │    - Collect thinking steps                             │  │
│  │    - Suggest next action                                │  │
│  │    - Get agent comm log if any                          │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │                    │                    │
    ┌────▼─────┐      ┌──────▼──────┐      ┌─────▼─────┐
    │          │      │             │      │           │
    │  📊      │      │  ⚖️         │      │  ✍️       │
    │ Process  │      │ Compliance  │      │  Writer   │
    │ Analyst  │      │  Advisor    │      │           │
    │          │      │             │      │           │
    └────┬─────┘      └──────┬──────┘      └─────┬─────┘
         │                   │                    │
         │                   │                    │
         └───────────────────┼────────────────────┘
                             │
                             ▼
         ┌───────────────────────────────────────┐
         │   AGENT COMMUNICATION BUS             │
         │   (agents/level3.py)                  │
         │                                       │
         │  Registered Responders:               │
         │  - ProcessAnalyst                     │
         │  - ComplianceAdvisor                  │
         │                                       │
         │  Methods:                             │
         │  - register_responder()               │
         │  - query(from, to, query, context)    │
         │  - get_log_formatted()                │
         │  - clear()                            │
         └───────────────────────────────────────┘
```

## Agent Communication Flow

### Scenario 1: Writer Queries ProcessAnalyst

```
┌─────────────────────────────────────────────────────────────┐
│ STEP 1: Writer Needs Information                            │
└─────────────────────────────────────────────────────────────┘
         │
         │ Writer.draft_section() executing
         │ Needs: "What is the loan amount?"
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 2: Query via Agent Bus                                 │
└─────────────────────────────────────────────────────────────┘
         │
         │ self.agent_bus.query(
         │     from_agent="Writer",
         │     to_agent="ProcessAnalyst",
         │     query="What is the loan amount?",
         │     context={
         │         "teaser_text": "...",
         │         "extracted_data": "...",
         │         "requirements": [...]
         │     }
         │ )
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 3: Bus Routes to Registered Responder                  │
└─────────────────────────────────────────────────────────────┘
         │
         │ responder = self._responders["ProcessAnalyst"]
         │ response = responder(query, context)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 4: ProcessAnalyst Responder Executes                   │
└─────────────────────────────────────────────────────────────┘
         │
         │ def responder(query, context):
         │     teaser = context["teaser_text"]
         │     analysis = context["extracted_data"]
         │
         │     prompt = f"""You are ProcessAnalyst.
         │     Question: {query}
         │     Teaser: {teaser}
         │     Analysis: {analysis}
         │     """
         │
         │     return call_llm(prompt, ...)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 5: Response Returned to Writer                         │
└─────────────────────────────────────────────────────────────┘
         │
         │ response = "The loan amount is €50M as stated..."
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 6: Communication Logged                                │
└─────────────────────────────────────────────────────────────┘
         │
         │ AgentMessage:
         │   from_agent: "Writer"
         │   to_agent: "ProcessAnalyst"
         │   query: "What is the loan amount?"
         │   response: "The loan amount is €50M..."
         │   timestamp: "2026-02-11 14:32:15"
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 7: Writer Continues with Response                      │
└─────────────────────────────────────────────────────────────┘
         │
         │ draft_content += f"The loan amount is €50M..."
         │ return SectionDraft(content=draft_content)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ STEP 8: User Sees Draft + Communication Log                 │
└─────────────────────────────────────────────────────────────┘

## Section: Executive Summary

The loan amount is €50M as stated in the teaser...

─────────────────────────────────────────────────────
💬 Agent-to-Agent Communications (1)

[2026-02-11 14:32:15] Writer → ProcessAnalyst
  Q: What is the loan amount?
  A: The loan amount is €50M as stated in the teaser...
```

### Scenario 2: User Queries Agent Directly

```
User: "Ask ProcessAnalyst about the borrower's credit rating"
         │
         ▼
ConversationalOrchestrator._detect_intent()
         │ → intent = "query_agent"
         ▼
ConversationalOrchestrator._handle_agent_query()
         │
         │ Parse: to_agent = "ProcessAnalyst"
         │        query = "borrower's credit rating"
         │
         ▼
AgentCommunicationBus.query(
    from_agent="User",
    to_agent="ProcessAnalyst",
    query="borrower's credit rating",
    context={...}
)
         │
         ▼
ProcessAnalyst responder executes
         │
         ▼
Response: "ProcessAnalyst: The borrower has a BBB+ rating..."
         │
         ▼
User sees:
  🤖 Assistant
    💬 Querying ProcessAnalyst...
    ✓ ProcessAnalyst responded

  **ProcessAnalyst:** The borrower has a BBB+ rating according to...

  💬 Agent Communication Log
  [2026-02-11 14:35:22] User → ProcessAnalyst
    Q: borrower's credit rating
    A: The borrower has a BBB+ rating...
```

## Data Structures

### AgentMessage

```python
@dataclass
class AgentMessage:
    from_agent: str           # "Writer", "User"
    to_agent: str             # "ProcessAnalyst", "ComplianceAdvisor"
    query: str                # The question being asked
    response: str = ""        # The answer received
    timestamp: datetime       # When the query was made
```

### Context Dictionary

```python
context = {
    "teaser_text": str,                    # Raw teaser content
    "teaser_filename": str,                # "loan_teaser.pdf"
    "example_text": str | None,            # Example pack content
    "example_filename": str | None,        # "example_pack.docx"
    "analysis": dict | None,               # ProcessAnalyst output
    "requirements": list[dict],            # Discovered requirements
    "compliance_result": str | None,       # ComplianceAdvisor text output
    "compliance_checks": list[dict],       # Structured checks
    "structure": list[dict],               # Document sections
    "drafts": dict[str, SectionDraft],     # Section name → draft
    "current_section_index": int,          # 0-based index
}
```

### Response Format

```python
{
    "response": str,                  # Markdown response to user
    "thinking": list[str],            # ["✓ step 1", "⏳ step 2", ...]
    "action": str | None,             # "analysis_complete", "section_drafted", ...
    "requires_approval": bool,        # True = show approval checkpoint
    "next_suggestion": str | None,    # "Discover requirements?"
    "agent_communication": str | None # Formatted comm log or None
}
```

## Registered Responders

### ProcessAnalyst Responder

**Purpose:** Answer queries about teaser content and analysis

**Input Context:**
- `teaser_text`: Original teaser
- `extracted_data`: ProcessAnalyst's analysis output
- `requirements`: Discovered requirements

**Example Queries:**
- "What is the loan amount?"
- "What is the borrower's industry?"
- "What is the repayment structure?"

**Response Pattern:**
```
"The loan amount is €50M as stated in the teaser on page 2..."
```

### ComplianceAdvisor Responder

**Purpose:** Answer queries about regulatory guidelines and compliance

**Input Context:**
- `compliance_result`: ComplianceAdvisor's assessment
- RAG search results from guidelines

**Example Queries:**
- "What is the IFRS 9 classification for this loan?"
- "What are the Basel III capital requirements?"
- "What disclosures are required?"

**Response Pattern:**
```
"According to EBA/GL/2020/06 Section 4.2, the IFRS 9 classification is..."
```

## Communication Log Format

```
💬 Agent Communication Log

[2026-02-11 14:32:15] Writer → ProcessAnalyst
  Q: What is the loan amount?
  A: The loan amount is €50M as stated in the teaser...

[2026-02-11 14:33:42] Writer → ComplianceAdvisor
  Q: What is the IFRS 9 classification?
  A: According to EBA/GL/2020/06 Section 4.2, the classification is...

[2026-02-11 14:35:22] User → ProcessAnalyst
  Q: borrower's credit rating
  A: The borrower has a BBB+ rating according to...
```

## Performance Characteristics

### Synchronous vs Asynchronous

**Current:** Synchronous (blocking)
- Writer queries → waits for response → continues

**Future (Phase 4):** Could be asynchronous
- Writer queries multiple agents in parallel
- Aggregates responses

### Caching

**Current:** No caching
- Each query calls LLM

**Future:** Could cache responses
- Same query + same context → cached response

### Governance-Aware Responses

**Current:** ✅ Implemented
- Responders use governance context
- Instructions adapted to frameworks

```python
if governance_context:
    pa_instr = get_process_analyst_instruction(governance_context)
    role_context = f"\n## YOUR ROLE\n{pa_instr[:1500]}\n"
```

## Benefits

### 1. **Autonomous Information Gathering**
- Writer doesn't need all context upfront
- Can query for missing information on-demand

### 2. **Transparency**
- All agent-to-agent queries logged
- User can see what agents are asking each other

### 3. **Modularity**
- Each agent only knows its own domain
- Queries enable cross-domain knowledge

### 4. **Debugging**
- Communication log helps debug issues
- Can see exactly what information was exchanged

### 5. **User Control**
- User can query agents directly
- Can inspect agent knowledge at any time

---

## Summary

The agent communication architecture enables:

✅ **Autonomous collaboration** - Agents query each other as needed
✅ **Full transparency** - All queries logged and visible
✅ **User interaction** - User can query agents directly
✅ **Modularity** - Each agent owns its domain
✅ **Governance-aware** - Responders use framework context

Ready for Phase 3: File System Integration! 🚀
