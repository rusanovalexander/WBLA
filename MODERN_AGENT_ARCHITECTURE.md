# Modern Conversational Agent Architecture (The Right Way)

## 🎯 Your Vision vs Current Implementation

### What You Want (Modern ChatGPT/Claude-style)
```
User: "Can you look at this deal?"

Agent (thinking visible):
🤔 REASONING: User uploaded a teaser and wants analysis.
   I should:
   1. Load the teaser document
   2. Extract key deal parameters
   3. Search RAG for similar deals
   4. Determine process path
   5. Present findings and ask for approval

✓ Loading teaser: CommercialRealEstate_NYC.pdf
✓ Extracting deal info... Found: $50M acquisition
✓ Searching RAG for "commercial real estate acquisition NYC"
✓ Found 3 similar deals in examples
✓ Process path determined: Full Credit Analysis

📋 ANALYSIS COMPLETE
[Shows full analysis]

💬 Would you like me to add more detail about the market analysis?
   Or should I proceed to discover requirements?

User: "Add more about market risks"

Agent (thinking visible):
🤔 REASONING: User wants deeper market risk analysis.
   I should search RAG for market risk frameworks and analyze NYC market.

✓ Searching guidelines for "market risk assessment commercial real estate"
✓ Analyzing NYC market conditions...
✓ Incorporating into analysis

📋 UPDATED ANALYSIS
[Shows enhanced analysis with market risks]

💬 Does this cover the market risks sufficiently?
```

### What I Built (Keyword-based - WRONG)
```
User: "Can you look at this deal?"

Agent: ❌ Sorry, I don't understand. Try:
- "Analyze this deal"
- "Discover requirements"
- "Check compliance"

User: "Analyze this deal"

Agent: [No reasoning shown]
       [Just executes analyze_deal()]
       [Shows result]

       💡 Next: Discover requirements?
       [✅ Proceed button]

User: "Add more about market risks"

Agent: ❌ Sorry, I don't understand...
```

---

## 🏗️ Proper Architecture (Modern Agentic AI)

### Core Principle: LLM is the Router, Not Keywords

```python
class ModernConversationalAgent:
    """
    The LLM itself decides what to do based on conversation history.
    No keyword matching, no rigid intent detection.
    """

    def __init__(self):
        self.conversation_history = []  # Full conversation memory
        self.context = {
            "uploaded_files": [],
            "current_analysis": None,
            "requirements": None,
            "drafted_sections": {}
        }

        # Available tools (LLM can call any of these)
        self.tools = [
            tool_load_document,
            tool_search_procedure,
            tool_search_guidelines,
            tool_search_examples,
            tool_analyze_deal,
            tool_discover_requirements,
            tool_assess_compliance,
            tool_draft_section,
            tool_revise_content,
        ]

    def process_message(self, user_message: str) -> dict:
        """
        1. Add user message to conversation history
        2. Let LLM decide what to do (no keywords!)
        3. Show reasoning before taking action
        4. Execute tools as needed
        5. Return conversational response
        """

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # LLM decides what to do with full context
        system_prompt = f"""
        You are a World Bank credit pack drafting assistant with access to:
        - RAG database of procedures and guidelines
        - Example credit packs for reference
        - User-uploaded documents (teasers, additional info)

        Current context:
        {json.dumps(self.context, indent=2)}

        Available tools:
        {self._format_tools()}

        CRITICAL INSTRUCTIONS:
        1. ALWAYS show your reasoning before taking action
        2. Use tools autonomously when needed (RAG search, document loading, etc.)
        3. Be conversational - don't require specific keywords
        4. Remember the full conversation context
        5. After each action, ask if user wants to add/review/modify
        6. Combine multiple sources: RAG + examples + uploaded files

        Response format:
        ```
        <reasoning>
        Explain what you understand and what you plan to do
        </reasoning>

        <actions>
        [Tool calls go here - system will execute and show progress]
        </actions>

        <response>
        Conversational response to user, present findings, ask follow-up questions
        </response>
        ```
        """

        # LLM generates response with tool calls
        response = self.llm.generate(
            system=system_prompt,
            messages=self.conversation_history,
            tools=self.tools,
            temperature=0.3,
            thinking_budget=8000  # Show extended reasoning
        )

        # Extract reasoning (visible to user)
        reasoning = self._extract_reasoning(response)

        # Execute tool calls (with progress indicators)
        actions_taken = []
        for tool_call in response.tool_calls:
            progress = f"✓ {tool_call.function.name}..."
            actions_taken.append(progress)
            result = self._execute_tool(tool_call)
            # Update context with results
            self._update_context(tool_call.function.name, result)

        # Get final conversational response
        final_response = response.content

        # Add assistant response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": final_response
        })

        return {
            "reasoning": reasoning,  # Show thinking process
            "actions": actions_taken,  # Show what agent did
            "response": final_response,  # Conversational response
            "context": self.context  # Updated context
        }
```

