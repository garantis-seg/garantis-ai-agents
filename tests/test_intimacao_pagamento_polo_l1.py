"""O campo do E10 no L1 — `intimacao_pagamento_polo` — e o `acionamento` que deixa de pegar a
intimação de uma parte.

O E10 da lista da Daycoval ("intimação do tomador para pagar") não tinha campo na leitura: o
despacho "intime-se a devedora para pagar em 15 dias" saía sem evento de garantia, ou como
`acionamento`, que é o E9 (a ordem de pagar com a GARANTIA). O campo é NEUTRO: o L1 diz o polo,
e quem decide se ele é o do Tomador é o código (frontend-api, `services/monit_eventos.py`).

As outras metades: a coluna (migration do frontend-api) e a linha tipada (garantis-shared
`card_to_row`).

Run: pytest tests/test_intimacao_pagamento_polo_l1.py -q
"""
from __future__ import annotations

import typing

import pytest

from src.agents.mov_factsheet.chunking import reduce_peca_cards
from src.agents.mov_factsheet.prompts_v4 import _REGRAS_CRUS
from src.agents.mov_factsheet.schemas_v4 import (
    EventoGarantiaV4,
    MovFactSheetCardV4,
    PeticaoExtractCardV4,
)

CAMPO = "intimacao_pagamento_polo"


class TestOSchemaDoL1:
    def test_mon07_120_2_o_schema_da_leitura_tem_o_campo_do_e10(self):
        """O campo existe, diz só o POLO (neutro) e nasce vazio: default diferente de None faria
        todo card AFIRMAR uma intimação por omissão."""
        f = MovFactSheetCardV4.model_fields[CAMPO]
        assert f.default is None
        valores = set(typing.get_args(typing.get_args(f.annotation)[0]))
        assert valores == {"ativo", "passivo"}

    def test_os_campos_do_e10_estao_no_FIM_do_card(self):
        """Sob constrained decoding a ordem dos campos é a ordem da saída: no fim, os campos
        antigos saem como antes. O nome da parte vem logo depois do polo. Depois deles, só o nome
        de quem recorreu."""
        assert list(MovFactSheetCardV4.model_fields)[-3:] == [CAMPO, "intimacao_pagamento_parte",
                                                              "recorrente_parte"]

    def test_a_peticao_herda_o_campo_vazio(self):
        """O schema da petição herda o do card: a peça de parte não intima ninguém, e o campo
        nasce null nela."""
        assert PeticaoExtractCardV4.model_fields[CAMPO].default is None

    def test_a_descricao_exclui_custas_honorarios_a_citacao_e_a_peca_de_parte(self):
        desc = MovFactSheetCardV4.model_fields[CAMPO].description.lower()
        for termo in ("custas", "honorários", "citação", "peça de parte", "acionamento"):
            assert termo in desc, termo


class TestAPeticaoInicial:
    def test_a_peticao_inicial_sai_sem_o_campo_mesmo_quando_a_leitura_o_preenche(self):
        """A inicial PEDE a intimação: o pedido não é o ato. O prompt do 1P não traz a regra do
        campo, então o card da petição o zera no código."""
        from src.agents.mov_factsheet.agent import _build_card_v4
        from src.agents.mov_factsheet.schemas import MovInput

        parsed = {"resumo_ato": "Requer a intimação da executada para pagar.",
                  "tipo_doc": "peticao_inicial", "relevancia_merito": "media", CAMPO: "passivo"}
        mov = MovInput(mov_id="peticao-x", texto="")
        assert _build_card_v4(parsed, mov, card_cls=PeticaoExtractCardV4, classe="peticao")[CAMPO] is None
        # controle: o ramo da movimentação guarda o polo que a leitura deu
        assert _build_card_v4({**parsed, "tipo_doc": "despacho"}, mov)[CAMPO] == "passivo"


class TestOAcionamento:
    def test_mon07_120_2_o_acionamento_exclui_a_intimacao_de_uma_parte(self):
        """A descrição do `acionamento` manda a intimação de uma PARTE para o campo novo. Sem
        isto, o despacho que intima o tomador a pagar seguiria saindo como E9."""
        desc = EventoGarantiaV4.model_fields["tipo"].description
        assert CAMPO in desc and "PARTE" in desc

    def test_o_prompt_repete_a_regra_nos_2_campos(self):
        """O `_REGRAS_CRUS` repete a regra do `acionamento`: o prompt e o schema dizendo coisas
        diferentes seria pior que um só."""
        assert CAMPO in _REGRAS_CRUS
        trecho = _REGRAS_CRUS.split("evento_garantia.tipo='acionamento'", 1)[1]
        assert "NÃO é" in trecho.split("- intimacao_pagamento_polo", 1)[0]


class TestAPecaChunkada:
    @pytest.mark.parametrize("posicao", [0, 1, 2])
    def test_o_reduce_guarda_o_campo_de_qualquer_pedaco(self, posicao):
        """Fora do reduce, a peça grande perderia o campo em silêncio."""
        cards = [{"mov_id": "m", "resumo_ato": f"parte {i}", "tipo_doc": "despacho",
                  "relevancia_merito": "alta", "decisao": {}, "evento_garantia": {"tipo": "nenhum"},
                  "valores": {}} for i in range(3)]
        cards[posicao][CAMPO] = "passivo"
        assert reduce_peca_cards(cards)[CAMPO] == "passivo"

    def test_sem_o_campo_em_pedaco_nenhum_o_reduce_da_None(self):
        cards = [{"mov_id": "m", "resumo_ato": "x", "tipo_doc": "despacho", "decisao": {},
                  "evento_garantia": {"tipo": "nenhum"}, "valores": {}}]
        assert reduce_peca_cards(cards)[CAMPO] is None


class TestOL2NaoMuda:
    def test_o_prompt_do_L2_e_BYTE_IDENTICO_com_e_sem_o_campo(self):
        """O campo serve o evento da lista da Daycoval, e não o risco: o L2 monta o prompt
        chave a chave, e a chave nova não entra nele. A faixa de risco só muda pelo
        `acionamento` mais estreito, na leitura nova."""
        from src.agents.processo_synthesis.prompts import _summarize_factsheet
        from src.agents.processo_synthesis.schemas import MovFactSheetMin

        base = {"mov_id": "m1", "data": "2026-03-25", "origem": "mov", "tipo_doc": "despacho",
                "resumo_ato": "Intime-se a devedora para pagar em 15 dias.",
                "decisao": {"tem_decisao": False}, "evento_garantia": {"tipo": "nenhum"}}
        sem = _summarize_factsheet(MovFactSheetMin(**base))
        com = _summarize_factsheet(MovFactSheetMin(**base, **{CAMPO: "passivo"}))
        assert com == sem
