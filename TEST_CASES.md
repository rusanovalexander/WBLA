# Test Cases - Modern Conversational Agent System

## Overview
This document contains structured test cases to verify all features of the modern conversational agent system work correctly.

**Instructions**:
1. Run each test case in order
2. Document results in `TEST_RESULTS.md`
3. Mark each test as ✅ PASS, ❌ FAIL, or ⚠️ PARTIAL
4. Include screenshots or error messages for failures

---

## Test Environment Setup

### Prerequisites
- [ ] Python environment activated
- [ ] All dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file configured with GCP credentials
- [ ] At least 1 teaser document available
- [ ] (Optional) 2-3 example credit packs in `data/examples/`

### Startup Check
```bash
streamlit run ui/chat_app.py
```

**Expected**: App starts without errors, shows chat interface

---

## TEST SUITE 1: System Initialization

### TC-1.1: App Loads Successfully
**Steps**:
1. Start the app: `streamlit run ui/chat_app.py`
2. Wait for UI to load

**Expected Results**:
- ✅ App loads without errors
- ✅ Title shows: "🤖 Credit Pack Assistant"
- ✅ Sidebar visible with sections: Files, Governance, Sources, Agent Comms
- ✅ Chat input box visible at bottom
- ✅ No error messages in console

**Record in TEST_RESULTS.md**:
- Status: [PASS/FAIL/PARTIAL]
- Actual behavior: [describe]
- Screenshots: [if any issues]

---

### TC-1.2: V2 Orchestrator Active
**Steps**:
1. Check sidebar for "📚 Sources" section
2. Look for text: "No sources used yet"

**Expected Results**:
- ✅ "📚 Sources" section exists in sidebar
- ✅ Shows "No sources used yet" initially
- ✅ This confirms V2 orchestrator is loaded

**If NOT visible**:
- ⚠️ V2 not loaded, fallback to V1 active
- Check console for import errors

**Record in TEST_RESULTS.md**:
- Orchestrator version: [V2/V1]
- Sources section visible: [YES/NO]

---

### TC-1.3: Governance Discovery
**Steps**:
1. Check sidebar "🔍 Governance" section
2. Look for framework items

**Expected Results**:
- ✅ At least 1 framework shown with checkmark
- ✅ Example: "✓ Credit Granting Framework" or similar

**Record in TEST_RESULTS.md**:
- Frameworks loaded: [number]
- Framework names: [list]

---

## TEST SUITE 2: Natural Language Intent Detection

### TC-2.1: Informal Analysis Request
**Steps**:
1. Upload a teaser file (any format: PDF, DOCX, TXT)
2. Type in chat: `"Can you look at this deal?"`
3. Press Enter

**Expected Results**:
- ✅ Agent understands intent (analyze_deal)
- ✅ Analysis starts automatically
- ✅ Thinking process visible: "⏳ Running ProcessAnalyst analysis..."
- ✅ NO "I don't understand" message
- ✅ Full analysis completes

**Record in TEST_RESULTS.md**:
- Intent detected: [what agent understood]
- Analysis completed: [YES/NO]
- Error messages: [if any]

---

### TC-2.2: Follow-up Question
**Steps**:
1. After TC-2.1 completes
2. Type: `"What's the loan amount?"`
3. Press Enter

**Expected Results**:
- ✅ Agent answers based on previous analysis
- ✅ NO re-analysis triggered
- ✅ Answer is accurate (mentions amount from teaser)
- ✅ Response time < 5 seconds

**Record in TEST_RESULTS.md**:
- Question answered: [YES/NO]
- Answer accuracy: [correct/incorrect/partial]
- Re-analysis triggered: [YES/NO - should be NO]

---

### TC-2.3: Enhancement Request
**Steps**:
1. After TC-2.1 completes
2. Type: `"Add more about market risks"`
3. Press Enter

**Expected Results**:
- ✅ Intent detected: enhance_analysis
- ✅ Agent searches RAG for "market risk" information
- ✅ Analysis updated with market risk section
- ✅ NO error messages
- ✅ Sidebar "RAG Searches" count increases

