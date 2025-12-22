"""
Main client for Garantis AI Agents service.
"""

import os
from typing import Optional

import httpx


class GarantisAIClient:
    """
    HTTP client for Garantis AI Agents service.

    Usage:
        client = GarantisAIClient("https://ai-agents.garantis.com.br")
        result = await client.timing.analyze(case_data, movements)
        result = await client.validation.domain(domain, law_firm_name, lawyer_name)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 120.0,
        api_key: Optional[str] = None,
    ):
        """
        Initialize the client.

        Args:
            base_url: Base URL of the service. Defaults to GARANTIS_AI_AGENTS_URL env var.
            timeout: Request timeout in seconds.
            api_key: Optional API key for authentication.
        """
        self.base_url = (
            base_url
            or os.getenv("GARANTIS_AI_AGENTS_URL")
            or "http://localhost:8080"
        ).rstrip("/")
        self.timeout = timeout
        self.api_key = api_key or os.getenv("GARANTIS_AI_AGENTS_API_KEY")

        # Lazy-loaded sub-clients
        self._timing: Optional["TimingClient"] = None
        self._categorization: Optional["CategorizationClient"] = None
        self._validation: Optional["ValidationClient"] = None
        self._text: Optional["TextClient"] = None

    def _get_headers(self) -> dict:
        """Get request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        """Get async HTTP client."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._get_headers(),
            timeout=self.timeout,
        )

    @property
    def timing(self) -> "TimingClient":
        """Get timing analysis client."""
        if self._timing is None:
            from .timing import TimingClient
            self._timing = TimingClient(self)
        return self._timing

    @property
    def categorization(self) -> "CategorizationClient":
        """Get categorization client."""
        if self._categorization is None:
            from .categorization import CategorizationClient
            self._categorization = CategorizationClient(self)
        return self._categorization

    @property
    def validation(self) -> "ValidationClient":
        """Get validation client."""
        if self._validation is None:
            from .validation import ValidationClient
            self._validation = ValidationClient(self)
        return self._validation

    @property
    def text(self) -> "TextClient":
        """Get text processing client."""
        if self._text is None:
            from .text import TextClient
            self._text = TextClient(self)
        return self._text

    async def health(self) -> dict:
        """Check service health."""
        async with self._get_client() as client:
            response = await client.get("/health")
            response.raise_for_status()
            return response.json()

    async def providers(self) -> dict:
        """List available LLM providers."""
        async with self._get_client() as client:
            response = await client.get("/providers")
            response.raise_for_status()
            return response.json()
