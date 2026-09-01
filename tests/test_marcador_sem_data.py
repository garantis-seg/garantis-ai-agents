"""A unidade SEM DATA declara a ausencia no prompt do L2, em vez de sair muda.

Medido 2026-09-01: 4.065 unidades sao renderizadas sem colchete de data em 93
processos — 1.873 delas COM decisao e 98 com transito certificado. Todas sao
classe 1D (documento orfao sem `juntada_at`). Elas entram no TOPO da timeline
(o sort e `(f.data or "", f.mov_id or "")`, entao None vira "" e ordena antes de
qualquer ISO), num bloco cujo cabecalho diz "ordenados por data ASC" — o LLM lia
"a mais antiga" onde o certo e "desconhecida".

⛔ NAO se conserta preenchendo a data: 14 fontes candidatas foram medidas e todas
as de DADO entregam JUNTAS 97 de 20.807 (0,47%) — a data nao existe a montante,
nao foi perdida no transporte. A unica fonte com cobertura (49,9%) e a INFERENCIA
do proprio LLM, que a decisao G.2 (2026-06-11) removeu da autoridade e cujas 3
colunas foram dropadas em 2026-09-01 (card 869etg201). Declarar a AUSENCIA nao
viola a G.2 porque nao afirma nada sobre QUANDO o ato aconteceu.

⭐ E o achado estrutural que fecha: o documento e 1D PORQUE nao tem vinculo com
movimento (`source_movimento_id` nao-nulo em 0 de 20.807), e e o mesmo vinculo
ausente que o deixa sem data. Nao existe ancora por construcao.
"""
from __future__ import annotations

from src.agents.processo_synthesis.prompts import _summarize_factsheet
from src.agents.processo_synthesis.schemas import MovFactSheetMin

_MOV_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _fs(**kw) -> MovFactSheetMin:
    base = {"mov_id": _MOV_ID, "data": None}
    base.update(kw)
    return MovFactSheetMin(**base)


def test_unidade_sem_data_declara_a_ausencia():
    linha = _summarize_factsheet(_fs(data=None))
    assert "[sem data]" in linha, (
        "a unidade sem data voltou a sair MUDA do prompt do L2. Sem o marcador ela "
        "entra no topo da timeline e o LLM le 'a mais antiga' onde o certo e "
        "'desconhecida'. Exposicao medida: 4.065 unidades em 93 processos, 1.873 "
        "delas com decisao."
    )


def test_unidade_COM_data_NAO_ganha_o_marcador():
    """Controle positivo. Sem ele, um marcador INCONDICIONAL passaria verde no teste
    acima e poluiria as ~374 mil unidades que TEM data."""
    linha = _summarize_factsheet(_fs(data="2026-03-14"))
    assert "[2026-03-14]" in linha
    assert "[sem data]" not in linha, (
        "o marcador de ausencia vazou pra unidade COM data — o `else` virou incondicional."
    )


def test_o_marcador_ocupa_a_MESMA_posicao_do_colchete_de_data():
    """A linha do timeline e POSICIONAL: o LLM le o 1o campo como a data. Um marcador
    anexado no fim seria lido como outra coisa — e o teste de presenca acima passaria
    verde do mesmo jeito."""
    com = _summarize_factsheet(_fs(data="2026-03-14"))
    sem = _summarize_factsheet(_fs(data=None))
    assert com.startswith("[2026-03-14]"), f"com data: {com[:40]!r}"
    assert sem.startswith("[sem data]"), f"sem data: {sem[:40]!r}"
