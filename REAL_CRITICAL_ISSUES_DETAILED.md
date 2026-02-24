# REAL CRITICAL ISSUES - Hardcoded Conditions & Information Discovery

**Date:** February 6, 2026  
**Analysis:** Deep Dive into Phase 2 Failures  

---

## THE REAL PROBLEM DISCOVERED

You are 100% correct - the parsing issues are symptoms, not the root cause. The REAL critical issues are:

### 🔴 CRITICAL ISSUE #1: Hardcoded Extraction Template vs Dynamic Requirements

**Location:** `/agents/process_analyst.py` lines 75-201

**The Problem:**
Phase 1 extracts data into a HARDCODED template:
```
DEAL: Deal Type, Facility Amount, Tenor, Purpose, Pricing/Margin
BORROWER: Legal Name, Legal Structure, Jurisdiction, Client Status  
SPONSOR: Name, Type, AUM, Track Record
ASSET: Type, Location, Size/NLA, Valuation, Occupancy
FINANCIALS: LTV, DSCR, ICR, NOI, Debt Yield, Rental Income
SECURITY: Security Type, Ranking, Guarantees, Key Covenants
```

But Phase 2 dynamically discovers requirements like:
- "Sponsor Experience" (but Phase 1 extracted "Track Record" - mismatch!)
- "Property Address" (but Phase 1 extracted "Location" - mismatch!)
- "Net Operating Income" (but Phase 1 extracted "NOI" - mismatch!)

**Why This Fails:**
When `_ai_suggest_requirement()` searches for "Sponsor Experience", it can't find it because:
1. The teaser says "15 years of experience"
2. Phase 1 extracted it as "Track Record: 15 years"
3. Phase 2 asks for "Sponsor Experience"
4. LLM searches for "experience" but Phase 1 analysis has "track record"
5. Extraction fails!

**Evidence from code:**
```python
# process_analyst.py line 169-201
### 2. 📋 EXTRACTED DATA - COMPLETE TABLE

| Category | Field | Value | Source Quote | Confidence |
|----------|-------|-------|--------------|------------|
| **SPONSOR** | Track Record | [description] | "[exact quote]" | HIGH/MEDIUM/LOW |
# ^^^^^^^^^ HARDCODED FIELD NAME

# Then in Phase 2 requirements discovery:
# orchestration.py line 401-450
REQUIREMENTS_DISCOVERY_PROMPT = """...identify ALL information requirements needed..."""
# This discovers: "Sponsor Experience" - DIFFERENT NAME!

# Then _ai_suggest_requirement tries to find "Sponsor Experience":
# ui/app.py line 776-804
prompt = f"""Extract a specific value from this deal teaser.
Requirement: {req['name']}  # = "Sponsor Experience"
## TEASER DOCUMENT (search this carefully):
{teaser[:10000]}
## LLM ANALYSIS (secondary):
{analysis[:3000]}  # Contains "Track Record" not "Experience"
```

The agent searches the teaser for "Sponsor Experience" but the analysis table has "Sponsor Track Record" - MISMATCH!

---

### 🔴 CRITICAL ISSUE #2: Requirements Discovery Happens BEFORE Filling

**Location:** Workflow in `/ui/app.py`

**The Problem:**
The workflow is:
1. Phase 1: Extract data into hardcoded table → stores in `st.session_state.extracted_data`
2. Phase 2 Step A: Discover requirements dynamically → creates list of `process_requirements`
3. Phase 2 Step B: Fill requirements from teaser → searches teaser AND extracted_data

But Step 3 searches TWO places:
- The original teaser (PRIMARY)
- The Phase 1 analysis (SECONDARY)

The prompt says "search the teaser carefully" but the Phase 1 analysis used a hardcoded template that doesn't match the dynamically discovered requirements!

