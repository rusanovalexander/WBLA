# Credit Pack Chat Interface

## Overview

Conversational UI for the multi-agent credit pack system, inspired by Claude Code.

## Features

### 🎯 Core Capabilities

1. **Natural Conversation Flow**
   - Chat-based interaction (no rigid phases)
   - Intent detection routes to appropriate agents
   - Context-aware suggestions

2. **File Upload**
   - Sidebar file upload ('+' button equivalent)
   - Supports PDF, DOCX, TXT
   - Auto-detects teaser vs example documents
   - Shows file size and type

3. **Visible Thinking Process**
   - Expandable status widgets
   - Color-coded progress indicators:
     - ✓ (green) - Success
     - ⏳ (blue) - In progress
     - ❌ (red) - Error
     - 💬 (blue) - Agent communication

4. **Agent-to-Agent Communication**
   - Writer queries ProcessAnalyst for clarification
   - Writer queries ComplianceAdvisor for guidelines
   - Communication log in sidebar
   - User can directly query agents

5. **Approval Checkpoints**
   - Human-in-the-loop after major actions
   - "Proceed" button to continue workflow
   - Suggested next steps displayed

6. **Governance Context**
   - Displays loaded frameworks in sidebar
   - Shows framework names (IFRS 9, Basel III, etc.)

## Usage

### Starting the Chat App

```bash
cd ui
streamlit run chat_app.py
```

### Example Conversation Flow

```
User: Analyze this deal
  ✓ Detected intent: analyze_deal
  📄 Using teaser: loan_teaser.pdf
  ⏳ Running ProcessAnalyst analysis...
  ✓ Analysis complete
  ✓ Found: Bilateral approach
  ✓ Method: Direct Origination