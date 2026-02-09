"""
LLM Client for Credit Pack PoC v3.2.

Centralized LLM call handler with:
- Retry logic via tenacity
- Streaming support
- Cost/token tracking via TraceStore
- Native Gemini function calling support
- Proper error handling (no bare excepts)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import PROJECT_ID, MODEL_PRO, ENABLE_STREAMING
from core.tracing import TraceStore, get_tracer, estimate_tokens
from models.schemas import LLMCallResult

logger = logging.getLogger(__name__)


# =============================================================================
# Singleton Client Cache (avoid creating new client per call)
# =============================================================================

_client_cache: dict[str, Any] = {}


def _get_client():
    """Return a cached genai.Client instance (created once, reused)."""
    if "client" not in _client_cache:
        from google import genai
        _client_cache["client"] = genai.Client(
            vertexai=True, project=PROJECT_ID, location="us-central1"
        )
        logger.info("Created singleton genai.Client for project=%s", PROJECT_ID)
    return _client_cache["client"]


# =============================================================================
# Retry configuration
# =============================================================================

RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
)

# Try to import Google-specific exceptions for retry
try:
    from google.api_core.exceptions import (
        ServiceUnavailable,
        DeadlineExceeded,
        ResourceExhausted,
        InternalServerError,
    )
    RETRYABLE_EXCEPTIONS = (
        *RETRYABLE_EXCEPTIONS,
        ServiceUnavailable,
        DeadlineExceeded,
        ResourceExhausted,
        InternalServerError,
    )
except ImportError:
    pass


# =============================================================================
# Core LLM Call
# =============================================================================

@retry(
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _call_gemini(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    tools: list[Any] | None = None,
    tool_config: Any | None = None,
) -> Any:
    """
    Raw Gemini API call with retry.

    Returns the raw response object for the caller to process.
    """
    from google.genai import types

    client = _get_client()

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    # Add tools if provided (native function calling)
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


def call_llm(
    prompt: str,
    model: str = MODEL_PRO,
    temperature: float = 0.1,
    max_tokens: int = 16384,
    agent_name: str = "LLM",
    tracer: TraceStore | None = None,
) -> LLMCallResult:
    """
    Call Vertex AI Gemini with full tracing and retry.

    Args:
        prompt: The prompt text
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum output tokens
        agent_name: Agent making the call (for tracing)
        tracer: TraceStore instance (uses global if not provided)

    Returns:
        LLMCallResult with text, metadata, and cost info
    """
    if tracer is None:
        tracer = get_tracer()

    with tracer.trace_llm_call(agent_name, model, prompt) as ctx:
        try:
            response = _call_gemini(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            # Guard: response.text can fail if no candidates (e.g., safety block, cancelled)
            try:
                result_text = response.text
            except (ValueError, AttributeError):
                result_text = "[No text in response — model may have returned empty/blocked output]"
                logger.warning("Response had no text for %s (candidates may be empty)", agent_name)
            ctx["response_text"] = result_text

            # Extract token counts if available
            if hasattr(response, "usage_metadata"):
                usage = response.usage_metadata
                ctx["tokens_in"] = getattr(usage, "prompt_token_count", 0) or 0
                ctx["tokens_out"] = getattr(usage, "candidates_token_count", 0) or 0
            else:
                ctx["tokens_in"] = estimate_tokens(prompt)
                ctx["tokens_out"] = estimate_tokens(result_text)

            return LLMCallResult(
                text=result_text,
                model=model,
                tokens_in=ctx["tokens_in"],
                tokens_out=ctx["tokens_out"],
                agent_name=agent_name,
                success=True,
            )

        except RETRYABLE_EXCEPTIONS:
            raise  # Let tenacity handle retry

        except Exception as e:
            error_msg = f"[LLM ERROR: {type(e).__name__}: {e}]"
            logger.error("LLM call failed for %s: %s", agent_name, e, exc_info=True)
            tracer.record(agent_name, "ERROR", str(e)[:200])

            return LLMCallResult(
                text=error_msg,
                model=model,
                agent_name=agent_name,
                success=False,
                error=str(e),
            )


# =============================================================================
# Rate Limit Backoff Support
# =============================================================================

def call_llm_with_backoff(
    prompt: str,
    model: str = MODEL_PRO,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    agent_name: str = "Agent",
    tracer: TraceStore | None = None,
    max_retries: int = 5,
) -> LLMCallResult:
    """
    Call LLM with exponential backoff for rate limit errors (429).

    FIXED: call_llm() catches exceptions internally and returns LLMCallResult(success=False),
    so we detect rate limits from the error message string instead of catching exceptions.

    Handles Google API rate limits gracefully:
    - Attempt 1: Immediate
    - Attempt 2: Wait 2 seconds
    - Attempt 3: Wait 4 seconds
    - Attempt 4: Wait 8 seconds
    - Attempt 5: Wait 16 seconds

    Args:
        Same as call_llm, plus:
        max_retries: Maximum retry attempts for 429 errors (default: 5)

    Returns:
        LLMCallResult
    """
    import time

    if tracer is None:
        tracer = get_tracer()

    result = None
    for attempt in range(max_retries):
        result = call_llm(prompt, model, temperature, max_tokens, agent_name, tracer)

        # If call succeeded, return immediately
        if result.success:
            return result

        # Detect rate limiting from the error message
        # (call_llm swallows exceptions into result.error string)
        error_lower = (result.error or "").lower()
        is_rate_limit = (
            "429" in error_lower
            or "resource exhausted" in error_lower
            or "rate limit" in error_lower
            or "resourceexhausted" in error_lower
            or "quota" in error_lower
        )
        # 499 CANCELLED is transient — worth retrying
        is_transient = (
            "499" in error_lower
            or "cancelled" in error_lower
            or "canceled" in error_lower
        )
        is_retryable = is_rate_limit or is_transient

        if is_retryable and attempt < max_retries - 1:
            wait_time = min(2 ** (attempt + 1), 30)
            retry_reason = "rate limit" if is_rate_limit else "transient error (499/cancelled)"
            tracer.record(
                agent_name, "RATE_LIMIT",
                f"Hit {retry_reason}, waiting {wait_time}s before retry {attempt + 2}/{max_retries}"
            )
            logger.warning(
                "%s for %s, waiting %ds (attempt %d/%d)",
                retry_reason.capitalize(), agent_name, wait_time, attempt + 1, max_retries
            )
            time.sleep(wait_time)
            continue  # Retry
        else:
            # Non-retryable error or exhausted retries
            if is_retryable:
                tracer.record(agent_name, "RATE_LIMIT_EXCEEDED", "All retries exhausted")
                logger.error("Retries exhausted for %s", agent_name)
            return result

    return result


# =============================================================================
# Streaming LLM Call
# =============================================================================

@retry(
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
def _call_gemini_streaming(
    prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    """
    Raw Gemini streaming API call with retry.

    Returns the concatenated response text. Retryable exceptions
    (429, 503, timeout, etc.) are retried by tenacity.
    """
    from google.genai import types

    client = _get_client()

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

    chunks: list[str] = []
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=prompt,
        config=config,
    ):
        if chunk.text:
            chunks.append(chunk.text)
            if on_chunk:
                on_chunk(chunk.text)

    return "".join(chunks)


def call_llm_streaming(
    prompt: str,
    model: str = MODEL_PRO,
    temperature: float = 0.1,
    max_tokens: int = 16384,
    agent_name: str = "LLM",
    on_chunk: Callable[[str], None] | None = None,
    tracer: TraceStore | None = None,
) -> LLMCallResult:
    """
    Call Vertex AI Gemini with streaming output.

    Args:
        prompt: The prompt text
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum output tokens
        agent_name: Agent making the call (for tracing)
        on_chunk: Callback for each text chunk (for Streamlit streaming)
        tracer: TraceStore instance

    Returns:
        LLMCallResult with complete text and metadata
    """
    if not ENABLE_STREAMING:
        return call_llm(prompt, model, temperature, max_tokens, agent_name, tracer)

    if tracer is None:
        tracer = get_tracer()

    with tracer.trace_llm_call(agent_name, model, prompt) as ctx:
        try:
            result_text = _call_gemini_streaming(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                on_chunk=on_chunk,
            )

            ctx["response_text"] = result_text
            ctx["tokens_in"] = estimate_tokens(prompt)
            ctx["tokens_out"] = estimate_tokens(result_text)

            return LLMCallResult(
                text=result_text,
                model=model,
                tokens_in=ctx["tokens_in"],
                tokens_out=ctx["tokens_out"],
                agent_name=agent_name,
                success=True,
            )

        except RETRYABLE_EXCEPTIONS:
            raise  # Let tenacity handle retry

        except Exception as e:
            error_msg = f"[LLM ERROR: {type(e).__name__}: {e}]"
            logger.error("Streaming LLM call failed for %s: %s", agent_name, e, exc_info=True)
            tracer.record(agent_name, "ERROR", str(e)[:200])
            return LLMCallResult(
                text=error_msg,
                model=model,
                agent_name=agent_name,
                success=False,
                error=str(e),
            )


# =============================================================================
# Result Validation Utility (AG-H3)
# =============================================================================

def require_success(
    result: LLMCallResult,
    agent_name: str = "",
    tracer: TraceStore | None = None,
) -> LLMCallResult:
    """Validate that an LLM call succeeded. Raises RuntimeError on failure."""
    if not result.success:
        name = agent_name or result.agent_name
        if tracer:
            tracer.record(name, "LLM_FAIL", result.error or "Unknown error")
        raise RuntimeError(f"LLM call failed for {name}: {result.error}")
    return result


# =============================================================================
# Native Function Calling
# =============================================================================

def call_llm_with_tools(
    prompt: str,
    tools: list[Any],
    tool_executor: Callable[[str, dict], Any],
    model: str = MODEL_PRO,
    temperature: float = 0.1,
    max_tokens: int = 16384,
    agent_name: str = "LLM",
    max_tool_rounds: int = 5,
    tracer: TraceStore | None = None,
) -> LLMCallResult:
    """
    Call Gemini with native function calling in a ReAct-style loop.

    The model can invoke tools, receive results, and continue reasoning
    for up to `max_tool_rounds` iterations.

    Args:
        prompt: The prompt text
        tools: List of google.genai.types.Tool objects
        tool_executor: Function(tool_name, tool_args) -> result
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum output tokens
        agent_name: Agent making the call
        max_tool_rounds: Max tool-use iterations before forcing text response
        tracer: TraceStore instance

    Returns:
        LLMCallResult with final text response
    """
    if tracer is None:
        tracer = get_tracer()

    import time as _time  # AG-M4: for wall-clock timeout

    from google.genai import types

    client = _get_client()

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        tools=tools,
    )

    # Build conversation history for multi-turn tool use
    contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

    all_text_parts: list[str] = []
    total_tokens_in = estimate_tokens(prompt)
    total_tokens_out = 0
    _loop_start = _time.time()
    _max_duration = 120  # AG-M4: 2-minute wall-clock timeout

    for round_num in range(max_tool_rounds):
        # AG-M4: Wall-clock timeout check
        elapsed = _time.time() - _loop_start
        if elapsed > _max_duration:
            tracer.record(agent_name, "TIMEOUT", f"Tool loop exceeded {_max_duration}s after {round_num} rounds")
            break

        tracer.record(
            agent_name,
            "TOOL_ROUND",
            f"Round {round_num + 1}/{max_tool_rounds}",
            model=model,
        )

        # AG-M1: Route through retryable _call_gemini for per-round retry
        try:
            response = _call_gemini(
                prompt=contents,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
            )
        except Exception as e:
            logger.error("Tool call round %d failed: %s", round_num + 1, e, exc_info=True)
            tracer.record(agent_name, "ERROR", f"Round {round_num + 1}: {e}")
            break

        # Guard against empty/cancelled responses (e.g., 499 CANCELLED)
        if not response.candidates:
            logger.warning("Tool round %d: no candidates in response (cancelled/empty)", round_num + 1)
            tracer.record(agent_name, "WARNING", f"Round {round_num + 1}: empty response (no candidates)")
            break

        # Check if model wants to call a function
        function_calls = []
        text_parts = []

        for candidate in response.candidates:
            if not candidate.content or not candidate.content.parts:
                continue
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    function_calls.append(part.function_call)
                elif hasattr(part, "text") and part.text:
                    text_parts.append(part.text)

        # Collect any text output
        if text_parts:
            all_text_parts.extend(text_parts)

        # If no function calls, we're done
        if not function_calls:
            break

        # Execute function calls and build response
        contents.append(response.candidates[0].content)  # Add model's response

        function_response_parts = []
        for fc in function_calls:
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            tracer.record(
                agent_name,
                "TOOL_CALL",
                f"{tool_name}({str(tool_args)[:100]})",
            )

            try:
                tool_result = tool_executor(tool_name, tool_args)
                result_str = str(tool_result) if not isinstance(tool_result, str) else tool_result
            except Exception as e:
                logger.error("Tool execution failed: %s(%s): %s", tool_name, tool_args, e)
                result_str = f"[TOOL ERROR: {e}]"

            tracer.record(
                agent_name,
                "TOOL_RESULT",
                f"{tool_name} → {len(result_str)} chars",
            )

            # AG-M6: Add truncation marker so the model knows data was lost
            truncated_result = result_str
            if len(result_str) > 4000:
                truncated_result = result_str[:4000] + f"\n[TRUNCATED: original was {len(result_str)} chars — ask a more specific question if needed]"

            function_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=tool_name,
                        response={"result": truncated_result},
                    )
                )
            )
            total_tokens_in += estimate_tokens(truncated_result)

        # Add function responses to conversation
        contents.append(types.Content(role="user", parts=function_response_parts))
    else:
        # Exhausted all rounds — record warning
        tracer.record(agent_name, "WARNING", f"Hit max tool rounds ({max_tool_rounds})")

    # AG-M2: Return success=False when no text was generated
    if all_text_parts:
        final_text = "\n".join(all_text_parts)
        total_tokens_out = estimate_tokens(final_text)
        return LLMCallResult(
            text=final_text,
            model=model,
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            agent_name=agent_name,
            success=True,
        )
    else:
        final_text = "[No text response generated]"
        return LLMCallResult(
            text=final_text,
            model=model,
            tokens_in=total_tokens_in,
            tokens_out=0,
            agent_name=agent_name,
            success=False,
            error="No text output from tool-calling loop",
        )
