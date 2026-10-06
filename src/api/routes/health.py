"""
Health check endpoints - liveness and readiness probes.
"""

import os
import logging
from datetime import datetime
from fastapi import APIRouter, Response

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

# Track service start time
_start_time = datetime.now()


def check_gemini_api() -> bool:
    """Check if Gemini is callable (backend-aware).

    Sob GEMINI_BACKEND=vertex (o default) a auth é ADC do service account — healthy
    sem key. Sob aistudio (legacy explícito), exige GEMINI_API_KEY/GOOGLE_API_KEY.
    """
    from garantis_shared.gemini_backend import gemini_available

    return gemini_available()


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
        "prompt_default": os.getenv("DEFAULT_PROMPT_VERSION", "v3"),
        "timestamp": datetime.now().isoformat(),
        "uptime_seconds": round(uptime, 2),
    }


@router.get("/health/ready")
async def readiness_check(response: Response):
    """
    Readiness check - verifies service can handle requests.

    Checks:
    - Gemini is callable (`check_gemini_api`: ADC no vertex, key no aistudio)

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
