"""
HTTP Client - Async HTTP client with retry and timeout handling.

Provides a standardized way to make HTTP requests to other Garantis services.

Usage:
    from garantis_shared.http_client import ServiceClient

    # Using context manager
    async with ServiceClient("garantis-ai-agents") as client:
        response = await client.post("/analyze", json={"text": "..."})
        data = response.json()

    # Manual lifecycle
    client = ServiceClient("garantis-ai-agents")
    await client.connect()
    response = await client.get("/health")
    await client.close()
"""

import logging
from typing import Any, Dict, Optional
from contextlib import asynccontextmanager

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from .service_registry import get_service_url

logger = logging.getLogger(__name__)


class ServiceClient:
    """
    HTTP client for communicating with Garantis services.

    Features:
    - Automatic service URL resolution from registry
    - Connection pooling
    - Configurable timeout and retries
    - Async context manager support
    """

    def __init__(
        self,
        service_name: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        base_url: Optional[str] = None,
    ):
        """
        Initialize service client.

        Args:
            service_name: Name of the service (e.g., "garantis-ai-agents")
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            base_url: Override base URL (otherwise resolved from registry)
        """
        if httpx is None:
            raise ImportError("httpx not installed. Install with: pip install httpx")

        self.service_name = service_name
        self.base_url = base_url or get_service_url(service_name)
        self.timeout = timeout
        self.max_retries = max_retries
        self._client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=True,
            )
            logger.debug(f"Connected to {self.service_name} at {self.base_url}")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.debug(f"Disconnected from {self.service_name}")

    async def __aenter__(self) -> "ServiceClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Make an HTTP request with retry logic.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path
            **kwargs: Additional arguments for httpx

        Returns:
            httpx.Response

        Raises:
            httpx.HTTPError: If all retries fail
        """
        if self._client is None:
            raise RuntimeError("Client not connected. Use 'async with' or call connect()")

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = await self._client.request(method, path, **kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    raise
                last_error = e
                logger.warning(
                    f"Request to {self.service_name}{path} failed (attempt {attempt + 1}/{self.max_retries}): {e}"
                )
            except httpx.RequestError as e:
                last_error = e
                logger.warning(
                    f"Request to {self.service_name}{path} failed (attempt {attempt + 1}/{self.max_retries}): {e}"
                )

        raise last_error or Exception("Request failed")

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a GET request."""
        return await self._request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a POST request."""
        return await self._request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a PUT request."""
        return await self._request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        """Make a DELETE request."""
        return await self._request("DELETE", path, **kwargs)

    async def health_check(self) -> Dict[str, Any]:
        """
        Check if the service is healthy.

        Returns:
            Health check response dict
        """
        response = await self.get("/health")
        return response.json()


@asynccontextmanager
async def service_request(
    service_name: str,
    method: str,
    path: str,
    **kwargs: Any,
):
    """
    Convenience function for one-off requests.

    Usage:
        async with service_request("garantis-ai-agents", "POST", "/analyze", json=data) as response:
            result = response.json()
    """
    async with ServiceClient(service_name) as client:
        response = await client._request(method, path, **kwargs)
        yield response
