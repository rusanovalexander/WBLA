"""
Agents module for Credit Pack PoC v3.2.

Multi-agent system:
- OrchestratorAgent: Coordinates workflow, analyzes findings, flags risks
- ProcessAnalystAgent: Analyzes teasers, autonomous RAG searches
- ComplianceAdvisorAgent: Compliance checks, autonomous RAG searches
- WriterAgent: Drafts sections, can query other agents
"""

from .orchestrator import orchestrator_config, ORCHESTRATOR_INSTRUCTION, get_orchestrator_instruction
from .process_analyst import process_analyst_config, PROCESS_ANALYST_INSTRUCTION, get_process_analyst_instruction
from .compliance_advisor import compliance_advisor_config, COMPLIANCE_ADVISOR_INSTRUCTION, get_compliance_advisor_instruction, ComplianceAdvisor
from .writer import writer_config, WRITER_INSTRUCTION, get_writer_instruction
from .level3 import (
    AgentCommunicationBus,
    create_process_analyst_responder,
    create_compliance_advisor_responder,
)

AGENT_CONFIGS = {
    "orchestrator": orchestrator_config,
    "process_analyst": process_analyst_config,
    "compliance_advisor": compliance_advisor_config,
    "writer": writer_config,
}

__all__ = [
    "orchestrator_config", "ORCHESTRATOR_INSTRUCTION", "get_orchestrator_instruction",
    "process_analyst_config", "PROCESS_ANALYST_INSTRUCTION", "get_process_analyst_instruction",
    "compliance_advisor_config", "COMPLIANCE_ADVISOR_INSTRUCTION", "get_compliance_advisor_instruction", "ComplianceAdvisor",
    "writer_config", "WRITER_INSTRUCTION", "get_writer_instruction",
    "AGENT_CONFIGS",
    "AgentCommunicationBus",
    "create_process_analyst_responder",
    "create_compliance_advisor_responder",
]