**Record in TEST_RESULTS.md**:
- Enhancement completed: [YES/NO]
- RAG search performed: [YES/NO]
- New content added: [describe briefly]

---

### TC-2.4: Example Search Request
**Steps**:
1. Type: `"Show me similar deals"`
2. Press Enter

**Expected Results**:
- ✅ Intent detected: search_examples
- ✅ If examples exist: Shows list with scores
- ✅ If no examples: "No example credit packs found" message
- ✅ Agent asks permission to use examples (not automatic)

**Record in TEST_RESULTS.md**:
- Intent recognized: [YES/NO]
- Examples found: [number, or "none"]
- Permission request shown: [YES/NO]

---

## TEST SUITE 3: File Upload & Auto-Analysis

### TC-3.1: Initial File Upload
**Steps**:
1. Click file uploader in sidebar
2. Upload a teaser PDF
3. Observe behavior

**Expected Results**:
- ✅ File appears in "Uploaded" section with icon 📄
- ✅ File size shown (e.g., "125.3 KB")
- ✅ Auto-analysis message appears in chat OR thinking steps
- ✅ Sidebar "📚 Sources" shows "Files Analyzed: 1"
- ✅ Message like: "✓ Analyzing teaser.pdf (teaser)..."

**Record in TEST_RESULTS.md**:
- File uploaded: [YES/NO]
- Auto-analysis triggered: [YES/NO]
- Insights shown: [YES/NO - describe]
- Sources count updated: [YES/NO]

---

### TC-3.2: Mid-Conversation File Upload
**Steps**:
1. Complete TC-2.1 (analysis of first file)
2. Upload ANOTHER file (e.g., market report, financial statements)
3. Observe behavior

**Expected Results**:
- ✅ New file auto-analyzed immediately
- ✅ Agent message: "I've analyzed [filename]. Key insights..."
- ✅ Agent OFFERS to integrate: "Should I update the analysis?"
- ✅ Sidebar shows "Files Analyzed: 2"
- ✅ NO automatic integration (asks first)

**Record in TEST_RESULTS.md**:
- Second file analyzed: [YES/NO]
- Integration offer made: [YES/NO]
- User choice respected: [YES/NO]
- Files analyzed count: [number]

---

### TC-3.3: File Type Detection
**Steps**:
1. Upload different file types in sequence:
   - File with "teaser" in name → should detect as teaser
   - File with "financial" in name → should detect as financial_statement
   - File with "market" in name → should detect as market_report

**Expected Results**:
- ✅ Each file type correctly identified
- ✅ Different insights for each type
- ✅ Teaser: "Commercial RE acquisition..."
- ✅ Financial: "DSCR, LTV, ratios..."
- ✅ Market: "Vacancy rates, market conditions..."

**Record in TEST_RESULTS.md**:
- Teaser detection: [PASS/FAIL]
- Financial detection: [PASS/FAIL]
- Market report detection: [PASS/FAIL]
- Insights relevant: [YES/NO]

---

## TEST SUITE 4: Sources Tracking & Transparency

### TC-4.1: RAG Search Tracking
**Steps**:
1. Complete TC-2.1 (deal analysis)
2. Check sidebar "📚 Sources" section
3. Look for "RAG Searches" metric

**Expected Results**:
- ✅ "RAG Searches: X" where X > 0
- ✅ Can expand to see search details
- ✅ Shows search type (procedure/guidelines)
- ✅ Shows query text and result count
- ✅ Example: "🔍 procedure: 'commercial real estate' (5 results)"

**Record in TEST_RESULTS.md**:
- RAG searches tracked: [YES/NO]
- Search count: [number]
- Details expandable: [YES/NO]
- Details accurate: [YES/NO]

---

### TC-4.2: Per-Message Sources
**Steps**:
1. Complete TC-2.1 (deal analysis)
2. Find the analysis response message
3. Look for "📚 Sources Consulted" expandable

**Expected Results**:
- ✅ Expandable "📚 Sources Consulted" visible
- ✅ Shows: "🔍 RAG Database: X searches"
- ✅ Shows: "📄 Uploaded Files: Y analyzed"
- ✅ Numbers match what was actually used

