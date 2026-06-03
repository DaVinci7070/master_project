import logging
from typing import Optional, Tuple

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace import Span, SpanKind
from fastapi import FastAPI, Request

log = logging.getLogger(__name__)

MIDDLEWARE_VERSION = "1.0.0"


def _server_request_hook(span: Span, scope: dict) -> None:
    """
    Hook called when a server request starts.

    Adds custom attributes to the span for request tracking.

    Args:
        span: The OpenTelemetry span for this request.
        scope: ASGI scope dictionary containing request info.
    """
    if span and span.is_recording():
        if "path" in scope:
            span.set_attribute("http.target", scope.get("path", ""))
        if "method" in scope:
            span.set_attribute("http.method", scope.get("method", ""))

        if "client" in scope and scope["client"]:
            client_host = scope["client"][0] if scope["client"] else None
            if client_host:
                span.set_attribute("net.peer.ip", client_host)


def _client_request_hook(span: Span, scope: dict) -> None:
    """
    Hook called for client requests (outgoing HTTP calls).

    Adds tracking for external service calls.

    Args:
        span: The OpenTelemetry span for this request.
        scope: Request scope dictionary.
    """
    if span and span.is_recording():
        span.set_attribute("http.client", True)


def _client_response_hook(span: Span, message: dict) -> None:
    """
    Hook called when a client response is received.

    Captures response metadata for external calls.

    Args:
        span: The OpenTelemetry span for this request.
        message: Response message dictionary.
    """
    if span and span.is_recording():
        pass


def setup_telemetry(
    app: FastAPI,
    service_name: str = "lumari-backend",
    service_version: str = "0.1.0",
    enable_console_export: bool = True,
    otlp_endpoint: Optional[str] = None,
) -> TracerProvider:
    """
    Set up OpenTelemetry instrumentation for a FastAPI application.

    This function configures:
    1. TracerProvider with service resource identification
    2. Span exporters (console for dev, OTLP for production)
    3. FastAPI automatic instrumentation with custom hooks

    Args:
        app: FastAPI application to instrument.
        service_name: Name identifying this service in traces.
        service_version: Version of the service.
        enable_console_export: Whether to export spans to console (dev mode).
        otlp_endpoint: Optional OTLP collector endpoint for production.

    Returns:
        TracerProvider for shutdown management.

    Example:
        provider = setup_telemetry(app, service_name="my-service")
        # ... app lifecycle ...
        shutdown_telemetry(provider)
    """
    log.info(f"Setting up OpenTelemetry for {service_name} v{service_version}")

    resource = Resource.create({
        SERVICE_NAME: service_name,
        SERVICE_VERSION: service_version,
        "service.namespace": "lumari",
        "deployment.environment": "development",
        "telemetry.sdk.name": "opentelemetry",
        "telemetry.middleware.version": MIDDLEWARE_VERSION,
    })

    provider = TracerProvider(resource=resource)

    if enable_console_export:
        console_processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(console_processor)
        log.info("Console span exporter enabled")

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            otlp_processor = BatchSpanProcessor(otlp_exporter)
            provider.add_span_processor(otlp_processor)
            log.info(f"OTLP exporter configured for {otlp_endpoint}")
        except ImportError:
            log.warning(
                "OTLP exporter requested but opentelemetry-exporter-otlp not installed"
            )
        except Exception as e:
            log.error(f"Failed to configure OTLP exporter: {e}")

    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(
        app,
        server_request_hook=_server_request_hook,
        client_request_hook=_client_request_hook,
        client_response_hook=_client_response_hook,
    )

    log.info("FastAPI instrumentation complete")

    return provider


def shutdown_telemetry(provider: Optional[TracerProvider]) -> None:
    """
    Gracefully shutdown telemetry provider.

    This flushes any pending spans and shuts down processors.
    Should be called during application shutdown.

    Args:
        provider: TracerProvider to shutdown, or None to skip.

    Example:
        # In FastAPI lifespan:
        async def lifespan(app: FastAPI):
            provider = setup_telemetry(app)
            yield
            shutdown_telemetry(provider)
    """
    if provider is None:
        log.debug("No telemetry provider to shutdown")
        return

    log.info("Shutting down OpenTelemetry provider")
    try:
        provider.shutdown()
        log.info("OpenTelemetry provider shutdown complete")
    except Exception as e:
        log.error(f"Error during telemetry shutdown: {e}")


def get_current_trace_context() -> Tuple[Optional[str], Optional[str]]:
    """
    Get current OpenTelemetry trace and span IDs.

    Useful for correlating logs with traces.

    Returns:
        Tuple of (trace_id, span_id) as hex strings, or (None, None) if
        no active span.

    Example:
        trace_id, span_id = get_current_trace_context()
        log.info(f"Processing request", extra={
            "trace_id": trace_id,
            "span_id": span_id
        })
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        span_context = current_span.get_span_context()
        if span_context.is_valid:
            return (
                format(span_context.trace_id, '032x'),
                format(span_context.span_id, '016x'),
            )
    return None, None
