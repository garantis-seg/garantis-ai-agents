"""
Service Registry - Centralized service URL management.

All Cloud Run service URLs are defined here to facilitate:
- Environment changes (dev/staging/prod)
- Region migrations
- URL updates
- Service discovery

Usage:
    from garantis_shared import SERVICES, get_service_url

    # Get URL by service name
    ai_url = get_service_url("garantis-ai-agents")
    response = requests.post(f"{ai_url}/timing/analyze", json=data)

    # Direct import of common URLs
    from garantis_shared import AI_AGENTS_URL
"""

import os
from typing import Dict

# GCP Project ID
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "394302633873")
GCP_REGION = os.getenv("GCP_REGION", "southamerica-east1")

# Service URLs - Cloud Run (southamerica-east1)
SERVICES: Dict[str, str] = {
    # AI & Analysis Services
    "garantis-ai-agents": os.getenv(
        "GARANTIS_AI_AGENTS_URL",
        f"https://garantis-ai-agents-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),

    # CNPJ & Company Services
    "cnpj-name-matcher": os.getenv(
        "CNPJ_NAME_MATCHER_URL",
        f"https://cnpj-name-matcher-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),
    "domain-discovery-service": os.getenv(
        "DOMAIN_DISCOVERY_URL",
        f"https://domain-discovery-service-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),

    # Database Tools
    "claude-db-tools": os.getenv(
        "CLAUDE_DB_TOOLS_URL",
        f"https://claude-db-tools-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),

    # Email & Contact Services
    "lawyer-email-api": os.getenv(
        "LAWYER_EMAIL_API_URL",
        f"https://lawyer-email-api-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),

    # Core API
    "frontend-api": os.getenv(
        "FRONTEND_API_URL",
        f"https://frontend-api-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),

    # Scraping Services
    "scraping-service": os.getenv(
        "SCRAPING_SERVICE_URL",
        f"https://scraping-service-{GCP_PROJECT_ID}.{GCP_REGION}.run.app"
    ),
    "esaj-pdf-api": os.getenv(
        "ESAJ_PDF_API_URL",
        "f"https://esaj-pdf-api-{GCP_PROJECT_ID}.{GCP_REGION}.run.app""
    ),
}


def get_service_url(service_name: str) -> str:
    """
    Get URL for a service by name.

    Args:
        service_name: Name of the service (e.g., "garantis-ai-agents")

    Returns:
        Service URL

    Raises:
        KeyError: If service name not found

    Example:
        >>> url = get_service_url("garantis-ai-agents")
        >>> print(url)
        https://garantis-ai-agents-394302633873.southamerica-east1.run.app
    """
    if service_name not in SERVICES:
        raise KeyError(
            f"Service '{service_name}' not found in registry. "
            f"Available services: {', '.join(SERVICES.keys())}"
        )
    return SERVICES[service_name]


def list_services() -> list[str]:
    """Get list of all available service names."""
    return list(SERVICES.keys())


# Convenience aliases for most-used services
AI_AGENTS_URL = SERVICES["garantis-ai-agents"]
CNPJ_MATCHER_URL = SERVICES["cnpj-name-matcher"]
DOMAIN_DISCOVERY_URL = SERVICES["domain-discovery-service"]
LAWYER_EMAIL_API_URL = SERVICES["lawyer-email-api"]
DB_TOOLS_URL = SERVICES["claude-db-tools"]
SCRAPING_SERVICE_URL = SERVICES["scraping-service"]
FRONTEND_API_URL = SERVICES["frontend-api"]
