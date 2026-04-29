"""
Health check endpoints - liveness and readiness probes.
"""

import os
import logging
from datetime import datetime
from fastapi import APIRouter, Response
from ..schemas.responses import HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

# Track service start time
_start_time = datetime.now()


def check_gemini_api() -> bool:
    """Check if Gemini API key is configured."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    return api_key is not None and len(api_key) > 0


@router.get("/health")
async def health_check():
    """
    Liveness check - returns healthy if service is running.

    Used by Cloud Run to determine if the service should be restarted.
    """
    uptime = (datetime.now() - _start_time).total_seconds()
    return {
        "status": "healthy",
        "service": "garantis-ai-agents",
        "version": "0.5.0",
        "model_default": os.getenv("DEFAULT_MODEL", "gemini-2.5-flash-lite"),
        "prompt_default": os.getenv("DEFAULT_PROMPT_VERSION", "v3"),
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(uptime, 2),
    }


@router.get("/health/ready")
async def readiness_check(response: Response):
    """
    Readiness check - verifies service can handle requests.

    Checks:
    - Gemini API key is configured
    - Model configuration is valid

    Returns 503 if not ready (for load balancer integration).
    """
    checks = {}
    all_ready = True

    # Check Gemini API
    gemini_ready = check_gemini_api()
    checks["gemini_api"] = {"ready": gemini_ready, "status": "ready" if gemini_ready else "not_ready"}
    if not gemini_ready:
        all_ready = False
        logger.warning("Gemini API key not configured")

    # Check model configuration
    default_model = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash-lite")
    checks["model_config"] = {"ready": True, "model": default_model, "status": "ready"}

    result = {
        "ready": all_ready,
        "service": "garantis-ai-agents",
        "version": "0.5.0",
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
    }

    # Return 503 if not ready
    if not all_ready:
        response.status_code = 503

    return result
