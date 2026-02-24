# Future Improvements Inspired by Openwork/DeepAgentsJS

**Date**: 2026-02-13
**Context**: Analysis of langchain-ai/openwork and deepagentsjs frameworks
**Purpose**: Identify patterns to enhance Credit Pack Multi-Agent PoC

---

## Executive Summary

The **Openwork/deepagentsjs** architecture demonstrates several advanced patterns that could significantly improve our credit pack drafting system:

1. **Formal planning tool** for task decomposition
2. **Hierarchical subagent spawning** for context isolation
3. **Approval workflows** for human-in-the-loop safety
4. **Multi-provider abstraction** for vendor independence
5. **Graph-based orchestration** (LangGraph)

---

## Current Architecture vs. Openwork

### What We Have ✅

| Feature | Our Implementation | Openwork/DeepAgentsJS |
|---------|-------------------|------------------------|
| Multi-agent system | ✅ 4 agents (Orchestrator, ProcessAnalyst, ComplianceAdvisor, Writer) | ✅ Main agent + spawned subagents |
| Tool calling | ✅ Native Gemini function calling | ✅ LangChain StructuredTools |
| Agent communication | ✅ Agent bus for queries | ✅ Task tool for subagent spawning |
| RAG integration | ✅ Vertex AI Search | ✅ File system as external memory |
| Human-in-the-loop | ✅ Phase transitions require approval | ✅ Tool approval before execution |
| Conversation memory | ✅ V2 persistent context | ✅ Thread-level state management |
| Planning | ❌ Implicit in orchestrator | ✅ Explicit `write_todos` tool |
| Subagent spawning | ❌ Pre-configured agents only | ✅ Dynamic subagent creation |
| Multi-provider | ❌ Gemini-only | ✅ Claude/GPT/Gemini abstraction |
| Graph-based workflow | ❌ Linear orchestration | ✅ LangGraph state machines |

---

## Pattern Analysis & Recommendations

### 1. Planning Tool Pattern 🌟 HIGH PRIORITY

**Openwork Approach**:
- Built-in `write_todos` tool that agents call to create/update task lists
- Agents break down complex requests into discrete steps
- Progress tracking and plan adaptation as new info emerges

**Current System**:
- No formal planning abstraction
- Orchestrator hard-codes workflow phases
- No dynamic task decomposition

**Recommendation**: Add Planning Tool

```python
# New tool: tools/planning.py
def create_planning_tool():
    """Tool for agents to create and track task decomposition."""

    def write_todos(task_list: list[dict]) -> str:
        """
        Create or update task decomposition plan.

        Args:
            task_list: [
                {"task": "Analyze teaser for key terms", "status": "pending"},
                {"task": "Search procedure for assessment criteria", "status": "in_progress"},
                {"task": "Draft executive summary", "status": "completed"}
            ]
        """
        # Store in orchestrator context
        # Enable agents to self-organize work
        # Track progress across complex workflows
        pass

    return {
        "name": "write_todos",
        "description": "Create plan by breaking down complex tasks into steps",
        "function": write_todos
    }
```

**Benefits**:
- Agents can decompose ambiguous requests autonomously
- Better observability into agent reasoning
- Supports iterative refinement as user provides more context
- Natural fit for credit pack workflows (multi-phase, complex)

**Implementation Effort**: Medium (2-3 days)

---

### 2. Subagent Spawning Pattern 🌟 MEDIUM PRIORITY

**Openwork Approach**:
- Main agent can spawn specialized subagents dynamically
- Each subagent has isolated context, custom tools, dedicated prompts
- Use case: "Spawn a compliance expert to review this clause"

**Current System**:
- Pre-configured agent instances (ProcessAnalyst, ComplianceAdvisor, Writer)
- Agent roles fixed at initialization
- Cannot create ad-hoc specialists

**Recommendation**: Add Dynamic Subagent Factory

