"""Configuration from environment. No dependency on parent repo."""

import os
from pathlib import Path

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
SEARCH_LOCATION = os.getenv("SEARCH_LOCATION", "global")
MODEL_DEFAULT = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

# Vertex AI Search (Discovery Engine) — required for RAG procedure/guidelines
DATA_STORE_ID = os.getenv("DATA_STORE_ID", "")

# Document type detection for Procedure vs Guidelines
DOC_TYPE_KEYWORDS = {
    "Procedure": ["procedure", "assessment", "process", "manual", "instruction", "operating", "methodology"],
    "Guidelines": ["guideline", "guidance", "policy", "standard", "framework", "criteria", "rule"],
}

# Outputs directory (relative to credit-pack project or cwd)
OUTPUTS_DIR = os.getenv("CREDIT_PACK_OUTPUTS", "outputs")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Credit_Pack")


def get_credentials():
    """Google Cloud credentials: key file or Application Default Credentials."""
    key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if key_path and Path(key_path).exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(key_path)
    import google.auth
    credentials, _ = google.auth.default()
    return credentials