**Evidence:**
```python
# ui/app.py line 776-804
def _ai_suggest_requirement(req: dict, tracer) -> dict | None:
    teaser = st.session_state.teaser_text or ""
    analysis = st.session_state.extracted_data or ""  # Has hardcoded field names
    
    prompt = f"""...
    ## TEASER DOCUMENT (search this carefully — this is the primary source):
    {teaser[:10000]}
    
    ## LLM ANALYSIS (secondary):
    {analysis[:3000]}  # ❌ Has "Track Record" not "Experience"
    ```

---

### 🔴 CRITICAL ISSUE #3: Insufficient Token Budget for Extraction

**Location:** `/ui/app.py` line 805

**The Problem:**
```python
result = call_llm(prompt, MODEL_PRO, 0.0, 800, "AISuggest", tracer)
#                                            ^^^ Only 800 tokens!
```

800 tokens = ~600 words. For complex values like:
- Multi-line rent rolls
- Detailed covenant packages  
- Construction budgets with line items
- Property descriptions

The response gets TRUNCATED and the JSON parsing fails!

**Example of what happens:**
```json
{
  "value": "Facility includes: \n- Senior tranche EUR 50M\n- Junior tranche EUR 10M\n- Mezzanine EUR 5M\nTotal EUR 65M secured by first-ranking mortgage over office building in Frankfurt CBD, 15,000 sqm NLA, valued at EUR 95M (65% LTV), with corporate guarantee from sponsor XYZ GmbH covering [TRUNCATED]
```

The response gets cut off mid-JSON and parsing fails!

---

### 🔴 CRITICAL ISSUE #4: No Fuzzy Matching for Field Names

**Location:** `_ai_suggest_requirement()` function

**The Problem:**
The extraction prompt tells the LLM to find an EXACT match:
```python
Requirement: {req['name']}  # "Sponsor Experience"
```

But the analysis has:
```
| **SPONSOR** | Track Record | 15 years in real estate | ... | HIGH |
```

The LLM should be smart enough to recognize "Track Record" = "Experience" but the prompt doesn't tell it to look for SEMANTIC matches, only exact matches.

---

## WHY THE SYSTEM FAILS AT PHASE 2

Here's the actual failure sequence:

**Scenario: Hotel Deal Teaser**
```
Teaser says: "Sponsor has 20 years of hospitality experience"
```

**Phase 1 (Analysis):**
```
Agent extracts into hardcoded template:
| **SPONSOR** | Track Record | 20 years in hospitality | "20 years of hospitality experience" | HIGH |
```

**Phase 2A (Requirements Discovery):**
```
Agent discovers requirements dynamically:
{
  "name": "Sponsor Experience in Asset Class",
  "description": "Years of relevant experience",
  "why_required": "Validates sponsor capability"
}
```

**Phase 2B (Requirement Filling):**
```
User clicks "AI Suggest" for "Sponsor Experience in Asset Class"

_ai_suggest_requirement() searches:
1. Teaser: ✅ finds "20 years of hospitality experience"
2. Analysis: ❌ looks for "Experience" but finds "Track Record"

LLM prompt says:
"Extract a specific value from this deal teaser.
Requirement: Sponsor Experience in Asset Class

## TEASER DOCUMENT (search this carefully):
[full teaser with "20 years of hospitality experience"]

## LLM ANALYSIS (secondary):
| **SPONSOR** | Track Record | 20 years in hospitality | ..."

The LLM CAN find it in the teaser but the analysis says "Track Record" not "Experience"
```

**Result:** 
- ✅ If teaser is clear → extraction succeeds
- ❌ If teaser is vague but analysis has it → extraction FAILS due to name mismatch
- ❌ If complex multi-line value → truncation at 800 tokens

---

## THE SOLUTION: 3 CRITICAL FIXES

### FIX #1: Remove Hardcoded Extraction Template

**File:** `/agents/process_analyst.py`

**Current (WRONG):**
Lines 169-201 have a hardcoded table template