```python
# New: agents/subagent_factory.py
class SubAgentFactory:
    """Create specialized subagents on-demand for focused tasks."""

    def spawn_subagent(
        self,
        name: str,
        purpose: str,
        tools: list[str],
        context: dict,
        parent_tracer: TraceStore
    ) -> Agent:
        """
        Spawn a specialized subagent with isolated context.

        Example:
            spawn_subagent(
                name="TermSheetValidator",
                purpose="Verify term sheet alignment with credit pack draft",
                tools=["search_guidelines", "search_examples"],
                context={"term_sheet": ts, "draft": draft}
            )
        """
        # Create agent with purpose-specific instruction
        # Isolate context from main workflow
        # Return results to parent agent
        pass
```

**Use Cases**:
1. **Ad-hoc validators**: Spawn expert to check specific compliance rule
2. **Parallel work**: Multiple subagents draft different sections simultaneously
3. **Specialized research**: Deep dive into niche topic without polluting main context
4. **Quality review**: Spawn "red team" agent to critique draft

**Benefits**:
- Flexibility beyond pre-configured agents
- Better context management (subagents don't bloat main context)
- Natural parallelization opportunities

**Implementation Effort**: High (4-5 days)

---

### 3. Approval Workflow Pattern 🌟 CRITICAL PRIORITY

**Openwork Approach**:
- Tool calls show preview of action before execution
- User clicks "Approve" or "Reject" for each action
- Safety-first: dangerous operations never auto-execute

**Current System**:
- Phase transitions require approval ✅
- Individual tool calls execute automatically ❌
- No preview of RAG search results before use

**Recommendation**: Granular Approval System

```python
# Enhanced: core/approval_system.py
class ApprovalWorkflow:
    """Fine-grained approval for high-risk operations."""

    REQUIRES_APPROVAL = [
        "draft_section",      # User should review before accepting draft
        "finalize_pack",      # Critical: final document assembly
        "send_to_committee",  # External action
    ]

    AUTO_APPROVED = [
        "search_procedure",   # Safe: read-only research
        "search_guidelines",  # Safe: read-only research
        "analyze_deal",       # Safe: internal analysis
    ]

    def request_approval(
        self,
        action: str,
        preview: dict,
        risk_level: str
    ) -> bool:
        """
        Request user approval with action preview.

        Shows:
        - What action will be performed
        - Which data will be used
        - Expected outcome
        - Risk assessment
        """
        pass
```

**Benefits**:
- Prevent runaway agents from making bad decisions
- Build user trust through transparency
- Audit trail for compliance (critical in banking)
- Catch errors before expensive LLM calls

**Implementation Effort**: Medium (3-4 days)

---

### 4. Multi-Provider Abstraction 🌟 LOW PRIORITY

**Openwork Approach**:
- Single interface for Claude, GPT-4, Gemini
- Switch providers without code changes
- Graceful fallback when primary provider unavailable

**Current System**:
- Gemini-only (Vertex AI)
- Hard-coded `genai.Client` calls
- No provider abstraction

**Recommendation**: Provider Abstraction Layer

```python
# New: core/llm_providers.py
class LLMProvider(ABC):
    """Abstract provider interface."""

    @abstractmethod
    def call(self, prompt: str, config: dict) -> LLMResult:
        pass

    @abstractmethod
    def call_with_tools(self, prompt: str, tools: list, config: dict) -> LLMResult:
        pass

class GeminiProvider(LLMProvider):
    """Current Vertex AI Gemini implementation."""
    pass

class ClaudeProvider(LLMProvider):
    """Anthropic Claude via AWS Bedrock or direct API."""
    pass

class GPTProvider(LLMProvider):
    """OpenAI GPT-4 implementation."""
    pass

# Config-driven selection
def get_provider(name: str = None) -> LLMProvider:
    name = name or settings.DEFAULT_LLM_PROVIDER
    return PROVIDERS[name]()
```

**Benefits**:
- Vendor independence (avoid lock-in)
- A/B testing different models for quality
- Cost optimization (use cheaper models for simple tasks)
- Resilience (fallback when primary provider down)

**Implementation Effort**: High (5-6 days)

**Priority**: Low - Current Gemini implementation works well, no immediate need

---

### 5. Graph-Based Orchestration (LangGraph) 🌟 MEDIUM-LOW PRIORITY

**Openwork Approach**:
- Workflow defined as state machine graph
- Nodes = agent actions, edges = transitions
- Cycles allowed (iterative refinement)
- Conditional branching based on state

**Current System**:
- Linear phase progression (SETUP → ANALYSIS → ... → COMPLETE)
- Hard-coded workflow in orchestrator
- Limited flexibility for non-standard workflows

**Recommendation**: Consider LangGraph for V3

**When to adopt**:
- ✅ If workflows become highly dynamic (customer-specific processes)
- ✅ If we need complex branching (e.g., "if high-risk, add extra review step")
- ✅ If we support multiple workflow templates (different credit types)
- ❌ Current linear workflow is sufficient for PoC

**Benefits**:
- Visual workflow editing (graph = diagram)
- Better support for iterative workflows (loops)
- Declarative configuration vs. imperative code

**Tradeoffs**:
- Major architectural change
- Learning curve
- Potential over-engineering for current needs

**Implementation Effort**: Very High (2-3 weeks)

**Priority**: Medium-Low - Evaluate after other improvements

---

## Recommended Implementation Roadmap

### Phase 1: Quick Wins (1-2 weeks)

**Priority 1: Approval Workflow Enhancement**
- Add preview for draft sections before committing
- Implement risk classification for operations
- Create approval UI components in Streamlit

**Priority 2: Planning Tool**
- Add `write_todos` function calling tool
- Enable agents to decompose complex requests
- Display plan in sidebar for visibility

**Expected Impact**:
- Better user control and trust
- Improved transparency
- Foundation for more autonomous operation

---

### Phase 2: Architectural Enhancements (3-4 weeks)

**Priority 3: Subagent Spawning**
- Create dynamic subagent factory
- Implement context isolation
- Add parallel execution support

**Priority 4: Testing & Refinement**
- Comprehensive testing of new patterns
- Performance optimization
- Documentation updates

**Expected Impact**:
- More flexible agent architecture
- Better scalability
- Enhanced capabilities for complex workflows

---

### Phase 3: Optional Advanced Features (4-6 weeks)

**Priority 5: Multi-Provider Abstraction** (if needed)
- Abstract LLM provider interface
- Implement Claude and GPT-4 providers
- Add provider selection UI

**Priority 6: Graph-Based Orchestration** (if needed)
- Evaluate LangGraph integration
- Prototype non-linear workflows
- Migration plan from current architecture

**Expected Impact**:
- Vendor independence
- More sophisticated workflow support
- Better cost optimization

---

## Specific Feature Inspirations

### 1. File System as External Memory

**Openwork Pattern**: Agents read/write files to offload large context

**Application to Credit Pack**:
```python
# Instead of keeping everything in memory:
orchestrator.context["full_analysis"] = huge_analysis_text  # ❌ Bloats context

# Write to temp files:
write_file("./workspace/analysis.md", huge_analysis_text)  # ✅ Clean context
# Later: read_file("./workspace/analysis.md") when needed
```

**Benefits**:
- Reduce LLM context size = lower costs
- Persist intermediate results
- Enable easier debugging (inspect files)

---

### 2. Middleware Pattern for Tools

**Openwork Pattern**: Extensible tool injection via middleware

**Application to Credit Pack**:
```python
# Current: Hard-coded tools in agent init
agent = ProcessAnalyst(search_procedure_fn=..., search_guidelines_fn=...)

# Better: Middleware-based tool composition
agent = ProcessAnalyst()
agent.use(SearchProcedureTool())
agent.use(SearchGuidelinesTool())
agent.use(AnalysisValidationTool())  # Easy to add new tools
```

**Benefits**:
- Easier to add/remove tools
- Better testing (mock individual tools)
- Plugin architecture for extensions

---

### 3. Detailed Agent Prompts

**Openwork Pattern**: Comprehensive system prompts steering behavior

**Application to Credit Pack**:

Current prompts are good but could be enhanced with:
- **Examples of good/bad outputs** (few-shot learning)
- **Explicit error handling instructions** ("If data missing, ask user, don't guess")
- **Quality criteria** ("Draft must cite sources, use formal tone, avoid speculation")
- **Self-critique prompts** ("Before finalizing, review your work for...")

---

### 4. Context Isolation

**Openwork Pattern**: Subagents don't share context with parent

**Application to Credit Pack**:

**Current**: All agents see full orchestrator context
**Problem**: Context bloat, agents distracted by irrelevant info

**Better**: Context scoping
```python
# Writer only needs:
writer_context = {
    "section_name": "Executive Summary",
    "structure": section_structure,
    "key_points": filtered_analysis,  # Not full analysis!
}

# ProcessAnalyst only needs:
analyst_context = {
    "teaser_text": teaser,
    "governance_vocab": vocab,
}
```

**Benefits**:
- Smaller context = lower cost
- Agents stay focused
- Easier to debug (less noise)

---

## Comparison Table: Current vs. Recommended

| Aspect | Current | After Phase 1 | After Phase 2 | After Phase 3 |
|--------|---------|---------------|---------------|---------------|
| **Planning** | Implicit | Explicit todos ✅ | Agent-driven ✅ | Graph-based ✅ |
| **Approval** | Phase-level | Action-level ✅ | Risk-based ✅ | Predictive ✅ |
| **Agents** | Fixed 4 | Fixed 4 | Dynamic spawning ✅ | Unlimited ✅ |
| **Providers** | Gemini only | Gemini only | Gemini only | Multi-provider ✅ |
| **Workflow** | Linear | Linear | Linear | Graph-based ✅ |
| **Context** | Shared | Shared | Isolated ✅ | Isolated ✅ |
| **Observability** | Good | Excellent ✅ | Excellent ✅ | Excellent ✅ |

---

## Key Takeaways

### Patterns to Adopt Immediately ✅
1. **Planning tool** - Low-hanging fruit, high value
2. **Approval workflows** - Critical for banking use case
3. **Context isolation** - Optimize costs and focus

### Patterns to Evaluate 🤔
4. **Subagent spawning** - Interesting but need clear use case
5. **Multi-provider** - Nice-to-have, not urgent

### Patterns to Defer 📋
6. **LangGraph migration** - Major effort, unclear ROI for current needs

---

## Action Items

### Immediate (This Week)
- [ ] Review planning tool design with team
- [ ] Prototype approval UI in Streamlit
- [ ] Identify high-risk operations requiring approval

### Short-term (Next 2 Weeks)
- [ ] Implement `write_todos` tool
- [ ] Add action preview to drafting workflow
- [ ] Test planning tool with real workflows

### Medium-term (Next Month)
- [ ] Design subagent spawning interface
- [ ] Implement context scoping for agents
- [ ] Performance testing and optimization

### Long-term (Future Sprints)
- [ ] Evaluate multi-provider abstraction need
- [ ] Research LangGraph migration feasibility
- [ ] Consider desktop app (Electron) for offline use

---

## Resources

- **Openwork Repository**: https://github.com/langchain-ai/openwork
- **DeepAgentsJS Framework**: https://github.com/langchain-ai/deepagentsjs
- **LangGraph Documentation**: https://langchain-ai.github.io/langgraph/
- **Our Current Architecture**: See `AGENT_COMMUNICATION_ARCHITECTURE.md`

---

## Conclusion

The **Openwork/deepagentsjs** architecture validates many of our current design decisions:
- ✅ Multi-agent approach
- ✅ Tool calling with function declarations
- ✅ Human-in-the-loop workflows
- ✅ Conversation memory

**Key gaps to address**:
1. **Formal planning** - Agents should create explicit task lists
2. **Granular approval** - Not just phase transitions, but critical actions
3. **Context isolation** - Smaller contexts = lower costs

**Recommended next step**: Start with **Phase 1** (Planning Tool + Approval Workflows) for maximum impact with minimal disruption to current architecture.

---

**Document Status**: Ready for review and prioritization
**Next Action**: Team discussion on Phase 1 priorities
