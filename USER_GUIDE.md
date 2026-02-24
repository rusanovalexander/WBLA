# Credit Pack Drafting App — Quick Start Guide

## What This App Does

This app uses AI agents to draft credit pack documents. It follows a 4-phase workflow:

1. **Setup** — Upload your deal teaser and (optionally) an example credit pack
2. **Analysis** — AI analyzes the deal, determines process path, extracts key data
3. **Compliance** — AI checks the deal against Guidelines via RAG search
4. **Drafting** — AI drafts each section of the credit pack

## How to Use

### Step 1: Open the App

Open the link shared with you in your browser.

### Step 2: Setup Phase

You will see two upload areas:

- **Deal Teaser** (required) — Upload your deal teaser file (`.txt` format)
- **Example Credit Pack** (optional) — Upload an anonymized example credit pack (`.txt` format). This is used as a style and structure reference during drafting. If you skip this, the AI will draft based on Procedure/Guidelines only.

Click **"Load Documents & Start"** to proceed.

### Step 3: Analysis Phase

- The AI automatically searches the Procedure document and analyzes your deal
- Review the extracted data and process path
- Fill in or correct any requirements the AI could not extract
- Click **"Continue"** when satisfied

### Step 4: Compliance Phase

- Click **"Run Agentic Compliance Check"**
- The AI searches Guidelines and checks the deal against every applicable criterion
- Review the compliance matrix (PASS / REVIEW / FAIL for each criterion)
- If there are failures, you can acknowledge and override to continue
- Click **"Continue to Drafting"**

### Step 5: Drafting Phase

- Click **"Generate Section Structure"** to create the outline
- You can add, remove, or reorder sections before drafting
- Click **"Draft All Sections"** or draft individual sections
- Review and edit each section as needed
- Download the final credit pack when done

## Tips

- You can upload supplementary documents (term sheets, financial models) during the Analysis phase — they will be available to the compliance and drafting agents
- The sidebar shows agent activity, phase history, and configuration status
- If compliance extraction fails, click **"Retry Compliance Extraction"** before rerunning the entire phase
- Use the **"Reset All"** button in the sidebar to start over (requires confirmation)