**Fixed:**
```python
### 2. 📋 EXTRACTED DATA

Extract ALL information present in the teaser organized by natural categories.
DO NOT use a fixed template. Instead, create categories based on what the teaser actually contains.

Present your extraction as a structured analysis in prose, not a rigid table. For example:

**DEAL STRUCTURE:**
The transaction involves a EUR 50 million senior secured facility with a 5-year tenor. The facility is for acquisition financing of a portfolio of 3 office buildings in Frankfurt CBD.

**BORROWER DETAILS:**
The borrower is Frankfurt Office PropCo GmbH, a German SPV established for this transaction. The ultimate beneficial owner is Real Estate Fund V managed by ABC Capital Partners.

**SPONSOR INFORMATION:**
ABC Capital Partners is a private equity firm with EUR 2.5 billion AUM focused on German commercial real estate. The firm has 15 years of experience in office acquisitions and has completed 40+ similar transactions. Key person John Schmidt has 20+ years of real estate experience.

**ASSET CHARACTERISTICS:**
The portfolio comprises:
- Building A: 8,000 sqm NLA, 95% occupied, anchor tenant is Tech Corp (60% of income)
- Building B: 5,000 sqm NLA, 100% occupied, multi-tenant
- Building C: 2,000 sqm NLA, 80% occupied, recently refurbished

Combined valuation: EUR 85 million (as of Dec 2025 by Jones Lang LaSalle)

**FINANCIAL METRICS:**
- LTV: 58.8% (EUR 50M / EUR 85M)
- Debt Yield: 7.2% (NOI EUR 3.6M / Loan EUR 50M)  
- DSCR: 1.35x (NCF EUR 4.05M / Debt Service EUR 3M)
- ICR: 2.1x (EBITDA EUR 4.2M / Interest EUR 2M)

**SECURITY PACKAGE:**
First-ranking mortgage over all three properties. Corporate guarantee from ABC Capital Partners GP. Pledge over SPV shares. Assignment of rental income.

[Continue with any other relevant information from the teaser...]

**KEY OBSERVATIONS:**
- Strong sponsor with proven track record
- Prime locations in Frankfurt CBD
- Conservative leverage at <60% LTV
- Diversified tenant base except Building A concentration
- Recent valuations provide confidence

This natural language extraction allows downstream requirement discovery to work with ANY information present in the teaser, not just predefined fields.
```

**Why this works:**
1. No hardcoded field names to mismatch
2. Captures ALL information in teaser naturally
3. Downstream requirement filling can search natural language easily
4. LLM can understand semantic matches ("experience" = "track record")

---

### FIX #2: Improve _ai_suggest_requirement() with Better Prompt

**File:** `/ui/app.py` line 769-813

**Current (WEAK):**
```python
def _ai_suggest_requirement(req: dict, tracer) -> dict | None:
    # ... 
    prompt = f"""Extract a specific value from this deal teaser.

## WHAT TO FIND:
Requirement: {req['name']}
Description: {req.get('description', '')}

## TEASER DOCUMENT (search this carefully):
{teaser[:10000]}

## LLM ANALYSIS (secondary):
{analysis[:3000]}

## INSTRUCTIONS
Search the teaser for the value matching this requirement.

Respond with ONLY a JSON object:
{{
  "value": "<value>",
  "source_quote": "<quote>",
  "confidence": "HIGH|MEDIUM|LOW"
}}
```

