"""
Configuration settings for Credit Pack PoC v3.2.

Environment variables:
    GOOGLE_CLOUD_PROJECT: GCP project ID
    GOOGLE_APPLICATION_CREDENTIALS: Path to service account key
    DATA_STORE_ID: Vertex AI Search data store ID
    DOCAI_PROCESSOR_ID: Document AI processor ID (optional)
"""

import os
import json
import tempfile
from pathlib import Path


# =============================================================================
# Streamlit Secrets helper (for Streamlit Community Cloud deployment)
# =============================================================================

def _get_secret(key: str, default: str = "") -> str:
    """Read a config value from Streamlit secrets (if available) or env var."""
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


def _init_service_account_from_secrets() -> str | None:
    """
    If running on Streamlit Cloud with gcp_service_account in secrets,
    write the key JSON to a temp file and return its path.
    Returns None if secrets are not available (local dev).
    """
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            sa_info = dict(st.secrets["gcp_service_account"])
            # Write to a temp file so Google SDKs can find it
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="gcp_sa_"
            )
            json.dump(sa_info, tmp)
            tmp.close()
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tmp.name
            return tmp.name
    except Exception:
        pass
    return None


# Attempt to load SA key from Streamlit secrets at import time
_SECRETS_KEY_PATH = _init_service_account_from_secrets()

# =============================================================================
# Version
# =============================================================================

VERSION = "3.2.0"

# =============================================================================
# Product / Domain Configuration (avoids hardcoded domain assumptions)
# =============================================================================

PRODUCT_NAME = _get_secret("PRODUCT_NAME", "CP")  # Configurable output document name
PRODUCT_ROLE = _get_secret("PRODUCT_ROLE", "Senior Analyst")  # Configurable agent persona
PRODUCT_AUDIENCE = _get_secret("PRODUCT_AUDIENCE", "decision committee")  # Target audience

# =============================================================================
# Google Cloud Configuration
# =============================================================================

PROJECT_ID = _get_secret("GOOGLE_CLOUD_PROJECT", "your-project-id")

# Locations
LOCATION = _get_secret("LOCATION", "us")
VERTEX_LOCATION = _get_secret("VERTEX_LOCATION", "us-central1")
SEARCH_LOCATION = _get_secret("SEARCH_LOCATION", "global")

# Authentication — prefer secrets-derived temp file, then env var, then local file
KEY_PATH = _SECRETS_KEY_PATH or os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "auth_key.json")

# Document AI
DOCAI_PROCESSOR_ID = _get_secret("DOCAI_PROCESSOR_ID", "")

# Vertex AI Search (RAG)
DATA_STORE_ID = _get_secret("DATA_STORE_ID", "")

# =============================================================================
# Models
# =============================================================================

MODEL_PRO = os.getenv("MODEL_PRO", "gemini-2.5-pro")  # Stable, fast, cost-effective
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-2.5-flash")  # Use same for consistency

# Agent model assignments
AGENT_MODELS = {
    "orchestrator": MODEL_PRO,
    "process_analyst": MODEL_FLASH,
    "compliance_advisor": MODEL_PRO,
    "writer": MODEL_PRO,
}

# Agent temperatures
AGENT_TEMPERATURES = {
    "orchestrator": 0.1,
    "process_analyst": 0.0,
    "compliance_advisor": 0.0,
    "writer": 0.3,
}

# =============================================================================
# Paths
# =============================================================================

BASE_DIR = Path(__file__).parent.parent
DATA_FOLDER = BASE_DIR / "data"
PROCEDURE_FOLDER = DATA_FOLDER / "procedure"
GUIDELINES_FOLDER = DATA_FOLDER / "guidelines"
EXAMPLES_FOLDER = DATA_FOLDER / "examples"
TEASERS_FOLDER = DATA_FOLDER / "teasers"
OUTPUTS_FOLDER = BASE_DIR / "outputs"

# Ensure directories exist
for _folder in [PROCEDURE_FOLDER, GUIDELINES_FOLDER, EXAMPLES_FOLDER, TEASERS_FOLDER, OUTPUTS_FOLDER]:
    _folder.mkdir(parents=True, exist_ok=True)

