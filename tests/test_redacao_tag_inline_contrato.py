"""O texto ENTRE COLCHETES da tag inline e o FATO, nunca o numero do processo.

Medido em 2026-07-27: 69,7% das tags do passe de redacao saiam como
`[5018681-38.2023.4.03.6100](5018681-38.2023.4.03.6100)` — o front linkava o
proprio CNJ no meio da frase, redundante (o leitor ja esta nesse processo), em vez
de linkar a decisao que sustenta a banda.

Causa: "Cite o CNJ dos processos relevantes." estava colada na instrucao da tag, na
MESMA sentenca, e o passe nao tinha exemplo. Este teste guarda as 3 propriedades do
prompt que impedem a recaida.
"""
import re

from src.agents.merito_synthesis.prompts import (
    REDACAO_PROMPT_VERSION,
    build_redacao_prompt,
)
from src.agents.merito_synthesis.schemas import RedacaoCard, RedacaoRequest

CNJ_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")


def _prompt(risco: str = "Medio") -> str:
    return build_redacao_prompt(RedacaoRequest(merito_id=1, risco_final=risco))


def test_nao_manda_mais_citar_cnj_colado_na_tag():
    """A frase toxica que ensinava o modelo a por o CNJ no colchete."""
    p = _prompt()
    assert "Cite o CNJ dos processos relevantes" not in p


def test_tem_instrucao_negativa_explicita():
    p = _prompt().lower()
    assert "nunca ponha o numero do processo dentro dos" in p


def test_tem_par_certo_errado():
    """Contraste ensina melhor que regra — o passe nao tinha exemplo nenhum."""
    p = _prompt()
    assert "CERTO" in p and "ERRADO" in p
    certo = p.split("CERTO", 1)[1].split("ERRADO", 1)[0]
    errado = p.split("ERRADO", 1)[1][:400]
    # no exemplo CERTO o colchete tem prosa; no ERRADO tem o CNJ
    m_certo = re.search(r"\[([^\]]+)\]", certo)
    m_errado = re.search(r"\[([^\]]+)\]", errado)
    assert m_certo and not CNJ_RE.search(m_certo.group(1)), "exemplo CERTO nao pode ter CNJ no colchete"
    assert m_errado and CNJ_RE.search(m_errado.group(1)), "exemplo ERRADO tem que mostrar o CNJ no colchete"


def test_schema_nao_pede_cite_cnj_solto():
    desc = RedacaoCard.model_fields["justificativa"].description or ""
    assert "Cite CNJ." not in desc
    assert "nunca o numero do processo" in desc.lower()


def test_versao_do_prompt_bumpada():
    """Prompt mudou -> versao muda (telemetria consegue separar antes/depois)."""
    assert REDACAO_PROMPT_VERSION == "redacao.v1.2"
