"""
OpenTelemetry export for VaP.

Turns each completed VaP run into an OpenTelemetry trace — one trace per run,
with every node (agent / step / tool / LLM) becoming a span whose parent is the
node's parent. Node start/end times, token usage, USD cost, and error status are
carried as span timings, attributes, and status. The spans flow through whatever
OTLP backend you configure (Jaeger, Grafana Tempo, Datadog, …).

Quick start — auto-export every run to an OTLP collector::

    import vap
    from vap.integrations.otel import enable_otel_export

    vap.configure(db="vap.db")
    enable_otel_export(endpoint="http://localhost:4317")   # OTLP/gRPC

    with vap.trace("My agent") as run:
        ...                                                # exported on completion

Send into an OpenTelemetry stack you've already configured globally::

    enable_otel_export()           # uses the global TracerProvider

Or export a single run on demand::

    from vap.integrations.otel import export_run
    export_run(store.get_graph(run_id), tracer_provider=my_provider)

Requirements
------------
    pip install "vap[otel]"
"""
from __future__ import annotations

from typing import Any, Optional

from ..events import EventType, NodeKind, NodeStatus, RunGraph

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import Status, StatusCode, set_span_in_context

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dep
    _OTEL_AVAILABLE = False


_INSTRUMENTATION_NAME = "vap"
_MAX_ATTR_LEN = 1000


# ---------------------------------------------------------------------------
# Span construction
# ---------------------------------------------------------------------------


def _ns(ts: Optional[float], fallback: Optional[float] = None) -> Optional[int]:
    """Convert epoch seconds (float) to integer nanoseconds for OTel."""
    if ts is None:
        ts = fallback
    if ts is None:
        return None
    return int(ts * 1_000_000_000)


def _node_attributes(node, run_id: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "vap.run_id": run_id,
        "vap.node.kind": node.kind.value,
        "vap.node.status": node.status.value,
        "vap.node.label": node.label,
    }

    data = node.data if isinstance(node.data, dict) else {}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}

    # GenAI semantic conventions for LLM nodes
    if node.kind == NodeKind.LLM:
        model = None
        inp = data.get("input")
        if isinstance(inp, dict):
            model = inp.get("model")
        if not model and node.label.startswith("llm/"):
            model = node.label[4:]
        if model:
            attrs["gen_ai.request.model"] = str(model)

        usage = output.get("usage") if isinstance(output, dict) else None
        if isinstance(usage, dict):
            if usage.get("input_tokens") is not None:
                attrs["gen_ai.usage.input_tokens"] = int(usage["input_tokens"])
            if usage.get("output_tokens") is not None:
                attrs["gen_ai.usage.output_tokens"] = int(usage["output_tokens"])

    cost = output.get("cost_usd") if isinstance(output, dict) else None
    if isinstance(cost, (int, float)):
        attrs["vap.cost_usd"] = float(cost)

    # Compact, bounded input/output snapshots for debugging
    if data.get("input") is not None:
        attrs["vap.input"] = _stringify(data.get("input"))
    if data.get("output") is not None:
        attrs["vap.output"] = _stringify(data.get("output"))

    return attrs


def build_spans(graph: RunGraph, tracer) -> int:
    """Emit OpenTelemetry spans for every node in *graph*.

    Returns the number of spans created. Spans are created parent-first with
    explicit start/end times, so the resulting trace mirrors the VaP graph
    exactly (one trace per run).
    """
    children: dict[Optional[str], list] = {}
    for node in graph.nodes:
        children.setdefault(node.parent_id, []).append(node)

    # Nodes whose parent is absent from the graph are treated as roots.
    node_ids = {n.id for n in graph.nodes}
    roots = [n for n in graph.nodes if n.parent_id is None or n.parent_id not in node_ids]

    # End time fallback: the run's end, else the latest node end we can see.
    run_end = graph.ended_at

    count = 0

    def emit(node, parent_ctx) -> None:
        nonlocal count
        start = _ns(node.started_at, fallback=graph.started_at)
        span = tracer.start_span(
            node.label,
            context=parent_ctx,
            start_time=start,
        )
        for key, value in _node_attributes(node, graph.run_id).items():
            span.set_attribute(key, value)

        if node.status == NodeStatus.ERROR:
            err = node.data.get("error") if isinstance(node.data, dict) else None
            span.set_status(Status(StatusCode.ERROR, _stringify(err) if err else "error"))
        else:
            span.set_status(Status(StatusCode.OK))

        count += 1
        child_ctx = set_span_in_context(span, parent_ctx)
        for child in children.get(node.id, []):
            emit(child, child_ctx)

        end = _ns(node.ended_at, fallback=run_end if run_end is not None else node.started_at)
        span.end(end_time=end)

    for root in roots:
        emit(root, None)

    return count


