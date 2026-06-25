"""Giant-filter v2 (2026-06-25): teto duro de cards renderizados em processo gigante,
sem nunca evictar SINAL em favor de media. Resolve os stragglers L2-ReadTimeout
(633163/1409966). Foldado com a condição A determinística.
"""
from __future__ import annotations

from src.agents.processo_synthesis.prompts import (
    _L2_CARD_FILTER_THRESHOLD,
    _L2_MAX_KEPT,
    _filtered_cards,
)
from src.agents.processo_synthesis.schemas import MovFactSheetMin


def _m(i, rel="ruido", *, tem_decisao=False, cautelar=None, evento=None):
    return MovFactSheetMin(
        mov_id=f"{i:08d}-0000-4000-8000-000000000000", data=f"2020-01-{(i % 28) + 1:02d}",
        relevancia_merito=rel,
        decisao={"tem_decisao": tem_decisao, "instrumento_cautelar": cautelar},
        evento_garantia={"tipo": evento or "nenhum"},
    )


def test_small_proc_unchanged():
    """<= threshold: render tudo, byte-idêntico (caminho quente intocado)."""
    movs = [_m(i) for i in range(_L2_CARD_FILTER_THRESHOLD)]
    kept, omit = _filtered_cards(movs)
    assert omit == 0 and len(kept) == len(movs)


def test_giant_caps_media_but_keeps_all_signal():
    """Gigante: ruído cortado, media até o teto, TODO sinal mantido."""
    movs = []
    movs += [_m(i, "ruido") for i in range(400)]            # 400 ruído -> cortados
    movs += [_m(1000 + i, "media") for i in range(200)]     # 200 media -> capadas
    movs += [_m(2000 + i, "alta") for i in range(10)]       # 10 alta (sinal) -> sempre
    movs += [_m(3000 + i, "baixa", tem_decisao=True) for i in range(5)]  # 5 decisões -> sempre
    kept, omit = _filtered_cards(movs)
    kept_ids = {m.mov_id for m in kept}
    # todo sinal presente
    for i in range(10):
        assert f"{2000 + i:08d}-0000-4000-8000-000000000000" in kept_ids
    for i in range(5):
        assert f"{3000 + i:08d}-0000-4000-8000-000000000000" in kept_ids
    # teto respeitado (sinal + media não estoura muito além do teto + cauda)
    assert len(kept) <= _L2_MAX_KEPT + 5  # folga p/ cauda recente
    assert omit > 300  # a maioria do ruído saiu


def test_hard_signal_never_evicted_even_above_cap():
    """Se há MAIS sinal que o teto, kept passa do teto (segurança > custo) — nunca corta sinal."""
    movs = [_m(i, "baixa", tem_decisao=True) for i in range(80)]  # 80 decisões > teto 50
    movs += [_m(1000 + i, "ruido") for i in range(300)]
    kept, _ = _filtered_cards(movs)
    # as 80 decisões TODAS presentes (nenhuma evictada pelo teto)
    decisao_ids = {f"{i:08d}-0000-4000-8000-000000000000" for i in range(80)}
    assert decisao_ids <= {m.mov_id for m in kept}


def test_suspension_signal_always_kept_even_if_media():
    """Mov com instrumento_cautelar é sinal de suspensão -> hard-keep mesmo sendo 'media'
    (preserva pra quando a suspensão derivada aterrissar)."""
    movs = [_m(i, "ruido") for i in range(400)]
    susp = _m(9999, "media", cautelar="suspensao_exigibilidade_ctn")
    movs.append(susp)
    kept, _ = _filtered_cards(movs)
    assert susp.mov_id in {m.mov_id for m in kept}
