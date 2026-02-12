# Testing Guide - Modern Conversational Agent System

## 🎯 What to Test

This guide helps you test the new modern conversational architecture with:
- Full conversation memory
- LLM-based intent detection
- Auto-file analysis
- Reasoning display
- Sources tracking

---

## 🚀 Quick Start

### 1. Run the App

```bash
cd "C:\Users\Aleksandr Rusanov\Downloads\refactored_FINAL_FIXED"
streamlit run ui/chat_app.py
```

The app will automatically use `ConversationalOrchestratorV2` if available, otherwise falls back to v1.

### 2. Verify V2 is Active

**Check for these NEW UI elements**:
- ✅ "📚 Sources" section in sidebar (should show "No sources used yet")
- ✅ Expandable "🤔 Agent Reasoning" in messages
- ✅ Expandable "📚 Sources Consulted" in messages

If you see these, V2 is working! ✅

---

## 📋 Test Scenarios

### Scenario 1: Basic Conversation Flow

**Goal**: Test natural language understanding and conversation memory

**Steps**:
1. Upload a teaser PDF
   - **Expected**: Auto-analysis message appears
   - **Check**: Sidebar "📚 Sources" shows "Files Analyzed: 1"

2. Say: "Can you look at this deal?"
   - **Expected**: Agent detects `analyze_deal` intent
   - **Check**: Analysis runs, shows full process path
   - **Check**: Expandable "📚 Sources Consulted" shows RAG searches

3. Say: "What's the loan amount?"
   - **Expected**: Agent answers based on previous analysis (uses conversation memory)
   - **Check**: Answer is correct without re-analyzing

4. Say: "Add more about market risks"
   - **Expected**: Agent detects `enhance_analysis` intent
   - **Expected**: Enhances analysis with market risk details
   - **Check**: RAG search for "market risk" visible in sources

**Success Criteria**:
- ✅ Natural language prompts work (no "I don't understand" errors)
- ✅ Conversation memory works (agent remembers previous analysis)
- ✅ Sources tracking shows RAG searches in sidebar

---

### Scenario 2: Multi-File Upload

**Goal**: Test auto-file analysis mid-conversation

**Steps**:
1. Upload teaser.pdf
   - **Expected**: "✓ Analyzing teaser.pdf..."
   - **Expected**: Shows insights summary

2. Say: "Analyze this deal"
   - **Expected**: Full analysis completes

3. Upload additional file (e.g., MarketReport.pdf)
   - **Expected**: Auto-analysis message immediately
   - **Expected**: Agent offers to integrate: "This market report adds..."
   - **Check**: Sidebar shows "Files Analyzed: 2"

4. Say: "Yes, include it"
   - **Expected**: Analysis updated with market report data
   - **Check**: Sources show file was used

**Success Criteria**:
- ✅ Files auto-analyzed when uploaded
- ✅ Agent proactively suggests integration
- ✅ Sidebar tracks file analysis count

---

### Scenario 3: Flexible Intent Detection

**Goal**: Test LLM-based intent detection (not keywords)

**Test Cases**:

| User Says | Expected Intent | Old System (keyword) | New System (LLM) |
|-----------|----------------|---------------------|------------------|
| "Can you look at this?" | analyze_deal | ❌ "I don't understand" | ✅ Analyzes |
| "Add more about risks" | enhance_analysis | ❌ Not supported | ✅ Enhances |
| "Show me similar deals" | search_examples | ❌ Not supported | ✅ Searches |
| "What's the DSCR?" | general_question | ❌ "I don't understand" | ✅ Answers |

**Success Criteria**:
- ✅ All natural language prompts work
- ✅ No "I don't understand" errors
- ✅ Agent understands context from conversation

---

### Scenario 4: Reasoning Display

**Goal**: Test extended thinking visibility

**Steps**:
1. Upload teaser and say "Analyze this deal"

