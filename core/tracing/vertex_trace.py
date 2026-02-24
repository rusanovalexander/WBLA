"""
Vertex AI Trace Integration

Provides persistent trace logging to Google Cloud's Vertex AI Trace API.
Traces are stored in Cloud Trace and can be viewed in the Google Cloud Console.

Key features:
- Persistent trace storage (survives session restarts)
- Hierarchical span structure (trace → spans → sub-spans)
- Automatic LLM call logging with token counts
- Context manager for easy span management
- Singleton pattern for session-wide trace coordination

Usage:
    from core.tracing.vertex_trace import get_trace_manager, create_span

    # Start a new trace
    trace_manager = get_trace_manager()
    trace_id = trace_manager.start_trace("DocumentAnalysis")

    # Create spans with context manager
    with create_span("ProcessTeaser") as span_id:
        result = some_llm_call()
        trace_manager.record_llm_call(span_id, model="gemini-2.5-pro", tokens=1500)

    # End trace when workflow completes
    trace_manager.end_trace()
"""

import logging
import time
from typing import Optional, Dict, Any
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from google.cloud import trace_v1
    from google.cloud.trace_v1 import TraceServiceClient
    VERTEX_TRACE_AVAILABLE = True
except ImportError:
    logger.warning("google-cloud-trace not installed. Vertex AI Trace disabled.")
    VERTEX_TRACE_AVAILABLE = False


