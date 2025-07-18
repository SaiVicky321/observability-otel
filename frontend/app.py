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
# from opentelemetry.instrumentation.flask import FlaskInstrumentor # Removed for manual instrumentation example
# from opentelemetry.instrumentation.requests import RequestsInstrumentor # Removed for manual instrumentation example
from opentelemetry.instrumentation.logging import LoggingInstrumentor


# Context
from opentelemetry.trace import get_current_span, SpanKind
from opentelemetry.propagate import inject

# Set up tracing resource
resource = Resource(attributes={
    "service.name": "frontend-service",
    "environment": "dev"
})

# Set up tracer
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer_provider().get_tracer(__name__)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint= "http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/traces"))
)

# Set up metrics
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
log_exporter = OTLPLogExporter(endpoint= "http://otlp-daemon-service.opentelemetry.svc.cluster.local:4318/v1/logs")
log_processor = BatchLogRecordProcessor(log_exporter)
log_provider.add_log_record_processor(log_processor)

# Bridge Python logging -> OpenTelemetry logs
otel_handler = LoggingHandler(level=logging.NOTSET, logger_provider=log_provider)
logging.getLogger().addHandler(otel_handler)

app = Flask(__name__)

# --- IMPORTANT: REMOVED AUTO-INSTRUMENTATION CALLS FOR MANUAL EXAMPLE ---
# FlaskInstrumentor().instrument_app(app)
# RequestsInstrumentor().instrument()
# -----------------------------------------------------------------------

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
    # Manually start a span for the incoming request
    # SpanKind.SERVER indicates this is an incoming request to the server
    with tracer.start_as_current_span("GET /", kind=SpanKind.SERVER) as span:
        # Add common HTTP attributes to the span
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.target", "/")

        try:
            # Manually create a child span for the product service request
            with tracer.start_as_current_span("get-products", kind=SpanKind.CLIENT) as product_span:
                headers = {}
                inject(headers) # Propagate trace context to outgoing request
                products = requests.get("http://product-service:5001/products", headers=headers).json()
                product_span.set_attribute("http.url", "http://product-service:5001/products")
                product_span.set_attribute("http.status_code", 200) # Assuming success

            # Manually create a child span for the cart service request
            with tracer.start_as_current_span("get-cart", kind=SpanKind.CLIENT) as cart_span:
                headers = {}
                inject(headers) # Propagate trace context to outgoing request
                cart = requests.get("http://cart-service:5002/cart", headers=headers).json()
                cart_span.set_attribute("http.url", "http://cart-service:5002/cart")
                cart_span.set_attribute("http.status_code", 200) # Assuming success

            logger.info("Loaded homepage", extra={
                "http.method": "GET",
                "http.status_code": 200,
                "service.name": "frontend-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.OK)) # Set span status to OK
            return render_template_string(TEMPLATE, products=products, cart=cart)
        except Exception as e:
            logger.error("Error loading homepage", exc_info=True, extra={
                "http.method": "GET",
                "http.status_code": 500,
                "error.message": str(e),
                "service.name": "frontend-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.ERROR, description=str(e))) # Set span status to ERROR
            return "Internal Server Error", 500
        finally:
            duration = time.time() - start_time
            request_latency.record(duration)
            request_counter.add(1)

@app.route("/add-to-cart", methods=["POST"])
def add_to_cart():
    start_time = time.time()
    # Manually start a span for the incoming request
    with tracer.start_as_current_span("POST /add-to-cart", kind=SpanKind.SERVER) as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.target", "/add-to-cart")
        try:
            item = {
                "id": request.form["id"],
                "name": request.form["name"],
                "price": request.form["price"],
            }
            # Manually create a child span for the cart service request
            with tracer.start_as_current_span("add-to-cart-service", kind=SpanKind.CLIENT) as cart_span:
                headers = {}
                inject(headers) # Propagate trace context to outgoing request
                response = requests.post("http://cart-service:5002/cart", json=item, headers=headers)
                response.raise_for_status()
                cart_span.set_attribute("http.url", "http://cart-service:5002/cart")
                cart_span.set_attribute("http.status_code", response.status_code)

            logger.info("Item added to cart", extra={
                "http.method": "POST",
                "http.status_code": response.status_code,
                "service.name": "frontend-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.OK))
            return redirect("/")
        except Exception as e:
            logger.error("Error adding to cart", exc_info=True, extra={
                "http.method": "POST",
                "http.status_code": 500,
                "error.message": str(e),
                "service.name": "frontend-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.ERROR, description=str(e)))
            return "Internal Server Error", 500
        finally:
            request_latency.record(time.time() - start_time)
            request_counter.add(1)

@app.route("/place-order", methods=["POST"])
def place_order():
    start_time = time.time()
    # Manually start a span for the incoming request
    with tracer.start_as_current_span("POST /place-order", kind=SpanKind.SERVER) as span:
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.target", "/place-order")
        try:
            # Manually create a child span for getting cart
            with tracer.start_as_current_span("get-cart-for-order", kind=SpanKind.CLIENT) as get_cart_span:
                headers = {}
                inject(headers)
                cart = requests.get("http://cart-service:5002/cart", headers=headers).json()
                get_cart_span.set_attribute("http.url", "http://cart-service:5002/cart")
                get_cart_span.set_attribute("http.status_code", 200) # Assuming success

            # Manually create a child span for placing order
            with tracer.start_as_current_span("place-order-service", kind=SpanKind.CLIENT) as order_span:
                headers = {}
                inject(headers)
                response = requests.post("http://order-service:5003/orders", json=cart, headers=headers)
                response.raise_for_status()
                order_span.set_attribute("http.url", "http://order-service:5003/orders")
                order_span.set_attribute("http.status_code", response.status_code)

            # Manually create a child span for clearing cart
            with tracer.start_as_current_span("clear-cart-service", kind=SpanKind.CLIENT) as clear_cart_span:
                headers = {}
                inject(headers)
                clear_cart_response = requests.delete("http://cart-service:5002/cart", headers=headers)
                clear_cart_response.raise_for_status()
                clear_cart_span.set_attribute("http.url", "http://cart-service:5002/cart")
                clear_cart_span.set_attribute("http.status_code", clear_cart_response.status_code)


            logger.info("Order placed", extra={
                "http.method": "POST",
                "http.status_code": response.status_code,
                "service.name": "frontend-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.OK))
            return "Order placed! <a href='/'>Back</a>"
        except Exception as e:
            logger.error("Error placing order", exc_info=True, extra={
                "http.method": "POST",
                "http.status_code": 500,
                "error.message": str(e),
                "service.name": "frontend-service",
                "environment": "dev"
            })
            span.set_status(trace.Status(trace.StatusCode.ERROR, description=str(e)))
            return "Internal Server Error", 500
        finally:
            request_latency.record(time.time() - start_time)
            request_counter.add(1)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