**Record in TEST_RESULTS.md**:
- Per-message sources shown: [YES/NO]
- Sources accurate: [YES/NO]
- Expandable works: [YES/NO]

---

### TC-4.3: Cumulative Source Tracking
**Steps**:
1. Perform multiple actions:
   - Analyze deal (uses RAG)
   - Add more about risks (uses RAG)
   - Upload second file (analyzed)
2. Check sidebar sources throughout

**Expected Results**:
- ✅ RAG count increases with each action
- ✅ Files analyzed count increases with uploads
- ✅ Cumulative totals accurate
- ✅ Can trace each search in expanded view

**Record in TEST_RESULTS.md**:
- Cumulative tracking works: [YES/NO]
- Final RAG count: [number]
- Final files count: [number]
- Matches actual actions: [YES/NO]

---

## TEST SUITE 5: Extended Thinking & Reasoning

### TC-5.1: Reasoning Display
**Steps**:
1. Complete any analysis action
2. Look for "🤔 Agent Reasoning (Extended Thinking)" expandable

**Expected Results**:
- ✅ Expandable exists (even if reasoning is minimal/None for now)
- ✅ If reasoning present: Shows LLM's thought process
- ✅ If reasoning None: Expandable exists but shows nothing
- ✅ Caption mentions "Gemini 2.5 extended thinking"

**Record in TEST_RESULTS.md**:
- Reasoning expandable exists: [YES/NO]
- Reasoning content present: [YES/NO - if NO, this is expected for now]
- UI element works: [YES/NO]

**Note**: Extended thinking may not show content yet if thinking_budget not fully implemented. This is expected - we're testing the UI component.

---

### TC-5.2: Thinking Process Steps
**Steps**:
1. Complete TC-2.1 (deal analysis)
2. Look at the "Processing..." status during execution
3. Observe color-coded steps

**Expected Results**:
- ✅ Steps shown during processing
- ✅ Color coding:
  - ✓ (success) = green
  - ⏳ (in progress) = blue
  - ❌ (error) = red
  - 💬 (agent comm) = blue
- ✅ Steps make sense chronologically

**Record in TEST_RESULTS.md**:
- Thinking steps visible: [YES/NO]
- Color coding works: [YES/NO]
- Steps logical: [YES/NO]

---

## TEST SUITE 6: Agent Communication

### TC-6.1: Writer Queries ProcessAnalyst
**Steps**:
1. Complete full workflow up to drafting:
   - Analyze deal
   - Discover requirements
   - Generate structure
   - Draft a section
2. Look for agent communication indicators

**Expected Results**:
- ✅ During drafting: "💬 Writer → ProcessAnalyst" messages
- ✅ Sidebar "💬 Agent Comms" shows query count > 0
- ✅ Can view communication log
- ✅ Log shows: who queried whom, what was asked, response

**Record in TEST_RESULTS.md**:
- Agent communication occurred: [YES/NO]
- Communication visible: [YES/NO]
- Log accessible: [YES/NO]
- Log content clear: [YES/NO]

---

### TC-6.2: Agent Communication Log
**Steps**:
1. After TC-6.1
2. Click "View Log" button in sidebar "💬 Agent Comms"

**Expected Results**:
- ✅ Log displays as chat message
- ✅ Shows all agent-to-agent queries
- ✅ Format: "Writer → ProcessAnalyst: 'What is X?'"
- ✅ Includes responses
- ✅ Can clear log with "Clear Log" button

**Record in TEST_RESULTS.md**:
- Log displayed: [YES/NO]
- Content complete: [YES/NO]
- Clear function works: [YES/NO]

---

## TEST SUITE 7: Conversation Memory

### TC-7.1: Context Retention
**Steps**:
1. Upload teaser, analyze deal
2. Ask: "What's the sponsor name?"
3. Ask: "What sector is this?"
4. Ask: "Summarize the key risks"

**Expected Results**:
- ✅ All questions answered without re-analysis
- ✅ Answers reference previous analysis
- ✅ No "I need to analyze first" messages
- ✅ Response time < 5 seconds per question

