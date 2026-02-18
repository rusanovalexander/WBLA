"""Configuration from environment. No dependency on parent repo."""

import os

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
MODEL_DEFAULT = os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")

# Outputs directory (relative to credit-pack project or cwd)
OUTPUTS_DIR = os.getenv("CREDIT_PACK_OUTPUTS", "outputs")
PRODUCT_NAME = os.getenv("PRODUCT_NAME", "Credit_Pack")