def export_run(
    graph: Optional[RunGraph],
    *,
    tracer=None,
    tracer_provider=None,
) -> int:
    """Export a single run graph as an OpenTelemetry trace.

    Pass an explicit *tracer* or *tracer_provider*, otherwise the global
    OpenTelemetry ``TracerProvider`` is used. Returns the number of spans
    created (``0`` if *graph* is ``None``).
    """
    if not _OTEL_AVAILABLE:
        raise ImportError(
            "opentelemetry-sdk is required for OTel export. "
            'Install it with: pip install "vap[otel]"'
        )
    if graph is None:
        return 0
    if tracer is None:
        if tracer_provider is not None:
            tracer = tracer_provider.get_tracer(_INSTRUMENTATION_NAME)
        else:
            tracer = _otel_trace.get_tracer(_INSTRUMENTATION_NAME)
    return build_spans(graph, tracer)


# ---------------------------------------------------------------------------
# Auto-export: wrap a store to export each run when it completes
# ---------------------------------------------------------------------------


class OtelExportHandle:
    """Returned by :func:`enable_otel_export`. Call :meth:`disable` to stop."""

    def __init__(self, store, original_add_event, tracer_provider) -> None:
        self._store = store
        self._original = original_add_event
        self.tracer_provider = tracer_provider

    def disable(self) -> None:
        """Restore the store's original ``add_event``."""
        try:
            del self._store.add_event          # remove the instance override
        except AttributeError:
            self._store.add_event = self._original

    def shutdown(self) -> None:
        """Disable export and flush/shut down the tracer provider (if owned)."""
        self.disable()
        flush = getattr(self.tracer_provider, "force_flush", None)
        if callable(flush):
            try:
                flush()
            except Exception:  # noqa: BLE001
                pass


def enable_otel_export(
    *,
    tracer_provider=None,
    endpoint: Optional[str] = None,
    protocol: str = "grpc",
    service_name: str = "vap",
    insecure: bool = True,
    store=None,
) -> OtelExportHandle:
    """Export every completed VaP run as an OpenTelemetry trace.

    Wraps the store's ``add_event`` so that when a run's ``agent_end`` event is
    recorded, the full run graph is emitted as spans.

    Parameters
    ----------
    tracer_provider:
        Use this provider. If ``None`` and *endpoint* is given, a provider with
        an OTLP exporter is created; if both are ``None``, the global provider
        is used (wire VaP into an OpenTelemetry stack you've already set up).
    endpoint:
        OTLP collector endpoint, e.g. ``"http://localhost:4317"`` (gRPC) or
        ``"http://localhost:4318/v1/traces"`` (HTTP).
    protocol:
        ``"grpc"`` (default) or ``"http"`` — selects the OTLP exporter.
    service_name:
        ``service.name`` resource attribute when a provider is created here.
    insecure:
        For gRPC, whether to use an insecure channel (default ``True``).
    store:
        Store to wrap. Defaults to ``vap.store.default_store``.
    """
    if not _OTEL_AVAILABLE:
        raise ImportError(
            "opentelemetry-sdk is required for OTel export. "
            'Install it with: pip install "vap[otel]"'
        )

    if tracer_provider is not None:
        provider = tracer_provider
    elif endpoint is not None:
        provider = _build_provider(endpoint, protocol, service_name, insecure)
    else:
        provider = _otel_trace.get_tracer_provider()

    tracer = provider.get_tracer(_INSTRUMENTATION_NAME)

    import vap.store as _sm

    target = store if store is not None else _sm.default_store
    original = target.add_event

    def wrapped(event) -> None:
        original(event)
        if event.type == EventType.AGENT_END:
            try:
                graph = target.get_graph(event.run_id)
                build_spans(graph, tracer) if graph is not None else None
            except Exception:  # noqa: BLE001 - export is best-effort
                pass

    target.add_event = wrapped  # instance-level override
    return OtelExportHandle(target, original, provider)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_provider(endpoint: str, protocol: str, service_name: str, insecure: bool):
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(_make_otlp_exporter(endpoint, protocol, insecure)))
    return provider


def _make_otlp_exporter(endpoint: str, protocol: str, insecure: bool):
    if protocol == "http":
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "The OTLP HTTP exporter is required. Install it with: "
                'pip install "vap[otel]"'
            ) from exc
        return OTLPSpanExporter(endpoint=endpoint)

    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "The OTLP gRPC exporter is required. Install it with: "
            'pip install "vap[otel]"'
        ) from exc
    return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            import json

            text = json.dumps(value, default=str)
        except Exception:  # noqa: BLE001
            text = str(value)
    return text if len(text) <= _MAX_ATTR_LEN else text[:_MAX_ATTR_LEN] + "…"
