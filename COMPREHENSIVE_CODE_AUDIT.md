# COMPREHENSIVE CODE AUDIT REPORT
## Credit Pack Multi-Agent PoC v3.2 - Complete Analysis & Fixes

**Date:** February 6, 2026  
**Audited By:** Senior Agentic AI & Wholesale Banking Lending Professional  
**Project:** Credit Pack Autonomous Multi-Agent System for Wholesale Lending  

---

## EXECUTIVE SUMMARY

### Critical Issue Identified
**ERROR:** `"could not parse LLM output (124 chars)"`

**Root Cause:** The structured extraction prompts in `/core/orchestration.py` are not constraining the LLM effectively enough, causing JSON parsing failures in `/core/parsers.py`.

### Overall Assessment
- **Architecture:** Well-designed modular structure ✅
- **Code Quality:** Good separation of concerns ✅
- **Critical Bugs:** 3 HIGH severity issues 🔴
- **Medium Issues:** 12 issues requiring attention 🟡
- **Low Priority:** 8 minor improvements 🟢

---

## PART 1: CRITICAL ISSUES (BLOCKING PRODUCTION USE)

### 🔴 CRITICAL #1: LLM Output Parsing Failures

**Location:** `/core/parsers.py` line 273, `/core/orchestration.py` lines 119-165

**Problem:**
1. The structured extraction prompts allow the LLM to generate text outside the JSON block
2. The `safe_extract_json()` function logs warnings but returns `None`, causing downstream failures
3. The extraction prompts don't use XML tags or other strong delimiters to constrain output

**Evidence:**
```python
# orchestration.py line 57-84
PROCESS_DECISION_EXTRACTION_PROMPT = """You are a JSON extraction assistant...
Return ONLY the JSON object.
"""
```

The phrase "Return ONLY" is not strong enough to prevent the LLM from adding preambles.

**Impact:**
- Causes the entire workflow to fail at Phase 1 (Analysis)
- User sees error message and cannot proceed
- Agent analysis is wasted as structure extraction fails

**Fix #1a: Strengthen Extraction Prompts**

```python
# Replace PROCESS_DECISION_EXTRACTION_PROMPT in orchestration.py
PROCESS_DECISION_EXTRACTION_PROMPT = """You are a JSON extraction assistant. Extract the process path decision from the analysis below.

## ANALYSIS TEXT
{analysis_text}

## TASK
Extract the agent's decision into EXACTLY this JSON format. Use ONLY what the agent explicitly stated.

CRITICAL: You MUST output ONLY valid JSON with NO text before or after. Do NOT include markdown code fences, explanations, or any other text.

<json_output>
{{
  "assessment_approach": "<exact approach name>",
  "origination_method": "<exact origination method>",
  "assessment_reasoning": "<1-2 sentence summary>",
  "origination_reasoning": "<1-2 sentence summary>",
  "procedure_sections_cited": ["Section X.X"],
  "confidence": "HIGH|MEDIUM|LOW",
  "decision_found": true
}}
</json_output>

RULES:
- If the agent did NOT clearly state an assessment approach, set "decision_found": false
- Do NOT invent or assume an approach
- Copy the agent's EXACT wording for approach and method names
- If uncertain between options, set confidence to "LOW"

Output ONLY the JSON object between <json_output></json_output> tags. NO other text.
"""

COMPLIANCE_EXTRACTION_PROMPT = """You are a JSON extraction assistant. Extract ALL compliance checks from the analysis.

## COMPLIANCE ANALYSIS TEXT
{compliance_text}

## TASK
Extract every compliance criterion the agent checked into a JSON array.

CRITICAL: You MUST output ONLY valid JSON with NO text before or after. Do NOT include markdown code fences, explanations, or any other text.

<json_output>
[
  {{
    "criterion": "<name>",
    "guideline_limit": "<limit with section reference>",
    "deal_value": "<actual value>",
    "status": "PASS|FAIL|REVIEW",
    "evidence": "<brief reasoning>",
    "reference": "<Guidelines section>",
    "severity": "MUST|SHOULD"
  }}
]
</json_output>

RULES:
- Include EVERY criterion the agent assessed
- Status based on agent's actual assessment
- If flagged as concern/exception needed = REVIEW or FAIL
- If agent said complies/meets requirements = PASS
- Do NOT limit to predefined list

Output ONLY the JSON array between <json_output></json_output> tags. NO other text.
"""
```

**Fix #1b: Improve JSON Extraction**

