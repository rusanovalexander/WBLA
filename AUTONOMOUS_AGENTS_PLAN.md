# Autonomous Multi-Agent System - Implementation Plan

**Branch:** `feature/autonomous-agents`
**Goal:** Transform current phase-based system into conversational, autonomous multi-agent architecture
**Inspiration:** Claude Code interaction model

---

## 🎯 Vision

An AI-powered lending system where:
- **Human uploads a teaser** → System handles everything autonomously
- **Agents communicate** with each other to gather information
- **Running commentary** keeps human informed ("I'm analyzing...", "Next, I'll...")
- **Approval checkpoints** at key decisions
- **4 clean agents** (no mini-agents) - each owns its domain end-to-end
- **File monitoring** detects new documents and triggers workflows
- **Conversational UX** feels like talking to Claude Code

---

## 🏗️ Target Architecture

### **4 Core Agents (Clean Separation)**

```
Human User
    ↓
┌──────────────────────────────────┐
│  📋 Orchestrator (Senior Analyst) │
│  - Conversational interface       │
│  - Workflow coordination          │
│  - Running commentary             │
│  - Approval checkpoints           │
└──────────────────────────────────┘
         │  │  │
    ┌────┘  │  └────┐
    ▼       ▼       ▼
┌─────┐ ┌─────┐ ┌─────┐
│ 📊  │ │ ⚖️   │ │ ✍️   │
│ Pro │ │ Gov │ │ Wri │
│ Ana │ │ Adv │ │ ter │
└─────┘ └─────┘ └─────┘
```

---

## 📋 Implementation Phases

### **Phase 1: Agent Consolidation** (Week 1-2)
Merge mini-agents into 4 core agents

**1.1 Merge GovernanceDiscovery → GovernanceAdvisor**
- Move `discover_governance_context()` into GovernanceAdvisor class
- Single method: `assess_compliance()` handles both discovery + assessment
- Remove standalone `GovernanceDiscovery` mini-agent

**1.2 Merge Analysis Mini-Agents → ProcessAnalyst**
- Merge: Extraction, RequirementsDiscovery, AutoFill, AISuggest, AISuggestRetry
- Create: `ProcessAnalyst.analyze_deal()` - single entry point
- Returns: analysis + requirements + auto-filled + suggestions

**1.3 Merge StructureGen → Writer**
- Writer generates structure internally
- Create: `Writer.draft_document()` - handles structure + sections
- Queries other agents via agent_bus

**1.4 Refactor Orchestration**
- Simplify orchestration.py to use 4 agent classes
- Remove mini-agent function calls
- Keep agent_bus for Level 3 communication

---

### **Phase 2: Conversational Interface + Agent Communication** ✅ (Week 3-4)
Replace phase-based UI with chat interface + integrate agent-to-agent communication

**2.1 Chat UI Component** ✅ COMPLETE
- ✅ Created `ui/chat_app.py` with Streamlit chat interface
- ✅ File upload sidebar ('+' button equivalent)
- ✅ Display: User messages + Agent responses
- ✅ Show: Progress indicators, summaries, checkpoints

**2.2 ConversationalOrchestrator** ✅ COMPLETE
- ✅ Created `core/conversational_orchestrator.py`
- ✅ Intent detection: analyze_deal, discover_requirements, check_compliance, draft_section, query_agent
- ✅ Context-aware routing to ProcessAnalyst, ComplianceAdvisor, Writer
- ✅ Integrated AgentCommunicationBus for agent-to-agent queries
- ✅ Registered responders for ProcessAnalyst and ComplianceAdvisor

**2.3 Agent-to-Agent Communication** ✅ COMPLETE
- ✅ Writer can query ProcessAnalyst for data clarification
- ✅ Writer can query ComplianceAdvisor for guideline context
- ✅ Communication log displayed in sidebar (💬 Agent Comms)
- ✅ User can view full agent-to-agent query history
- ✅ User can directly query agents: "Ask ProcessAnalyst about loan amount"