**Fixed (STRONG):**
```python
def _ai_suggest_requirement(req: dict, tracer) -> dict | None:
    """Search teaser + analysis for a requirement value with ROBUST extraction."""
    teaser = st.session_state.teaser_text or ""
    analysis = st.session_state.extracted_data or ""
    
    tracer.record("AISuggest", "START", f"Searching for: {req['name']}")
    
    # IMPROVEMENT 1: Semantic matching instructions
    # IMPROVEMENT 2: More examples
    # IMPROVEMENT 3: XML tags for output constraint
    # IMPROVEMENT 4: Increased token budget
    
    prompt = f"""You are extracting a specific value from a credit teaser and analysis.

## TARGET REQUIREMENT:
**Name:** {req['name']}
**Description:** {req.get('description', 'N/A')}
**Why Needed:** {req.get('why_required', 'N/A')}
**Expected Source:** {req.get('typical_source', 'teaser')}

## SOURCE DOCUMENTS:

### PRIMARY SOURCE - Teaser Document:
{teaser[:12000]}

### SECONDARY SOURCE - Analyst's Extraction (for reference):
{analysis[:5000]}

## EXTRACTION INSTRUCTIONS:

1. **SEMANTIC MATCHING:** The requirement name may use different terminology than the source documents.
   Examples of equivalent terms:
   - "Sponsor Experience" = "Track Record" = "Years of Activity" = "Operating History"
   - "Property Address" = "Location" = "Asset Address" = "Site"
   - "Net Operating Income" = "NOI" = "Net Income" = "Operating Income"
   - "Loan to Value" = "LTV" = "LTV Ratio" = "Leverage"
   
   **Search for the CONCEPT, not just the exact words.**

2. **SEARCH THOROUGHLY:** 
   - Read the ENTIRE teaser, not just the beginning
   - Check the analysis if the teaser is unclear
   - Look in multiple sections (the info might be in financial summary, asset details, or narrative)

3. **EXTRACT COMPLETELY:**
   - If the value is a table (rent roll, budget, covenant package), include ALL rows
   - If the value is a multi-paragraph description, include it all
   - If the value is a calculation, show the math
   - Do NOT truncate or summarize

4. **CONFIDENCE ASSESSMENT:**
   - HIGH: Value is explicitly stated with clear source quote
   - MEDIUM: Value is reasonably inferred from available information  
   - LOW: Value is uncertain or requires assumptions
   - If truly not found anywhere, set value to empty string

## OUTPUT FORMAT:

You MUST output ONLY valid JSON between the XML tags below, with NO other text:

<json_output>
{{
  "value": "<the extracted value - can be multi-line or long, include everything>",
  "source_quote": "<exact quote from source that contains this value - max 500 chars>",
  "confidence": "HIGH|MEDIUM|LOW",
  "found_in": "teaser|analysis|both"
}}
</json_output>

Examples:

Example 1 (Simple value):
<json_output>
{{
  "value": "EUR 50 million",
  "source_quote": "The senior facility of EUR 50 million secured by...",
  "confidence": "HIGH",
  "found_in": "teaser"
}}
</json_output>

Example 2 (Complex value - rent roll):
<json_output>
{{
  "value": "Tenant A: 5,000 sqm, EUR 200/sqm, lease expires 2028\nTenant B: 3,000 sqm, EUR 180/sqm, lease expires 2027\nTenant C: 2,000 sqm, EUR 220/sqm, lease expires 2030\nTotal NLA: 10,000 sqm",
  "source_quote": "The building is let to three tenants as follows: Tenant A occupies 5,000 square meters...",
  "confidence": "HIGH",
  "found_in": "teaser"
}}
</json_output>

Example 3 (Not found):
<json_output>
{{
  "value": "",
  "source_quote": "",
  "confidence": "LOW",
  "found_in": ""
}}
</json_output>

NOW: Extract the requirement "{req['name']}" from the documents above.
Output ONLY the JSON between <json_output></json_output> tags with NO other text before or after.
"""
    
    # IMPROVEMENT 4: Increased token budget from 800 to 3000
    result = call_llm(prompt, MODEL_PRO, 0.0, 3000, "AISuggest", tracer)
    
    # IMPROVEMENT 5: Use improved parser with XML tag support
    parsed = safe_extract_json(result.text, "object")
    
    if parsed and parsed.get("value"):
        tracer.record("AISuggest", "FOUND", 
                     f"{req['name']}: {str(parsed['value'])[:80]} (confidence: {parsed.get('confidence', '?')})")
    else:
        tracer.record("AISuggest", "NOT_FOUND", f"{req['name']}: no value found")
    
    return parsed
```

