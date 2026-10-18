"""O `risco_processo_intermediario` nao existe mais no L2 nem no L3.

O L2 o emitia em toda chamada, e so o prompt do L3 legado o lia. O L2 segue com o par
`risco_factual` + `risco_jurisprudencial`, e a escala que o `risco_factual` cita fica no
prompt. O card L2 ja gravado ainda traz o campo: o L3 o aceita e o ignora.
"""
from __future__ import annotations

from src.agents.merito_synthesis.prompts import build_merito_synthesis_prompt
from src.agents.merito_synthesis.schemas import MeritoSynthesisRequest
from src.agents.processo_synthesis.prompts import build_processo_synthesis_prompt
from src.agents.processo_synthesis.schemas import (
    MovFactSheetMin,
    ProcessoSynthesisCard,
    ProcessoSynthesisCardRich,
    ProcessoSynthesisRequest,
)


def test_l2_o_campo_saiu_do_schema_e_do_prompt():
    assert "risco_processo_intermediario" not in ProcessoSynthesisCard.model_fields
    assert "risco_processo_intermediario" not in ProcessoSynthesisCardRich.model_fields
    p = build_processo_synthesis_prompt(ProcessoSynthesisRequest(
        processo_numero="0", mov_factsheets=[MovFactSheetMin(mov_id="m1", data="2024-01-01")],
    ))
    assert "risco_processo_intermediario" not in p
    # A escala que o risco_factual cita continua no prompt.
    assert "A escala esta no item 4." in p
    assert "4. Escala do risco_factual" in p


def test_l3_o_card_l2_antigo_e_aceito_e_o_campo_nao_entra_no_prompt():
    antigo = {"processo_numero": "0", "estado_processual": "execucao em curso",
              "risco_processo_intermediario": "SENTINELA_DO_CARD_ANTIGO"}
    p = build_merito_synthesis_prompt(MeritoSynthesisRequest(merito_id=1, processo_syntheses=[antigo]))
    assert "SENTINELA_DO_CARD_ANTIGO" not in p
    assert "Risco intermediario:" not in p
    # Controle: o mesmo card ainda chega ao prompt.
    assert "Estado: execucao em curso" in p
