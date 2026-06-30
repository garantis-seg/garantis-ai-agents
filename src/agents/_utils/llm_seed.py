"""Seed determinístico pros calls Gemini do cascade (L2/L3).

Os agents já chamam o Gemini com `temperature=0.0, top_p=1.0, top_k=1,
thinking_budget=0` (greedy strict). Mesmo assim o Gemini a temp=0 SEM seed tem
micro-ruído entre runs (decode não-determinístico residual) — e a re-síntese do
L2 oscila entre re-cascates (memory `volatilidade-L3-raiz-e-reextração-L1-cold`).
Fixar o `seed` torna o call reproduzível DADO o input: mesmo prompt → mesma banda
N×. Fecha o ~2% de ruído do L3 + a re-síntese não-determinística do L2, e torna o
gate volatility-robust reproduzível.

Gated em ENGINE_LLM_SEED_ENABLED (default OFF — ship inerte + flip explícito, igual
aos #1/#4 e ao estilo da casa pra surety-change; é tightening de determinismo a temp=0,
surety-neutro). Flip prod: `--update-env-vars ENGINE_LLM_SEED_ENABLED=true` (ou
services.yaml+cloudbuild p/ persistir). O gate L3-only seta ON pra medir o spread~0.
"""
import hashlib

from .feature_flags import flag_enabled

_SEED_FLAG = "ENGINE_LLM_SEED_ENABLED"


def deterministic_seed(*parts: object) -> int:
    """Seed estável (0..2^31-1) das `parts` via SHA-256.

    NÃO usa `hash()` builtin — ele é salgado por processo (PYTHONHASHSEED) e dá
    valor diferente a cada container Cloud Run, quebrando a reprodutibilidade.
    `\\x1f` separa as parts (evita colisão de concatenação). Mascarado pra int32
    positivo (range aceito pelo Gemini).
    """
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) & 0x7FFFFFFF


def seed_for(*parts: object) -> int | None:
    """`deterministic_seed(*parts)` quando ENGINE_LLM_SEED_ENABLED, senão None.

    Passar `seed=None` pro provider é no-op (Gemini usa seed aleatório) — então o
    caller pode sempre `agenerate(..., seed=seed_for(...))` sem branch.
    """
    if not flag_enabled(_SEED_FLAG, default="false"):
        return None
    return deterministic_seed(*parts)
