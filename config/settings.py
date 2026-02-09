"""
Configuration settings for Credit Pack PoC v3.2.

Environment variables:
    GOOGLE_CLOUD_PROJECT: GCP project ID
    GOOGLE_APPLICATION_CREDENTIALS: Path to service account key
    DATA_STORE_ID: Vertex AI Search data store ID
    DOCAI_PROCESSOR_ID: Document AI processor ID (optional)
"""

import os
from pathlib import Path

# =============================================================================
# Version
# =============================================================================

VERSION = "3.2.0"

# =============================================================================
# Google Cloud Configuration
# =============================================================================

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "your-project-id")

# Locations
LOCATION = os.getenv("LOCATION", "us")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
SEARCH_LOCATION = os.getenv("SEARCH_LOCATION", "global")

# Authentication
KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "auth_key.json")

# Document AI
DOCAI_PROCESSOR_ID = os.getenv("DOCAI_PROCESSOR_ID", "")

# Vertex AI Search (RAG)
DATA_STORE_ID = os.getenv("DATA_STORE_ID", "")

# =============================================================================
# Models
# =============================================================================

MODEL_PRO = os.getenv("MODEL_PRO", "gemini-2.0-flash-exp")  # Stable, fast, cost-effective
MODEL_FLASH = os.getenv("MODEL_FLASH", "gemini-2.0-flash-exp")  # Use same for consistency

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
    "Guidelines": ["guideline", "guidance", "lending", "policy", "standard", "framework", "criteria", "rule"],
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
# Helper Functions
# =============================================================================

def get_credentials():
    """Get Google Cloud credentials."""
    if os.path.exists(KEY_PATH):
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(KEY_PATH)
    else:
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
    status = {
        "project_id": bool(PROJECT_ID and PROJECT_ID != "your-project-id"),
        "credentials": os.path.exists(KEY_PATH),
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
