"""
Native Gemini Function Declarations for Credit Pack PoC v3.2 — DOCUMENT-DRIVEN VERSION

Key changes:
- get_tool_declarations() accepts governance_context parameter (M14)
- Search query examples derived from governance documents when available
- Falls back to generic examples when governance context is not available
"""

from __future__ import annotations

from typing import Any, Callable


def get_tool_declarations(governance_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Get Gemini-native tool declarations.

    Args:
        governance_context: Optional governance context from discovery

    Returns dict mapping tool names to their function declarations.
    These are passed to the Gemini API via GenerateContentConfig.tools.
    """
    try:
        from google.genai import types
    except ImportError:
        return {}

    # Build search query examples from governance context or defaults (M14)
    if governance_context and governance_context.get("search_vocabulary"):
        vocab = governance_context["search_vocabulary"]
        proc_examples = ", ".join(f"'{v}'" for v in vocab[:3]) if vocab else "'assessment approach thresholds'"
        guide_examples = ", ".join(f"'{v}'" for v in vocab[3:6]) if len(vocab) > 3 else "'compliance criteria limits'"
    else:
        proc_examples = "'assessment approach thresholds', 'credit origination methods', 'assessment decision criteria'"
        guide_examples = "'compliance criteria limits', 'financial ratio requirements', 'security package requirements'"

    return {
        "search_procedure": types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="search_procedure",
                    description=(
                        "Search the Procedure document for specific rules, thresholds, "
                        "process requirements, decision criteria, or section text. Use this to "
                        "find assessment approaches, origination methods, and required steps."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "query": types.Schema(
                                type="STRING",
                                description=(
                                    "Search query — be specific about what rule or threshold you need. "
                                    f"Examples: {proc_examples}"
                                ),
                            ),
                            "num_results": types.Schema(
                                type="INTEGER",
                                description="Number of results to return (1-5, default 3)",
                            ),
                        },
                        required=["query"],
                    ),
                ),
            ]
        ),
        "search_guidelines": types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="search_guidelines",
                    description=(
                        "Search the Guidelines document for specific limits, thresholds, "
                        "compliance criteria, security requirements, or section text. "
                        "Use this to find lending limits, ratio requirements, and collateral rules."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "query": types.Schema(
                                type="STRING",
                                description=(
                                    "Search query — be specific about what limit or rule you need. "
                                    f"Examples: {guide_examples}"
                                ),
                            ),
                            "num_results": types.Schema(
                                type="INTEGER",
                                description="Number of results to return (1-5, default 3)",
                            ),
                        },
                        required=["query"],
                    ),
                ),
            ]
        ),
        "search_rag": types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="search_rag",
                    description=(
                        "Search all indexed documents (Procedure + Guidelines) for any information. "
                        "Use when you're not sure which document to search."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "query": types.Schema(
                                type="STRING",
                                description="Search query",
                            ),
                            "num_results": types.Schema(
                                type="INTEGER",
                                description="Number of results to return (1-5, default 3)",
                            ),
                        },
                        required=["query"],
                    ),
                ),
            ]
        ),
        "submit_analysis_result": types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="submit_analysis_result",
                    description=(
                        "Submit the final structured analysis result. "
                        "Call this LAST, after completing all Procedure searches. "
                        "This is the REQUIRED way to record your decision — do NOT write "
                        "a RESULT_JSON text block; use this tool instead."
                    ),
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "assessment_approach": types.Schema(
                                type="STRING",
                                description="Exact assessment approach term from the Procedure document.",
                            ),
                            "origination_method": types.Schema(
                                type="STRING",
                                description="Exact origination method term from the Procedure document.",
                            ),
                            "assessment_reasoning": types.Schema(
                                type="STRING",
                                description=(
                                    "1-2 sentence explanation of why this assessment approach "
                                    "was chosen, citing Procedure sections."
                                ),
                            ),
                            "origination_reasoning": types.Schema(
                                type="STRING",
                                description=(
                                    "1-2 sentence explanation of why this origination method "
                                    "was chosen, citing Procedure sections."
                                ),
                            ),
                            "procedure_sections_cited": types.Schema(
                                type="ARRAY",
                                items=types.Schema(type="STRING"),
                                description=(
                                    "List of Procedure section references used "
                                    "(e.g. ['Section 3.1', 'Section 4.2'])."
                                ),
                            ),
                            "confidence": types.Schema(
                                type="STRING",
                                description="Confidence level: HIGH, MEDIUM, or LOW.",
                            ),
                        },
                        required=[
                            "assessment_approach",
                            "origination_method",
                            "assessment_reasoning",
                            "origination_reasoning",
                            "confidence",
                        ],
                    ),
                ),
            ]
        ),
    }


def create_tool_executor(
    search_procedure_fn,
    search_guidelines_fn,
    search_rag_fn,
) -> Callable[[str, dict], str]:
    """
    Create a tool executor function that routes native function calls
    to the appropriate tool implementation.

    Args:
        search_procedure_fn: Function(query, num_results) -> dict
        search_guidelines_fn: Function(query, num_results) -> dict
        search_rag_fn: Function(query, num_results) -> dict

    Returns:
        Executor function(tool_name, tool_args) -> str
    """

    def executor(tool_name: str, tool_args: dict) -> str:
        query = tool_args.get("query", "")
        num_results = tool_args.get("num_results", 3)

        if tool_name == "search_procedure":
            result = search_procedure_fn(query, num_results)
        elif tool_name == "search_guidelines":
            result = search_guidelines_fn(query, num_results)
        elif tool_name == "search_rag":
            result = search_rag_fn(query, num_results)
        else:
            return f"[Unknown tool: {tool_name}]"

        # Format results as readable text for the model
        if result.get("status") != "OK" or not result.get("results"):
            return f"No results found for: {query}"

        formatted_parts = []
        for r in result["results"][:num_results]:
            doc_type = r.get("doc_type", "Document")
            title = r.get("title", "Untitled")
            content = r.get("content", "")[:2000]
            formatted_parts.append(f"[{doc_type}] {title}\n{content}")

        return "\n\n---\n\n".join(formatted_parts)

    return executor


def get_agent_tools(agent_name: str, governance_context: dict[str, Any] | None = None) -> list[Any]:
    """
    Get the appropriate tool declarations for a given agent.

    Args:
        agent_name: Name of the agent
        governance_context: Optional governance context from discovery

    Returns:
        List of Tool objects for the agent
    """
    declarations = get_tool_declarations(governance_context)
    if not declarations:
        return []

    agent_tool_map = {
        "ProcessAnalyst": ["search_procedure", "submit_analysis_result"],
        "ComplianceAdvisor": ["search_guidelines", "search_procedure"],
        "Orchestrator": ["search_procedure", "search_guidelines", "search_rag"],
        "Writer": [],  # Writer uses agent queries, not direct RAG
    }

    tool_names = agent_tool_map.get(agent_name, [])
    return [declarations[name] for name in tool_names if name in declarations]
