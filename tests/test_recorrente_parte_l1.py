"""O nome de quem recorreu (`recorrente_parte`): a leitura copia o nome do ato, e o sentido do recurso
compara o nome com o do Tomador.

O sentido comparava o polo que a leitura dá ao recorrente com o polo do Tomador, e os 2 não saem da
mesma fonte. Em 4 acórdãos reais, o Tomador perdeu o recurso e o sentido saiu favorável. Sem o nome,
tudo fica como antes.

As outras metades: a coluna (migration do frontend-api), a linha tipada e a régua do lado
(garantis-shared `card_to_row` e `recorrente_pelo_nome`).

Run: pytest tests/test_recorrente_parte_l1.py -q
"""
from __future__ import annotations

import typing

from src.agents.mov_factsheet.agent import _build_card_v4
from src.agents.mov_factsheet.chunking import reduce_peca_cards
from src.agents.mov_factsheet.prompts_v4 import _REGRAS_CRUS
from src.agents.mov_factsheet.schemas import MovInput
from src.agents.mov_factsheet.schemas_v4 import MovFactSheetCardV4, PeticaoExtractCardV4

CAMPO = "recorrente_parte"
NOME = "COMPANHIA ESTADUAL DE AGUAS E ESGOTOS CEDAE"
ANCORA = f"CONHECIDO O RECURSO DE {NOME} E NÃO PROVIDO"


def _parsed(**decisao) -> dict:
    d = {"tem_decisao": True, "provido": "nao", "recorrente_polo": "ativo",
         "natureza": "improcedente", "dispositivo": ANCORA, **decisao}
    return {"resumo_ato": "O tribunal negou provimento ao recurso.", "tipo_doc": "acordao",
            "relevancia_merito": "alta", "decisao": d, CAMPO: NOME}


def _mov() -> MovInput:
    return MovInput(mov_id="m", texto=ANCORA + " " + "texto do acórdão " * 10)


class TestOSchema:
    def test_r4_sentido_o_schema_tem_o_nome_de_quem_recorreu_e_ele_nasce_vazio(self):
        f = MovFactSheetCardV4.model_fields[CAMPO]
        assert f.default is None
        assert typing.get_args(f.annotation) == (str, type(None))
        assert PeticaoExtractCardV4.model_fields[CAMPO].default is None

    def test_r4_sentido_o_nome_e_o_ULTIMO_campo_do_card(self):
        """Sob constrained decoding a ordem dos campos é a ordem da saída: no fim, os campos antigos
        saem como antes."""
        assert list(MovFactSheetCardV4.model_fields)[-1] == CAMPO

    def test_a_descricao_pede_o_nome_copiado_e_null_sem_ele(self):
        """O nome tirado dos polos seria palpite. O papel ('a apelante') não identifica ninguém."""
        desc = MovFactSheetCardV4.model_fields[CAMPO].description
        for termo in ("NOME", "COPIADO", "'; '", "null", "papel", "CONTEXTO DO PROCESSO", "provido"):
            assert termo in desc, termo

    def test_mais_de_um_recorrente_com_um_sem_nome_sai_sem_nome(self):
        """'Nego provimento aos recursos da executada e de JOÃO': com só o JOÃO no campo, o sentido
        leria o recurso como do outro lado."""
        assert "algum recorrente fica sem nome" in MovFactSheetCardV4.model_fields[CAMPO].description
        assert "algum recorrente fica sem nome" in _REGRAS_CRUS

    def test_o_prompt_repete_a_regra(self):
        assert f"- {CAMPO}:" in _REGRAS_CRUS


class TestOCard:
    def test_r4_sentido_o_acordao_guarda_o_nome_que_a_leitura_deu(self):
        assert _build_card_v4(_parsed(), _mov())[CAMPO] == NOME

    def test_o_nome_sem_o_resultado_do_recurso_nao_fica_no_card(self):
        """O sentido só usa o nome com o `provido`. Sem ele, o nome não é de um recurso julgado."""
        assert _build_card_v4(_parsed(provido=None), _mov())[CAMPO] is None

    def test_a_decisao_sem_a_ancora_leva_o_nome_junto(self):
        """A trava do dispositivo zera a decisão, e o nome cai com ela."""
        assert _build_card_v4(_parsed(dispositivo=None), _mov())[CAMPO] is None

    def test_a_unidade_sem_corpo_leva_o_nome_junto(self):
        assert _build_card_v4(_parsed(), _mov(), sem_corpo=True)[CAMPO] is None

    def test_a_peticao_inicial_sai_sem_o_nome(self):
        """A petição é pedido da parte, e não decisão de recurso."""
        parsed = {**_parsed(tem_decisao=False, provido=None, dispositivo=None), "tipo_doc": "peticao_inicial"}
        card = _build_card_v4(parsed, MovInput(mov_id="peticao-x", texto=""),
                              card_cls=PeticaoExtractCardV4, classe="peticao")
        assert card[CAMPO] is None


class TestAPecaChunkada:
    @staticmethod
    def _cards(n: int) -> list[dict]:
        return [{"mov_id": "m", "resumo_ato": f"parte {i}", "tipo_doc": "acordao",
                 "relevancia_merito": "alta", "decisao": {}, "evento_garantia": {"tipo": "nenhum"},
                 "valores": {}} for i in range(n)]

    def test_r4_sentido_o_reduce_guarda_o_nome_do_pedaco_que_decide(self):
        """O `provido` vem do pedaço que decide, e o nome anda com ele. O relatório cita o recurso de
        outra parte num pedaço anterior, e esse nome não é o do recurso julgado."""
        cards = self._cards(2)
        cards[0][CAMPO] = "OUTRA PARTE"
        cards[1][CAMPO] = NOME
        cards[1]["decisao"] = {"tem_decisao": True, "natureza": "improcedente", "provido": "nao"}
        assert reduce_peca_cards(cards)[CAMPO] == NOME

    def test_o_pedaco_que_decide_sem_o_nome_deixa_o_card_sem_nome(self):
        cards = self._cards(2)
        cards[0][CAMPO] = "OUTRA PARTE"
        cards[1]["decisao"] = {"tem_decisao": True, "natureza": "improcedente", "provido": "nao"}
        assert reduce_peca_cards(cards)[CAMPO] is None


class TestOL2:
    def test_r4_sentido_o_prompt_do_L2_e_BYTE_IDENTICO_com_e_sem_o_nome(self):
        """O L2 lê o sentido, que o código deriva, e não o nome: o prompt é montado chave a chave."""
        from src.agents.processo_synthesis.prompts import _summarize_factsheet
        from src.agents.processo_synthesis.schemas import MovFactSheetMin

        base = {"mov_id": "m1", "data": "2026-06-24", "origem": "mov", "tipo_doc": "acordao",
                "resumo_ato": "O tribunal negou provimento ao recurso.",
                "decisao": {"tem_decisao": True, "provido": "nao", "sentido": "desfavoravel"},
                "evento_garantia": {"tipo": "nenhum"}}
        assert _summarize_factsheet(MovFactSheetMin(**base, **{CAMPO: NOME})) == _summarize_factsheet(
            MovFactSheetMin(**base))
