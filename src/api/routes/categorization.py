"""
Endpoints para categorização de editais.
"""

import logging
import os
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...agents.edital_categorizer import (
    EditalCategorizerAgent,
    categorize_edital,
    categorize_l1,
    categorize_l2,
    categorize_l3,
    optimize_title,
)
from ...agents.edital_categorizer.schemas import (
    CategorizationResult,
    EditalData,
    L1Result,
    L2Result,
    L3Result,
    TitleOptimizationResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/categorization", tags=["categorization"])

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


# Request schemas

class CategorizeL1Request(BaseModel):
    """Request for L1 categorization."""
    edital: EditalData
    provider: Optional[str] = Field(default=None, description="LLM provider")
    model: Optional[str] = Field(default=None, description="Model to use")


class CategorizeL2Request(BaseModel):
    """Request for L2 categorization."""
    edital: EditalData
    base_type: str = Field(description="L1 type: 'serviço' or 'produto'")
    existing_categories: List[str] = Field(
        default=[],
        description="Existing L2 categories with IDs in brackets, e.g. 'Limpeza [123]'"
    )
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)


class CategorizeL3Request(BaseModel):
    """Request for L3 categorization."""
    edital: EditalData
    l2_category: str = Field(description="L2 category name")
    existing_categories: List[str] = Field(
        default=[],
        description="Existing L3 categories with IDs in brackets"
    )
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)


class CategorizeFullRequest(BaseModel):
    """Request for full categorization pipeline."""
    edital: EditalData
    existing_l2_categories: Dict[str, List[str]] = Field(
        default={},
        description="Dict mapping base_type to list of L2 categories"
    )
    existing_l3_categories: Dict[str, List[str]] = Field(
        default={},
        description="Dict mapping L2 category to list of L3 categories"
    )
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    validation_model: Optional[str] = Field(default=None, description="Model for validation (smarter)")
    include_title_optimization: bool = Field(default=True)
    include_validation: bool = Field(default=True)


class OptimizeTitleRequest(BaseModel):
    """Request for title optimization."""
    edital: EditalData
    l1_type: str = Field(description="L1 type")
    l2_category: str = Field(description="L2 category name")
    l3_category: str = Field(description="L3 category name")
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)


class BatchCategorizeRequest(BaseModel):
    """Request for batch categorization."""
    editais: List[EditalData] = Field(description="List of editais to categorize")
    existing_l2_categories: Dict[str, List[str]] = Field(default={})
    existing_l3_categories: Dict[str, List[str]] = Field(default={})
    provider: Optional[str] = Field(default=None)
    model: Optional[str] = Field(default=None)
    include_title_optimization: bool = Field(default=True)
    include_validation: bool = Field(default=False)  # Default false for batch


class BatchCategorizeResponse(BaseModel):
    """Response for batch categorization."""
    results: List[CategorizationResult]
    total: int
    success_count: int
    error_count: int


# Endpoints

@router.post("/l1", response_model=L1Result)
async def categorize_l1_endpoint(request: CategorizeL1Request):
    """
    Categorize edital into L1 (serviço or produto).
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await categorize_l1(
            edital=request.edital,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("L1 categorization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/l2", response_model=L2Result)
async def categorize_l2_endpoint(request: CategorizeL2Request):
    """
    Categorize edital into L2 category.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await categorize_l2(
            edital=request.edital,
            base_type=request.base_type,
            existing_categories=request.existing_categories,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("L2 categorization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/l3", response_model=L3Result)
async def categorize_l3_endpoint(request: CategorizeL3Request):
    """
    Categorize edital into L3 subcategory.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await categorize_l3(
            edital=request.edital,
            l2_category=request.l2_category,
            existing_categories=request.existing_categories,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("L3 categorization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/full", response_model=CategorizationResult)
async def categorize_full_endpoint(request: CategorizeFullRequest):
    """
    Full categorization pipeline: L1 -> L2 -> L3 + validation + title optimization.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await categorize_edital(
            edital=request.edital,
            existing_l2_categories=request.existing_l2_categories,
            existing_l3_categories=request.existing_l3_categories,
            provider=provider,
            model=request.model,
            validation_model=request.validation_model,
            include_title_optimization=request.include_title_optimization,
            include_validation=request.include_validation,
        )
        return result
    except Exception as e:
        logger.exception("Full categorization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/title", response_model=TitleOptimizationResult)
async def optimize_title_endpoint(request: OptimizeTitleRequest):
    """
    Optimize edital title to max 60 characters.
    """
    provider = request.provider or DEFAULT_PROVIDER

    try:
        result = await optimize_title(
            edital=request.edital,
            l1_type=request.l1_type,
            l2_category=request.l2_category,
            l3_category=request.l3_category,
            provider=provider,
            model=request.model,
        )
        return result
    except Exception as e:
        logger.exception("Title optimization failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch", response_model=BatchCategorizeResponse)
async def categorize_batch_endpoint(request: BatchCategorizeRequest):
    """
    Batch categorize multiple editais.

    Processes sequentially to avoid rate limits.
    """
    provider = request.provider or DEFAULT_PROVIDER

    results: List[CategorizationResult] = []
    success_count = 0
    error_count = 0

    for edital in request.editais:
        try:
            result = await categorize_edital(
                edital=edital,
                existing_l2_categories=request.existing_l2_categories,
                existing_l3_categories=request.existing_l3_categories,
                provider=provider,
                model=request.model,
                include_title_optimization=request.include_title_optimization,
                include_validation=request.include_validation,
            )
            results.append(result)
            success_count += 1
        except Exception as e:
            logger.error(f"Batch item failed: {e}")
            # Create error result
            results.append(
                CategorizationResult(
                    edital_id=edital.id,
                    l1=L1Result(id=0, name="error", confidence=0, success=False, error=str(e)),
                    l2=L2Result(name="error", confidence=0, success=False, error=str(e)),
                    l3=L3Result(name="error", confidence=0, success=False, error=str(e)),
                    provider=provider,
                )
            )
            error_count += 1

    return BatchCategorizeResponse(
        results=results,
        total=len(request.editais),
        success_count=success_count,
        error_count=error_count,
    )