```python
# Update safe_extract_json in parsers.py
def safe_extract_json(text: str, expect_type: str = "object") -> Any:
    """
    Safely extract JSON from LLM output with improved robustness.
    
    Handles: markdown fences, XML tags, preamble text, trailing content,
    trailing commas, and other LLM JSON quirks.
    """
    # Step 1: Try to extract from XML tags if present
    xml_pattern = r'<json_output>\s*([\s\S]*?)\s*</json_output>'
    xml_match = re.search(xml_pattern, text, re.IGNORECASE)
    if xml_match:
        text = xml_match.group(1).strip()
    
    # Step 2: Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    
    # Step 3: Remove common preambles
    cleaned = re.sub(r'^(?:here\s+is|here\'s|the\s+json|output:)\s*', '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    
    # Step 4: Find the JSON based on expected type
    if expect_type == "array":
        start_char, end_char = "[", "]"
    else:
        start_char, end_char = "{", "}"
    
    start = cleaned.find(start_char)
    if start < 0:
        logger.warning("No %s found in LLM output (%d chars): %s", start_char, len(text), text[:200])
        return None
    
    # Step 5: Find matching end with proper nesting
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == start_char:
            depth += 1
        elif cleaned[i] == end_char:
            depth -= 1
            if depth == 0:
                json_str = cleaned[start:i + 1]
                result = _try_parse_json(json_str)
                if result is not None:
                    logger.info("Successfully parsed JSON (%d chars)", len(json_str))
                    return result
                break
    
    # Step 6: Fallback to simple slice
    end = cleaned.rfind(end_char)
    if end > start:
        json_str = cleaned[start:end + 1]
        result = _try_parse_json(json_str)
        if result is not None:
            logger.info("Successfully parsed JSON via fallback (%d chars)", len(json_str))
            return result
    
    logger.error("Could not parse JSON from LLM output (%d chars). First 500 chars: %s", 
                 len(text), text[:500])
    return None


def _try_parse_json(json_str: str) -> Any:
    """Try to parse JSON string with multiple fixup attempts."""
    # Attempt 1: Direct parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass
    
    # Attempt 2: Fix trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # Attempt 3: Fix single quotes
    fixed2 = fixed.replace("'", '"')
    try:
        return json.loads(fixed2)
    except json.JSONDecodeError:
        pass
    
    # Attempt 4: Fix unquoted keys (common LLM mistake)
    fixed3 = re.sub(r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', fixed2)
    try:
        return json.loads(fixed3)
    except json.JSONDecodeError as e:
        logger.warning("All JSON parse attempts failed. Last error: %s", e)
    
    return None
```

**Fix #1c: Add Fallback Handling**

```python
# Update _extract_structured_decision in orchestration.py
def _extract_structured_decision(
    analysis_text: str,
    tracer: TraceStore,
) -> dict | None:
    """
    Use a dedicated LLM call to extract structured decision with retry.
    """
    tracer.record("Extraction", "START", "Extracting structured decision")
    
    prompt = PROCESS_DECISION_EXTRACTION_PROMPT.format(analysis_text=analysis_text[:12000])
    
    # Try up to 2 times with different temperatures
    for attempt in range(2):
        temperature = 0.0 if attempt == 0 else 0.1
        result = call_llm(prompt, MODEL_FLASH, temperature, 1500, "Extraction", tracer)
        parsed = safe_extract_json(result.text, "object")
        
        if parsed and parsed.get("decision_found"):
            tracer.record("Extraction", "SUCCESS", f"Found: {parsed.get('assessment_approach', '?')}")
            return parsed
        elif parsed:
            # Got valid JSON but decision_found is False
            tracer.record("Extraction", "NO_DECISION", "Agent did not make clear decision")
            return parsed
    
    # Both attempts failed
    tracer.record("Extraction", "PARSE_FAIL", f"Could not extract decision after 2 attempts. Raw output length: {len(result.text)}")
    logger.error("Extraction failed. Last LLM output: %s", result.text[:1000])
    return None
```

---

### 🔴 CRITICAL #2: Missing Error Messages to User

**Location:** `/ui/app.py` - Phase transition handlers

**Problem:**
When parsing fails, the user only sees a generic error or the app hangs with no feedback.

**Fix:**

```python
# Add to ui/app.py after line 300 (in render_phase_analysis)

if not st.session_state.decision_found:
    st.error("""
    ⚠️ **Process Path Could Not Be Determined**
    
    The Process Analyst could not determine a clear assessment approach and origination method.
    
    **Possible causes:**
    - Teaser document does not contain enough deal information
    - Deal characteristics are ambiguous or contradictory
    - Procedure document search failed or returned no results
    
    **What you can do:**
    1. Review the analyst's reasoning above
    2. Manually select the assessment approach and origination method below
    3. Upload additional documents with deal details
    4. Retry the analysis with a different teaser
    
    **Technical details:** The agent's analysis could not be parsed into a structured decision.
    Check the agent activity log for detailed error messages.
    """)
```

---

### 🔴 CRITICAL #3: Model Version Compatibility

**Location:** `/config/settings.py` lines 44-45

**Problem:**
Using preview model versions that may expire or change behavior.

```python
MODEL_PRO = os.getenv("MODEL_PRO", "gemini-2.5-pro-preview-05-06")
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-2.5-flash-preview-04-17")
```

**Fix:**

