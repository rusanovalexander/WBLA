# Phase 2 Demo Guide: Conversational Interface + Agent Communication

## Overview

Phase 2 transforms the credit pack system into a conversational, Claude Code-style interface with autonomous agent-to-agent communication.

## What's New

### 1. Conversational Chat Interface (`ui/chat_app.py`)

**Before (Phase-based):**
```
┌─────────────────────────┐
│ Phase 1: Setup          │
│ [Upload Files]          │
│ [Next Phase] button     │
└─────────────────────────┘
```

**After (Conversational):**
```
┌──────────────┬──────────────────────────┐
│  📁 Files    │  Chat Interface          │
│  [+ Upload]  │  User: Analyze this deal │
│              │  🤖: [Thinking process]  │
│  📄 teaser   │      ✓ Reading teaser    │
│  📋 example  │      ⏳ Analyzing...      │
│              │      💬 Querying analyst │
│  🔍 Gov      │                          │
│  ✓ IFRS 9    │  [Next: ✅ Proceed]      │
│              │                          │
│  💬 Comms: 3 │  Type your message...    │
└──────────────┴──────────────────────────┘
```

### 2. Agent-to-Agent Communication

**How it works:**

1. **Writer drafts a section** and needs clarification
2. **Writer queries ProcessAnalyst** via AgentCommunicationBus:
   ```
   Writer → ProcessAnalyst: "What is the loan amount?"
   ProcessAnalyst → Writer: "The loan amount is €50M as stated in the teaser..."
   ```
3. **Communication logged** in sidebar and visible to user

**User can also query agents directly:**
```
User: Ask ProcessAnalyst about the borrower's credit rating
Assistant: ProcessAnalyst: "The borrower has a BBB+ rating according to..."
```

### 3. Visible Thinking Process

Every agent action shows live progress:

```
🤖 Assistant
  ✅ Complete
    ✓ Detected intent: analyze_deal
    📄 Using teaser: loan_teaser.pdf
    ⏳ Running ProcessAnalyst analysis...
    ⏳ Searching procedures (3 docs)...
    ✓ Analysis complete
    ✓ Found: Bilateral approach
    💬 Writer consulting ComplianceAdvisor...
```

### 4. Approval Checkpoints

After major actions, system asks for approval:

```
💡 Next: Discover requirements based on this analysis?
[✅ Proceed]
```

User clicks "Proceed" or types next instruction.

## Running the Demo

### Step 1: Start Chat Interface

```bash
cd "C:\Users\Aleksandr Rusanov\Downloads\refactored_FINAL_FIXED\ui"
streamlit run chat_app.py
```

### Step 2: Upload Files

1. Click sidebar file uploader
2. Upload:
   - **Teaser document** (PDF/DOCX with "teaser" in filename)
   - **Example pack** (optional, with "example" or "template" in filename)

Files appear in sidebar with icons:
```
📁 Files
  Uploaded:
    📄 loan_teaser.pdf
       127.3 KB
    📋 example_pack.docx
       89.5 KB
```

### Step 3: Natural Conversation

**Example 1: Full Workflow**

```
User: Analyze this deal