2. After analysis completes, look for:
   - **Check**: Expandable "🤔 Agent Reasoning (Extended Thinking)"
   - **Click**: Should show LLM's internal reasoning process

3. Say: "Add more about sponsor background"

4. Check reasoning again:
   - **Expected**: Shows why agent searched for "sponsor" information
   - **Expected**: Explains data sources used

**Success Criteria**:
- ✅ Reasoning expandable appears
- ✅ Reasoning content is meaningful (not empty)
- ✅ Shows agent's decision-making process

---

### Scenario 5: Sources Tracking

**Goal**: Verify transparent source tracking

**Steps**:
1. Complete a full workflow:
   - Upload teaser
   - Analyze deal
   - Discover requirements
   - Check compliance

2. Check sidebar "📚 Sources" section:
   - **Expected**: "RAG Searches: X" (should be > 0)
   - **Expected**: Click to expand shows search details

3. Click on any message's "📚 Sources Consulted":
   - **Expected**: Shows which sources were used for that response
   - **Expected**: Distinguishes RAG vs examples vs files

**Success Criteria**:
- ✅ Sidebar shows cumulative source counts
- ✅ Per-message sources are accurate
- ✅ RAG searches are tracked and visible

---

### Scenario 6: Example Search (When Available)

**Goal**: Test example credit pack search

**Prerequisites**: Add 2-3 example credit packs to `data/examples/`

**Steps**:
1. Say: "Show me similar deals"
   - **Expected**: Agent searches examples folder
   - **Expected**: Shows list of relevant examples with scores

2. Agent asks: "Would you like to use one as template?"
   - Say: "Yes, use the first one"
   - **Expected**: Example added to context
   - **Check**: Sidebar shows "Examples Used: 1"

**Success Criteria**:
- ✅ Example search works
- ✅ Agent asks permission before using
- ✅ Examples tracked in sidebar

---

## 🐛 Common Issues & Fixes

### Issue 1: V2 Not Loading

**Symptom**: No "📚 Sources" section in sidebar

**Fix**:
```bash
# Check if v2 file exists
ls core/conversational_orchestrator_v2.py

# If missing, it wasn't imported - check for errors
# Run with verbose output:
streamlit run ui/chat_app.py --logger.level=debug
```

### Issue 2: "I don't understand" Errors

**Symptom**: Agent still gives "I don't understand" responses

**Diagnosis**: V1 orchestrator is running (not V2)

**Fix**:
```python
# In chat_app.py, verify import:
print(type(st.session_state.orchestrator))
# Should show: ConversationalOrchestratorV2
```

### Issue 3: No Auto-File Analysis

**Symptom**: Files upload but no analysis message

**Diagnosis**: V1 orchestrator or _analyze_uploaded_files not running

**Fix**: Verify V2 is active (see Issue 1)

### Issue 4: Sources Always Show 0

**Symptom**: Sidebar shows "No sources used yet" even after analysis