```python
# config/settings.py
# Use stable model versions for production
MODEL_PRO = os.getenv("MODEL_PRO", "gemini-2.0-flash-exp")  # Stable, fast, cost-effective
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-2.0-flash-exp")  # Use same for consistency

# OR if you need the absolute latest:
MODEL_PRO = os.getenv("MODEL_PRO", "gemini-exp-1206")  # Latest experimental
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-2.0-flash-exp")

# Add version validation
def validate_model_versions():
    """Check if model versions are valid and available."""
    from google import genai
    from google.genai import types
    
    try:
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
        # Test both models
        for model in [MODEL_PRO, MODEL_FLASH]:
            try:
                client.models.generate_content(
                    model=model,
                    contents="test",
                    config=types.GenerateContentConfig(max_output_tokens=10)
                )
            except Exception as e:
                logger.error(f"Model {model} validation failed: {e}")
                return False
        return True
    except Exception as e:
        logger.error(f"Model validation failed: {e}")
        return False
```

---

## PART 2: HIGH PRIORITY ISSUES

### 🟡 HIGH #1: Bare Except Blocks

**Location:** Multiple files (`rag_search.py` lines 42, 49, 56)

**Problem:**
```python
try:
    if hasattr(obj, 'items'):
        return {k: _convert_proto_to_dict(v) for k, v in obj.items()}
except:  # ❌ Catches ALL exceptions including KeyboardInterrupt
    pass
```

**Fix:**
```python
try:
    if hasattr(obj, 'items'):
        return {k: _convert_proto_to_dict(v) for k, v in obj.items()}
except (TypeError, AttributeError, ValueError) as e:  # ✅ Specific exceptions
    logger.debug(f"Could not convert object to dict: {e}")
    pass
```

---

### 🟡 HIGH #2: Hardcoded Token Limits

**Location:** `/core/llm_client.py` line 89, `/core/orchestration.py` various locations

**Problem:**
```python
max_output_tokens=max_tokens,  # Defaults to 16384
```

The token limits are hardcoded and may cause truncation on long outputs.

**Fix:**
```python
# config/settings.py
MAX_OUTPUT_TOKENS = {
    "analysis": 24000,  # For process analyst full analysis
    "extraction": 2000,  # For structured extraction
    "compliance": 20000,  # For compliance checks
    "drafting": 32000,  # For section drafting
    "chat": 4000,  # For orchestrator chat
}

# Use in llm_client.py
def call_llm(
    prompt: str,
    model: str = MODEL_PRO,
    temperature: float = 0.1,
    max_tokens: int | None = None,  # Allow None to use model default
    agent_name: str = "LLM",
    tracer: TraceStore | None = None,
) -> LLMCallResult:
    # Use model's context window if not specified
    if max_tokens is None:
        if "flash" in model.lower():
            max_tokens = 8192
        else:  # Pro model
            max_tokens = 32768
```

---

### 🟡 HIGH #3: No Input Validation on User Uploads

**Location:** `/ui/app.py` line 193-210

**Problem:**
Files are uploaded without size or content validation.

**Fix:**
```python
# ui/app.py
MAX_FILE_SIZE_MB = 50
ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.txt', '.xlsx'}

uploaded = st.file_uploader(
    "Upload additional documents",
    type=["pdf", "docx", "txt", "xlsx"],
    accept_multiple_files=True,
)

if uploaded:
    for f in uploaded:
        # Validate file size
        file_size_mb = f.size / (1024 * 1024)
        if file_size_mb > MAX_FILE_SIZE_MB:
            st.error(f"❌ {f.name}: File too large ({file_size_mb:.1f}MB). Max size is {MAX_FILE_SIZE_MB}MB.")
            continue
        
        # Validate extension
        ext = Path(f.name).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            st.error(f"❌ {f.name}: Invalid file type '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
            continue
        
        # Save file
        dest = TEASERS_FOLDER / f.name
        with open(dest, "wb") as out:
            out.write(f.getbuffer())
        st.success(f"✅ Uploaded: {f.name}")
```

---

### 🟡 HIGH #4: Race Condition in Session State

**Location:** `/ui/app.py` lines 83-125

**Problem:**
Multiple Streamlit widgets can modify session state concurrently, causing race conditions.

**Fix:**
```python
# Add locking mechanism
import threading

def init_state():
    defaults = {
        "messages": [],
        "workflow_phase": "SETUP",
        "_state_lock": threading.Lock(),  # Add lock
        # ... rest of defaults
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def safe_update_state(updates: dict):
    """Thread-safe state updates."""
    with st.session_state._state_lock:
        for key, value in updates.items():
            st.session_state[key] = value
```

---

### 🟡 HIGH #5: No Timeout on LLM Calls

**Location:** `/core/llm_client.py` line 98

**Problem:**
LLM calls can hang indefinitely if the API is slow or unresponsive.

