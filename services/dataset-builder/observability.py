"""
Shared OTel + Prometheus setup for Python FastAPI services.
Import and call setup_observability(app, service_name) before registering routes.
"""
import os
import logging

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from prometheus_fastapi_instrumentator import Instrumentator

log = logging.getLogger(__name__)

OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")


def setup_observability(app: FastAPI, service_name: str) -> None:
    """Wire OTel tracing + Prometheus /metrics into a FastAPI app."""
    # ── OTel tracing ────────────────────────────────────────────────
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=f"{OTEL_ENDPOINT}/v1/traces")
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    log.info(f"[{service_name}] OTel tracing → {OTEL_ENDPOINT}")

    # ── Prometheus /metrics ──────────────────────────────────────────
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        inprogress_name="alpaca_rl_http_requests_inprogress",
        inprogress_labels=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
    log.info(f"[{service_name}] Prometheus /metrics exposed")