---

## 🔄 Conversation Flow Examples

### Example 1: Natural Language Analysis

```
User: "I just uploaded a deal teaser, can you take a look?"

Agent Reasoning (visible):
🤔 The user has uploaded a document and wants me to analyze it.
   I should:
   1. Check what files were uploaded
   2. Load the teaser document
   3. Extract key deal parameters
   4. Search RAG for relevant procedures
   5. Search examples for similar deals
   6. Provide comprehensive analysis

Agent Actions (visible with progress):
✓ Loading document: NYC_Commercial_Teaser.pdf
✓ Extracting deal information...
✓ Searching procedure docs for "commercial real estate acquisition"
✓ Searching example credit packs for similar deals
✓ Found 4 relevant examples
✓ Analyzing deal structure...

Agent Response:
📋 I've analyzed your commercial real estate acquisition deal:

**Deal Overview:**
- Property: Office building, Midtown Manhattan
- Amount: $50M acquisition + $10M renovation
- Sponsor: XYZ Development Corp

**Process Path Recommendation:**
Based on procedure document search and 4 similar deals in our database,
I recommend: **Full Credit Analysis** (not simplified) because:
1. Amount exceeds $25M threshold
2. Renovation component adds complexity
3. Sponsor has limited track record in this market

**Similar Deals Found:**
I found 4 similar commercial RE deals that can serve as templates:
- Chicago Office Acquisition (2023) - $45M
- Boston Mixed-Use Development (2023) - $60M
- ...

💬 Would you like me to:
- Add more detail about the market analysis?
- Show you one of the similar deals as reference?
- Proceed to discover the requirements we'll need?
```

### Example 2: Follow-up with Additional Context

```
User: "Can you add more about market risks? I also have a consultant report I can upload."

Agent Reasoning (visible):
🤔 User wants deeper market risk analysis AND has additional information.
   I should:
   1. Search RAG for market risk assessment frameworks
   2. Wait for user to upload consultant report
   3. Integrate both sources into enhanced analysis

Agent Response:
I'll enhance the market risk analysis. Please upload the consultant report,
and I'll integrate it with our guidelines.

[User uploads: MarketReport_NYC_2024.pdf]

Agent Reasoning (visible):
🤔 Now I have the consultant report. I should:
   1. Load and analyze the consultant report
   2. Search guidelines for "commercial real estate market risk"
   3. Combine: guidelines + consultant report + my previous analysis
   4. Present enhanced risk assessment

Agent Actions (visible):
✓ Loading: MarketReport_NYC_2024.pdf
✓ Extracting market insights from consultant report
✓ Searching guidelines: "commercial real estate market risk assessment"
✓ Found relevant sections in Guidelines Doc 4.2
✓ Synthesizing: guidelines + consultant report + deal specifics

Agent Response:
📋 **ENHANCED MARKET RISK ANALYSIS**

Based on three sources:
1. ✅ WB Guidelines (Section 4.2 - Market Risk)
2. ✅ Your consultant report (MarketReport_NYC_2024.pdf)
3. ✅ 4 similar deals in our database

**Key Market Risks:**
- **Office Vacancy Risk**: Consultant report shows NYC office vacancy at 18%
  (above 10% threshold per Guidelines 4.2.3)
  → Mitigation: Property has signed 7-year anchor tenant

- **Interest Rate Risk**: Rate environment per consultant report...
  → Mitigation: ...

[... detailed analysis combining all sources ...]

💬 Does this market risk analysis cover everything you need?
   Or should I explore any specific risk area more deeply?
```

### Example 3: Drafting with Continuous Feedback

```
User: "Let's draft the Executive Summary"

Agent Reasoning (visible):
🤔 User wants to draft Executive Summary. I should:
   1. Review all context (analysis, requirements, compliance)
   2. Search examples for Executive Summary sections from similar deals
   3. Search procedures for Executive Summary requirements
   4. Draft initial version
   5. Ask for feedback before finalizing

Agent Actions (visible):
✓ Reviewing current context: analysis ✓, requirements ✓, compliance ✓
✓ Searching examples: "Executive Summary commercial real estate"
✓ Found 4 example Executive Summaries
✓ Searching procedures: "Executive Summary requirements"
✓ Drafting section based on: guidelines + examples + deal specifics

Agent Response:
📋 **EXECUTIVE SUMMARY - DRAFT V1**

[Shows drafted content]

💬 I've drafted the Executive Summary based on:
- 4 similar deals from our examples database
- Procedure requirements for Executive Summaries
- All the analysis and context we've gathered

Would you like me to:
- Add more detail to any specific part?
- Adjust the tone (more/less formal)?
- Include additional risk discussion?
- Revise any section?

User: "Can you make the risk section more detailed and add a paragraph about the sponsor's exit strategy?"

Agent Reasoning (visible):
🤔 User wants two enhancements:
   1. More detailed risk section
   2. New paragraph on sponsor exit strategy

   I should:
   1. Search RAG for "exit strategy analysis"
   2. Review teaser for sponsor's exit plan
   3. Expand risk section with more specifics
   4. Add exit strategy paragraph

Agent Actions (visible):
✓ Searching procedures: "exit strategy assessment"
✓ Reviewing teaser for exit strategy details
✓ Expanding risk section with market-specific risks
✓ Adding exit strategy paragraph
✓ Revising Executive Summary

Agent Response:
📋 **EXECUTIVE SUMMARY - DRAFT V2**

[Shows revised content with enhancements]

**What I changed:**
✓ Risk section expanded: Added 3 specific market risks with data
✓ New paragraph on exit strategy: Included sponsor's 5-year hold plan

💬 How does this look? Any other adjustments needed?
```

