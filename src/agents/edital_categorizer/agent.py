"""
Edital Categorizer Agent.

Categorizes government bidding documents (editais) into L1/L2/L3 hierarchy
using LLM providers.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Union

from ...providers import create_provider
from ...providers.base import LLMResponse
from .prompts import (
    build_l1_prompt,
    build_l2_prompt,
    build_l3_prompt,
    build_title_optimization_prompt,
    build_validation_prompt,
)
from .schemas import (
    BaseType,
    CategorizationResult,
    EditalData,
    L1LLMResponse,
    L1Result,
    L2LLMResponse,
    L2Result,
    L3LLMResponse,
    L3Result,
    TitleLLMResponse,
    TitleOptimizationResult,
    ValidationLLMResponse,
    ValidationResult,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")


def _extract_json_from_text(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown blocks."""
    if not text or not text.strip():
        raise ValueError("Empty response text")

    text = text.strip()

    # Handle markdown code blocks
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        text = text[start:end].strip()
    elif "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        text = text[start:end]

    return json.loads(text)


def _extract_category_id(id_value) -> Optional[int]:
    """Extract category ID from various formats."""
    if not id_value:
        return None

    try:
        if isinstance(id_value, int):
            return id_value

        if isinstance(id_value, str):
            if id_value.strip() == "-1":
                return -1
            clean_id = re.sub(r"[^\d-]", "", id_value)
            if clean_id and clean_id != "-":
                return int(clean_id)

        if isinstance(id_value, list) and id_value:
            return _extract_category_id(id_value[0])

        return None
    except (ValueError, TypeError):
        return None


async def categorize_l1(
    edital: Union[EditalData, dict],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> L1Result:
    """
    Categorize edital into L1 (serviço or produto).

    Args:
        edital: Edital data
        provider: LLM provider name
        model: Model to use (optional)

    Returns:
        L1Result with category and confidence
    """
    if isinstance(edital, dict):
        edital = EditalData(**edital)

    context = edital.to_context_string()
    prompt = build_l1_prompt(context)

    try:
        llm = create_provider(provider)
        if model is None:
            model = llm.get_default_model()

        response: LLMResponse = await llm.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.1,
            response_schema=L1LLMResponse,
        )

        data = _extract_json_from_text(response.text)

        return L1Result(
            id=data.get("id", 1),
            name=data.get("name", "serviço"),
            confidence=float(data.get("confidence", 0.8)),
            success=True,
        )

    except Exception as e:
        logger.error(f"L1 categorization failed: {e}")
        # Fallback using keyword matching
        context_lower = context.lower()
        service_keywords = ["serviço", "consultoria", "manutenção", "limpeza", "segurança", "prestação"]
        product_keywords = ["aquisição", "compra", "fornecimento", "material", "equipamento"]

        service_score = sum(1 for kw in service_keywords if kw in context_lower)
        product_score = sum(1 for kw in product_keywords if kw in context_lower)

        if service_score >= product_score:
            return L1Result(id=1, name="serviço", confidence=0.5, success=True)
        else:
            return L1Result(id=2, name="produto", confidence=0.5, success=True)


async def categorize_l2(
    edital: Union[EditalData, dict],
    base_type: str,
    existing_categories: List[str],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> L2Result:
    """
    Categorize edital into L2 category.

    Args:
        edital: Edital data
        base_type: L1 type ("serviço" or "produto")
        existing_categories: List of existing L2 categories with IDs in brackets
        provider: LLM provider name
        model: Model to use (optional)

    Returns:
        L2Result with category details
    """
    if isinstance(edital, dict):
        edital = EditalData(**edital)

    context = edital.to_context_string()
    prompt = build_l2_prompt(context, base_type, existing_categories)

    try:
        llm = create_provider(provider)
        if model is None:
            model = llm.get_default_model()

        response: LLMResponse = await llm.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.1,
            response_schema=L2LLMResponse,
        )

        data = _extract_json_from_text(response.text)

        category_id = _extract_category_id(data.get("id"))
        is_new = data.get("is_new", False) or category_id == -1
        confidence = float(data.get("confidence", 0.8))

        return L2Result(
            id=category_id if not is_new else None,
            name=data.get("name", "Outros"),
            confidence=confidence,
            is_new=is_new,
            needs_review=is_new or confidence < 0.7,
            success=True,
        )

    except Exception as e:
        logger.error(f"L2 categorization failed: {e}")
        return L2Result(
            id=None,
            name="Outros",
            confidence=0.3,
            is_new=True,
            needs_review=True,
            success=False,
            error=str(e),
        )


