# Agent Scalability Example: Adding Financial Analyst

## Current Agent Structure (Keep This Pattern)

All agents follow the same pattern:

```python
# agents/process_analyst.py
class ProcessAnalyst:
    def __init__(self, agent_bus: AgentCommunicationBus, tracer: TraceStore):
        self.agent_bus = agent_bus
        self.tracer = tracer
        self.model = MODEL_FLASH
        self.tools = [tool_search_procedure]

    def analyze_deal(self, teaser: str, governance: dict) -> dict:
        """Main analysis method - uses RAG automatically"""
        # Implementation...
```

## Future: Adding Financial Analyst (Easy!)

### Step 1: Create New Agent File

```python
# agents/financial_analyst.py
"""
Financial Analyst Agent

Responsibilities:
- Analyze financial statements from uploaded files
- Calculate financial ratios (DSCR, LTV, etc.)
- Assess borrower creditworthiness
- Search for financial benchmarks in procedures
"""

from typing import Any
from agents.level3 import AgentCommunicationBus
from core.tracing import TraceStore
from tools.rag_search import tool_search_procedure
from tools.document_loader import tool_load_document
from config.settings import MODEL_FLASH

class FinancialAnalyst:
    """Agent specialized in financial analysis"""

    def __init__(self, agent_bus: AgentCommunicationBus, tracer: TraceStore):
        self.agent_bus = agent_bus
        self.tracer = tracer
        self.model = MODEL_FLASH

        # Tools this agent can use
        self.tools = [
            tool_search_procedure,  # Search for financial benchmarks
            tool_load_document,     # Load financial statements
        ]

    def analyze_financials(
        self,
        financial_statements: str | dict,
        deal_context: dict,
        governance: dict
    ) -> dict:
        """
        Analyze financial statements and calculate key metrics.

        Args:
            financial_statements: Uploaded financial data (PDF, Excel, or dict)
            deal_context: Context from ProcessAnalyst (deal type, amount, etc.)
            governance: Governance context (procedures, frameworks)

        Returns:
            dict: Financial analysis with ratios, benchmarks, concerns
        """

        # 1. Search procedures for financial benchmarks
        benchmark_query = f"financial ratios {deal_context.get('sector', '')} DSCR LTV"
        benchmarks = tool_search_procedure(benchmark_query, num_results=5)

        # 2. Build prompt with governance context
        prompt = f"""
        You are a World Bank Financial Analyst.

        DEAL CONTEXT:
        {deal_context}

        FINANCIAL BENCHMARKS (from procedures):
        {benchmarks}

        FINANCIAL STATEMENTS:
        {financial_statements}

        INSTRUCTIONS:
        1. Calculate key financial ratios:
           - Debt Service Coverage Ratio (DSCR)
           - Loan-to-Value (LTV)
           - Debt-to-Equity
           - Current Ratio
           - Any sector-specific ratios from procedures

        2. Compare against benchmarks from procedures

        3. Identify any red flags or concerns

        4. Provide recommendation: Strong / Acceptable / Weak / Reject

        Return structured JSON with calculations and reasoning.
        """

        # 3. Call LLM (uses core/llm_client.py)
        from core.llm_client import call_llm

        response = call_llm(
            prompt=prompt,
            model=self.model,
            tracer=self.tracer,
            agent_name="FinancialAnalyst"
        )

        # 4. Parse response
        result = self._parse_financial_analysis(response)

        return result

    def _parse_financial_analysis(self, response: str) -> dict:
        """Parse LLM response into structured format"""
        # Implementation similar to ProcessAnalyst._parse_analysis()
        pass
```

### Step 2: Register Agent in Orchestrator

