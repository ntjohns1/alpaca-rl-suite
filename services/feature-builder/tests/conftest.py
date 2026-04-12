"""
Conftest for feature-builder unit tests.
Stubs out observability dependencies (opentelemetry, prometheus) so tests
can import main.py without those heavy packages installed locally.
"""
import sys
import types


def _stub_observability():
    """Install lightweight module stubs so `from observability import ...` succeeds."""
    for mod_name in [
        "opentelemetry",
        "opentelemetry.trace",
        "opentelemetry.sdk",
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.trace.export",
        "opentelemetry.sdk.resources",
        "opentelemetry.exporter",
        "opentelemetry.exporter.otlp",
        "opentelemetry.exporter.otlp.proto",
        "opentelemetry.exporter.otlp.proto.http",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "prometheus_client",
        "prometheus_fastapi_instrumentator",
    ]:
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            # Provide the minimal attributes observability.py expects
            stub.TracerProvider = lambda **kw: type("TP", (), {"add_span_processor": lambda s, p: None})()
            stub.BatchSpanProcessor = lambda e: None
            stub.OTLPSpanExporter = lambda **kw: None
            stub.Resource = type("R", (), {"create": staticmethod(lambda d: None)})
            stub.SERVICE_NAME = "service.name"
            stub.trace = type("T", (), {"set_tracer_provider": staticmethod(lambda p: None)})()

            class _FakeInstrumentator:
                def __init__(self, **kw):
                    pass
                def instrument(self, app):
                    return self
                def expose(self, app, **kw):
                    return self

            stub.Instrumentator = _FakeInstrumentator
            sys.modules[mod_name] = stub


_stub_observability()
