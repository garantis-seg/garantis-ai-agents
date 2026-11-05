"""O nome da parte intimada a pagar (`intimacao_pagamento_parte`) e a decisão administrativa
juntada como `prova_anexa`: as 2 regras do E10 e do CARF na leitura nova.

1. O E10 comparava só o POLO intimado com o do Tomador. No processo com outra parte no polo dele (o
   coexecutado, o sócio redirecionado), a intimação dela também saía como E10. O L1 passa a copiar
   o NOME da parte quando o ato o traz, e o frontend-api compara o nome com o do Tomador
   (garantis-shared `parte_e_o_tomador`). Sem o nome, vale o polo.
2. A leitura tipava como `acordao` o acórdão do CARF juntado como prova, e o evento ganhava um E2
   que não é ato do processo. A taxonomia passa a mandar a decisão de órgão administrativo para
   `prova_anexa`.

As outras metades: a coluna (migration do frontend-api) e a linha tipada (garantis-shared
`card_to_row`).

Run: pytest tests/test_intimacao_pagamento_parte_l1.py -q
"""
from __future__ import annotations

import typing

import pytest

from src.agents.mov_factsheet.chunking import reduce_peca_cards
from src.agents.mov_factsheet.fundacao import TAXONOMIA_TIPO_DOC
from src.agents.mov_factsheet.prompts_v4 import _REGRAS_CRUS
from src.agents.mov_factsheet.schemas_v4 import MovFactSheetCardV4, PeticaoExtractCardV4

CAMPO = "intimacao_pagamento_parte"
POLO = "intimacao_pagamento_polo"


class TestONomeDaParte:
    def test_mon07_120_7_o_schema_da_leitura_tem_o_nome_da_parte_intimada(self):
        """O campo é texto livre e nasce vazio: default diferente de None faria todo card nomear
        uma parte por omissão."""
        f = MovFactSheetCardV4.model_fields[CAMPO]
        assert f.default is None
        assert typing.get_args(f.annotation) == (str, type(None))
        assert PeticaoExtractCardV4.model_fields[CAMPO].default is None

    def test_a_descricao_pede_o_nome_copiado_e_null_sem_ele(self):
        """O nome tirado dos polos seria palpite: com 2 executados, o L1 escolheria um. O papel
        ('a executada') no lugar do nome não identifica ninguém."""
        desc = MovFactSheetCardV4.model_fields[CAMPO].description
        for termo in ("NOME", "COPIADO", "'; '", "null", "papel", "CONTEXTO DO PROCESSO", POLO):
            assert termo in desc, termo

    def test_o_prompt_repete_a_regra(self):
        assert f"- {CAMPO}:" in _REGRAS_CRUS


class TestAPeticaoInicial:
    def test_a_peticao_inicial_sai_sem_o_nome_mesmo_quando_a_leitura_o_preenche(self):
        """A inicial PEDE a intimação: o pedido não é o ato, para o polo e para o nome."""
        from src.agents.mov_factsheet.agent import _build_card_v4
        from src.agents.mov_factsheet.schemas import MovInput

        parsed = {"resumo_ato": "Requer a intimação da executada ACME para pagar.",
                  "tipo_doc": "peticao_inicial", "relevancia_merito": "media",
                  POLO: "passivo", CAMPO: "ACME S.A."}
        mov = MovInput(mov_id="peticao-x", texto="")
        card = _build_card_v4(parsed, mov, card_cls=PeticaoExtractCardV4, classe="peticao")
        assert card[CAMPO] is None and card[POLO] is None
        # controle: o ramo da movimentação guarda o nome que a leitura deu
        assert _build_card_v4({**parsed, "tipo_doc": "despacho"}, mov)[CAMPO] == "ACME S.A."


class TestAPecaChunkada:
    @staticmethod
    def _cards(n: int) -> list[dict]:
        return [{"mov_id": "m", "resumo_ato": f"parte {i}", "tipo_doc": "despacho",
                 "relevancia_merito": "alta", "decisao": {}, "evento_garantia": {"tipo": "nenhum"},
                 "valores": {}} for i in range(n)]

    def test_o_reduce_junta_os_nomes_de_todos_os_pedacos(self):
        """O coexecutado num pedaço e o Tomador noutro: guardar só o 1º nome perderia o E10 do
        Tomador. O nome repetido entra 1 vez."""
        cards = self._cards(3)
        cards[0][CAMPO] = "JOAO DA SILVA"
        cards[1][CAMPO] = "ACME S.A."
        cards[2][CAMPO] = "JOAO DA SILVA"
        assert reduce_peca_cards(cards)[CAMPO] == "JOAO DA SILVA; ACME S.A."

    def test_sem_o_nome_em_pedaco_nenhum_o_reduce_da_None(self):
        assert reduce_peca_cards(self._cards(2))[CAMPO] is None


class TestOL2NaoMuda:
    def test_o_prompt_do_L2_e_BYTE_IDENTICO_com_e_sem_o_nome(self):
        """O nome serve o evento da lista da Daycoval, e não o risco: o L2 monta o prompt chave a
        chave, e a chave nova não entra nele."""
        from src.agents.processo_synthesis.prompts import _summarize_factsheet
        from src.agents.processo_synthesis.schemas import MovFactSheetMin

        base = {"mov_id": "m1", "data": "2026-03-25", "origem": "mov", "tipo_doc": "despacho",
                "resumo_ato": "Intime-se a devedora ACME para pagar em 15 dias.",
                "decisao": {"tem_decisao": False}, "evento_garantia": {"tipo": "nenhum"},
                POLO: "passivo"}
        sem = _summarize_factsheet(MovFactSheetMin(**base))
        com = _summarize_factsheet(MovFactSheetMin(**base, **{CAMPO: "ACME S.A."}))
        assert com == sem


def _linha(tipo: str) -> str:
    """A linha do tipo na prosa da taxonomia, com as linhas de continuação."""
    linhas = TAXONOMIA_TIPO_DOC.splitlines()
    i = next(n for n, linha in enumerate(linhas) if linha.strip().startswith(tipo + " "))
    fim = next((n for n in range(i + 1, len(linhas)) if not linhas[n].startswith(" " * 29)),
               len(linhas))
    return " ".join(linhas[i:fim])


class TestADecisaoAdministrativaJuntada:
    @pytest.mark.parametrize("orgao", ["CARF", "CSRF", "DRJ", "TIT"])
    def test_mon07_120_8_a_decisao_administrativa_juntada_e_prova_anexa(self, orgao):
        """A taxonomia (o texto do prompt) e a descrição do campo mandam a decisão do órgão
        administrativo para `prova_anexa`: ela não é ato deste processo."""
        assert orgao in _linha("prova_anexa")
        assert orgao in MovFactSheetCardV4.model_fields["tipo_doc"].description

    def test_o_acordao_e_so_o_do_tribunal_judicial(self):
        assert "JUDICIAL" in _linha("acordao")

    def test_a_taxonomia_segue_com_os_34_tipos_do_schema(self):
        """CONTROLE: a prosa mudou, e a lista de tipos não. Cada tipo do Literal abre 1 linha."""
        from src.agents.mov_factsheet.schemas_v4 import _TIPO_DOC_VALORES

        for tipo in _TIPO_DOC_VALORES:
            assert _linha(tipo)