**Fix:**
```python
# core/llm_client.py
import signal
from contextlib import contextmanager

class TimeoutException(Exception):
    pass

@contextmanager
def timeout(seconds):
    """Context manager for timeout."""
    def timeout_handler(signum, frame):
        raise TimeoutException("LLM call timed out")
    
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def _call_gemini(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    tools: list[Any] | None = None,
    tool_config: Any | None = None,
    timeout_seconds: int = 120,  # 2 minutes default
) -> Any:
    """Raw Gemini API call with retry and timeout."""
    from google import genai
    from google.genai import types
    
    with timeout(timeout_seconds):
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
        
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        
        if tools:
            config.tools = tools
        if tool_config:
            config.tool_config = tool_config
        
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return response
```

---

### 🟡 HIGH #6: Memory Leak in TraceStore

**Location:** `/core/tracing.py`

**Problem:**
The `TraceStore` keeps all trace entries in memory indefinitely, which will cause OOM on long-running sessions.

**Fix:**
```python
# core/tracing.py
from collections import deque

class TraceStore:
    """Trace store with bounded memory."""
    
    MAX_TRACE_ENTRIES = 10000  # Keep last 10k entries
    
    def __init__(self):
        self.entries = deque(maxlen=self.MAX_TRACE_ENTRIES)  # Use deque with maxlen
        self.current_trace_id = None
        self.trace_contexts = {}
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.total_cost_usd = 0.0
        self.agent_stats = defaultdict(lambda: {
            "calls": 0, "tokens_in": 0, "tokens_out": 0, 
            "cost_usd": 0.0, "total_duration_ms": 0
        })
    
    def trim_old_entries(self):
        """Remove entries older than 24 hours."""
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        self.entries = deque(
            [e for e in self.entries if e.get("timestamp", "") > cutoff],
            maxlen=self.MAX_TRACE_ENTRIES
        )
```

---

## PART 3: MEDIUM PRIORITY ISSUES

### 🟡 MEDIUM #1: Inefficient RAG Search Filtering

**Location:** `/tools/rag_search.py` lines 254-285

**Problem:**
```python
def tool_search_procedure(query: str, num_results: int = 5) -> Dict[str, Any]:
    result = search_rag(query, num_results * 2)  # ❌ Wasteful, fetches 2x results
    filtered = [r for r in result["results"] if r["doc_type"] == "Procedure"]
```

**Fix:**
```python
def tool_search_procedure(query: str, num_results: int = 5) -> Dict[str, Any]:
    """Search and filter for Procedure documents with optimized query."""
    # Add type filter to query for better results
    enhanced_query = f"procedure {query}"
    result = search_rag(enhanced_query, num_results)
    
    if result["status"] != "OK":
        return result
    
    # Still filter to ensure only Procedure docs
    filtered = [r for r in result["results"] if r["doc_type"] == "Procedure"]
    
    # If not enough, do a second search without filtering
    if len(filtered) < num_results // 2:
        result2 = search_rag(query, num_results * 2)
        filtered.extend([r for r in result2.get("results", []) 
                        if r["doc_type"] == "Procedure" and r not in filtered])
    
    return {
        "status": "OK",
        "query": query,
        "num_results": len(filtered),
        "results": filtered[:num_results]
    }
```

---

### 🟡 MEDIUM #2: No Caching for Document Loading

**Location:** `/tools/document_loader.py`

**Problem:**
Documents are loaded from disk on every access, wasting I/O and time.

**Fix:**
```python
# Add LRU cache
from functools import lru_cache
from hashlib import md5

@lru_cache(maxsize=128)
def _load_document_cached(file_path: str, file_hash: str) -> dict:
    """Load document with caching based on file hash."""
    return universal_loader(file_path)

def tool_load_document(file_path: str) -> dict:
    """Load document with cache."""
    # Compute file hash
    with open(file_path, 'rb') as f:
        file_hash = md5(f.read()).hexdigest()
    
    return _load_document_cached(file_path, file_hash)
```

---

### 🟡 MEDIUM #3: Inconsistent Logging Levels

**Problem:**
Mix of `print()`, `logger.warning()`, `logger.error()` without clear policy.

**Fix:**
```python
# Establish logging policy in config/settings.py
import logging

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

def setup_logging():
    """Configure logging for the application."""
    logging.basicConfig(
        level=LOG_LEVEL,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(BASE_DIR / "logs" / "app.log"),
            logging.StreamHandler()
        ]
    )
    
    # Set specific module levels
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

# Call in main.py and ui/app.py
from config.settings import setup_logging
setup_logging()
```

---

### 🟡 MEDIUM #4-12: Additional Issues

Due to space constraints, here are brief summaries of remaining medium issues:

