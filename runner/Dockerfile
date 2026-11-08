FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends docker.io iptables ca-certificates && rm -rf /var/lib/apt/lists/*
COPY runner/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY runner /app/runner
ENV PYTHONPATH=/app PORT=9000
EXPOSE 9000
CMD ["uvicorn", "runner.main:app", "--host", "0.0.0.0", "--port", "9000"]