**Record in TEST_RESULTS.md**:
- Question 1 answered: [YES/NO]
- Question 2 answered: [YES/NO]
- Question 3 answered: [YES/NO]
- Memory works: [YES/NO]

---

### TC-7.2: Multi-Turn Enhancement
**Steps**:
1. Analyze deal
2. Say: "Add more about market risks"
3. Say: "Now add sponsor background"
4. Say: "Also include exit strategy"

**Expected Results**:
- ✅ Each enhancement builds on previous
- ✅ No loss of previous enhancements
- ✅ Final analysis includes ALL additions
- ✅ Agent remembers what was already added

**Record in TEST_RESULTS.md**:
- Enhancement 1 worked: [YES/NO]
- Enhancement 2 worked: [YES/NO]
- Enhancement 3 worked: [YES/NO]
- All retained: [YES/NO]

---

### TC-7.3: File Context Memory
**Steps**:
1. Upload teaser.pdf (analyzed)
2. Ask: "What files have I uploaded?"
3. Upload second file
4. Ask again: "What files do I have now?"

**Expected Results**:
- ✅ First question: Lists teaser.pdf
- ✅ Second question: Lists both files
- ✅ Agent remembers file names and types
- ✅ Can reference file contents in answers

**Record in TEST_RESULTS.md**:
- File memory works: [YES/NO]
- Lists accurate: [YES/NO]
- Can reference content: [YES/NO]

---

## TEST SUITE 8: Complete Workflow

### TC-8.1: End-to-End Credit Pack Draft
**Steps**:
1. Upload teaser
2. Say: "Help me draft a credit pack"
3. Follow agent prompts, approve each step:
   - Analysis
   - Requirements discovery
   - Compliance check
   - Structure generation
   - Section drafting

**Expected Results**:
- ✅ Workflow completes without errors
- ✅ Each step produces valid output
- ✅ Approval checkpoints work
- ✅ Agent suggests next steps
- ✅ Sources tracked throughout
- ✅ Agent communication visible during drafting

**Record in TEST_RESULTS.md**:
- Workflow completed: [YES/NO]
- Steps completed: [number/total]
- Errors encountered: [list any]
- Time to complete: [minutes]

---

### TC-8.2: Workflow with Enhancements
**Steps**:
1. Start workflow (TC-8.1)
2. After analysis, say: "Add more about financial structure"
3. Continue workflow
4. After drafting starts, upload financial statements
5. Say: "Include the financial data"

**Expected Results**:
- ✅ Enhancement integrated before requirements
- ✅ File upload handled mid-workflow
- ✅ Agent incorporates new data
- ✅ Workflow continues smoothly
- ✅ Final output includes all additions

**Record in TEST_RESULTS.md**:
- Enhancement worked: [YES/NO]
- Mid-workflow upload handled: [YES/NO]
- Data integrated: [YES/NO]
- Workflow smooth: [YES/NO]

---

## TEST SUITE 9: Error Handling

### TC-9.1: No File Uploaded
**Steps**:
1. WITHOUT uploading file, say: "Analyze this deal"

**Expected Results**:
- ✅ Error message: "❌ Please upload a teaser document first"
- ✅ Suggestion: "Upload a teaser PDF or DOCX file to begin"
- ✅ No crash or exception
- ✅ Can proceed after uploading file

**Record in TEST_RESULTS.md**:
- Error handled gracefully: [YES/NO]
- Message clear: [YES/NO]
- Recovery possible: [YES/NO]

---

### TC-9.2: Invalid Intent
**Steps**:
1. Say something completely unrelated: "What's the weather?"

**Expected Results**:
- ✅ Fallback to general handler
- ✅ Helpful response about what system can do
- ✅ Shows current status
- ✅ Suggests valid next steps
- ✅ No crash

**Record in TEST_RESULTS.md**:
- Handled gracefully: [YES/NO]
- Response helpful: [YES/NO]
- Suggestions relevant: [YES/NO]

---

### TC-9.3: Large File Upload
**Steps**:
1. Upload a very large file (>10MB if available)

**Expected Results**:
- ✅ Upload succeeds or shows size warning
- ✅ Analysis completes or shows timeout message
- ✅ No crash
- ✅ System remains responsive