```python
# core/conversational_orchestrator.py

class ConversationalOrchestrator:
    def __init__(self, tracer: TraceStore | None = None):
        self.tracer = tracer or get_tracer()
        self.governance_context = self._load_governance()
        self.agent_bus = AgentCommunicationBus()

        # Existing agents
        self.analyst = ProcessAnalyst(self.agent_bus, self.tracer)
        self.advisor = ComplianceAdvisor(self.agent_bus, self.tracer)
        self.writer = Writer(self.agent_bus, self.tracer)

        # NEW: Add financial analyst
        self.financial_analyst = FinancialAnalyst(self.agent_bus, self.tracer)

        # Register all responders
        self._register_agent_responders()

    def _register_agent_responders(self):
        """Register agents to respond to queries via bus"""
        # Existing registrations
        self.agent_bus.register_responder("process_analyst", self.analyst)
        self.agent_bus.register_responder("compliance_advisor", self.advisor)

        # NEW: Register financial analyst
        self.agent_bus.register_responder("financial_analyst", self.financial_analyst)
```

### Step 3: Add Intent Handler

```python
# core/conversational_orchestrator.py

def process_message(self, message: str, uploaded_files: dict) -> dict:
    """Process user message and route to appropriate handler"""

    # Detect intent (will now recognize financial analysis requests)
    intent = self._detect_intent(message, self.persistent_context)

    if intent == "analyze_deal":
        return self._handle_analysis(message, [])
    elif intent == "analyze_financials":  # NEW!
        return self._handle_financial_analysis(message, uploaded_files, [])
    elif intent == "discover_requirements":
        return self._handle_requirement_discovery(message, [])
    # ... other intents

def _handle_financial_analysis(
    self,
    message: str,
    uploaded_files: dict,
    thinking: list
) -> dict:
    """Handle financial analysis request"""

    thinking.append("🤔 User wants financial analysis")

    # Check if financial statements are uploaded
    financial_files = [
        f for f in uploaded_files.keys()
        if "financial" in f.lower() or "statement" in f.lower() or ".xlsx" in f.lower()
    ]

    if not financial_files:
        return {
            "response": "⚠️ Please upload financial statements (PDF or Excel) first.",
            "thinking": thinking
        }

    thinking.append(f"✓ Found financial files: {financial_files}")

    # Get deal context from previous analysis
    deal_context = self.persistent_context.get("analysis_result", {})

    if not deal_context:
        return {
            "response": "⚠️ Please analyze the deal first before financial analysis.",
            "thinking": thinking,
            "suggest_action": "analyze_deal"
        }

    thinking.append("✓ Loading financial statements...")

    # Load financial files
    financial_data = {}
    for filename in financial_files:
        content = uploaded_files[filename]
        financial_data[filename] = content

    thinking.append("✓ Analyzing financials with FinancialAnalyst agent...")

    # Call FinancialAnalyst
    result = self.financial_analyst.analyze_financials(
        financial_statements=financial_data,
        deal_context=deal_context,
        governance=self.governance_context
    )

    thinking.append("✓ Financial analysis complete")

    # Store result in context
    self.persistent_context["financial_analysis"] = result

    # Format response
    response = f"""
    ## 💰 Financial Analysis Complete

    **Key Ratios:**
    - DSCR: {result.get('dscr', 'N/A')}
    - LTV: {result.get('ltv', 'N/A')}
    - Debt-to-Equity: {result.get('debt_to_equity', 'N/A')}

    **Benchmark Comparison:**
    {result.get('benchmark_comparison', 'N/A')}

    **Concerns:**
    {result.get('concerns', 'None identified')}

    **Recommendation:** {result.get('recommendation', 'N/A')}

    💬 Would you like me to:
    - Include this in the credit pack draft?
    - Analyze specific financial aspects more deeply?
    - Proceed to compliance check?
    """

    return {
        "response": response,
        "thinking": thinking,
        "data": result
    }
```

### Step 4: Enable Agent-to-Agent Communication

Now **Writer** can ask **FinancialAnalyst** for data:

