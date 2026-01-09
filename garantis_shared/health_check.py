"""
Health Check - Standardized health endpoints for all services.

Provides consistent /health and /health/ready endpoints for monitoring.

Usage (FastAPI):
    from garantis_shared.health_check import create_health_router

    health_router = create_health_router(
        service_name="frontend-api",
        version="1.0.0",
        readiness_checks=[("database", check_db)]
    )
    app.include_router(health_router)

Usage (Flask):
    from garantis_shared.health_check import create_flask_health_endpoints

    create_flask_health_endpoints(
        app,
        "service-name",
        "1.0.0",
        [("database", check_db)]
    )
"""

from datetime import datetime
from typing import Callable, Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


class HealthCheck:
    """
    Health check helper for service health monitoring.

    Provides both liveness (/health) and readiness (/health/ready) checks.
    """

    def __init__(
        self,
        service_name: str,
        version: str = "1.0.0",
        extra_info: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize health check.

        Args:
            service_name: Name of the service
            version: Service version
            extra_info: Additional info to include in health responses
        """
        self.service_name = service_name
        self.version = version
        self.extra_info = extra_info or {}
        self.readiness_checks: Dict[str, Callable] = {}
        self.start_time = datetime.now()

    def add_readiness_check(self, name: str, check_func: Callable) -> None:
        """
        Add a readiness check function.

        Args:
            name: Check name (e.g., "database", "external_api")
            check_func: Function that returns True if ready, False otherwise
        """
        self.readiness_checks[name] = check_func

    def check(self) -> Dict[str, Any]:
        """
        Basic liveness check - always returns healthy if service is running.

        Returns:
            Health status dict
        """
        uptime = (datetime.now() - self.start_time).total_seconds()
        response = {
            "status": "healthy",
            "service": self.service_name,
            "version": self.version,
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": round(uptime, 2),
        }
        response.update(self.extra_info)
        return response

    def check_ready(self) -> Dict[str, Any]:
        """
        Readiness check - verifies service can handle requests.

        Runs all registered readiness checks and reports status.

        Returns:
            Readiness status dict with individual check results
        """
        results = {}
        all_ready = True

        for name, check_func in self.readiness_checks.items():
            try:
                is_ready = check_func()
                results[name] = {
                    "status": "ready" if is_ready else "not_ready",
                    "ready": is_ready
                }
                if not is_ready:
                    all_ready = False
            except Exception as e:
                logger.error(f"Readiness check '{name}' failed: {e}")
                results[name] = {
                    "status": "error",
                    "ready": False,
                    "error": str(e)
                }
                all_ready = False

        return {
            "ready": all_ready,
            "service": self.service_name,
            "version": self.version,
            "timestamp": datetime.now().isoformat(),
            "checks": results,
        }


def create_health_router(
    service_name: str,
    version: str = "1.0.0",
    readiness_checks: Optional[List[tuple]] = None,
    extra_info: Optional[Dict[str, Any]] = None,
):
    """
    Create FastAPI router with health endpoints.

    Args:
        service_name: Name of the service
        version: Service version
        readiness_checks: List of (name, check_function) tuples
        extra_info: Additional info to include in health responses

    Returns:
        FastAPI APIRouter with /health and /health/ready endpoints

    Example:
        def check_db():
            try:
                conn = get_connection()
                conn.cursor().execute("SELECT 1")
                return True
            except:
                return False

        health_router = create_health_router(
            "frontend-api",
            "1.0.0",
            [("database", check_db)],
            {"model": "gemini-2.0-flash-lite"}
        )
        app.include_router(health_router)
    """
    try:
        from fastapi import APIRouter, Response
        import json
    except ImportError:
        raise ImportError("FastAPI not installed. Install with: pip install fastapi")

    router = APIRouter(tags=["health"])
    health = HealthCheck(service_name, version, extra_info)

    if readiness_checks:
        for name, check_func in readiness_checks:
            health.add_readiness_check(name, check_func)

    @router.get("/health")
    async def health_check():
        """Liveness check - returns healthy if service is running."""
        return health.check()

    @router.get("/health/ready")
    async def readiness_check():
        """Readiness check - verifies service can handle requests."""
        result = health.check_ready()
        if not result["ready"]:
            return Response(
                content=json.dumps(result),
                status_code=503,
                media_type="application/json"
            )
        return result

    return router


def create_flask_health_endpoints(
    app,
    service_name: str,
    version: str = "1.0.0",
    readiness_checks: Optional[List[tuple]] = None,
    extra_info: Optional[Dict[str, Any]] = None,
):
    """
    Add health endpoints to Flask app.

    Args:
        app: Flask app instance
        service_name: Name of the service
        version: Service version
        readiness_checks: List of (name, check_function) tuples
        extra_info: Additional info to include in health responses

    Example:
        from flask import Flask
        app = Flask(__name__)

        def check_db():
            return True

        create_flask_health_endpoints(
            app,
            "my-service",
            "1.0.0",
            [("database", check_db)]
        )
    """
    try:
        from flask import jsonify
    except ImportError:
        raise ImportError("Flask not installed. Install with: pip install flask")

    health = HealthCheck(service_name, version, extra_info)

    if readiness_checks:
        for name, check_func in readiness_checks:
            health.add_readiness_check(name, check_func)

    @app.route("/health")
    def health_endpoint():
        return jsonify(health.check())

    @app.route("/health/ready")
    def ready_endpoint():
        result = health.check_ready()
        status_code = 200 if result["ready"] else 503
        return jsonify(result), status_code