---

## 🛠️ Technical Implementation

### 1. Remove Intent Detection (It's Wrong)

```python
# ❌ DELETE THIS (keyword-based)
def _detect_intent(self, message: str) -> str:
    message_lower = message.lower()
    if "analyz" in message_lower or "assess" in message_lower:
        return "analyze_deal"
    # ...

# ✅ REPLACE WITH THIS (LLM-based)
def process_message(self, message: str) -> dict:
    """Let LLM decide what to do - no keywords!"""

    # LLM has full conversation context
    response = self.llm.generate(
        system=self._get_system_prompt(),
        messages=self.conversation_history + [
            {"role": "user", "content": message}
        ],
        tools=self._get_available_tools(),
        thinking_budget=8000  # Show extended reasoning
    )

    return self._process_llm_response(response)
```

### 2. Add Conversation Memory

```python
class ConversationalAgent:
    def __init__(self):
        # CRITICAL: Store full conversation history
        self.conversation_history = []

        # Store context that persists across messages
        self.persistent_context = {
            "uploaded_files": {},  # filename -> content
            "current_analysis": None,
            "discovered_requirements": None,
            "compliance_assessment": None,
            "drafted_sections": {},  # section_name -> content
            "rag_sources_used": [],  # Track what was searched
            "example_deals_referenced": []  # Track examples used
        }

    def process_message(self, user_message: str) -> dict:
        # Add to history
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })

        # LLM sees FULL conversation history + context
        response = self._call_llm_with_full_context()

        # Add response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": response["content"]
        })

        return response
```

### 3. Show Reasoning (Gemini 2.5 Extended Thinking)

```python
def _call_llm_with_full_context(self) -> dict:
    """Use Gemini 2.5 Pro with extended thinking budget"""

    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=VERTEX_LOCATION
    )

    response = client.models.generate_content(
        model="gemini-2.5-pro-latest",
        contents=self.conversation_history,
        config={
            "thinking_budget_tokens": 8000,  # Extended reasoning visible
            "temperature": 0.3,
            "tools": self._get_available_tools()
        }
    )

    # Extract reasoning (shown to user)
    reasoning = []
    for part in response.candidates[0].content.parts:
        if hasattr(part, 'thought') and part.thought:
            reasoning.append(part.thought)

    return {
        "reasoning": reasoning,  # User sees this!
        "tool_calls": response.candidates[0].function_calls,
        "content": response.text
    }
```

### 4. Integrate Multiple Sources Automatically

```python
def _get_system_prompt(self) -> str:
    return f"""
    You are a World Bank credit pack drafting assistant.

    AVAILABLE KNOWLEDGE SOURCES (use automatically as needed):

    1. **RAG Database**:
       - Procedures (tool_search_procedure): Process paths, requirements
       - Guidelines (tool_search_guidelines): Compliance, frameworks

    2. **Example Credit Packs**:
       - tool_search_examples: Find similar deals for templates
       - Full text of example sections available

    3. **User-Provided Documents**:
       - Uploaded teasers: {list(self.persistent_context['uploaded_files'].keys())}
       - Additional context files: [available in context]

    CURRENT CONTEXT:
    {json.dumps(self.persistent_context, indent=2)}

    CRITICAL BEHAVIOR:
    1. Be CONVERSATIONAL - no keywords required
    2. Show your REASONING before acting
    3. Use ALL sources (RAG + examples + uploads) when relevant
    4. After EVERY response, ask: "Would you like me to add/review/modify anything?"
    5. Remember the full conversation - user shouldn't repeat themselves
    6. Be proactive: If you see missing info, offer to search for it

    CONVERSATION HISTORY:
    {len(self.conversation_history)} messages exchanged
    """
```

---

## 📊 Comparison: Old vs New Architecture

