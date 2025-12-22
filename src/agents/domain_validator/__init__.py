"""
Domain Validator Agent - Validates if a domain matches a law firm.

Uses semantic understanding to catch abbreviations and variations that string
matching would miss. For example: "mjradv.com.br" = "Moraes Junior Advogados"
"""

from .agent import (
    DomainValidatorAgent,
    validate_domain,
    validate_domains_batch,
)
from .schemas import (
    DomainValidationRequest,
    DomainValidationResult,
    BatchValidationResult,
)

__all__ = [
    "DomainValidatorAgent",
    "validate_domain",
    "validate_domains_batch",
    "DomainValidationRequest",
    "DomainValidationResult",
    "BatchValidationResult",
]