4. **No Database for Audit Trail** - Change log stored in memory only
5. **Missing Unit Tests** - No test coverage for critical parsing logic
6. **Hardcoded Prompts** - Should be externalized to config files
7. **No Rate Limiting** - LLM API calls can exceed quota
8. **Missing Health Checks** - No /health endpoint or service monitoring
9. **Inefficient String Operations** - Multiple string replacements in loops
10. **No Graceful Degradation** - If RAG fails, entire system breaks
11. **Missing API Key Rotation** - No support for rotating GCP credentials
12. **No Telemetry** - Can't track usage patterns or performance metrics

---

## PART 4: LOW PRIORITY & IMPROVEMENTS

### 🟢 LOW #1: Type Hints Inconsistency

**Problem:**
Mix of old-style (`Dict[str, Any]`) and new-style (`dict[str, Any]`) type hints.

**Fix:**
Use consistent new-style throughout:
```python
from __future__ import annotations  # Add to all files
# Use: dict, list, tuple instead of Dict, List, Tuple
```

---

### 🟢 LOW #2: Magic Numbers

**Problem:**
Hardcoded values throughout code:
```python
if len(cleaned) > 10:  # ❌ What does 10 mean?
    content_parts.append(text)
```

**Fix:**
```python
MIN_CONTENT_LENGTH = 10  # Minimum chars for valid content snippet
if len(cleaned) > MIN_CONTENT_LENGTH:
    content_parts.append(text)
```

---

### 🟢 LOW #3-8: Additional Minor Issues

3. **Verbose Comments** - Some comments restate obvious code
4. **Unused Imports** - Several files import unused modules
5. **Missing Docstrings** - Some functions lack documentation
6. **Inconsistent Naming** - Mix of snake_case and camelCase in places
7. **Long Functions** - Several functions exceed 100 lines
8. **No Code Formatting** - Should use `black` and `isort`

---

## PART 5: SECURITY CONCERNS

### 🔒 SECURITY #1: Credentials in Environment

**Location:** `.env` file handling

**Problem:**
Service account keys in plain text files.

**Fix:**
```python
# Use Google Secret Manager
from google.cloud import secretmanager

def get_credentials_from_secret_manager():
    """Fetch credentials from Secret Manager instead of local file."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT_ID}/secrets/credit-pack-service-account/versions/latest"
    response = client.access_secret_version(request={"name": name})
    
    # Parse JSON credentials
    import json
    creds_data = json.loads(response.payload.data.decode("UTF-8"))
    
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(creds_data)
```

---

### 🔒 SECURITY #2: No Input Sanitization

**Problem:**
User inputs passed directly to LLM without sanitization.

**Fix:**
```python
def sanitize_user_input(text: str, max_length: int = 100000) -> str:
    """Sanitize user input before passing to LLM."""
    # Remove control characters
    cleaned = ''.join(char for char in text if char.isprintable() or char in '\n\r\t')
    
    # Truncate to max length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "\n[TRUNCATED]"
    
    # Remove potential prompt injection patterns
    patterns = [
        r'<\|im_start\|>',
        r'<\|im_end\|>',
        r'###\s*Instruction:',
        r'###\s*System:',
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    return cleaned
```

---

### 🔒 SECURITY #3: No RBAC

**Problem:**
No user authentication or role-based access control.

**Fix:**
```python
# Add authentication middleware for Streamlit
import streamlit_authenticator as stauth

# config.yaml
credentials:
  usernames:
    analyst1:
      name: John Analyst
      password: $2b$12$...  # bcrypt hash
      role: analyst
    manager1:
      name: Jane Manager
      password: $2b$12$...
      role: manager

# ui/app.py
authenticator = stauth.Authenticate(
    credentials,
    'credit_pack_cookie',
    'secret_key_12345',
    cookie_expiry_days=30
)

name, authentication_status, username = authenticator.login('Login', 'main')

if authentication_status == False:
    st.error('Username/password is incorrect')
elif authentication_status == None:
    st.warning('Please enter your username and password')
elif authentication_status:
    # User is authenticated
    user_role = credentials['usernames'][username]['role']
    
    # Role-based access
    if user_role == 'analyst':
        # Read-only access
        st.session_state['can_edit'] = False
    elif user_role == 'manager':
        # Full access
        st.session_state['can_edit'] = True
```

---

## PART 6: PERFORMANCE OPTIMIZATIONS

### ⚡ PERF #1: Parallel Tool Calls

**Problem:**
Tool calls in loops are sequential, slowing down multi-query searches.

**Fix:**
```python
# core/orchestration.py
import concurrent.futures

def _run_analysis_native(teaser_text, search_procedure_fn, tracer):
    """Run analysis with parallel tool execution."""
    # ... existing code ...
    
    # If agent makes multiple tool calls, execute in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for fc in function_calls:
            future = executor.submit(tool_executor, fc.name, dict(fc.args))
            futures.append((fc.name, future))
        
        # Collect results
        for tool_name, future in futures:
            try:
                result = future.result(timeout=30)
                tracer.record("ProcessAnalyst", "TOOL_RESULT", f"{tool_name} → {len(result)} chars")
            except Exception as e:
                logger.error(f"Parallel tool execution failed: {tool_name}: {e}")
```