async def categorize_l3(
    edital: Union[EditalData, dict],
    l2_category: str,
    existing_categories: List[str],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> L3Result:
    """
    Categorize edital into L3 subcategory.

    Args:
        edital: Edital data
        l2_category: L2 category name
        existing_categories: List of existing L3 categories with IDs in brackets
        provider: LLM provider name
        model: Model to use (optional)

    Returns:
        L3Result with subcategory details
    """
    if isinstance(edital, dict):
        edital = EditalData(**edital)

    context = edital.to_context_string()
    prompt = build_l3_prompt(context, l2_category, existing_categories)

    try:
        llm = create_provider(provider)
        if model is None:
            model = llm.get_default_model()

        response: LLMResponse = await llm.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.1,
            response_schema=L3LLMResponse,
        )

        data = _extract_json_from_text(response.text)

        category_id = _extract_category_id(data.get("id"))
        is_new = data.get("is_new", False) or category_id == -1
        confidence = float(data.get("confidence", 0.8))

        return L3Result(
            id=category_id if not is_new else None,
            name=data.get("name", "Outros"),
            confidence=confidence,
            is_new=is_new,
            needs_review=is_new or confidence < 0.7,
            success=True,
        )

    except Exception as e:
        logger.error(f"L3 categorization failed: {e}")
        return L3Result(
            id=None,
            name="Outros",
            confidence=0.3,
            is_new=True,
            needs_review=True,
            success=False,
            error=str(e),
        )


async def validate_categorization(
    edital: Union[EditalData, dict],
    base_type: str,
    l2_category: str,
    l3_category: str,
    existing_l2: List[str],
    existing_l3: List[str],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> ValidationResult:
    """
    Validate L2/L3 categorization using a smarter model.

    Args:
        edital: Edital data
        base_type: L1 type
        l2_category: Proposed L2 category
        l3_category: Proposed L3 category
        existing_l2: Existing L2 categories
        existing_l3: Existing L3 categories for the L2
        provider: LLM provider name
        model: Model to use (should be a smarter model for validation)

    Returns:
        ValidationResult with approval status and suggestions
    """
    if isinstance(edital, dict):
        edital = EditalData(**edital)

    context = edital.to_context_string()
    prompt = build_validation_prompt(
        context, base_type, l2_category, l3_category, existing_l2, existing_l3
    )

    try:
        llm = create_provider(provider)
        if model is None:
            model = llm.get_default_model()

        response: LLMResponse = await llm.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.1,
            response_schema=ValidationLLMResponse,
        )

        data = _extract_json_from_text(response.text)

        return ValidationResult(
            approved=data.get("approved", True),
            suggested_l2=data.get("suggested_l2"),
            suggested_l3=data.get("suggested_l3"),
        )

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        # Fallback: approve original categorization
        return ValidationResult(approved=True)


async def optimize_title(
    edital: Union[EditalData, dict],
    l1_type: str,
    l2_category: str,
    l3_category: str,
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
) -> TitleOptimizationResult:
    """
    Optimize edital title to max 60 characters.

    Args:
        edital: Edital data
        l1_type: L1 type (serviço/produto)
        l2_category: L2 category name
        l3_category: L3 category name
        provider: LLM provider name
        model: Model to use

    Returns:
        TitleOptimizationResult with optimized title
    """
    if isinstance(edital, dict):
        edital_dict = edital
        edital = EditalData(**edital)
    else:
        edital_dict = edital.model_dump()

    original_title = edital.title
    prompt = build_title_optimization_prompt(edital_dict, l1_type, l2_category, l3_category)

    try:
        llm = create_provider(provider)
        if model is None:
            model = llm.get_default_model()

        response: LLMResponse = await llm.agenerate(
            prompt=prompt,
            model=model,
            temperature=0.1,
            response_schema=TitleLLMResponse,
        )

        data = _extract_json_from_text(response.text)

        optimized = data.get("optimized_title", original_title)
        # Ensure max 60 chars
        if len(optimized) > 60:
            optimized = optimized[:57] + "..."

        return TitleOptimizationResult(
            optimized_title=optimized,
            original_title=original_title,
            success=True,
        )

    except Exception as e:
        logger.error(f"Title optimization failed: {e}")
        return TitleOptimizationResult(
            optimized_title=original_title[:60] if len(original_title) > 60 else original_title,
            original_title=original_title,
            success=False,
            error=str(e),
        )


