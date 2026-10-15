"""MON-06 · 2 leituras da decisao_vigente que o L2 errava em processo sem andamento.

Sem andamento (só autos do Escavador), o redutor do garantis-shared não tem linha do tempo
para consertar o L2. Então o prompt e o schema têm de dizer:
- DECISAO MISTA: mérito contra o Tomador + extinção de outra parte = vale o mérito (regra 7).
- recorrida: embargos de declaração e contrarrazões não são recurso pendente (regra 10).

Os nomes não levam o par card × cenário: estes testes provam o prompt, não um cenário do
cronograma.
"""
from __future__ import annotations

from src.agents.processo_synthesis.prompts import build_processo_synthesis_prompt
from src.agents.processo_synthesis.schemas import (
    DecisaoVigente,
    MovFactSheetMin,
    ProcessoSynthesisRequest,
)


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


def test_l2_anulacao_devolve_o_estagio_e_da_a_data():
    """Regra 4. O redutor do garantis-shared lê `anulacao_data` e tira o ruling da sentença
    anulada (o andamento só diz "Provimento em Parte"). Sem a data, o `natureza=null` da
    anulação voltaria derrota pelo P2. A causa madura e a anulação de um capítulo julgam ou
    mantêm o mérito: ali a data fica null."""
    secao = _secao_decisao_vigente(_prompt())
    regra = secao[secao.index("ANULACAO:"):]
    assert "DEVOLVE os autos a origem sem julgar o merito" in regra
    assert "anulacao_data = a data do acordao que anulou" in regra
    assert "causa madura" in regra and "SO um capitulo" in regra
    assert "nova sentenca ou acordao de merito" in regra
    assert "(mantenha anulacao_data)" in regra   # o redutor guarda o ruling posterior a ela
    assert "ANULACAO" in _lembrete(_prompt())
    desc = DecisaoVigente.model_fields["anulacao_data"].description or ""
    assert "anulou a sentenca" in desc
    # Optional[str] com descricao longa trava o decoder do Gemini (docstring do schema).
    assert len(desc) <= len(DecisaoVigente.model_fields["data"].description or "") * 3


def test_l2_embargos_de_declaracao_nao_sao_recurso_pendente():
    """O prompt e o `response_schema` dizem a mesma coisa: a descrição do campo vai ao
    Gemini junto com o schema, e uma contradição entre os dois deixa o LLM escolher."""
    secao = _secao_decisao_vigente(_prompt())
    linha = secao[secao.index("- recorrida:"):secao.index("- Se NAO ha decisao de merito")]
    assert "Embargos de declaracao (acolhidos ou rejeitados) e\n     contrarrazoes NAO contam" in linha
    assert "Prazo aberto sem recurso interposto tambem e false" in linha
    assert "Embargos de declaracao e contrarrazoes NAO tornam recorrida=true" in _lembrete(_prompt())
    desc = DecisaoVigente.model_fields["recorrida"].description or ""
    assert "ainda pendente" in desc
    assert "Embargos de declaracao e contrarrazoes NAO contam" in desc