**2.4 Running Commentary + Thinking Process** ✅ COMPLETE
- ✅ Visible thinking steps with st.status()
- ✅ Color-coded progress: ✓ (success), ⏳ (in progress), ❌ (error), 💬 (agent comm)
- ✅ Example: "📄 Reading teaser... ✓", "🔍 Analyzing structure...", "💬 Writer consulting ComplianceAdvisor..."
- ✅ Display progress in expandable status widget

**2.5 Approval Checkpoints** ✅ COMPLETE
- ✅ Human-in-the-loop prompts after major actions
- ✅ Format: "💡 Next: [suggested action]" with [✅ Proceed] button
- ✅ requires_approval flag blocks autonomous execution
- ✅ next_suggestion provides context for user decision

**2.6 Inline Summaries** ✅ COMPLETE
- ✅ Display "Current Status" in general help
- ✅ Show "🎯 Next steps" after each action
- ✅ Context-aware suggestions based on workflow state

---

### **Phase 3: File System Integration** (Week 5)
Monitor folders and auto-trigger workflows

**3.1 Document Monitor**
- Watch `/deals/pending/` for new teasers
- Detect uploads and notify Orchestrator
- Link supporting docs to active deals

**3.2 Auto-Trigger**
- New teaser → Start workflow autonomously
- Notify user: "📄 New deal detected: ProjectAlpha.pdf"
- Request approval: "Should I analyze this?"

**3.3 Artifact Management**
- Save generated documents to `/deals/outputs/`
- Version control for drafts
- Link all artifacts to deal ID

---

### **Phase 4: Enhanced Agent Communication** (Week 6)
Make Level 3 communication more prevalent

**4.1 Mandatory Queries**
- Writer MUST query for specific citations
- Writer MUST query for compliance thresholds
- ProcessAnalyst can query GovernanceAdvisor for rules

**4.2 Query Templates**
- Provide structured query formats
- Example: "Get specific threshold for [criterion]"
- Track all queries in audit trail

**4.3 Communication Dashboard**
- Display agent-to-agent conversations
- Show: "Writer → GovernanceAdvisor: What's the leverage limit?"
- Show: "← 3.5x EBITDA per Guidelines Section 4.2"

---

### **Phase 5: Autonomous Workflow** (Week 7-8)
Full autonomous execution with checkpoints

**5.1 State Machine**
- Orchestrator decides next steps automatically
- Uses: deal parameters, phase completion, compliance status
- Minimal human intervention (only at checkpoints)

**5.2 Smart Routing**
- Based on deal type, route to appropriate process
- Standard vs Fast Track determination
- Escalation for unusual cases

**5.3 Proactive Suggestions**
- "I noticed this deal is similar to DealX..."
- "Based on sector, I recommend..."
- "This requires additional Environmental assessment"

---

## 🔧 Technical Implementation Details

### **ProcessAnalyst Consolidation**

**Before (Current):**
```python
# Fragmented across multiple functions
governance_ctx = discover_governance_context()
analysis = run_agentic_analysis(teaser, governance_ctx)
extracted = call_llm(..., agent_name="Extraction")
requirements = discover_requirements(analysis)
auto_fill_requirements(requirements, teaser)
suggestions = ai_suggest_requirements(requirements)
```

**After (Consolidated):**
```python
class ProcessAnalyst:
    def __init__(self, llm_caller, search_procedure_fn, governance_context):
        self.llm = llm_caller
        self.search_procedure = search_procedure_fn
        self.governance = governance_context

    def analyze_deal(self, teaser_text: str) -> DealAnalysis:
        """
        Complete deal analysis - handles everything internally.

        Returns:
            DealAnalysis with:
            - extracted_data
            - requirements (discovered + auto-filled + AI-suggested)
            - process_path
            - confidence
        """
        # 1. Extract deal parameters (absorbs Extraction)
        data = self._extract_deal_data(teaser_text)

        # 2. Determine process path
        process = self._determine_process(data)

        # 3. Discover requirements (absorbs RequirementsDiscovery)
        requirements = self._discover_requirements(data, process)

        # 4. Auto-fill from teaser (absorbs AutoFill)
        self._auto_fill(requirements, teaser_text)

        # 5. AI suggest remaining (absorbs AISuggest)
        self._ai_suggest_critical(requirements, teaser_text)

        return DealAnalysis(
            data=data,
            requirements=requirements,
            process_path=process,
            confidence=self._calculate_confidence()
        )
```

