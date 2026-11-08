FROM python:3.11-slim

WORKDIR /app

# Install docker CLI so runner can control host docker daemon via mounted /var/run/docker.sock
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh \
    && rm -rf /var/lib/apt/lists/* get-docker.sh

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/runner

ENV PYTHONPATH=/app \
    PORT=9000

EXPOSE 9000

CMD ["uvicorn", "runner.main:app", "--host", "0.0.0.0", "--port", "9000"]

