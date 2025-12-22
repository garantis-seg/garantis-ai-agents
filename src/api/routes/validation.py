"""
Endpoints para validação de domínios.
"""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agents.domain_validator import (
    DomainValidationRequest,
    DomainValidationResult,
    BatchValidationResult,
    validate_domain,
    validate_domains_batch,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/validation", tags=["validation"])

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


# Request schemas


class ValidateDomainRequest(BaseModel):
    """Request for single domain validation."""

    domain: str = Field(description="Domain to validate (e.g., 'mjradv.com.br')")
    law_firm_name: Optional[str] = Field(
        default=None, description="Law firm name from OAB registration"
    )
    lawyer_name: Optional[str] = Field(default=None, description="Lawyer's name")
    provider: Optional[str] = Field(default=None, description="LLM provider to use")
    model: Optional[str] = Field(default=None, description="Model to use")


class ValidateBatchRequest(BaseModel):
    """Request for batch domain validation."""

    domains: List[DomainValidationRequest] = Field(
        description="List of domains to validate"
    )
    provider: Optional[str] = Field(default=None, description="LLM provider to use")
    model: Optional[str] = Field(default=None, description="Model to use")


# Endpoints


@router.post("/domain", response_model=DomainValidationResult)
async def validate_domain_endpoint(request: ValidateDomainRequest):
    """
    Validate if a domain matches a law firm.

    Uses semantic understanding to catch abbreviations and variations
    that string matching would miss.

    Examples:
    - "mjradv.com.br" matches "MORAES JUNIOR ADVOGADOS ASSOCIADOS"
    - "pinheironeto.com.br" matches "PINHEIRO NETO ADVOGADOS"
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await validate_domain(
            domain=request.domain,
            law_firm_name=request.law_firm_name,
            lawyer_name=request.lawyer_name,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("Domain validation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/domains", response_model=BatchValidationResult)
async def validate_domains_endpoint(request: ValidateBatchRequest):
    """
    Validate multiple domains.

    Processes domains sequentially to avoid rate limits.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await validate_domains_batch(
            domains=request.domains,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("Batch domain validation failed")
        raise HTTPException(status_code=500, detail=str(e))
