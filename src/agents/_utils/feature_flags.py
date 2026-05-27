"""Feature flag helper compartilhado entre agents.

Pattern extraído de `merito_synthesis/prompts.py::_flag_enabled` (Sprint 2 P&P
E4-E7) pra reuso em outros agents — VISION_L1_ENABLED é o primeiro consumer.

Env vars são estáticas durante o lifetime do container Cloud Run; restart pra
rotacionar.
"""
import os


def flag_enabled(name: str, default: str = "false") -> bool:
    """Lê env var como bool.

    Default `false` (OFF) porque a maioria dos flags adicionados pós-Sprint 2
    são opt-in (experimentos). Callers que querem default ON passam
    `default="true"` explicitamente.

    Aceita: "true", "1", "yes", "on" (case-insensitive). Qualquer outro = False.
    """
    return os.environ.get(name, default).strip().lower() in {"true", "1", "yes", "on"}
