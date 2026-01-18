# Base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

# Build arg for Artifact Registry authentication (CI)
ARG PIP_EXTRA_INDEX_URL
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}

# Copy requirements and install dependencies
COPY requirements.txt ./
# Remove hardcoded extra-index-url (we use the authenticated one from build arg)
RUN sed -i '/--extra-index-url/d' requirements.txt && \
    pip install --no-cache-dir -r requirements.txt

# Copy pyproject.toml for package metadata (optional)
COPY pyproject.toml README.md ./

# Copy application code (excluding garantis_shared - now installed via pip)
COPY src/ ./src/

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3     CMD curl -f http://localhost:8080/health || exit 1

# Run the application
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
