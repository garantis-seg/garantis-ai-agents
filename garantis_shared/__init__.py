"""
Garantis Shared - Shared utilities for Garantis microservices.

This package provides common functionality used across all Garantis services:
- Service discovery and URL management
- Health check endpoints (FastAPI & Flask)
- Structured JSON logging for Cloud Run
- Base configuration with Pydantic Settings
- Service sync tracking
- HTTP client utilities
"""

from .service_registry import (
    SERVICES,
    get_service_url,
    list_services,
    AI_AGENTS_URL,
    CNPJ_MATCHER_URL,
    DOMAIN_DISCOVERY_URL,
    LAWYER_EMAIL_API_URL,
    DB_TOOLS_URL,
    SCRAPING_SERVICE_URL,
    FRONTEND_API_URL,
)

__version__ = "1.0.0"

__all__ = [
    # Service Registry
    "SERVICES",
    "get_service_url",
    "list_services",
    "AI_AGENTS_URL",
    "CNPJ_MATCHER_URL",
    "DOMAIN_DISCOVERY_URL",
    "LAWYER_EMAIL_API_URL",
    "DB_TOOLS_URL",
    "SCRAPING_SERVICE_URL",
    "FRONTEND_API_URL",
    # Version
    "__version__",
]