# =============================================================================
# RAG Document Type Detection Keywords (configurable)
# =============================================================================

DOC_TYPE_KEYWORDS = {
    "Procedure": ["procedure", "assessment", "process", "manual", "instruction", "operating", "methodology"],
    "Guidelines": ["guideline", "guidance", "policy", "standard", "framework", "criteria", "rule"],
}

# =============================================================================
# Feature Flags
# =============================================================================

VERBOSE_REASONING = os.getenv("VERBOSE_REASONING", "true").lower() == "true"
ENABLE_STREAMING = os.getenv("ENABLE_STREAMING", "true").lower() == "true"
REQUIRE_APPROVAL = os.getenv("REQUIRE_APPROVAL", "true").lower() == "true"

# Max tokens for context
MAX_CONTEXT_TOKENS = 100_000

# =============================================================================
# Thinking Budget Configuration (gemini-2.5-pro/flash thinking control)
# =============================================================================
# 0 = disabled (extraction tasks — pure JSON output)
# 2048 = light thinking (tool-calling loops, routing decisions)
# 4096 = standard thinking (agent analysis, drafting)
# None = model default (no ThinkingConfig set)

THINKING_BUDGET_NONE = 0       # Extraction, JSON parsing, auto-fill
THINKING_BUDGET_LIGHT = 2048   # Tool loops, routing, planning
THINKING_BUDGET_STANDARD = 4096  # Agent analysis, compliance, drafting


# =============================================================================
# Helper Functions
# =============================================================================

def get_credentials():
    """Get Google Cloud credentials.

    Priority:
    1. Streamlit secrets (gcp_service_account) → from_service_account_info()
    2. Key file on disk (local dev) → from_service_account_file()
    3. Application Default Credentials (ADC) → google.auth.default()
    """
    # 1. Try Streamlit secrets (direct dict, no temp file needed)
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            from google.oauth2 import service_account
            sa_info = dict(st.secrets["gcp_service_account"])
            return service_account.Credentials.from_service_account_info(sa_info)
    except Exception:
        pass

    # 2. Try key file on disk
    if KEY_PATH and os.path.exists(KEY_PATH):
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(KEY_PATH)

    # 3. Fall back to ADC
    import google.auth
    credentials, _ = google.auth.default()
    return credentials


def setup_environment():
    """Set up environment variables for Google Cloud."""
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJECT_ID
    os.environ["GOOGLE_CLOUD_LOCATION"] = VERTEX_LOCATION
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

    if os.path.exists(KEY_PATH):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH


def validate_config() -> dict[str, bool]:
    """Validate configuration and return status dict."""
    # Credentials are valid if: Streamlit secrets have SA key, OR key file exists on disk
    has_credentials = bool(_SECRETS_KEY_PATH) or (KEY_PATH and os.path.exists(KEY_PATH))
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            has_credentials = True
    except Exception:
        pass

    status = {
        "project_id": bool(PROJECT_ID and PROJECT_ID != "your-project-id"),
        "credentials": has_credentials,
        "data_store": bool(DATA_STORE_ID),
        "docai_processor": bool(DOCAI_PROCESSOR_ID),
    }
    status["all_ok"] = all(v for k, v in status.items() if k != "docai_processor")
    return status


def get_verbose_block() -> str:
    """Get verbose reasoning instruction block for agents."""
    if not VERBOSE_REASONING:
        return ""

    return """

## OUTPUT FORMAT (VISIBLE REASONING — REQUIRED)

You MUST structure EVERY response with visible reasoning:

### 🧠 THINKING
1. **Observations:** What I see in the input data...
2. **Relevant Rules:** According to [Procedure/Guidelines section X.X]...
3. **Application:** How the rules apply to this case...
4. **Confidence:** [HIGH/MEDIUM/LOW] because...

### 📋 RESULT
[Your actual output/answer]

### ❓ OPEN QUESTIONS (if any)
[List anything unclear that needs human clarification]

---

This visible reasoning is CRITICAL for the demo. Never skip it.
"""
