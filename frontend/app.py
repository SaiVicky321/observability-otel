from flask import Flask, render_template_string, request, redirect
import requests
import logging
import os
import time

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
from opentelemetry.instrumentation.requests import RequestsInstrumentor


# Context
from opentelemetry.trace import get_current_span



# Set up tracing resource
resource = Resource(attributes={
    "service.name": "frontend-service",
    "environment": "dev"
})

# Set up tracer
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer_provider().get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=f"http://{os.environ['NODE_IP']}:4318/v1/traces"))
)

# Set up metrics
metrics.set_meter_provider(
    MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"http://{os.environ['NODE_IP']}:4318/v1/metrics"))]
    )
)
meter = metrics.get_meter(__name__)
request_counter = meter.create_counter(
    name="http.server.request.count",
    unit="1",
    description="Counts number of incoming HTTP requests"
)
request_latency = meter.create_histogram(
    name="http.server.request.duration",
    unit="s",
    description="Tracks request durations"
)

# Logging setup
LoggingInstrumentor().instrument(set_logging_format=True)
logger = logging.getLogger("frontend")
logging.basicConfig(level=logging.INFO)

# Set up OpenTelemetry logger provider
log_provider = LoggerProvider(resource=resource)
set_logger_provider(log_provider)

# Export logs to OTEL Collector
log_exporter = OTLPLogExporter(endpoint=f"http://{os.environ['NODE_IP']}:4318/v1/logs")
log_processor = BatchLogRecordProcessor(log_exporter)  # ✅ Updated name
log_provider.add_log_record_processor(log_processor)   # ✅ method name also

# Bridge Python logging -> OpenTelemetry logs
otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
logging.getLogger().addHandler(otel_handler)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

TEMPLATE = """
<h1>Products</h1>
<ul>
{% for p in products %}
  <li>{{p['name']}} - ${{p['price']}}
    <form action="/add-to-cart" method="post" style="display:inline;">
      <input type="hidden" name="id" value="{{p['id']}}">
      <input type="hidden" name="name" value="{{p['name']}}">
      <input type="hidden" name="price" value="{{p['price']}}">
      <button type="submit">Add to Cart</button>
    </form>
  </li>
{% endfor %}
</ul>
<hr>
<h2>Cart</h2>
<ul>
{% for item in cart %}
  <li>{{item['name']}} - ${{item['price']}}</li>
{% endfor %}
</ul>
<form action="/place-order" method="post">
  <button type="submit">Place Order</button>
</form>
"""

@app.route("/", methods=["GET"])
def index():
    start_time = time.time()
    try:
      products = requests.get("http://product-service:5001/products").json()
      cart = requests.get("http://cart-service:5002/cart").json()
      logger.info("Loaded homepage", extra={
            "http.method": "GET",
            "http.status_code": 200,
            "trace_id": format(get_current_span().get_span_context().trace_id, 'x'),
            "span_id": format(get_current_span().get_span_context().span_id, 'x'),
            "service.name": "frontend-service",
            "environment": "dev"
        })
      return render_template_string(TEMPLATE, products=products, cart=cart)
    except Exception as e:
        logger.error("Error loading homepage", exc_info=True, extra={
            "http.method": "GET",
            "http.status_code": 500,
            "error.message": str(e),
            "trace_id": format(get_current_span().get_span_context().trace_id, 'x'),
            "span_id": format(get_current_span().get_span_context().span_id, 'x'),
            "service.name": "frontend-service",
            "environment": "dev"
        })
        return "Internal Server Error", 500
    finally:
        duration = time.time() - start_time
        request_latency.record(duration)
        request_counter.add(1)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    start_time = time.time()
    span = trace.get_current_span()
    try:
        item = {
            "id": request.form["id"],
            "name": request.form["name"],
            "price": request.form["price"],
        }
        response = requests.post("http://cart-service:5002/cart", json=item)
        response.raise_for_status()

        logger.info("Item added to cart", extra={
            "http.method": "POST",
            "http.status_code": response.status_code,
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "frontend-service",
            "environment": "dev"
        })
        return redirect("/")
    except Exception as e:
        logger.error("Error adding to cart", exc_info=True, extra={
            "http.method": "POST",
            "http.status_code": 500,
            "error.message": str(e),
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "frontend-service",
            "environment": "dev"
        })
        return "Internal Server Error", 500
    finally:
        request_latency.record(time.time() - start_time)
        request_counter.add(1)

@app.route("/place-order", methods=["POST"])
def place_order():
    start_time = time.time()
    span = trace.get_current_span()
    try:
        cart = requests.get("http://cart-service:5002/cart").json()
        response = requests.post("http://order-service:5003/orders", json=cart)
        response.raise_for_status()

        logger.info("Order placed", extra={
            "http.method": "POST",
            "http.status_code": response.status_code,
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "frontend-service",
            "environment": "dev"
        })
        return "Order placed! <a href='/'>Back</a>"
    except Exception as e:
        logger.error("Error placing order", exc_info=True, extra={
            "http.method": "POST",
            "http.status_code": 500,
            "error.message": str(e),
            "trace_id": format(span.get_span_context().trace_id, 'x'),
            "span_id": format(span.get_span_context().span_id, 'x'),
            "service.name": "frontend-service",
            "environment": "dev"
        })
        return "Internal Server Error", 500
    finally:
        request_latency.record(time.time() - start_time)
        request_counter.add(1)
        requests.delete("http://cart-service:5002/cart")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)