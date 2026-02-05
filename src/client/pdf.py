"""
PDF processing client.
"""

from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .client import GarantisAIClient


class PdfClient:
    """Client for PDF processing endpoints."""

    def __init__(self, client: "GarantisAIClient"):
        self._client = client

    async def ocr(
        self,
        pdf_base64: str,
        filename: str = "document.pdf",
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert a scanned PDF to Markdown using Gemini Vision OCR.

        Args:
            pdf_base64: Base64-encoded PDF bytes.
            filename: Original filename.
            model: Gemini model.
            provider: LLM provider.

        Returns:
            PdfOcrResult dict with markdown_text, tokens, cost.
        """
        payload = {
            "pdf_base64": pdf_base64,
            "filename": filename,
        }
        if model:
            payload["model"] = model
        if provider:
            payload["provider"] = provider

        async with self._client._get_client() as client:
            response = await client.post("/pdf/ocr", json=payload)
            response.raise_for_status()
            return response.json()