async def categorize_edital(
    edital: Union[EditalData, dict],
    existing_l2_categories: Dict[str, List[str]],
    existing_l3_categories: Dict[str, List[str]],
    provider: str = DEFAULT_PROVIDER,
    model: Optional[str] = None,
    validation_model: Optional[str] = None,
    include_title_optimization: bool = True,
    include_validation: bool = True,
) -> CategorizationResult:
    """
    Complete edital categorization pipeline: L1 -> L2 -> L3 + validation + title.

    Args:
        edital: Edital data
        existing_l2_categories: Dict mapping base_type to list of L2 categories
        existing_l3_categories: Dict mapping L2 category to list of L3 categories
        provider: LLM provider name
        model: Model for categorization
        validation_model: Model for validation (should be smarter)
        include_title_optimization: Whether to optimize title
        include_validation: Whether to validate categorization

    Returns:
        CategorizationResult with all categorization data
    """
    if isinstance(edital, dict):
        edital = EditalData(**edital)

    total_tokens = 0
    total_cost = 0.0

    # Step 1: L1 categorization
    l1_result = await categorize_l1(edital, provider, model)
    base_type = l1_result.name

    # Step 2: L2 categorization
    l2_categories = existing_l2_categories.get(base_type, [])
    l2_result = await categorize_l2(edital, base_type, l2_categories, provider, model)

    # Step 3: L3 categorization
    l3_categories = existing_l3_categories.get(l2_result.name, [])
    l3_result = await categorize_l3(edital, l2_result.name, l3_categories, provider, model)

    # Step 4: Validation (optional)
    validation_result = None
    if include_validation:
        validation_result = await validate_categorization(
            edital,
            base_type,
            l2_result.name,
            l3_result.name,
            l2_categories,
            l3_categories,
            provider,
            validation_model or model,
        )

        # Apply suggestions if not approved
        if not validation_result.approved:
            if validation_result.suggested_l2:
                l2_result.name = validation_result.suggested_l2
                l2_result.needs_review = True
            if validation_result.suggested_l3:
                l3_result.name = validation_result.suggested_l3
                l3_result.needs_review = True

    # Step 5: Title optimization (optional)
    optimized_title = None
    if include_title_optimization:
        title_result = await optimize_title(
            edital, base_type, l2_result.name, l3_result.name, provider, model
        )
        if title_result.success:
            optimized_title = title_result.optimized_title

    return CategorizationResult(
        edital_id=edital.id,
        l1=l1_result,
        l2=l2_result,
        l3=l3_result,
        validation=validation_result,
        optimized_title=optimized_title,
        provider=provider,
        model=model or "default",
        tokens_used=total_tokens,
        cost_usd=total_cost,
    )


class EditalCategorizerAgent:
    """
    Agent wrapper for edital categorization.

    Provides a convenient interface for categorizing editais with
    configurable provider and model.
    """

    def __init__(
        self,
        provider: str = DEFAULT_PROVIDER,
        model: Optional[str] = None,
        validation_model: Optional[str] = None,
    ):
        """
        Initialize the agent.

        Args:
            provider: LLM provider name
            model: Model for categorization
            validation_model: Model for validation (smarter model recommended)
        """
        self.provider = provider
        self.model = model
        self.validation_model = validation_model

        # Get default model from provider if not specified
        if model is None:
            llm = create_provider(provider)
            self.model = llm.get_default_model()

        logger.info(f"EditalCategorizerAgent initialized: provider={provider}, model={self.model}")

    async def categorize(
        self,
        edital: Union[EditalData, dict],
        existing_l2_categories: Dict[str, List[str]],
        existing_l3_categories: Dict[str, List[str]],
        include_title_optimization: bool = True,
        include_validation: bool = True,
    ) -> CategorizationResult:
        """
        Categorize an edital.

        Args:
            edital: Edital data
            existing_l2_categories: Dict mapping base_type to L2 categories
            existing_l3_categories: Dict mapping L2 category to L3 categories
            include_title_optimization: Whether to optimize title
            include_validation: Whether to validate

        Returns:
            CategorizationResult
        """
        return await categorize_edital(
            edital=edital,
            existing_l2_categories=existing_l2_categories,
            existing_l3_categories=existing_l3_categories,
            provider=self.provider,
            model=self.model,
            validation_model=self.validation_model,
            include_title_optimization=include_title_optimization,
            include_validation=include_validation,
        )

    async def categorize_l1(self, edital: Union[EditalData, dict]) -> L1Result:
        """Categorize into L1 only."""
        return await categorize_l1(edital, self.provider, self.model)

    async def categorize_l2(
        self,
        edital: Union[EditalData, dict],
        base_type: str,
        existing_categories: List[str],
    ) -> L2Result:
        """Categorize into L2."""
        return await categorize_l2(edital, base_type, existing_categories, self.provider, self.model)

    async def categorize_l3(
        self,
        edital: Union[EditalData, dict],
        l2_category: str,
        existing_categories: List[str],
    ) -> L3Result:
        """Categorize into L3."""
        return await categorize_l3(edital, l2_category, existing_categories, self.provider, self.model)

    async def optimize_title(
        self,
        edital: Union[EditalData, dict],
        l1_type: str,
        l2_category: str,
        l3_category: str,
    ) -> TitleOptimizationResult:
        """Optimize edital title."""
        return await optimize_title(edital, l1_type, l2_category, l3_category, self.provider, self.model)

    def get_config(self) -> dict:
        """Get agent configuration."""
        return {
            "name": "edital_categorizer_agent",
            "provider": self.provider,
            "model": self.model,
            "validation_model": self.validation_model,
            "description": "Categorizes editais into L1/L2/L3 hierarchy",
        }
