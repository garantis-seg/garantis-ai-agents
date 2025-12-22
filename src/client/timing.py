"""
Timing analysis client.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import GarantisAIClient


class TimingClient:
    """Client for timing analysis endpoints."""

    def __init__(self, client: "GarantisAIClient"):
        self._client = client

    async def analyze(
        self,
        case_data: Dict[str, Any],
        movements: List[Dict[str, str]],
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze a legal case for timing opportunities.

        Args:
            case_data: Case information including processo_numero, foro, classe, etc.
            movements: List of case movements with data_movimento and descricao.
            model: LLM model to use.
            prompt_version: Prompt version (default: v3).
            provider: LLM provider to use.

        Returns:
            Analysis result with timing_base, score_final, etc.
        """
        payload = {
            "case_data": case_data,
            "movements": movements,
        }
        if model:
            payload["model"] = model
        if prompt_version:
            payload["prompt_version"] = prompt_version
        if provider:
            payload["provider"] = provider

        async with self._client._get_client() as client:
            response = await client.post("/timing/analyze", json=payload)
            response.raise_for_status()
            return response.json()

    async def analyze_batch(
        self,
        cases: List[Dict[str, Any]],
        model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Analyze multiple cases in batch.

        Args:
            cases: List of cases, each with case_data and movements.
            model: LLM model to use.
            prompt_version: Prompt version.
            provider: LLM provider.

        Returns:
            Batch result with results list and summary.
        """
        payload = {
            "cases": cases,
        }
        if model:
            payload["model"] = model
        if prompt_version:
            payload["prompt_version"] = prompt_version
        if provider:
            payload["provider"] = provider

        async with self._client._get_client() as client:
            response = await client.post("/timing/analyze-batch", json=payload)
            response.raise_for_status()
            return response.json()

    async def prompts(self) -> Dict[str, Any]:
        """List available prompt versions."""
        async with self._client._get_client() as client:
            response = await client.get("/timing/prompts")
            response.raise_for_status()
            return response.json()
