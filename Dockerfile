# AgentForge API_Service image.
FROM python:3.11-slim

# System deps kept minimal; sentence-transformers/pypdf are pure-python wheels.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
COPY migrations ./migrations

RUN pip install --upgrade pip && pip install .

EXPOSE 8000

# API_Service listens on the documented port (overridable via API_PORT env).
CMD ["sh", "-c", "uvicorn agentforge.main:app --host 0.0.0.0 --port ${API_PORT:-8000}"]
