# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

# Layer 1: AR keyring auth for private packages (rarely changes — cached)
RUN pip install --no-cache-dir keyrings.google-artifactregistry-auth

# Layer 2: Dependencies (changes only when requirements.txt changes — cached by Kaniko)
COPY requirements.txt ./
ENV PIP_EXTRA_INDEX_URL=https://southamerica-east1-python.pkg.dev/neqsti/python-packages/simple/
RUN pip install --no-cache-dir -r requirements.txt

# Copy pyproject.toml for package metadata (optional)
COPY pyproject.toml README.md ./

# Copy application code (excluding garantis_shared - now installed via pip)
COPY src/ ./src/

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3     CMD curl -f http://localhost:8080/health || exit 1

# Run the application
# --timeout-keep-alive 75: o default do uvicorn e 5s — o risk-engine-worker reusa
# conexoes keepalive do pool por mais tempo (httpx) e batia em conexao que o
# servidor ja fechou em 5s -> ReadError em massa no fan-out L1 do re-cascade
# (incidente 2026-06-14: ReadError = transporte, ai-agents nunca caiu). 75s >>
# qualquer janela de reuse do client -> reuse sempre seguro.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--timeout-keep-alive", "75"]
