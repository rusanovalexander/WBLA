"""
Lazy-loaded Credit Pack agents for ADK tools.

Adds repo root to sys.path so we can import agents, core, config, tools.
Run from repo root: PYTHONPATH=. uv run --project credit-pack adk web
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if _REPO_ROOT.exists() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config.settings import setup_environment

setup_environment()

from config.settings import MODEL_PRO
from core.governance_discovery import run_governance_discovery
from core.llm_client import call_llm
from core.tracing import get_tracer
from tools.rag_search import tool_search_procedure, tool_search_guidelines
from agents import ProcessAnalyst, ComplianceAdvisor, Writer, AgentCommunicationBus
from agents.level3 import create_process_analyst_responder, create_compliance_advisor_responder

_analyst = None
_advisor = None
_writer = None
_governance_context = None
_tracer = None


def _ensure_governance():
    global _governance_context, _tracer
    if _governance_context is not None:
        return
    _tracer = get_tracer()
    result = run_governance_discovery(
        search_procedure_fn=tool_search_procedure,
        search_guidelines_fn=tool_search_guidelines,
        tracer=_tracer,
    )
    result.setdefault("discovery_status", "ok")
    _governance_context = result


def _search_procedure(query: str, num_results: int = 3):
    return tool_search_procedure(query, num_results=num_results)


def _search_guidelines(query: str, num_results: int = 3):
    return tool_search_guidelines(query, num_results=num_results)


def get_analyst() -> ProcessAnalyst:
    global _analyst
    _ensure_governance()
    if _analyst is None:
        _analyst = ProcessAnalyst(
            search_procedure_fn=_search_procedure,
            governance_context=_governance_context,
            tracer=_tracer,
        )
    return _analyst


def _rag_search_guidelines(query: str, num_results: int = 3):
    return tool_search_guidelines(query, num_results=num_results)


def get_advisor() -> ComplianceAdvisor:
    global _advisor
    _ensure_governance()
    if _advisor is None:
        _advisor = ComplianceAdvisor(
            search_guidelines_fn=_rag_search_guidelines,
            governance_context=_governance_context,
            tracer=_tracer,
            search_procedure_fn=_search_procedure,
        )
    return _advisor


def get_writer() -> Writer:
    global _writer
    _ensure_governance()
    if _writer is None:
        def llm_with_tracer(prompt, model, temperature, max_tokens, agent_name):
            return call_llm(prompt, model, temperature, max_tokens, agent_name, tracer=_tracer)
        bus = AgentCommunicationBus()
        pa_responder = create_process_analyst_responder(
            llm_caller=llm_with_tracer, model=MODEL_PRO, governance_context=_governance_context
        )
        ca_responder = create_compliance_advisor_responder(
            llm_caller=llm_with_tracer, model=MODEL_PRO, rag_tool=_rag_search_guidelines, governance_context=_governance_context
        )
        bus.register_responder("ProcessAnalyst", pa_responder)
        bus.register_responder("ComplianceAdvisor", ca_responder)
        _writer = Writer(
            search_procedure_fn=_search_procedure,
            governance_context=_governance_context,
            agent_bus=bus,
            tracer=_tracer,
        )
    return _writer


def get_governance_context() -> dict:
    _ensure_governance()
    return _governance_context