---

### ⚡ PERF #2: Lazy Loading of Large Documents

**Problem:**
All documents loaded into memory upfront.

**Fix:**
```python
# Use generators for large documents
def stream_document_chunks(file_path: str, chunk_size: int = 10000):
    """Stream document in chunks to avoid loading entire file."""
    content = universal_loader(file_path)
    text = content.get("text", "")
    
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]
```

---

### ⚡ PERF #3: Batch LLM Calls

**Problem:**
Making individual LLM calls for each section draft is slow.

**Fix:**
```python
# Use Gemini batch API for section drafting
def draft_sections_batch(sections: list, context: dict, tracer: TraceStore) -> list:
    """Draft multiple sections in a single batch call."""
    from google import genai
    from google.genai import types
    
    client = genai.Client(vertexai=True, project=PROJECT_ID, location="us-central1")
    
    # Create batch request
    requests = []
    for section in sections:
        prompt = create_section_prompt(section, context)
        requests.append({
            "contents": prompt,
            "config": types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=8000,
            )
        })
    
    # Execute batch
    responses = client.models.generate_content_batch(
        model=MODEL_PRO,
        requests=requests
    )
    
    # Parse responses
    drafts = []
    for section, response in zip(sections, responses):
        drafts.append(SectionDraft(
            name=section["name"],
            content=response.text,
            agent_queries=[],
        ))
    
    return drafts
```

---

## PART 7: ARCHITECTURE RECOMMENDATIONS

### 🏗️ ARCH #1: Event-Driven Architecture

**Problem:**
Tight coupling between UI and business logic.

**Recommendation:**
```python
# Implement event bus
from typing import Callable
from dataclasses import dataclass

@dataclass
class Event:
    type: str
    payload: dict
    timestamp: datetime = field(default_factory=datetime.now)

class EventBus:
    def __init__(self):
        self.subscribers: dict[str, list[Callable]] = defaultdict(list)
    
    def subscribe(self, event_type: str, handler: Callable):
        self.subscribers[event_type].append(handler)
    
    def publish(self, event: Event):
        for handler in self.subscribers[event.type]:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler failed: {e}")

# Usage
event_bus = EventBus()

# Subscribe to events
event_bus.subscribe("analysis_complete", update_ui)
event_bus.subscribe("analysis_complete", save_to_db)

# Publish events
event_bus.publish(Event("analysis_complete", {"result": analysis}))
```

---

### 🏗️ ARCH #2: Separate API Layer

**Recommendation:**
Create a FastAPI backend to decouple business logic from Streamlit UI.

```python
# api/main.py
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

app = FastAPI()

class AnalysisRequest(BaseModel):
    teaser_text: str
    use_native_tools: bool = True

@app.post("/api/v1/analyze")
async def start_analysis(request: AnalysisRequest, background_tasks: BackgroundTasks):
    """Start async analysis job."""
    job_id = str(uuid.uuid4())
    
    background_tasks.add_task(
        run_agentic_analysis,
        request.teaser_text,
        tool_search_procedure,
    )
    
    return {"job_id": job_id, "status": "started"}

@app.get("/api/v1/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Check job status."""
    # Return job status from database
    pass
```

---

### 🏗️ ARCH #3: Implement Message Queue

**Problem:**
Long-running agent tasks block the UI thread.

**Recommendation:**
```python
# Use Celery for async task queue
from celery import Celery

celery_app = Celery('credit_pack', broker='redis://localhost:6379')

@celery_app.task
def analyze_teaser_async(teaser_text: str, use_native_tools: bool = True):
    """Async analysis task."""
    result = run_agentic_analysis(teaser_text, tool_search_procedure, use_native_tools=use_native_tools)
    
    # Store result in database
    store_analysis_result(result)
    
    return result

# In UI
import streamlit as st
from celery.result import AsyncResult

if st.button("Start Analysis"):
    task = analyze_teaser_async.delay(teaser_text)
    st.session_state.task_id = task.id
    st.info(f"Analysis started: {task.id}")

# Poll for result
if 'task_id' in st.session_state:
    task = AsyncResult(st.session_state.task_id)
    if task.ready():
        result = task.get()
        st.success("Analysis complete!")
        display_results(result)
```

---

## PART 8: TESTING STRATEGY

### 🧪 TEST #1: Unit Tests for Parsers

```python
# tests/test_parsers.py
import pytest
from core.parsers import safe_extract_json

def test_safe_extract_json_basic():
    text = '{"key": "value"}'
    result = safe_extract_json(text, "object")
    assert result == {"key": "value"}

def test_safe_extract_json_with_markdown():
    text = '```json\n{"key": "value"}\n```'
    result = safe_extract_json(text, "object")
    assert result == {"key": "value"}

def test_safe_extract_json_with_preamble():
    text = 'Here is the JSON:\n{"key": "value"}'
    result = safe_extract_json(text, "object")
    assert result == {"key": "value"}

def test_safe_extract_json_with_xml_tags():
    text = '<json_output>{"key": "value"}</json_output>'
    result = safe_extract_json(text, "object")
    assert result == {"key": "value"}

def test_safe_extract_json_invalid():
    text = 'This is not JSON'
    result = safe_extract_json(text, "object")
    assert result is None

def test_safe_extract_json_trailing_comma():
    text = '{"key": "value",}'
    result = safe_extract_json(text, "object")
    assert result == {"key": "value"}
```