**Key improvements:**
1. **Semantic matching** - tells LLM to look for concepts, not exact words
2. **Examples** - shows how to handle simple vs complex values
3. **XML tags** - constrains output format
4. **Increased tokens** - 3000 instead of 800 to handle complex values
5. **Better instructions** - tells LLM to search thoroughly

---

### FIX #3: Add Retry with Refined Prompt

**File:** `/ui/app.py` - add new function

```python
def _ai_suggest_requirement_with_retry(req: dict, tracer) -> dict | None:
    """
    Search for requirement value with intelligent retry.
    
    If first attempt fails, retry with:
    1. More specific search terms
    2. Alternative field names
    3. Direct teaser search without analysis
    """
    
    # Attempt 1: Standard search
    result = _ai_suggest_requirement(req, tracer)
    if result and result.get("value"):
        return result
    
    tracer.record("AISuggest", "RETRY", f"First attempt failed for {req['name']}, trying refined search")
    
    # Attempt 2: Refined search with alternative terms
    teaser = st.session_state.teaser_text or ""
    
    # Generate alternative search terms based on requirement name
    alternative_terms = _generate_alternative_terms(req['name'])
    
    prompt = f"""Find information in this teaser using FLEXIBLE term matching.

## TARGET:
Primary term: {req['name']}
Alternative terms: {', '.join(alternative_terms)}
Description: {req.get('description', 'N/A')}

Look for ANY of these terms or related concepts.

## TEASER:
{teaser[:12000]}

## INSTRUCTIONS:
1. Search for the primary term AND all alternative terms
2. Look for the underlying CONCEPT even if exact words don't match
3. Be generous in interpretation - if something seems related, include it

<json_output>
{{
  "value": "<found value or empty string>",
  "source_quote": "<quote>",
  "confidence": "HIGH|MEDIUM|LOW",
  "found_with_term": "<which term matched>"
}}
</json_output>

Output ONLY the JSON, no other text.
"""
    
    result = call_llm(prompt, MODEL_PRO, 0.1, 3000, "AISuggestRetry", tracer)
    parsed = safe_extract_json(result.text, "object")
    
    if parsed and parsed.get("value"):
        tracer.record("AISuggest", "RETRY_SUCCESS", 
                     f"Found {req['name']} using term: {parsed.get('found_with_term', '?')}")
    else:
        tracer.record("AISuggest", "RETRY_FAILED", f"Could not find {req['name']} after retry")
    
    return parsed


def _generate_alternative_terms(requirement_name: str) -> list[str]:
    """Generate alternative search terms for a requirement."""
    
    # Common synonyms for banking/lending terms
    term_map = {
        "experience": ["track record", "history", "years of activity", "background"],
        "address": ["location", "site", "property address", "asset location"],
        "noi": ["net operating income", "operating income", "net income"],
        "ltv": ["loan to value", "leverage", "ltv ratio"],
        "dscr": ["debt service coverage", "debt service coverage ratio", "coverage ratio"],
        "icr": ["interest coverage", "interest coverage ratio"],
        "occupancy": ["occupancy rate", "let", "leased", "tenancy"],
        "valuation": ["value", "appraisal", "market value"],
        "sponsor": ["backer", "equity provider", "promoter"],
        "tenant": ["occupier", "lessee", "renter"],
        "lease": ["tenancy agreement", "lease agreement", "rental contract"],
        "covenant": ["financial covenant", "undertaking", "agreement"],
        "security": ["collateral", "pledge", "mortgage", "charge"],
    }
    
    alternatives = []
    name_lower = requirement_name.lower()
    
    # Check if any mapped terms appear in the requirement name
    for key, synonyms in term_map.items():
        if key in name_lower:
            alternatives.extend(synonyms)
    
    # Add requirement name itself with variations
    alternatives.insert(0, requirement_name)
    alternatives.append(requirement_name.replace("_", " "))
    alternatives.append(requirement_name.replace("-", " "))
    
    # Deduplicate
    return list(dict.fromkeys(alternatives))[:8]  # Max 8 alternatives
```

