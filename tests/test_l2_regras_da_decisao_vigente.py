"""MON-06 · 3 leituras da decisao_vigente que o L2 errava em processo sem andamento.

Sem andamento (só autos do Escavador), o redutor do garantis-shared não tem linha do tempo
para corrigir o L2. Então o prompt tem de dizer:
- DECISAO MISTA: mérito contra o Tomador + extinção de outra parte = vale o mérito (regra 7).
- ANULACAO: "parcial provimento" que anula a sentença não é procedência parcial (regra 4).
- recorrida: embargos de declaração e contrarrazões não são recurso pendente (regra 10).

Os nomes não levam o par card × cenário: estes testes provam o prompt, não um cenário do
cronograma.
"""
from __future__ import annotations

from src.agents.processo_synthesis.prompts import build_processo_synthesis_prompt
from src.agents.processo_synthesis.schemas import MovFactSheetMin, ProcessoSynthesisRequest


def _prompt() -> str:
    req = ProcessoSynthesisRequest(
        processo_numero="10087315520184013400", classe="PROCEDIMENTO COMUM CIVEL",
        tipo_judicial="fiscal", apolices=[],
        mov_factsheets=[MovFactSheetMin(mov_id="m1", data="2026-06-02", categoria="acordao",
                                        relevancia_merito="alta", resumo_ato="acordao")],
    )
    return build_processo_synthesis_prompt(req)


def _secao_decisao_vigente(p: str) -> str:
    ini = p.index("2. decisao_vigente:")
    return p[ini:p.index("3. lifecycle_garantia:", ini)]


def _lembrete(p: str) -> str:
    return p[p.index("<lembrete_final>"):p.index("</lembrete_final>")]


def test_l2_decisao_mista_vale_o_merito():
    secao = _secao_decisao_vigente(_prompt())
    assert "DECISAO MISTA" in secao
    assert "A decisao_vigente\n   e a parte de MERITO" in secao
    assert "extincao encerra o processo INTEIRO do Tomador" in secao
    assert "DECISAO MISTA" in _lembrete(_prompt())


def test_l2_anulacao_por_parcial_provimento_nao_e_merito():
    secao = _secao_decisao_vigente(_prompt())
    assert "ANULACAO" in secao
    assert "TOTAL OU PARCIAL" in secao
    assert "SEM decisao de merito: natureza=null e\n   sentido=null" in secao
    assert "transito_certificado=false" in secao.split("ANULACAO", 1)[1]
    assert "ANULACAO da sentenca" in _lembrete(_prompt())


def test_l2_embargos_de_declaracao_nao_sao_recurso_pendente():
    secao = _secao_decisao_vigente(_prompt())
    linha = secao[secao.index("- recorrida:"):secao.index("- Se NAO ha decisao de merito")]
    assert "Embargos de declaracao (acolhidos ou rejeitados) e\n     contrarrazoes NAO contam" in linha
    assert "Prazo aberto sem recurso interposto tambem e false" in linha
    assert "Embargos de declaracao e contrarrazoes NAO tornam recorrida=true" in _lembrete(_prompt())
