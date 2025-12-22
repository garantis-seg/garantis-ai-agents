"""
Validation client.
"""

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import GarantisAIClient


class ValidationClient:
    """Client for validation endpoints."""

    def __init__(self, client: "GarantisAIClient"):
        self._client = client

    async def domain(
        self,
        domain: str,
        law_firm_name: Optional[str] = None,
        lawyer_name: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate if a domain matches a law firm.

        Args:
            domain: Domain to validate (e.g., "mjradv.com.br").
            law_firm_name: Law firm name from OAB.
            lawyer_name: Lawyer's name.
            provider: LLM provider.
            model: LLM model.

        Returns:
            DomainValidationResult with valid, confidence, reason.
        """
        payload = {
            "domain": domain,
        }
        if law_firm_name:
            payload["law_firm_name"] = law_firm_name
        if lawyer_name:
            payload["lawyer_name"] = lawyer_name
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/validation/domain", json=payload)
            response.raise_for_status()
            return response.json()

    async def domain_legacy(
        self,
        domain: str,
        law_firm_name: Optional[str] = None,
        lawyer_name: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Tuple[bool, int, str]:
        """
        Validate domain with legacy tuple response format.

        Compatible with existing DomainValidatorService interface.

        Args:
            domain: Domain to validate.
            law_firm_name: Law firm name.
            lawyer_name: Lawyer's name.
            provider: LLM provider.
            model: LLM model.

        Returns:
            Tuple of (is_valid, confidence, reason).
        """
        result = await self.domain(
            domain=domain,
            law_firm_name=law_firm_name,
            lawyer_name=lawyer_name,
            provider=provider,
            model=model,
        )
        return result["valid"], result["confidence"], result["reason"]

    async def domains_batch(
        self,
        domains: List[Dict[str, Any]],
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate multiple domains.

        Args:
            domains: List of domain validation requests.
            provider: LLM provider.
            model: LLM model.

        Returns:
            BatchValidationResult with results, valid_count, invalid_count.
        """
        payload = {
            "domains": domains,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/validation/domains", json=payload)
            response.raise_for_status()
            return response.json()
