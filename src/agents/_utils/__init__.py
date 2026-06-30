"""Utilities compartilhadas entre agents."""
from .feature_flags import flag_enabled
from .llm_seed import deterministic_seed, seed_for
from .vision import (
    MODEL_VARIANT_TEXT,
    MODEL_VARIANT_VISION,
    ModelVariant,
    call_l1_with_vision_fallback,
    call_vision_l1,
    fetch_pdfs_from_gcs,
)

__all__ = [
    "MODEL_VARIANT_TEXT",
    "MODEL_VARIANT_VISION",
    "ModelVariant",
    "call_l1_with_vision_fallback",
    "call_vision_l1",
    "deterministic_seed",
    "fetch_pdfs_from_gcs",
    "flag_enabled",
    "seed_for",
]