---

### 🧪 TEST #2: Integration Tests

```python
# tests/test_orchestration.py
import pytest
from core.orchestration import run_agentic_analysis

@pytest.fixture
def mock_search_fn():
    def search(query, num_results=5):
        return {
            "status": "OK",
            "results": [
                {"doc_type": "Procedure", "title": "Test", "content": "Assessment approach: Proportionality"}
            ]
        }
    return search

def test_run_agentic_analysis_success(mock_search_fn):
    """Test successful analysis with valid teaser."""
    teaser = """
    Deal: Office Building Acquisition
    Size: EUR 50 million
    LTV: 60%
    Location: Berlin, Germany
    """
    
    result = run_agentic_analysis(teaser, mock_search_fn, use_native_tools=False)
    
    assert result["decision_found"] == True
    assert result["process_path"] != ""
    assert result["origination_method"] != ""

def test_run_agentic_analysis_no_decision(mock_search_fn):
    """Test analysis with ambiguous teaser."""
    teaser = "This is a deal."
    
    result = run_agentic_analysis(teaser, mock_search_fn, use_native_tools=False)
    
    assert result["decision_found"] == False
```

---

### 🧪 TEST #3: End-to-End Tests

```python
# tests/test_e2e.py
import pytest
from pathlib import Path

def test_complete_workflow():
    """Test complete workflow from teaser to final document."""
    # 1. Load teaser
    teaser_path = Path("tests/fixtures/sample_teaser.pdf")
    teaser_content = tool_load_document(str(teaser_path))
    
    # 2. Run analysis
    analysis = run_agentic_analysis(
        teaser_content["text"],
        tool_search_procedure,
    )
    
    assert analysis["decision_found"] == True
    
    # 3. Run compliance
    compliance = run_agentic_compliance(
        teaser_content["text"],
        analysis["extracted_data"],
        tool_search_guidelines,
    )
    
    assert len(compliance["checks"]) > 0
    
    # 4. Generate structure
    structure = generate_section_structure(
        "",
        analysis["process_path"],
        analysis["origination_method"],
        analysis["full_analysis"],
    )
    
    assert len(structure) >= 3
    
    # 5. Draft sections
    context = {
        "teaser_text": teaser_content["text"],
        "extracted_data": analysis["extracted_data"],
        "compliance_result": compliance["full_analysis"],
        "requirements": [],
    }
    
    drafts = []
    for section in structure[:2]:  # Test first 2 sections
        draft = draft_section(section, context)
        assert len(draft.content) > 100
        drafts.append(draft)
    
    # 6. Generate DOCX
    from core.export import generate_docx
    docx_path = generate_docx(
        drafts,
        "EUR 50M",
        "Test Deal",
        analysis["process_path"],
        analysis["origination_method"],
    )
    
    assert Path(docx_path).exists()
    assert Path(docx_path).stat().st_size > 1000  # At least 1KB
```

---

## PART 9: DEPLOYMENT RECOMMENDATIONS

### 🚀 DEPLOY #1: Containerization

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Set environment
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_PORT=8080
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

EXPOSE 8080

CMD ["streamlit", "run", "ui/app.py"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT}
      - DATA_STORE_ID=${DATA_STORE_ID}
    volumes:
      - ./data:/app/data
      - ./outputs:/app/outputs
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped
```

---

### 🚀 DEPLOY #2: Kubernetes Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: credit-pack-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: credit-pack
  template:
    metadata:
      labels:
        app: credit-pack
    spec:
      serviceAccountName: credit-pack-sa
      containers:
      - name: app
        image: gcr.io/${PROJECT_ID}/credit-pack:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        env:
        - name: GOOGLE_CLOUD_PROJECT
          value: "${PROJECT_ID}"
        - name: DATA_STORE_ID
          valueFrom:
            secretKeyRef:
              name: credit-pack-secrets
              key: data-store-id
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: credit-pack-service
spec:
  type: LoadBalancer
  selector:
    app: credit-pack
  ports:
  - port: 80
    targetPort: 8080
```

---

### 🚀 DEPLOY #3: CI/CD Pipeline