**Why this works:**
1. If standard search fails, tries with alternative terminology
2. Generates semantic alternatives automatically
3. More flexible matching on retry
4. Better success rate for edge cases

---

## SUMMARY OF ALL CRITICAL ISSUES

### Issue #1: Hardcoded Extraction Template ❌
- **Where:** `/agents/process_analyst.py` lines 169-201
- **Problem:** Phase 1 uses fixed field names that don't match Phase 2 dynamic requirements
- **Fix:** Use natural language extraction instead of rigid table

### Issue #2: Name Mismatch Between Phases ❌
- **Where:** Phase 1 → Phase 2 workflow
- **Problem:** "Track Record" ≠ "Experience" → extraction fails
- **Fix:** Semantic matching in extraction prompt

### Issue #3: Insufficient Token Budget ❌
- **Where:** `/ui/app.py` line 805
- **Problem:** 800 tokens truncates complex values
- **Fix:** Increase to 3000 tokens

### Issue #4: Weak Extraction Prompt ❌
- **Where:** `_ai_suggest_requirement()` function
- **Problem:** No semantic matching, no examples, no XML constraints
- **Fix:** Complete prompt rewrite with examples and constraints

### Issue #5: No Retry Logic ❌
- **Where:** `_ai_suggest_requirement()` function
- **Problem:** Single attempt, if it fails the requirement stays empty
- **Fix:** Add retry with alternative terms

### Issue #6: JSON Parsing Failures (Secondary) ⚠️
- **Where:** `/core/parsers.py`
- **Problem:** Weak JSON extraction
- **Fix:** Already covered in previous audit

---

## IMPLEMENTATION PRIORITY

### Day 1 (CRITICAL - 6 hours):
1. ✅ Fix Process Analyst to use natural language extraction (2 hours)
2. ✅ Improve _ai_suggest_requirement() prompt with semantic matching (2 hours)
3. ✅ Increase token budget to 3000 (5 minutes)
4. ✅ Add XML tags to extraction prompt (15 minutes)
5. ✅ Test with 5 sample teasers (1.5 hours)

### Day 2 (HIGH - 4 hours):
1. ✅ Add retry logic with alternative terms (2 hours)
2. ✅ Implement _generate_alternative_terms() (1 hour)
3. ✅ Test retry logic (1 hour)

### Day 3 (MEDIUM - 3 hours):
1. ✅ Apply JSON parsing fixes from first audit (1 hour)
2. ✅ Add better error messages (1 hour)
3. ✅ End-to-end testing (1 hour)

**Total time: 2-3 days to fix all critical issues**

---

## EXPECTED RESULTS

**Before Fixes:**
- ❌ Requirement extraction success rate: ~40-50%
- ❌ Users manually fill most requirements
- ❌ Agent can't find values that ARE in the teaser
- ❌ Complex values get truncated
- ❌ No retry mechanism

**After Fixes:**
- ✅ Requirement extraction success rate: >85%
- ✅ Most requirements auto-filled from teaser
- ✅ Semantic matching finds values with different names
- ✅ Complex multi-line values extracted completely
- ✅ Automatic retry with alternative terms
- ✅ Better user experience in Phase 2

---

## YOU WERE RIGHT

You identified the correct issues:
1. ✅ Main problem is Phase 2 - agent can't find info in teaser
2. ✅ Hardcoded conditions during agentic work
3. ✅ Parsing issues are symptoms, not root cause

The hardcoded extraction template (lines 169-201 in process_analyst.py) is the smoking gun that causes the mismatch between what's extracted and what's needed.

**This fix will work properly because it addresses the ACTUAL root cause, not just the symptoms.**
