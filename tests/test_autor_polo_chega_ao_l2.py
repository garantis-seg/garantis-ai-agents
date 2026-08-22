"""`autor_polo` sai do L1 e CHEGA ao prompt do L2 — fatias 3 e 4 do 869efuvwk.

O DEFEITO. Sentenca de EMBARGOS A EXECUCAO trasladada pros autos da EXECUCAO julga OUTRA
acao: la o autor e o EMBARGANTE, que e o EXECUTADO da execucao. O `<regra_polos>` do L2
bucketiza pela CLASSE DO PROCESSO — a regra de cada bucket esta certa, o que erra e a
ATRIBUICAO do bucket quando a decisao nao e da acao daquele processo. Resultado medido em
prod: 29 cards / 22 PNs de classe Execucao Fiscal / 18 meritos (15 com apolice) com o
sentido invertido; o mais claro e `50329845120204047000` (embargos PROCEDENTES, o tomador
GANHOU, e o card diz desfavoravel).

⭐⭐ POR QUE O TESTE DO RENDER E O QUE IMPORTA. `_summarize_factsheet` monta a linha da
timeline escolhendo CHAVE A CHAVE (`natureza`, `instancia`, `sentido`,
`transito_certificado`). Campo que nao esta ali **nao chega ao LLM**, por mais que o
prompt fale dele. A 1a versao desta fatia mexeu so no prompt — e teria sido LETRA MORTA:
instrucao sem dado nao muda nada, e o modo de falha e invisivel (nenhum erro, nenhum log,
so o mesmo veredito de antes).

⚠️ `MovFactSheetMin.decisao` e `dict[str, Any]` livre, entao o campo ATRAVESSA o schema
sozinho — o que engana: passar pelo schema nao e chegar ao prompt.

Run: pytest tests/test_autor_polo_chega_ao_l2.py -q
"""
from __future__ import annotations

from src.agents.mov_factsheet.schemas_v4 import DecisaoBlockV4
from src.agents.processo_synthesis.prompts import _summarize_factsheet
from src.agents.processo_synthesis.schemas import MovFactSheetMin


def _fs(**decisao):
    return MovFactSheetMin(mov_id="11111111-2222-3333-4444-555555555555",
                           data="2026-02-19", resumo_ato="Sentenca nos embargos",
                           decisao={"tem_decisao": True, **decisao})


# ── fatia 3: o L1 sabe emitir ────────────────────────────────────────────────

def test_o_L1_aceita_autor_polo_e_so_os_2_valores_neutros():
    """Neutro como os irmaos: 'ativo'/'passivo', nunca 'o cliente'/'tomador'."""
    assert DecisaoBlockV4(autor_polo="passivo").autor_polo == "passivo"
    assert DecisaoBlockV4(autor_polo="ativo").autor_polo == "ativo"
    assert DecisaoBlockV4().autor_polo is None, "ausente tem de ser None — o default mora no consumidor"


def test_o_campo_e_da_FAMILIA_dos_polos_por_ato():
    """CONTRA-EXEMPLO estrutural: se `autor_polo` fosse criado fora da familia (ex. como
    bool ou como texto livre), o `_papel_na_acao_julgada` do shared nao conseguiria
    compara-lo com `lado`. Os tres tem de ter o MESMO dominio."""
    campos = DecisaoBlockV4.model_fields
    for nome in ("autor_polo", "recorrente_polo", "requerente_polo"):
        assert nome in campos, f"{nome} sumiu do schema do L1"
    d = DecisaoBlockV4(autor_polo="passivo", recorrente_polo="ativo", requerente_polo="ativo")
    assert {d.autor_polo, d.recorrente_polo, d.requerente_polo} <= {"ativo", "passivo"}


# ── fatia 4: o valor CHEGA ao prompt do L2 ───────────────────────────────────

def test_o_render_do_L2_EMITE_autor_polo():
    """🚨 A guarda central. Sem ela, a instrucao no `<regra_polos>` e letra morta."""
    linha = _summarize_factsheet(_fs(natureza="procedente", autor_polo="passivo"))
    assert "autor_polo=passivo" in linha, (
        f"o render nao emitiu autor_polo — o LLM do L2 nunca o ve. Linha: {linha!r}"
    )


def test_sem_o_campo_o_render_NAO_INVENTA():
    """CONTRA-EXEMPLO: card antigo (os 409.875 do acervo, todos NULL) nao pode ganhar um
    `autor_polo=ativo` de brinde na linha — isso faria o LLM ler uma AFIRMACAO onde ha
    ausencia, e o acervo inteiro deixaria de ser byte-neutro."""
    linha = _summarize_factsheet(_fs(natureza="procedente"))
    assert "autor_polo" not in linha, f"o render inventou um polo: {linha!r}"


def test_o_render_nao_perdeu_os_campos_que_ja_emitia():
    """Nao-regressao do render: `natureza`, `instancia`, `sentido` e o marcador de
    transito continuam saindo. Acrescentar campo nao pode deslocar os que ja estavam."""
    linha = _summarize_factsheet(_fs(natureza="improcedente", instancia="2g",
                                     sentido="desfavoravel", transito_certificado=True,
                                     autor_polo="passivo"))
    for esperado in ("DECISAO improcedente", "2g", "desfavoravel", "(TRANSITO)", "autor_polo=passivo"):
        assert esperado in linha, f"'{esperado}' sumiu do render. Linha: {linha!r}"


# ── o prompt do L2 ensina o PASSO 0 ──────────────────────────────────────────

def test_a_regra_de_polos_manda_resolver_a_ACAO_antes_do_bucket():
    """O bucket do `<regra_polos>` e pela CLASSE do processo. A regra de cada bucket esta
    certa; o que errava era aplicar o bucket a uma decisao de OUTRA acao. O PASSO 0 tem
    de existir ANTES do PASSO 1, e nomear `autor_polo` como o sinal."""
    from src.agents.processo_synthesis.prompts import build_processo_synthesis_prompt  # noqa: F401
    import src.agents.processo_synthesis.prompts as p
    import inspect

    fonte = inspect.getsource(p)
    # ⚠️ ANCORA ESTREITA, de proposito: a 1a versao procurava so "PASSO 0" e o mutante
    # SOBREVIVEU — o mesmo texto aparece no comentario que eu escrevi no renderizador,
    # entao a busca achava com a regra REMOVIDA. Ancora mais larga que a coisa guardada
    # nao separa CITAR de EXISTIR. Aqui a ancora e o cabecalho literal da regra.
    CABECALHO = "PASSO 0 — DE QUAL ACAO E ESTA DECISAO?"
    assert CABECALHO in fonte, "o PASSO 0 (de qual acao e a decisao) sumiu do <regra_polos>"
    i0, i1 = fonte.index(CABECALHO), fonte.index("PASSO 1 — Bucket")
    assert i0 < i1, "o PASSO 0 tem de vir ANTES do bucket — depois dele nao muda decisao nenhuma"
    trecho = fonte[i0:i1]
    assert "autor_polo" in trecho, "o PASSO 0 nao nomeia o sinal que o resolve"
    assert "traslad" in trecho.lower(), "o PASSO 0 nao nomeia o caso que o obriga (traslado)"
