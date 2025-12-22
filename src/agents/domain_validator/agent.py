"""
Domain Validator Agent implementation.

Validates if a domain matches a law firm using semantic understanding
to catch abbreviations and variations that string matching would miss.
"""

import logging
import os
from typing import List, Optional

from ...providers import LLMFactory
from .prompts import build_validation_prompt
from .schemas import (
    BatchValidationResult,
    DomainValidationRequest,
    DomainValidationResult,
    LLMValidationResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gemini-2.0-flash")


async def validate_domain(
    domain: str,
    law_firm_name: Optional[str] = None,
    lawyer_name: Optional[str] = None,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> DomainValidationResult:
    """
    Validate if a domain matches a law firm.

    Args:
        domain: The domain to validate (e.g., "mjradv.com.br")
        law_firm_name: Law firm name from OAB (e.g., "MORAES JUNIOR ADVOGADOS")
        lawyer_name: Lawyer's name (e.g., "ODAIR DE MORAES JUNIOR")
        provider: LLM provider to use
        model: Model to use (defaults to provider's default)

    Returns:
        DomainValidationResult with validation result
    """
    try:
        llm = LLMFactory.create_provider(provider)
        prompt = build_validation_prompt(domain, law_firm_name, lawyer_name)

        logger.info(f"Validating domain '{domain}' for firm '{law_firm_name}'")

        response = await llm.generate_async(
            prompt=prompt,
            model=model,
            response_schema=LLMValidationResponse,
        )

        if response.structured_output:
            result = response.structured_output
            return DomainValidationResult(
                domain=domain,
                valid=result.valid,
                confidence=result.confidence,
                reason=result.reason,
                success=True,
            )
        else:
            # Fallback: try to parse from text
            import json
            import re

            text = response.text.strip()

            # Remove markdown code blocks if present
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
                if text.startswith("json"):
                    text = text[4:].strip()

            # Try to parse JSON
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                json_match = re.search(r"\{[^}]+\}", text)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    raise ValueError(f"Could not parse JSON from: {text[:200]}")

            return DomainValidationResult(
                domain=domain,
                valid=data.get("valid", True),
                confidence=data.get("confidence", 50),
                reason=data.get("reason", "Sem explicação"),
                success=True,
            )

    except Exception as e:
        logger.error(f"Domain validation failed for '{domain}': {e}")
        # Fallback: assume valid to not block pipeline
        return DomainValidationResult(
            domain=domain,
            valid=True,
            confidence=50,
            reason="Validação indisponível (erro de API)",
            success=False,
            error=str(e),
        )


async def validate_domains_batch(
    domains: List[DomainValidationRequest],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> BatchValidationResult:
    """
    Validate multiple domains.

    Args:
        domains: List of domain validation requests
        provider: LLM provider to use
        model: Model to use

    Returns:
        BatchValidationResult with all results
    """
    results: List[DomainValidationResult] = []
    valid_count = 0
    invalid_count = 0
    error_count = 0

    for req in domains:
        result = await validate_domain(
            domain=req.domain,
            law_firm_name=req.law_firm_name,
            lawyer_name=req.lawyer_name,
            provider=provider,
            model=model,
        )
        results.append(result)

        if not result.success:
            error_count += 1
        elif result.valid:
            valid_count += 1
        else:
            invalid_count += 1

    return BatchValidationResult(
        results=results,
        total=len(domains),
        valid_count=valid_count,
        invalid_count=invalid_count,
        error_count=error_count,
    )


class DomainValidatorAgent:
    """
    Agent for validating law firm domains.

    Provides a class-based interface for domain validation.
    """

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: Optional[str] = None,
    ):
        """
        Initialize the domain validator agent.

        Args:
            provider: LLM provider to use
            model: Model to use (defaults to provider's default)
        """
        self.provider = provider
        self.model = model
        self._llm = None

    @property
    def llm(self):
        """Lazy-load LLM provider."""
        if self._llm is None:
            self._llm = LLMFactory.create_provider(self.provider)
        return self._llm

    async def validate(
        self,
        domain: str,
        law_firm_name: Optional[str] = None,
        lawyer_name: Optional[str] = None,
    ) -> DomainValidationResult:
        """
        Validate a single domain.

        Args:
            domain: Domain to validate
            law_firm_name: Law firm name from OAB
            lawyer_name: Lawyer's name

        Returns:
            DomainValidationResult
        """
        return await validate_domain(
            domain=domain,
            law_firm_name=law_firm_name,
            lawyer_name=lawyer_name,
            provider=self.provider,
            model=self.model,
        )

    async def validate_batch(
        self,
        domains: List[DomainValidationRequest],
    ) -> BatchValidationResult:
        """
        Validate multiple domains.

        Args:
            domains: List of domain validation requests

        Returns:
            BatchValidationResult
        """
        return await validate_domains_batch(
            domains=domains,
            provider=self.provider,
            model=self.model,
        )
