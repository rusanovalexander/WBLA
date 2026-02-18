"""Minimal governance context. No dependency on parent repo."""


def get_governance_context() -> dict:
    """Return governance dict for prompts. Override with JSON file or env if needed."""
    return {
        "discovery_status": "ok",
        "categories": [],
        "vocabulary": {},
    }
