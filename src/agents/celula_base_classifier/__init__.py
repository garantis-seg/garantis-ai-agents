"""Classificador estreito de celula-base (D1) — N=3 leitura por merito, unanime = sinal do piso L3.

O engine (materializer L3) monta o dossie coerente e POSTa aqui SO quando banda==Baixo e a flag
CELULA_BASE_CLASSIFIER_ENABLED liga; o sinal unanime alimenta derive_risco_celula_base_floor
(Baixo->Medio, surety-safe). Referencia = adjudicacao 76/76 (report-celula-base-classifier).
"""
from .agent import CelulaBaseClassifyRequest, classify_celula_base

__all__ = ["CelulaBaseClassifyRequest", "classify_celula_base"]
