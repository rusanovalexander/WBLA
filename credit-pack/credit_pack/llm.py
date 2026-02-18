"""Minimal LLM client using Vertex AI (google-genai). Self-contained."""

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
        _client = genai.Client(vertexai=True, project=project, location=location)
    return _client


def generate(prompt: str, model: str | None = None, temperature: float = 0.0, max_tokens: int = 8192) -> str:
    """Sync generate. Returns response text or empty string on error."""
    from google.genai import types
    try:
        client = _get_client()
        model = model or os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return (response.text or "").strip()
    except Exception as e:
        logger.exception("LLM generate failed: %s", e)
        return ""


def generate_with_thinking(prompt: str, model: str | None = None, max_tokens: int = 8192) -> tuple[str, str]:
    """Generate and return (answer_text, thinking_text). Thinking may be empty."""
    from google.genai import types
    try:
        client = _get_client()
        model = model or os.getenv("ROOT_AGENT_MODEL", "gemini-2.5-flash")
        config = types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=max_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=1024, include_thoughts=True),
        )
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        thinking_parts = []
        answer_parts = []
        if getattr(response, "candidates", None) and response.candidates:
            c0 = response.candidates[0]
            if getattr(c0, "content", None) and getattr(c0.content, "parts", None):
                for p in c0.content.parts:
                    t = getattr(p, "text", None) or ""
                    if not t:
                        continue
                    if getattr(p, "thought", False):
                        thinking_parts.append(t)
                    else:
                        answer_parts.append(t)
        answer = "\n".join(answer_parts) if answer_parts else (response.text or "")
        thinking = "\n\n".join(thinking_parts) if thinking_parts else ""
        return (answer.strip(), thinking.strip())
    except Exception as e:
        logger.exception("LLM generate_with_thinking failed: %s", e)
        return ("", "")