class VertexTraceManager:
    """
    Manages Vertex AI Trace lifecycle for a single workflow session.

    Traces have a hierarchical structure:
    - Trace (workflow-level, e.g., "CreditPackDrafting_20260211_143052")
      - Span (phase-level, e.g., "ANALYSIS_Phase")
        - Sub-span (agent-level, e.g., "ProcessAnalyst_ExtractData")
          - Sub-sub-span (LLM call-level, e.g., "LLM_call_gemini-2.5-pro")
    """

    def __init__(self, project_id: str, enabled: bool = True):
        """
        Initialize the trace manager.

        Args:
            project_id: Google Cloud project ID
            enabled: Whether tracing is enabled (can disable for local dev)
        """
        self.project_id = project_id
        self.enabled = enabled and VERTEX_TRACE_AVAILABLE
        self.trace_id: Optional[str] = None
        self.current_trace_name: Optional[str] = None
        self.span_stack: list[str] = []  # Stack of active span IDs
        self.span_metadata: Dict[str, Dict[str, Any]] = {}  # span_id -> metadata

        if self.enabled:
            try:
                self.client = TraceServiceClient()
                logger.info("Vertex AI Trace client initialized for project: %s", project_id)
            except Exception as e:
                logger.error("Failed to initialize Vertex AI Trace client: %s", e)
                self.enabled = False
                self.client = None
        else:
            self.client = None
            if not VERTEX_TRACE_AVAILABLE:
                logger.info("Vertex AI Trace disabled (library not available)")
            else:
                logger.info("Vertex AI Trace disabled by configuration")

    def start_trace(self, trace_name: str) -> Optional[str]:
        """
        Start a new trace for this workflow session.

        Args:
            trace_name: Human-readable trace name (e.g., "CreditPackDrafting")

        Returns:
            trace_id if successful, None if tracing disabled
        """
        if not self.enabled or not self.client:
            return None

        try:
            # Generate trace ID: "projects/{project_id}/traces/{trace_hex}"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            trace_hex = f"{trace_name}_{timestamp}".replace(" ", "_")
            self.trace_id = f"projects/{self.project_id}/traces/{trace_hex}"
            self.current_trace_name = trace_name
            self.span_stack = []
            self.span_metadata = {}

            logger.info("Started Vertex AI Trace: %s", self.trace_id)
            return self.trace_id

        except Exception as e:
            logger.error("Failed to start trace: %s", e)
            return None

    def create_span(
        self,
        span_name: str,
        parent_span_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Create a new span within the current trace.

        Args:
            span_name: Human-readable span name (e.g., "ANALYSIS_Phase")
            parent_span_id: Parent span ID (None = root span)
            metadata: Optional metadata to attach to span

        Returns:
            span_id if successful, None if tracing disabled
        """
        if not self.enabled or not self.trace_id or not self.client:
            return None

        try:
            # Generate span ID
            span_id = f"{self.trace_id}/spans/{span_name}_{int(time.time() * 1000)}"

            # Build span object
            span = trace_v1.Span(
                name=span_id,
                display_name=trace_v1.TruncatableString(value=span_name),
                start_time=self._current_timestamp(),
            )

            # Set parent if provided
            if parent_span_id:
                span.parent_span_id = parent_span_id
            elif self.span_stack:
                # Auto-parent to current active span
                span.parent_span_id = self.span_stack[-1]

            # Store metadata
            if metadata:
                self.span_metadata[span_id] = metadata

            # Send to Vertex AI Trace
            project_name = f"projects/{self.project_id}"
            self.client.batch_write_spans(
                name=project_name,
                spans=[span]
            )

            logger.debug("Created span: %s (parent: %s)", span_name, parent_span_id or "root")
            return span_id

        except Exception as e:
            logger.error("Failed to create span '%s': %s", span_name, e)
            return None

    def end_span(self, span_id: str, status: str = "OK", metadata: Optional[Dict[str, Any]] = None):
        """
        End a span and send final metadata to Vertex AI.

        Args:
            span_id: Span ID to end
            status: Status code (OK, ERROR, CANCELLED)
            metadata: Final metadata to attach
        """
        if not self.enabled or not self.client or not span_id:
            return

        try:
            # Build final span with end time
            span = trace_v1.Span(
                name=span_id,
                end_time=self._current_timestamp(),
            )

            # Merge metadata
            final_metadata = self.span_metadata.get(span_id, {})
            if metadata:
                final_metadata.update(metadata)

            # Add status
            final_metadata["status"] = status

            # Convert metadata to span attributes (Vertex AI Trace format)
            if final_metadata:
                span.attributes = trace_v1.Span.Attributes(
                    attribute_map={
                        k: trace_v1.AttributeValue(string_value=trace_v1.TruncatableString(value=str(v)))
                        for k, v in final_metadata.items()
                    }
                )

            # Send to Vertex AI
            project_name = f"projects/{self.project_id}"
            self.client.batch_write_spans(
                name=project_name,
                spans=[span]
            )

            logger.debug("Ended span: %s (status: %s)", span_id, status)

        except Exception as e:
            logger.error("Failed to end span '%s': %s", span_id, e)

    def record_llm_call(
        self,
        span_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        thinking_tokens: int = 0,
        success: bool = True
    ):
        """
        Record LLM call metadata to the current span.

        Args:
            span_id: Span ID to attach metadata to
            model: Model name (e.g., "gemini-2.5-pro")
            prompt_tokens: Input token count
            completion_tokens: Output token count
            latency_ms: Call duration in milliseconds
            thinking_tokens: Extended thinking token count (if applicable)
            success: Whether call succeeded
        """
        if not self.enabled or not span_id:
            return

        metadata = {
            "model": model,
            "prompt_tokens": str(prompt_tokens),
            "completion_tokens": str(completion_tokens),
            "total_tokens": str(prompt_tokens + completion_tokens),
            "latency_ms": str(int(latency_ms)),
            "success": str(success),
        }

        if thinking_tokens > 0:
            metadata["thinking_tokens"] = str(thinking_tokens)

        # Merge with existing metadata
        if span_id in self.span_metadata:
            self.span_metadata[span_id].update(metadata)
        else:
            self.span_metadata[span_id] = metadata

    def end_trace(self):
        """End the current trace and clean up resources."""
        if not self.enabled or not self.trace_id:
            return

        logger.info("Ended Vertex AI Trace: %s", self.trace_id)
        self.trace_id = None
        self.current_trace_name = None
        self.span_stack = []
        self.span_metadata = {}

    def _current_timestamp(self):
        """Get current timestamp in Vertex AI Trace format."""
        from google.protobuf.timestamp_pb2 import Timestamp
        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        return timestamp

    @contextmanager
    def span_context(self, span_name: str, metadata: Optional[Dict[str, Any]] = None):
        """
        Context manager for automatic span lifecycle management.

        Usage:
            with trace_manager.span_context("MyOperation") as span_id:
                do_work()
        """
        span_id = self.create_span(span_name, metadata=metadata)
        if span_id:
            self.span_stack.append(span_id)

        try:
            yield span_id
        except Exception as e:
            if span_id:
                self.end_span(span_id, status="ERROR", metadata={"error": str(e)})
            raise
        finally:
            if span_id:
                self.end_span(span_id, status="OK")
                self.span_stack.pop()


# Singleton instance
_trace_manager: Optional[VertexTraceManager] = None


def get_trace_manager() -> Optional[VertexTraceManager]:
    """
    Get the singleton trace manager instance.

    Returns None if tracing is disabled or not initialized.
    """
    return _trace_manager


def init_trace_manager(project_id: str, enabled: bool = True) -> VertexTraceManager:
    """
    Initialize the singleton trace manager.

    Args:
        project_id: Google Cloud project ID
        enabled: Whether tracing is enabled

    Returns:
        Initialized trace manager
    """
    global _trace_manager
    _trace_manager = VertexTraceManager(project_id, enabled)
    return _trace_manager


def create_span(span_name: str, metadata: Optional[Dict[str, Any]] = None):
    """
    Convenience function for creating spans with context manager.

    Usage:
        with create_span("MyOperation") as span_id:
            do_work()
    """
    manager = get_trace_manager()
    if manager:
        return manager.span_context(span_name, metadata)
    else:
        # No-op context manager when tracing disabled
        from contextlib import nullcontext
        return nullcontext()
