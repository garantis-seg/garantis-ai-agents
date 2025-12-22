"""
Text processing client.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import GarantisAIClient


class TextClient:
    """Client for text processing endpoints."""

    def __init__(self, client: "GarantisAIClient"):
        self._client = client

    async def correct_ocr(
        self,
        text: str,
        preserve_structure: bool = True,
        language: str = "português brasileiro",
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Correct OCR errors in text.

        Args:
            text: Text to correct.
            preserve_structure: Whether to preserve markdown/formatting.
            language: Text language.
            provider: LLM provider.
            model: LLM model.

        Returns:
            OCRCorrectionResult with corrected_text, changes_made.
        """
        payload = {
            "text": text,
            "preserve_structure": preserve_structure,
            "language": language,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/text/correct-ocr", json=payload)
            response.raise_for_status()
            return response.json()

    async def format(
        self,
        text: str,
        target_format: str = "markdown",
        preserve_line_breaks: bool = True,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Format text to a specific format.

        Args:
            text: Text to format.
            target_format: Target format ('markdown', 'plain', 'structured').
            preserve_line_breaks: Whether to preserve line breaks.
            provider: LLM provider.
            model: LLM model.

        Returns:
            TextFormattingResult with formatted_text.
        """
        payload = {
            "text": text,
            "target_format": target_format,
            "preserve_line_breaks": preserve_line_breaks,
        }
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/text/format", json=payload)
            response.raise_for_status()
            return response.json()

    async def extract(
        self,
        text: str,
        fields: List[str],
        context: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Extract key information from text.

        Args:
            text: Text to extract from.
            fields: Fields to extract (e.g., ['cnpj', 'razao_social']).
            context: Additional context about the document.
            provider: LLM provider.
            model: LLM model.

        Returns:
            KeyInfoExtractionResult with extracted_fields, confidence.
        """
        payload = {
            "text": text,
            "fields": fields,
        }
        if context:
            payload["context"] = context
        if provider:
            payload["provider"] = provider
        if model:
            payload["model"] = model

        async with self._client._get_client() as client:
            response = await client.post("/text/extract", json=payload)
            response.raise_for_status()
            return response.json()
