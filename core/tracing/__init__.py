"""
Core Tracing Module

Provides both in-memory and persistent tracing capabilities:
- TraceStore: In-memory trace storage (existing)
- VertexTraceManager: Persistent Vertex AI Trace integration (new)
"""

from .trace_store import TraceStore, set_tracer, get_tracer

# Import Vertex AI tracing only if available
try:
    from .vertex_trace import (
        VertexTraceManager,
        get_trace_manager,
        init_trace_manager,
        create_span,
    )
    VERTEX_TRACE_AVAILABLE = True
except ImportError:
    VERTEX_TRACE_AVAILABLE = False
    VertexTraceManager = None
    get_trace_manager = None
    init_trace_manager = None
    create_span = None

__all__ = [
    "TraceStore",
    "set_tracer",
    "get_tracer",
    "VertexTraceManager",
    "get_trace_manager",
    "init_trace_manager",
    "create_span",
    "VERTEX_TRACE_AVAILABLE",
]
