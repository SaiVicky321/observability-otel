from flask import Flask, jsonify
import time
import logging
import os
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.trace import get_current_span
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

# --- OpenTelemetry Setup ---
resource = Resource(attributes={
    "service.name": "product-service",
    "environment": "dev"
})

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer_provider().get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"http://{os.environ['NODE_IP']}:4318/v1/traces"))
)

metrics.set_meter_provider(
    MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"http://{os.environ['NODE_IP']}:4318/v1/metrics")
        )]
    )
)
meter = metrics.get_meter(__name__)
request_counter = meter.create_counter("http.server.request.count", unit="1", description="Request count")
request_latency = meter.create_histogram("http.server.request.duration", unit="s", description="Request latency")

# Logging setup
LoggingInstrumentor().instrument(set_logging_format=True)
logger = logging.getLogger("frontend")
logging.basicConfig(level=logging.INFO)

# Set up OpenTelemetry logger provider
log_provider = LoggerProvider(resource=resource)
set_logger_provider(log_provider)

# Export logs to OTEL Collector
log_exporter = OTLPLogExporter(endpoint=f"http://{os.environ['NODE_IP']}:4318/v1/logs")
log_processor = BatchLogProcessor(log_exporter)
log_provider.add_log_processor(log_processor)

# Bridge Python logging -> OpenTelemetry logs
otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
logging.getLogger().addHandler(otel_handler)

# --- Flask Setup ---
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

PRODUCTS = [
    {"id": 1, "name": "Laptop", "price": 1000},
    {"id": 2, "name": "Phone", "price": 500},
]

@app.route("/products")
def get_products():
    start = time.time()
    span = get_current_span()
    try:
        logger.info("Fetched product list", extra={
            "http.method": "GET",
            "http.status_code": 200,
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "product-service",
            "environment": "dev"
        })
        return jsonify(PRODUCTS)
    except Exception as e:
        logger.error("Error fetching products", exc_info=True, extra={
            "http.method": "GET",
            "http.status_code": 500,
            "error.message": str(e),
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "product-service",
            "environment": "dev"
        })
        return "Internal Server Error", 500
    finally:
        request_counter.add(1)
        request_latency.record(time.time() - start)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)