FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
#RUN opentelemetry-bootstrap --action=install
COPY . .
#CMD ["opentelemetry-instrument", "python", "app.py"]
CMD ["python", "app.py"]