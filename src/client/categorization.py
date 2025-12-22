"""
Categorization client.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import GarantisAIClient


class CategorizationClient:
    """Client for categorization endpoints."""

    def __init__(self, client: "GarantisAIClient"):
        self._client = client

    async def categorize_l1(
        self,
        edital: Dict[str, Any],
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Categorize edital into L1 (serviço or produto).

        Args:
            edital: Edital data with id, title, description, etc.
            provider: LLM provider.
            model: LLM model.

        Returns:
            L1Result with id, name, confidence.
        """
        payload = {"edital": edital}
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/categorization/l1", json=payload)
            response.raise_for_status()
            return response.json()

    async def categorize_l2(
        self,
        edital: Dict[str, Any],
        base_type: str,
        existing_categories: List[str],
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Categorize edital into L2 category.

        Args:
            edital: Edital data.
            base_type: L1 type ('serviço' or 'produto').
            existing_categories: Existing L2 categories with IDs.
            provider: LLM provider.
            model: LLM model.

        Returns:
            L2Result with name, confidence, is_new.
        """
        payload = {
            "edital": edital,
            "base_type": base_type,
            "existing_categories": existing_categories,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/categorization/l2", json=payload)
            response.raise_for_status()
            return response.json()

    async def categorize_l3(
        self,
        edital: Dict[str, Any],
        l2_category: str,
        existing_categories: List[str],
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Categorize edital into L3 subcategory.

        Args:
            edital: Edital data.
            l2_category: L2 category name.
            existing_categories: Existing L3 categories with IDs.
            provider: LLM provider.
            model: LLM model.

        Returns:
            L3Result with name, confidence, is_new.
        """
        payload = {
            "edital": edital,
            "l2_category": l2_category,
            "existing_categories": existing_categories,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/categorization/l3", json=payload)
            response.raise_for_status()
            return response.json()

    async def categorize_full(
        self,
        edital: Dict[str, Any],
        existing_l2_categories: Optional[Dict[str, List[str]]] = None,
        existing_l3_categories: Optional[Dict[str, List[str]]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        validation_model: Optional[str] = None,
        include_title_optimization: bool = True,
        include_validation: bool = True,
    ) -> Dict[str, Any]:
        """
        Full categorization pipeline: L1 -> L2 -> L3 + validation + title optimization.

        Args:
            edital: Edital data.
            existing_l2_categories: Dict mapping base_type to L2 categories.
            existing_l3_categories: Dict mapping L2 category to L3 categories.
            provider: LLM provider.
            model: LLM model for categorization.
            validation_model: Model for validation (smarter).
            include_title_optimization: Whether to optimize title.
            include_validation: Whether to validate result.

        Returns:
            CategorizationResult with l1, l2, l3, validation, optimized_title.
        """
        payload = {
            "edital": edital,
            "existing_l2_categories": existing_l2_categories or {},
            "existing_l3_categories": existing_l3_categories or {},
            "include_title_optimization": include_title_optimization,
            "include_validation": include_validation,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model
        if validation_model:
            payload["validation_model"] = validation_model

        async with self._client._get_client() as client:
            response = await client.post("/categorization/full", json=payload)
            response.raise_for_status()
            return response.json()

    async def optimize_title(
        self,
        edital: Dict[str, Any],
        l1_type: str,
        l2_category: str,
        l3_category: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Optimize edital title to max 60 characters.

        Args:
            edital: Edital data.
            l1_type: L1 type.
            l2_category: L2 category name.
            l3_category: L3 category name.
            provider: LLM provider.
            model: LLM model.

        Returns:
            TitleOptimizationResult with optimized_title.
        """
        payload = {
            "edital": edital,
            "l1_type": l1_type,
            "l2_category": l2_category,
            "l3_category": l3_category,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/categorization/title", json=payload)
            response.raise_for_status()
            return response.json()

    async def categorize_batch(
        self,
        editais: List[Dict[str, Any]],
        existing_l2_categories: Optional[Dict[str, List[str]]] = None,
        existing_l3_categories: Optional[Dict[str, List[str]]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        include_title_optimization: bool = True,
        include_validation: bool = False,
    ) -> Dict[str, Any]:
        """
        Batch categorize multiple editais.

        Args:
            editais: List of editais to categorize.
            existing_l2_categories: Dict mapping base_type to L2 categories.
            existing_l3_categories: Dict mapping L2 category to L3 categories.
            provider: LLM provider.
            model: LLM model.
            include_title_optimization: Whether to optimize titles.
            include_validation: Whether to validate (default False for batch).

        Returns:
            BatchCategorizeResponse with results, total, success_count, error_count.
        """
        payload = {
            "editais": editais,
            "existing_l2_categories": existing_l2_categories or {},
            "existing_l3_categories": existing_l3_categories or {},
            "include_title_optimization": include_title_optimization,
            "include_validation": include_validation,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/categorization/batch", json=payload)
            response.raise_for_status()
            return response.json()
