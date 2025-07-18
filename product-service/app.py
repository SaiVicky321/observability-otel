from flask import Flask, jsonify
import time
import logging
import os


from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource

# Tracing
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

# Logging
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggingHandler

# Instrumentation
# from opentelemetry.instrumentation.flask import FlaskInstrumentor # Removed for manual instrumentation example
# from opentelemetry.instrumentation.requests import RequestsInstrumentor # Not applicable for this service
from opentelemetry.instrumentation.logging import LoggingInstrumentor


# Context
from opentelemetry.trace import get_current_span, SpanKind
from opentelemetry.propagate import extract, inject # extract is important for incoming requests

# --- OpenTelemetry Setup ---
resource = Resource(attributes={
    "service.name": "product-service",
    "environment": "dev"
})

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer_provider().get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/traces"))
)

metrics.set_meter_provider(
    MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint="http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/metrics")
        )]
    )
)
meter = metrics.get_meter(__name__)
request_counter = meter.create_counter("http.server.request.count", unit="1", description="Request count")
request_latency = meter.create_histogram("http.server.request.duration", unit="s", description="Request latency")

# Logging setup
LoggingInstrumentor().instrument(set_logging_format=True)
logger = logging.getLogger("product-service") # Changed logger name for clarity
logging.basicConfig(level=logging.INFO)

# Set up OpenTelemetry logger provider
log_provider = LoggerProvider(resource=resource)
set_logger_provider(log_provider)

# Export logs to OTEL Collector
log_exporter = OTLPLogExporter(endpoint="http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/logs")
log_processor = BatchLogRecordProcessor(log_exporter)
log_provider.add_log_record_processor(log_processor)

# Bridge Python logging -> OpenTelemetry logs
otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
logging.getLogger().addHandler(otel_handler)

# --- Flask Setup ---
app = Flask(__name__)

PRODUCTS = [
    {"id": 1, "name": "Laptop", "price": 1000},
    {"id": 2, "name": "Phone", "price": 500},
]

@app.route("/products")
def get_products():
    start = time.time()
    # Extract context from incoming request headers
    carrier = request.headers
    ctx = extract(carrier)
    # Manually start a span for the incoming request
    with tracer.start_as_current_span("GET /products", context=ctx, kind=SpanKind.SERVER) as span:
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.target", "/products")
        try:
            logger.info("Fetched product list", extra={
                "http.method": "GET",
                "http.status_code": 200,
                "service.name": "product-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.OK))
            return jsonify(PRODUCTS)
        except Exception as e:
            logger.error("Error fetching products", exc_info=True, extra={
                "http.method": "GET",
                "http.status_code": 500,
                "error.message": str(e),
                "service.name": "product-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.ERROR, description=str(e)))
            return "Internal Server Error", 500
        finally:
            request_counter.add(1)
            request_latency.record(time.time() - start)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
