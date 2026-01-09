"""
Logging Setup - Structured JSON logging for Cloud Run.

Provides consistent logging configuration across all Garantis services.
Automatically detects Cloud Run environment and uses JSON format.

Usage:
    from garantis_shared.logging_setup import setup_logging

    # Auto-detect environment
    setup_logging("my-service")

    # Force JSON logging
    setup_logging("my-service", json_logs=True)

    # Get logger
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Processing started", extra={"count": 100})
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for Cloud Run structured logging.

    Produces logs in the format expected by Cloud Logging:
    - timestamp: ISO format with timezone
    - severity: Log level name
    - message: Log message
    - service: Service name
    - Additional fields from extra parameter
    """

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra context fields
        skip_keys = {
            "name", "msg", "args", "levelname", "levelno",
            "exc_info", "exc_text", "message", "pathname",
            "filename", "module", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread",
            "threadName", "processName", "process", "stack_info",
            "taskName"
        }

        for key, value in record.__dict__.items():
            if key not in skip_keys and not key.startswith("_"):
                log_data[key] = value

        return json.dumps(log_data, default=str, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter for local development."""

    def __init__(self, service_name: str):
        super().__init__(
            fmt=f"%(asctime)s - {service_name} - %(name)s - %(levelname)s - %(message)s"
        )


def is_cloud_run() -> bool:
    """Check if running in Cloud Run environment."""
    return bool(os.getenv("K_SERVICE"))


def setup_logging(
    service_name: str,
    log_level: Optional[str] = None,
    json_logs: Optional[bool] = None,
) -> logging.Logger:
    """
    Configure logging for a Garantis service.

    Automatically detects Cloud Run environment and uses JSON logging.
    In local development, uses human-readable format.

    Args:
        service_name: Name of the service (e.g., "frontend-api")
        log_level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to LOG_LEVEL env var or INFO.
        json_logs: Force JSON logging. If None, auto-detects based on environment.

    Returns:
        Root logger configured for the service

    Example:
        setup_logging("frontend-api")

        # Then in your code:
        logger = logging.getLogger(__name__)
        logger.info("User logged in", extra={"user_id": "123"})
    """
    # Determine log level
    level_str = log_level or os.getenv("LOG_LEVEL", "INFO")
    level = getattr(logging, level_str.upper(), logging.INFO)

    # Determine if JSON logging should be used
    use_json = json_logs if json_logs is not None else is_cloud_run()

    # Create handler with appropriate formatter
    handler = logging.StreamHandler(sys.stdout)

    if use_json:
        handler.setFormatter(JSONFormatter(service_name))
    else:
        handler.setFormatter(HumanReadableFormatter(service_name))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers = []  # Clear existing handlers
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Reduce noise from external libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    Convenience function that wraps logging.getLogger().

    Args:
        name: Logger name, typically __name__

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
