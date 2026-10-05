"""B1 — redução mérito-level de 1 passada (L3_MERITO_SYNTHESIS_V2).

Substitui o per-processo→merge do L3 legado por UMA síntese que vê os N processos
JUNTOS sobre um dossiê coerente (valência + doc-text dos rulings + suspensão/garantia/
exposição). Semente = a CONVENTION do oráculo da redução (validada no gate-0 em
gemini-3.5-flash, com o resíduo controlável pelos 3 gates).
"""
from .agent import classify_merito_reducao_v2

__all__ = ["classify_merito_reducao_v2"]