**Diagnosis**: V1 orchestrator (v1 doesn't have persistent_context)

**Fix**: Ensure V2 is loaded properly

---

## ✅ Complete Test Checklist

### Basic Functionality
- [ ] App starts without errors
- [ ] Can upload files (teaser, example, other)
- [ ] Chat input works
- [ ] Messages display correctly

### V2-Specific Features
- [ ] "📚 Sources" section appears in sidebar
- [ ] "🤔 Agent Reasoning" expanders work
- [ ] "📚 Sources Consulted" expanders work
- [ ] Files auto-analyze on upload

### Conversation Flow
- [ ] Natural language prompts work (no keywords required)
- [ ] Agent remembers context (can answer follow-up questions)
- [ ] "Add more about X" works (enhance_analysis)
- [ ] Multiple file uploads are tracked

### Intent Detection
- [ ] "Can you look at this?" → analyze_deal ✅
- [ ] "Add more about X" → enhance_analysis ✅
- [ ] "Show examples" → search_examples ✅
- [ ] "What's the [field]?" → general_question ✅

### Sources Tracking
- [ ] RAG searches appear in sidebar
- [ ] Files analyzed count is accurate
- [ ] Per-message sources are correct
- [ ] Sources expandable shows details

### Agent Communication
- [ ] Writer can query ProcessAnalyst
- [ ] Writer can query ComplianceAdvisor
- [ ] Communication log tracks queries
- [ ] "💬 Agent Comms" sidebar shows count

---

## 📊 Expected Test Results

### Successful V2 Test Session

```
User: [Uploads teaser.pdf]
✅ Auto-analysis: "✓ Analyzing teaser.pdf (teaser)..."
✅ Sidebar: "Files Analyzed: 1"

User: "Can you look at this deal?"
✅ Intent detected: analyze_deal
✅ Analysis completes
✅ Sources show: "RAG Searches: 3"
✅ Expandable reasoning appears

User: "What's the loan amount?"
✅ Answers: "$50M acquisition + $10M renovation"
✅ No re-analysis (uses memory)

User: "Add more about market risks"
✅ Intent detected: enhance_analysis
✅ Enhances analysis
✅ Sources show: "RAG Searches: 5" (2 new searches)

User: [Uploads MarketReport.pdf]
✅ Auto-analysis: "✓ Analyzing MarketReport.pdf..."
✅ Agent suggests: "This market report adds..."
✅ Sidebar: "Files Analyzed: 2"

User: "Include it"
✅ Analysis updated
✅ Sources show file was used

TOTAL SOURCES USED:
- RAG Searches: 5
- Examples: 0
- Files Analyzed: 2
```

---

## 🔄 Regression Testing (V1 Compatibility)

If V2 fails to load, V1 should still work:

### V1 Fallback Test
1. Rename `conversational_orchestrator_v2.py` temporarily
2. Run `streamlit run ui/chat_app.py`
3. Verify:
   - ✅ App still works
   - ✅ Basic workflow functions
   - ⚠️ No "📚 Sources" section (expected)
   - ⚠️ Keywords required ("Analyze this deal" not "Can you look?")

---

## 📝 Bug Report Template

If you find issues, report with:

```markdown
**Issue**: [Brief description]

**Steps to Reproduce**:
1.
2.
3.

**Expected**: [What should happen]

**Actual**: [What actually happened]

**Environment**:
- Orchestrator version: [V1 or V2 - check sidebar]
- Files uploaded: [Yes/No, filenames]
- Message that failed: "[exact text]"

**Logs**: [Any error messages]
```

---

## 🎉 Success Indicators

You'll know the system is working correctly when:

1. ✅ **Natural Conversation**: You can chat naturally without specific keywords
2. ✅ **Context Memory**: Agent remembers previous messages
3. ✅ **Auto-Analysis**: Files analyze automatically on upload
4. ✅ **Transparency**: You see what sources were consulted
5. ✅ **Reasoning**: You can expand and read agent's thinking
6. ✅ **Sources Tracking**: Sidebar shows accurate source counts
7. ✅ **Flexibility**: "Add more about X" works seamlessly
8. ✅ **No Errors**: No "I don't understand" messages

---

## 🚀 Next: Production Readiness

Once testing passes, consider:

1. **Replace V1**: Rename v2 → v1, archive old v1
2. **Add Examples**: Put 3-5 example credit packs in `data/examples/`
3. **Extended Thinking**: Enable thinking_budget in production
4. **Performance**: Monitor RAG search counts (optimize if > 10 per analysis)
5. **User Feedback**: Collect feedback on conversation naturalness

---

## 📞 Support

If you encounter issues:

1. Check `errors.txt` in the repo
2. Review `PHASE2_MODERN_IMPLEMENTATION.md` for architecture details
3. Compare with `MODERN_AGENT_ARCHITECTURE.md` for expected behavior
4. Check `output_example.txt` for conversation examples

**Happy Testing!** 🎉