```python
# agents/writer.py

def draft_section(self, section_name: str, context: dict) -> str:
    """Draft a section - can query other agents via bus"""

    # Check if section needs financial data
    if section_name == "Financial Assessment" or "financial" in section_name.lower():
        # Query FinancialAnalyst via bus
        financial_response = self.agent_bus.query(
            target_agent="financial_analyst",
            query="What are the key financial metrics for this deal?",
            context=context
        )

        # Use response in drafting
        prompt = f"""
        Draft the Financial Assessment section.

        Financial metrics from FinancialAnalyst:
        {financial_response}

        Context: {context}
        """
    else:
        # Regular drafting...
```

---

## User Experience After Adding FinancialAnalyst

```
User: [uploads teaser + financial statements Excel]

Agent: ✓ Loaded 2 files: teaser.pdf, financials.xlsx
       I see you've uploaded financial statements. Would you like me to:
       1. Analyze the deal first (recommended)
       2. Jump straight to financial analysis

User: "Analyze the deal first"

Agent: 🤔 THINKING: User wants deal analysis before financials
       ✓ Loading teaser...
       ✓ Searching procedure docs...
       ✓ Determining process path...

       📋 ANALYSIS COMPLETE
       [Shows analysis]

       💬 I notice you also uploaded financial statements. Should I analyze
          those now using our FinancialAnalyst agent?

User: "Yes, analyze the financials"

Agent: 🤔 THINKING: User wants financial analysis
       ✓ Found financial file: financials.xlsx
       ✓ Loading financial data...
       ✓ Searching procedures for financial benchmarks...
       💬 FinancialAnalyst: Calculating ratios...
       ✓ Analysis complete

       💰 FINANCIAL ANALYSIS

       **Key Ratios:**
       - DSCR: 1.45x (Benchmark: min 1.25x) ✅
       - LTV: 65% (Benchmark: max 70%) ✅
       - Debt-to-Equity: 60/40 (Acceptable per Procedure 8.2) ✅

       **Concerns:**
       - Working capital appears tight (Current Ratio 1.1x)
       - Revenue concentration: 60% from single client

       **Recommendation:** Acceptable - proceed with standard covenants

       💬 Should I draft the Financial Assessment section now?
```

---

## Adding More Agents (Easy Pattern)

### Security Analyst Agent
```python
# agents/security_analyst.py
class SecurityAnalyst:
    """Analyzes collateral, security packages, guarantees"""
    def analyze_security(self, collateral_docs, deal_context, governance):
        # Search procedures for collateral requirements
        # Analyze security package
        # Calculate coverage ratios
        pass
```

### Market Analyst Agent
```python
# agents/market_analyst.py
class MarketAnalyst:
    """Analyzes market conditions, sector trends"""
    def analyze_market(self, sector, location, deal_context, governance):
        # Search procedures for sector-specific requirements
        # Could integrate external APIs (market data)
        # Provide market assessment
        pass
```

### Legal Analyst Agent
```python
# agents/legal_analyst.py
class LegalAnalyst:
    """Reviews legal documents, flags issues"""
    def review_legal_docs(self, legal_docs, deal_context, governance):
        # Load legal documents
        # Search guidelines for legal requirements
        # Flag any legal concerns
        pass
```

---

## Benefits of This Architecture

1. **Scalable**: Add new agents without changing existing code
2. **Composable**: Agents can call each other via `AgentCommunicationBus`
3. **Procedure-Driven**: All agents search RAG for bank procedures
4. **Context-Aware**: All agents receive governance context
5. **Traceable**: All agents use unified `TraceStore` for observability
6. **Flexible**: ConversationalOrchestrator routes to correct agent based on user input

---

## Summary

**I will NOT change your agent structure** - it's excellent!

**I will ONLY improve the orchestrator layer**:
- ✅ Add conversation memory
- ✅ Smarter intent detection
- ✅ Extended thinking display
- ✅ Auto-file analysis
- ✅ Example search control

**Your agents remain unchanged and scalable** for future additions like:
- FinancialAnalyst
- SecurityAnalyst
- MarketAnalyst
- LegalAnalyst
- ESG Analyst
- Technical Analyst
- etc.

All follow the same pattern: `__init__()`, main method, RAG tools, agent bus integration.