---

### **GovernanceAdvisor Consolidation**

**Before:**
```python
governance_ctx = discover_governance_context(search_guidelines_fn)
compliance = run_agentic_compliance(requirements, governance_ctx)
```

**After:**
```python
class GovernanceAdvisor:
    def __init__(self, llm_caller, search_guidelines_fn):
        self.llm = llm_caller
        self.search_guidelines = search_guidelines_fn
        self.governance_context = None

    def assess_compliance(self, requirements, teaser_text) -> ComplianceResult:
        """
        Complete compliance assessment including governance discovery.
        """
        # 1. Discover governance context (absorbs GovernanceDiscovery)
        if not self.governance_context:
            self.governance_context = self._discover_governance(
                sector=requirements.sector,
                country=requirements.country
            )

        # 2. Assess each requirement
        checks = []
        for req in requirements:
            check = self._assess_requirement(req, teaser_text)
            checks.append(check)

        return ComplianceResult(
            checks=checks,
            governance_context=self.governance_context
        )
```

---

### **Conversational Interface Example**

```python
class ConversationalOrchestrator:
    def __init__(self):
        self.chat_history = []
        self.process_analyst = ProcessAnalyst(...)
        self.governance_advisor = GovernanceAdvisor(...)
        self.writer = Writer(...)

    async def handle_user_input(self, message: str):
        """Process user message and respond conversationally."""

        if "new deal" in message.lower():
            await self.notify("📄 I found a teaser document")
            await self.notify("🔍 Let me analyze it...")

            # Show progress
            with self.progress_tree():
                await self.show_progress("Reading document", done=True)
                await self.show_progress("Extracting parameters", active=True)

                # Call ProcessAnalyst
                analysis = await self.process_analyst.analyze_deal(teaser)

                await self.show_progress("Extracting parameters", done=True)

            # Summary
            await self.show_summary(
                title="Initial Analysis",
                items=[
                    f"Size: ${analysis.size}M",
                    f"Sector: {analysis.sector}",
                    f"Process: {analysis.process_path}"
                ]
            )

            # Checkpoint
            response = await self.ask_user(
                "Should I proceed with requirements discovery?",
                options=["Yes, continue", "Let me review", "Change process"]
            )

            if response == "Yes, continue":
                await self.discover_requirements()
```

---

## 📊 Expected Outcomes

### **Agent Call Reduction**
```
Before: 34 LLM calls (11 agent types)
After:  20-25 LLM calls (4 agent types)

Orchestrator: 4-6 calls
ProcessAnalyst: 8-12 calls (was: Extraction + RequirementsDiscovery + AutoFill + AISuggest = 15)
GovernanceAdvisor: 3-5 calls (was: GovernanceDiscovery + ComplianceAdvisor = 2-3)
Writer: 8-10 calls (was: StructureGen + Writer = 9)
```

### **User Experience**
```
Before: Click through 6 phase screens
After:  Conversational flow with 3-4 approval checkpoints

User actions reduced by 60%
Autonomous execution increased by 80%
```

---

## 🎯 Success Criteria

✅ **User uploads teaser** → Full workflow runs with 3-4 approvals only
✅ **Agent count** → Reduced from 11 to 4
✅ **LLM calls** → Reduced from 34 to 20-25
✅ **Chat interface** → Running commentary visible
✅ **Agent queries** → Writer queries other agents in 80%+ of runs
✅ **File monitoring** → New files detected within 5 seconds
✅ **Zero functionality loss** → All current features preserved

---

## 📅 Timeline

**Week 1-2:** Agent consolidation
**Week 3-4:** Conversational interface
**Week 5:** File monitoring
**Week 6:** Enhanced communication
**Week 7-8:** Autonomous workflow + testing

**Total: 8 weeks**

---

## 🚀 Next Steps

1. ✅ Create this branch
2. ✅ Create design document (this file)
3. ⏭️ Start Phase 1.1: GovernanceAdvisor consolidation
4. ⏭️ Test each phase incrementally
5. ⏭️ Document as we go

---

**Let's build your dream! 🎉**
