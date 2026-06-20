"""
OpenTelemetry export demo.

Shows how a VaP run is mirrored into OpenTelemetry spans (one trace per run).
This demo prints the spans to the console via OTel's ConsoleSpanExporter, so it
needs **no collector and no network** — you can see the exported trace directly.

To send the same spans to a real backend instead, swap the provider setup for an
OTLP exporter (or just call ``enable_otel_export(endpoint="http://localhost:4317")``
after configuring VaP):

    from vap.integrations.otel import enable_otel_export
    enable_otel_export(endpoint="http://localhost:4317")   # Jaeger / Tempo / Datadog …

Requirements:
    pip install "vap[otel]"

Run:
    python examples/otel_demo.py
"""
import time

import vap
from vap.store import MemoryStore


def main() -> None:
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
        from opentelemetry.sdk.resources import Resource
    except ImportError:
        raise SystemExit(
            "opentelemetry-sdk is not installed.\n"
            'Run: pip install "vap[otel]"'
        )

    from vap.integrations.otel import enable_otel_export

    # A console-printing OTel provider (stands in for an OTLP backend).
    provider = TracerProvider(resource=Resource.create({"service.name": "vap-demo"}))
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    # Trace into an isolated store and export every completed run to OTel.
    store = MemoryStore()
    tracer = vap.Tracer(store=store)
    handle = enable_otel_export(tracer_provider=provider, store=store)

    print("\n[vap] Running a traced agent — spans print below as the run completes:\n")
    with tracer.trace("Research agent") as run:
        with run.step("search_web", kind="tool") as step:
            step.set_input({"query": "renewable energy 2024"})
            time.sleep(0.05)
            step.set_output({"results": 3})

        with run.step("summarize", kind="step") as parent:
            parent.set_input({"results": 3})
            with run.step("ask_llm", kind="llm") as step:
                step.set_input({"model": "gpt-4o"})
                time.sleep(0.05)
                step.set_output({
                    "text": "Renewables grew sharply in 2024.",
                    "usage": {"input_tokens": 1200, "output_tokens": 180},
                    "cost_usd": 0.0048,
                })
            parent.set_output({"summary_ready": True})

    handle.shutdown()   # flush spans
    print(f"\n[vap] Done. The run above was exported as one OTel trace "
          f"(run_id={run.run_id}).")


if __name__ == "__main__":
    main()
