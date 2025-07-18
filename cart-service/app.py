from flask import Flask, request, jsonify
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
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor


# Context
from opentelemetry.trace import get_current_span

# Resource attributes for logs/metrics/traces
resource = Resource(attributes={
    "service.name": "cart-service",
    "environment": "dev"
})

# Tracer setup
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer_provider().get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/traces"))
)

# Metrics setup
metrics.set_meter_provider(
    MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint="http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/metrics"))]
    )
)
meter = metrics.get_meter(__name__)
request_counter = meter.create_counter(
    name="http.server.request.count",
    unit="1",
    description="Total number of HTTP requests"
)
request_latency = meter.create_histogram(
    name="http.server.request.duration",
    unit="s",
    description="HTTP request duration"
)

# Logging setup
LoggingInstrumentor().instrument(set_logging_format=True)
logger = logging.getLogger("frontend")
logging.basicConfig(level=logging.INFO)

# Set up OpenTelemetry logger provider
log_provider = LoggerProvider(resource=resource)
set_logger_provider(log_provider)

# Export logs to OTEL Collector
log_exporter = OTLPLogExporter(endpoint="http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/logs")
# log_processor = BatchLogProcessor(log_exporter)
# log_provider.add_log_processor(log_processor)
log_processor = BatchLogRecordProcessor(log_exporter)  # ✅ Updated name
log_provider.add_log_record_processor(log_processor)   # ✅ method name also

# Bridge Python logging -> OpenTelemetry logs
otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
logging.getLogger().addHandler(otel_handler)

# Flask app
app = Flask(__name__)

# In-memory cart store
CART = []

@app.route("/cart", methods=["GET"])
def get_cart():
    start_time = time.time()
    span = get_current_span()
    try:
        logger.info("Fetching cart contents", extra={
            "http.method": "GET",
            "http.status_code": 200,
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "cart-service",
            "environment": "dev"
        })
        return jsonify(CART)
    except Exception as e:
        logger.error("Failed to fetch cart", exc_info=True, extra={
            "http.method": "GET",
            "http.status_code": 500,
            "error.message": str(e),
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "cart-service",
            "environment": "dev"
        })
        return "Internal Server Error", 500
    finally:
        request_counter.add(1)
        request_latency.record(time.time() - start_time)

@app.route("/cart", methods=["POST"])
def add_to_cart():
    start_time = time.time()
    span = get_current_span()
    try:
        item = request.json
        CART.append(item)
        logger.info("Added item to cart", extra={
            "http.method": "POST",
            "http.status_code": 201,
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "cart-service",
            "environment": "dev"
        })
        return jsonify({"message": "Added to cart"}), 201
    except Exception as e:
        logger.error("Failed to add to cart", exc_info=True, extra={
            "http.method": "POST",
            "http.status_code": 500,
            "error.message": str(e),
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "cart-service",
            "environment": "dev"
        })
        return "Internal Server Error", 500
    finally:
        request_counter.add(1)
        request_latency.record(time.time() - start_time)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002)