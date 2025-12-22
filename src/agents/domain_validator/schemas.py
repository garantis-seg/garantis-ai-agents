"""
Schemas for Domain Validator Agent.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class DomainValidationRequest(BaseModel):
    """Request for domain validation."""

    domain: str = Field(description="Domain to validate (e.g., 'mjradv.com.br')")
    law_firm_name: Optional[str] = Field(
        default=None, description="Law firm name from OAB registration"
    )
    lawyer_name: Optional[str] = Field(default=None, description="Lawyer's name")


class DomainValidationResult(BaseModel):
    """Result of domain validation."""

    domain: str = Field(description="The domain that was validated")
    valid: bool = Field(description="Whether the domain matches the law firm")
    confidence: int = Field(ge=0, le=100, description="Confidence score 0-100")
    reason: str = Field(description="Explanation of the validation result")
    success: bool = Field(default=True, description="Whether the validation succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class LLMValidationResponse(BaseModel):
    """Schema for LLM structured output."""

    valid: bool = Field(description="Whether domain matches the law firm")
    confidence: int = Field(ge=0, le=100, description="Confidence score 0-100")
    reason: str = Field(description="Brief explanation in Portuguese")


class BatchValidationRequest(BaseModel):
    """Request for batch domain validation."""

    domains: List[DomainValidationRequest] = Field(
        description="List of domains to validate"
    )
    provider: Optional[str] = Field(default=None, description="LLM provider to use")
    model: Optional[str] = Field(default=None, description="Model to use")


class BatchValidationResult(BaseModel):
    """Result of batch domain validation."""

    results: List[DomainValidationResult]
    total: int
    valid_count: int
    invalid_count: int
    error_count: int