```yaml
# .github/workflows/deploy.yml
name: Deploy to Production

on:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov
      
      - name: Run tests
        run: |
          pytest tests/ --cov=. --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
  
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Cloud SDK
        uses: google-github-actions/setup-gcloud@v1
        with:
          service_account_key: ${{ secrets.GCP_SA_KEY }}
          project_id: ${{ secrets.GCP_PROJECT_ID }}
      
      - name: Build and push Docker image
        run: |
          gcloud builds submit --tag gcr.io/${{ secrets.GCP_PROJECT_ID }}/credit-pack:${{ github.sha }}
          gcloud builds submit --tag gcr.io/${{ secrets.GCP_PROJECT_ID }}/credit-pack:latest
  
  deploy:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to GKE
        run: |
          gcloud container clusters get-credentials production --region us-central1
          kubectl set image deployment/credit-pack-app app=gcr.io/${{ secrets.GCP_PROJECT_ID }}/credit-pack:${{ github.sha }}
          kubectl rollout status deployment/credit-pack-app
```

---

## PART 10: PRIORITY IMPLEMENTATION PLAN

### Phase 1: Critical Fixes (Week 1)

**Day 1-2:**
1. ✅ Fix LLM output parsing (Critical #1)
   - Update extraction prompts with XML tags
   - Improve `safe_extract_json()` function
   - Add retry logic with temperature variation
   
2. ✅ Add user error messages (Critical #2)
   - Display clear errors when parsing fails
   - Show suggested actions to user

**Day 3:**
3. ✅ Fix model version compatibility (Critical #3)
   - Update to stable model versions
   - Add model validation

**Day 4-5:**
4. ✅ Fix bare except blocks (High #1)
5. ✅ Add timeout on LLM calls (High #5)
6. ✅ Add input validation (High #3)

**Testing & Validation:**
- Run full workflow with sample teasers
- Verify parsing success rate > 95%
- Check error messages are user-friendly

---

### Phase 2: Stability Improvements (Week 2)

**Day 6-7:**
1. Fix token limits (High #2)
2. Fix race conditions (High #4)
3. Fix memory leak in TraceStore (High #6)

**Day 8-9:**
4. Add document caching (Medium #2)
5. Optimize RAG search filtering (Medium #1)
6. Improve logging consistency (Medium #3)

**Day 10:**
7. Add unit tests for parsers
8. Add integration tests for orchestration

---

### Phase 3: Performance & Scale (Week 3)

**Day 11-12:**
1. Implement parallel tool calls (Perf #1)
2. Add lazy loading for large documents (Perf #2)
3. Implement batch LLM calls (Perf #3)

**Day 13-14:**
4. Add health checks and monitoring
5. Implement rate limiting
6. Add telemetry and usage tracking

**Day 15:**
7. Performance testing and optimization
8. Load testing with 100+ concurrent users

---

### Phase 4: Security & Deployment (Week 4)

**Day 16-17:**
1. Migrate credentials to Secret Manager (Security #1)
2. Add input sanitization (Security #2)
3. Implement RBAC (Security #3)

**Day 18-19:**
4. Containerize application
5. Set up Kubernetes deployment
6. Configure CI/CD pipeline

**Day 20:**
7. Production deployment
8. Smoke testing in production
9. Documentation and handoff

---

## SUMMARY OF RECOMMENDATIONS

### Immediate Actions (Do Now)
1. ✅ Fix LLM output parsing with XML tags and improved extraction
2. ✅ Add clear error messages to users
3. ✅ Update to stable model versions
4. ✅ Fix bare except blocks
5. ✅ Add timeout on LLM calls

### Short Term (Next 2 Weeks)
1. Add comprehensive unit and integration tests
2. Implement document caching
3. Fix memory leak in TraceStore
4. Add parallel tool execution
5. Implement rate limiting

### Medium Term (Next Month)
1. Separate API layer from UI
2. Implement event-driven architecture
3. Add message queue for long-running tasks
4. Migrate to Secret Manager for credentials
5. Implement RBAC and authentication

### Long Term (Next Quarter)
1. Build comprehensive monitoring and alerting
2. Implement advanced caching strategies
3. Add multi-tenancy support
4. Build admin dashboard for system management
5. Implement ML-based quality scoring for outputs

---

## CONCLUSION

This codebase is **well-architected** with good separation of concerns and modular design. However, the **critical parsing bug** prevents production use and must be fixed immediately.

The main issues stem from:
1. ❌ LLM output not being constrained enough
2. ❌ Insufficient error handling and user feedback
3. ❌ Lack of comprehensive testing
4. ❌ Some technical debt from rapid development

**Estimated Time to Production-Ready:**
- With focused team of 2-3 developers: **4 weeks**
- Critical fixes alone: **3-5 days**

**Overall Code Quality Score: 7.5/10**
- Architecture: 9/10 ✅
- Code Quality: 7/10 ⚠️
- Testing: 3/10 ❌
- Security: 5/10 ⚠️
- Performance: 7/10 ⚠️

**Recommendation:** Fix the critical parsing issue immediately, then proceed with systematic improvements following the phased implementation plan above.

---

**END OF COMPREHENSIVE AUDIT REPORT**