**Record in TEST_RESULTS.md**:
- Large file handled: [YES/NO]
- Warnings shown: [YES/NO if applicable]
- System stable: [YES/NO]

---

## TEST SUITE 10: UI/UX

### TC-10.1: Approval Checkpoints
**Steps**:
1. Complete analysis
2. Look for "💡 Next: ..." suggestion
3. Find "✅ Proceed" button

**Expected Results**:
- ✅ Suggestion is clear and actionable
- ✅ Button is visible and clickable
- ✅ Clicking button proceeds to next step
- ✅ User can also type alternative instruction

**Record in TEST_RESULTS.md**:
- Checkpoints visible: [YES/NO]
- Buttons work: [YES/NO]
- Alternative input works: [YES/NO]

---

### TC-10.2: Mobile/Responsive
**Steps**:
1. Resize browser window to mobile width (400px)
2. Test basic interactions

**Expected Results**:
- ✅ Layout adjusts to narrow screen
- ✅ Sidebar collapsible
- ✅ Chat messages readable
- ✅ Input box accessible
- ✅ Buttons clickable

**Record in TEST_RESULTS.md**:
- Responsive: [YES/NO]
- Usable on mobile: [YES/NO]
- Issues: [list any]

---

### TC-10.3: File Management
**Steps**:
1. Upload 3 files
2. Click delete (🗑️) on middle file
3. Verify file removed

**Expected Results**:
- ✅ Delete button works
- ✅ File removed from list
- ✅ Other files remain
- ✅ No errors
- ✅ Can continue working

**Record in TEST_RESULTS.md**:
- Delete works: [YES/NO]
- UI updates correctly: [YES/NO]
- No side effects: [YES/NO]

---

## TEST SUITE 11: Performance

### TC-11.1: Response Time
**Steps**:
1. Time each operation:
   - File upload → analysis start: [X seconds]
   - Analysis completion: [Y seconds]
   - Follow-up question: [Z seconds]
   - Enhancement request: [W seconds]

**Expected Results**:
- ✅ File analysis start: < 3 seconds
- ✅ Analysis completion: 15-60 seconds (depends on file size)
- ✅ Follow-up question: < 5 seconds
- ✅ Enhancement: 10-30 seconds

**Record in TEST_RESULTS.md**:
- File analysis start: [X seconds]
- Analysis completion: [Y seconds]
- Follow-up question: [Z seconds]
- Enhancement: [W seconds]

---

### TC-11.2: Concurrent Operations
**Steps**:
1. Upload file while previous analysis running (if possible)
2. Type message while analysis running

**Expected Results**:
- ✅ UI remains responsive
- ✅ Operations queue properly
- ✅ No race conditions
- ✅ Results appear in correct order

**Record in TEST_RESULTS.md**:
- Concurrent handling: [GOOD/POOR]
- UI responsive: [YES/NO]
- Order preserved: [YES/NO]

---

## TEST SUITE 12: Example Search (Optional)

### TC-12.1: Example Search Functionality
**Prerequisites**: Add 2-3 example credit pack files to `data/examples/`

**Steps**:
1. Say: "Show me similar deals"
2. Observe results

**Expected Results**:
- ✅ Examples found and listed
- ✅ Relevance scores shown
- ✅ Sector detected correctly
- ✅ Content preview available
- ✅ Agent asks permission to use

**Record in TEST_RESULTS.md**:
- Examples found: [number]
- Scoring works: [YES/NO]
- Permission requested: [YES/NO]

**If no examples**: Skip this test or add examples first

---

## Summary Template

After completing all tests, provide summary in TEST_RESULTS.md:

```
## Overall Summary

Total Tests: [number]
Passed: [number]
Failed: [number]
Partial: [number]

Pass Rate: [percentage]%

### Critical Issues
[List any critical failures that prevent usage]

### Minor Issues
[List any minor issues or improvements needed]

### Recommendations
[Any suggestions based on testing]
```

---

## Test Completion

When done:
1. Complete `TEST_RESULTS.md` with all results
2. Include screenshots for any failures
3. Note any unexpected behaviors
4. Provide overall assessment

**Thank you for testing!** 🎉
