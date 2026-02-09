"""
LLM Output Parsers for Credit Pack PoC v3.2 - FIXED VERSION

Key fixes:
1. Improved safe_extract_json() with XML tag support
2. Better error messages with output samples
3. Additional JSON fixup attempts
4. Proper logging throughout
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from models.schemas import (
    OrchestratorInsights,
    RiskFlag,
    RiskSeverity,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Orchestrator Decision Parsing
# =============================================================================

def parse_orchestrator_insights(response: str) -> OrchestratorInsights:
    """Parse orchestrator decision point response into structured format."""
    insights = OrchestratorInsights(full_text=response)
    response_lower = response.lower()

    # Extract observations
    if "key observations" in response_lower:
        obs_end = response_lower.find("risk flags") if "risk flags" in response_lower else -1
        obs_section = response_lower.split("key observations")[1]
        if obs_end > 0:
            obs_section = obs_section[:obs_end]
        else:
            obs_section = obs_section[:500]

        for line in obs_section.split("\n"):
            cleaned = line.strip().lstrip("-•*").strip()
            if cleaned and len(cleaned) > 10:
                insights.observations.append(cleaned[:200])
        insights.observations = insights.observations[:5]

    # Extract risk flags
    if "risk flags" in response_lower:
        flags_section = response_lower.split("risk flags")[1]
        # Find end of flags section
        end_markers = ["plan", "recommendation", "message"]
        end_idx = len(flags_section)
        for marker in end_markers:
            pos = flags_section.find(marker)
            if 0 < pos < end_idx:
                end_idx = pos
        flags_section = flags_section[:min(end_idx, 500)]

        for line in flags_section.split("\n"):
            cleaned = line.strip().lstrip("-•*⚠️ ").strip()
            if not cleaned or len(cleaned) <= 5:
                continue

            severity = RiskSeverity.MEDIUM
            if "high" in cleaned.lower():
                severity = RiskSeverity.HIGH
            elif "low" in cleaned.lower():
                severity = RiskSeverity.LOW

            flag_text = re.sub(
                r"\(severity:\s*\w+\)", "", cleaned, flags=re.IGNORECASE
            ).strip()
            if flag_text:
                insights.flags.append(RiskFlag(text=flag_text[:150], severity=severity))
        insights.flags = insights.flags[:5]

    # Extract recommendations
    if "recommendation" in response_lower:
        rec_section = response_lower.split("recommendation")[1][:500]
        for line in rec_section.split("\n"):
            cleaned = line.strip().lstrip("-•*").strip()
            if cleaned and len(cleaned) > 10:
                insights.recommendations.append(cleaned[:200])
        insights.recommendations = insights.recommendations[:5]

    # Extract message to human
    if "message to human" in response_lower:
        msg = response.split("Message to Human")[-1].split("---")[0]
        insights.message_to_human = msg.lstrip(":").strip()[:400]

    return insights


# =============================================================================
# Tool Call Parsing (legacy — for backward compat with text-based tool calls)
# =============================================================================

def parse_tool_calls(response: str, tool_name: str = "search") -> list[str]:
    """
    Extract tool calls from agent response text.

    Looks for: <TOOL>search_procedure: "query text"</TOOL>

    NOTE: This is the LEGACY parser for text-based tool calls.
    New code should use native Gemini function calling via call_llm_with_tools().
    """
    queries: list[str] = []

    patterns = [
        rf'<TOOL>{tool_name}[^:]*:\s*"([^"]+)"</TOOL>',
        rf"<TOOL>{tool_name}[^:]*:\s*'([^']+)'</TOOL>",
        rf"<TOOL>{tool_name}[^:]*:\s*([^<]+)</TOOL>",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, response, re.IGNORECASE | re.DOTALL)
        for match in matches:
            query = match.strip().strip("\"'")
            if query and len(query) > 3:
                queries.append(query)

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for q in queries:
        q_lower = q.lower().strip()
        if q_lower not in seen:
            seen.add(q_lower)
            unique.append(q)

    return unique


def parse_agent_queries(response: str) -> list[dict[str, str]]:
    """Extract agent-to-agent queries from response text."""
    queries: list[dict[str, str]] = []
    pattern = r'<AGENT_QUERY\s+to="(\w+)">(.*?)</AGENT_QUERY>'
    matches = re.findall(pattern, response, re.DOTALL | re.IGNORECASE)

    for agent, query in matches:
        query_text = query.strip()
        if query_text:
            queries.append({"to": agent, "query": query_text})

    return queries


# =============================================================================
# RAG Result Formatting
# =============================================================================

def format_rag_results(rag_results: dict[str, Any]) -> str:
    """Format RAG search results for inclusion in prompts."""
    if not rag_results:
        return "(No RAG results)"

    formatted: list[str] = []

    for query, result in rag_results.items():
        if not isinstance(result, dict):
            continue

        if result.get("status") != "OK":
            formatted.append(f"\n### Query: \"{query}\"\n(No results found)")
            continue

        formatted.append(f"\n### Query: \"{query}\"\n")

        for r in result.get("results", [])[:3]:
            doc_type = r.get("doc_type", "Document")
            title = r.get("title", "Untitled")
            content = r.get("content", "")[:1500]
            formatted.append(f"**[{doc_type}] {title}**\n{content}\n")

    return "\n".join(formatted) if formatted else "(No results)"


# =============================================================================
# Requirements Formatting
# =============================================================================

def format_requirements_for_context(requirements: list[dict]) -> str:
    """
    Format filled requirements for inclusion in agent context.

    Preserves multi-line values (tables, rent rolls, covenant packages).
    """
    if not requirements:
        return "(No requirements)"

    filled = [r for r in requirements if r.get("status") == "filled"]
    if not filled:
        return "(No requirements filled yet)"

    lines: list[str] = []
    for r in filled:
        name = r.get("name", "Unknown")
        value = r.get("value", "N/A")
        source = r.get("source", "unknown")

        # Preserve multi-line structure
        if "\n" in value:
            lines.append(f"\n### {name} (Source: {source})\n{value}\n")
        else:
            lines.append(f"- **{name}**: {value} (Source: {source})")

        # Include AI analysis detail if available
        suggestion_detail = r.get("suggestion_detail", "")
        if suggestion_detail:
            lines.append(f"  _AI Analysis: {suggestion_detail[:300]}_")

    return "\n".join(lines)



# =============================================================================
# JSON Extraction Utilities - IMPROVED VERSION
# =============================================================================

def safe_extract_json(text: str, expect_type: str = "object") -> Any:
    """
    Safely extract JSON from LLM output with IMPROVED robustness.

    Handles common issues: markdown fences, XML tags, preamble text, trailing content,
    trailing commas, unquoted keys, and other LLM JSON quirks.

    Args:
        text: Raw LLM output
        expect_type: "object" for {}, "array" for []

    Returns:
        Parsed JSON or None on failure
    """
    if not text or not isinstance(text, str):
        logger.warning("safe_extract_json received invalid input: %s", type(text))
        return None
    
    # IMPROVEMENT 1: Try to extract from XML tags if present
    xml_pattern = r'<json_output>\s*([\s\S]*?)\s*</json_output>'
    xml_match = re.search(xml_pattern, text, re.IGNORECASE)
    if xml_match:
        logger.debug("Found JSON within <json_output> tags")
        text = xml_match.group(1).strip()
    
    # IMPROVEMENT 2: Strip ALL variations of markdown code fences robustly
    # Remove "codeJSON" or similar artifacts that appear before fences
    cleaned = re.sub(r'^\s*code(?:JSON|json)?\s*\n', '', text, flags=re.IGNORECASE)
    # Remove opening fences: ```json, ```JSON, ``` json, ```, with optional newlines
    cleaned = re.sub(r'```\s*(?:json|JSON)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
    # Remove closing fences: ``` with optional whitespace before/after
    cleaned = re.sub(r'\n?\s*```\s*$', '', cleaned)
    # Remove any remaining standalone backticks
    cleaned = cleaned.replace('```', '')
    cleaned = cleaned.strip()
    
    # IMPROVEMENT 3: Remove common preambles
    preamble_patterns = [
        r'^(?:here\s+is|here\'s|the\s+json|output:)\s*',
        r'^(?:sure|okay|certainly)[,.]?\s*',
    ]
    for pattern in preamble_patterns:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()

    # IMPROVEMENT 4: Find the JSON based on expected type
    if expect_type == "array":
        start_char, end_char = "[", "]"
    else:
        start_char, end_char = "{", "}"

    start = cleaned.find(start_char)
    if start < 0:
        logger.warning(
            "No %s found in LLM output (%d chars). First 200 chars: %s", 
            start_char, len(text), text[:200]
        )
        return None

    # IMPROVEMENT 5: Find matching end — track ALL bracket types to avoid
    # premature closure (e.g., `[{"id": 4]}` where `]` is misplaced)
    brace_depth = 0  # {}
    bracket_depth = 0  # []
    in_str = False
    escape_next = False
    for i in range(start, len(cleaned)):
        if escape_next:
            escape_next = False
            continue
        ch = cleaned[i]
        if ch == '\\' and in_str:
            escape_next = True  # skip next char (the escaped character)
            continue
        if ch == '"':
            in_str = not in_str
        if in_str:
            continue
        if ch == '{':
            brace_depth += 1
        elif ch == '}':
            brace_depth -= 1
        elif ch == '[':
            bracket_depth += 1
        elif ch == ']':
            bracket_depth -= 1
        # Only match when ALL brackets are closed
        if brace_depth == 0 and bracket_depth == 0:
            json_str = cleaned[start:i + 1]
            result = _try_parse_json(json_str)
            if result is not None:
                logger.info("Successfully parsed JSON (%d chars)", len(json_str))
                return result
            # If first match fails, keep looking
            break

    # IMPROVEMENT 6: Fallback to simple slice approach
    end = cleaned.rfind(end_char)
    if end > start:
        json_str = cleaned[start:end + 1]
        result = _try_parse_json(json_str)
        if result is not None:
            logger.info("Successfully parsed JSON via fallback (%d chars)", len(json_str))
            return result

    # IMPROVEMENT 7: Try to recover truncated JSON (LLM ran out of tokens mid-output)
    truncated_json = cleaned[start:] if start >= 0 else cleaned
    truncated_result = _try_recover_truncated_json(truncated_json, expect_type)
    if truncated_result is not None:
        logger.info("Recovered truncated JSON via repair (%d chars input)", len(truncated_json))
        return truncated_result

    # IMPROVEMENT 8: Better error logging with sample
    logger.error(
        "Could not parse JSON from LLM output (%d chars). First 500 chars:\n%s\n[...]\nLast 200 chars:\n%s",
        len(text), text[:500], text[-200:]
    )
    return None


def _try_recover_truncated_json(text: str, expect_type: str = "object") -> Any:
    """
    Attempt to recover truncated JSON from LLM output that ran out of tokens.

    Handles common truncation patterns:
    - Unterminated string values (missing closing quote)
    - Missing closing brackets/braces
    - Partial key-value pairs

    Strategy: progressively trim from the end to find a parseable subset,
    then close any open structures.

    Returns:
        Parsed JSON (partial — may be missing some fields) or None if unrecoverable.
    """
    if not text or len(text) < 10:
        return None

    start_char = "[" if expect_type == "array" else "{"
    end_char = "]" if expect_type == "array" else "}"

    start = text.find(start_char)
    if start < 0:
        return None

    working = text[start:]

    # Step 1: If we're inside an unterminated string, close it
    # Count unescaped quotes to determine if we're mid-string
    in_string = False
    last_good_pos = 0
    i = 0
    while i < len(working):
        ch = working[i]
        if ch == '\\' and in_string:
            i += 2  # Skip escaped character
            continue
        if ch == '"':
            in_string = not in_string
            if not in_string:
                last_good_pos = i  # Just closed a string
        elif not in_string and ch in ',}]':
            last_good_pos = i
        i += 1

    # If we ended mid-string, truncate to last complete string + close it
    if in_string:
        # Find the last complete value boundary before the unterminated string
        # Look backwards from end for the last comma, closing brace, or closing bracket
        # that's NOT inside a string
        working = working[:last_good_pos + 1]

    # Step 2: Remove any trailing partial key-value pair
    # e.g., trim trailing `"key": "partial_val` or `, "key"` or `, "key":`
    stripped = working.rstrip()

    # Remove trailing comma if present
    if stripped.endswith(','):
        stripped = stripped[:-1].rstrip()

    # If ends with a colon (partial key-value with colon), remove the partial key
    if stripped.endswith(':'):
        key_start = stripped.rfind('"', 0, len(stripped) - 1)
        if key_start > 0:
            prefix = stripped[:key_start].rstrip()
            if prefix.endswith(','):
                stripped = prefix[:-1].rstrip()
            else:
                stripped = prefix

    # If ends with a quoted string that is a dangling key (e.g., `, "assessment_reasoning"`),
    # check if the character before the opening quote is a comma (key context, not value)
    if stripped.endswith('"'):
        # Find the matching opening quote
        quote_end = len(stripped) - 1
        quote_start = stripped.rfind('"', 0, quote_end)
        if quote_start >= 0:
            before_key = stripped[:quote_start].rstrip()
            # If preceded by comma or colon-value-comma, it's a dangling key — remove it
            if before_key.endswith(','):
                stripped = before_key[:-1].rstrip()
            elif before_key.endswith('{') or before_key.endswith('['):
                pass  # It's the first key — keep it, it's a value not a key

    # Step 3: Close open brackets/braces
    open_braces = 0
    open_brackets = 0
    in_str = False
    for i, ch in enumerate(stripped):
        if ch == '\\' and in_str:
            continue
        if ch == '"' and (i == 0 or stripped[i - 1] != '\\'):
            in_str = not in_str
        if in_str:
            continue
        if ch == '{':
            open_braces += 1
        elif ch == '}':
            open_braces -= 1
        elif ch == '[':
            open_brackets += 1
        elif ch == ']':
            open_brackets -= 1

    # Append missing closers
    closers = ']' * max(0, open_brackets) + '}' * max(0, open_braces)
    repaired = stripped + closers

    # Step 4: Try to parse the repaired JSON
    result = _try_parse_json(repaired)
    if result is not None:
        # Validate: for arrays, should have at least 1 item; for objects, at least 1 key
        if expect_type == "array" and isinstance(result, list) and len(result) > 0:
            logger.info("Truncation recovery: got %d items from repaired array", len(result))
            return result
        elif expect_type == "object" and isinstance(result, dict) and len(result) > 0:
            logger.info("Truncation recovery: got %d keys from repaired object", len(result))
            return result
        elif result:  # Non-empty
            return result

    # Step 5: More aggressive — trim last incomplete array element
    if expect_type == "array":
        # Find the last complete object in the array (last `}`)
        last_obj_end = stripped.rfind('}')
        if last_obj_end > 0:
            candidate = stripped[:last_obj_end + 1].rstrip().rstrip(',')
            # Close any remaining open brackets
            if not candidate.endswith(']'):
                candidate += ']'
            result = _try_parse_json(candidate)
            if result is not None and isinstance(result, list) and len(result) > 0:
                logger.info("Truncation recovery (aggressive): got %d items", len(result))
                return result

    return None


def _try_parse_json(json_str: str) -> Any:
    """
    Try to parse JSON string with MULTIPLE fixup attempts for common LLM issues.
    
    Returns parsed JSON or None if all attempts fail.
    """
    # Attempt 1: Direct parse
    try:
        result = json.loads(json_str)
        logger.debug("JSON parsed successfully on first attempt")
        return result
    except json.JSONDecodeError:
        pass

    # Attempt 2: Fix trailing commas (very common LLM mistake)
    fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
    try:
        result = json.loads(fixed)
        logger.debug("JSON parsed after fixing trailing commas")
        return result
    except json.JSONDecodeError:
        pass

    # Attempt 3: Fix single quotes (another common mistake)
    fixed2 = fixed.replace("'", '"')
    try:
        result = json.loads(fixed2)
        logger.debug("JSON parsed after converting single quotes")
        return result
    except json.JSONDecodeError:
        pass
    
    # Attempt 4: Fix unquoted keys (e.g., {key: "value"} → {"key": "value"})
    fixed3 = re.sub(
        r'(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:',
        r'\1"\2":',
        fixed2
    )
    try:
        result = json.loads(fixed3)
        logger.debug("JSON parsed after quoting unquoted keys")
        return result
    except json.JSONDecodeError:
        pass
    
    # Attempt 5: Try to fix missing commas between objects/arrays
    fixed4 = re.sub(r'}\s*{', '},{', fixed3)
    fixed4 = re.sub(r']\s*\[', '],[', fixed4)
    try:
        result = json.loads(fixed4)
        logger.debug("JSON parsed after adding missing commas")
        return result
    except json.JSONDecodeError as e:
        logger.warning(
            "All JSON parse attempts failed. Last error: %s. JSON string (first 300 chars): %s",
            str(e), json_str[:300]
        )

    return None
