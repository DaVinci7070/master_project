FROM python:3.10-slim

# Systempakete – hier mit git
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates libgomp1 tini git \
 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 appuser
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app \
    UVICORN_HOST=0.0.0.0 UVICORN_PORT=8000

# Deps zuerst
COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# Code
COPY . .
RUN chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["sh","-c","uvicorn app.main:app --host ${UVICORN_HOST:-0.0.0.0} --port ${UVICORN_PORT:-8000}"]

