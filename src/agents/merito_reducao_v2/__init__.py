"""B1 — redução mérito-level de 1 passada (L3_MERITO_SYNTHESIS_V2).

Substitui o per-processo→merge do L3 legado por UMA síntese que vê os N processos
JUNTOS sobre um dossiê coerente (valência + doc-text dos rulings + suspensão/garantia/
exposição). Semente = a CONVENTION do oráculo da redução (gate-0 provou em gemini-3.5-flash:
14/19 consensus-miss recuperados, net consenso 57%→77%, resíduo controlável pelos 3 gates).
Report: ~/.claude/plans/report-gate0-flash-B1-2026-07-11.md.
"""
from .agent import classify_merito_reducao_v2

__all__ = ["classify_merito_reducao_v2"]