| Feature | Current (Keyword-based) | Modern (LLM-based) |
|---------|------------------------|---------------------|
| **User Input** | Must use keywords | Natural language |
| **Reasoning** | Hidden | Visible (thinking budget) |
| **Context Memory** | None | Full conversation history |
| **Follow-ups** | Not supported | Fully supported |
| **Tool Selection** | Rigid intent mapping | LLM decides autonomously |
| **Multi-source** | Manual | Automatic (RAG+examples+uploads) |
| **Feedback Loop** | Approval buttons | Conversational |
| **Flexibility** | Low (predefined intents) | High (true AI agent) |

---

## 🚀 Implementation Plan

### Phase 1: Core Refactor (1-2 days)
1. Remove intent detection system entirely
2. Add conversation history storage
3. Update system prompt to be conversational
4. Implement reasoning extraction and display

### Phase 2: Multi-Source Integration (1 day)
1. Add tool_search_examples (search example credit packs)
2. Enhance context to track all sources used
3. Update system prompt to encourage multi-source use

### Phase 3: Conversational UX (1 day)
1. Show reasoning in expandable UI component
2. Add "add/review/modify" prompts after each response
3. Enable file upload mid-conversation
4. Display what sources were used for each response

### Phase 4: Testing & Refinement (1 day)
1. Test natural language inputs
2. Test follow-up questions
3. Test multi-source synthesis
4. Refine system prompt based on behavior

---

## 💡 Key Insights: Modern AI Agents

### What Makes ChatGPT/Claude Conversational?

1. **No Intent Detection**: The LLM itself decides what to do
2. **Full Context Memory**: Remembers entire conversation
3. **Extended Thinking**: Shows reasoning before acting
4. **Tool Use**: Autonomously calls functions when needed
5. **Conversational Responses**: Asks clarifying questions, offers options

### What You Need to Change

```python
# ❌ OLD WAY (Your current code)
if "analyze" in message:
    return self._handle_analysis()

# ✅ NEW WAY (Modern agentic AI)
response = llm.generate(
    messages=full_conversation_history,
    tools=[analyze, discover, draft, search_rag, search_examples],
    thinking_budget=8000
)
# LLM decides: "I should analyze this, then search for examples"
```

---

## 🎯 Expected User Experience After Refactor

```
User: "Hey, can you help me with this deal?"

Agent: 🤔 THINKING: User is greeting and asking for help. They likely want
       to start analyzing a deal. I should ask what they have available.

Agent: Hi! I'd be happy to help with your deal. Do you have:
       - A teaser document I can analyze?
       - Any additional context or reports?
       - Or would you like me to explain the process first?

User: [uploads teaser]

Agent: 🤔 THINKING: User uploaded a teaser. I should load it and analyze.

Agent: ✓ Loading NYC_Commercial.pdf
       ✓ Extracting deal info...

       Great! I've loaded your teaser. This is a $50M commercial real estate
       acquisition in Manhattan. Would you like me to:
       1. Provide a full analysis of the deal structure
       2. Search for similar deals in our database
       3. Both of the above

User: "Both please, and also check if there are any compliance issues"

Agent: 🤔 THINKING: User wants analysis + examples + compliance. I'll do all three.

Agent: ✓ Analyzing deal structure...
       ✓ Searching examples for "commercial real estate NYC"
       ✓ Searching guidelines for compliance requirements
       ✓ Assessing compliance...

       📋 COMPLETE ASSESSMENT
       [Shows analysis, examples, compliance]

       Should I proceed to draft sections, or would you like me to
       explore any area more deeply?

User: "Can you add more about market risks? I have a consultant report"

Agent: 🤔 THINKING: User wants enhanced market risk analysis and has additional data.

Agent: Please upload the consultant report, and I'll integrate it with
       our market risk guidelines to provide a comprehensive assessment.

[User uploads report]

Agent: ✓ Loading consultant report
       ✓ Searching guidelines for market risk frameworks
       ✓ Synthesizing: guidelines + report + deal specifics

       📋 ENHANCED MARKET RISK ANALYSIS
       [Shows synthesis of all sources]

       I've combined your consultant's report with our guidelines. Does this
       cover everything, or should I dive deeper into any specific risk?
```

---

## ❓ Questions for You

Before I start the refactor, I need to understand:

1. **Do you want me to completely replace the intent detection system?** (Yes/No)

2. **Should I show the LLM's reasoning as an expandable section?** (Like Claude Code shows thinking)

3. **Do we have example credit packs in the data/ folder that I can index for tool_search_examples?**

4. **What should happen when user uploads a file mid-conversation?** Should it automatically analyze, or ask what to do with it?

5. **How much autonomy do you want?** Should the agent automatically search RAG+examples without asking, or should it ask first?

Let me know, and I'll implement the modern conversational architecture properly.
