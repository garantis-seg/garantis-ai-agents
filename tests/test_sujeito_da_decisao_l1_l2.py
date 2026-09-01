"""O SUJEITO da decisao no L1 e no L2 — `acao_julgada_cnj`. RAIZ 869ep4gp1 (fecha 869efuvwk).

Metade ai-agents. A outra e `garantis-shared#467` (o `on_read` por sujeito) e a coluna e
`execucao-fiscal#2162`.

⭐ Este PR entrega CAPACIDADE, nao exposicao: o token `acao_julgada=` existe hoje em
**0 de 395.241** cards, entao sem ponteiro o prompt do L2 e BYTE-IDENTICO. E o que separa
esta tentativa do PR #180, que agia sobre 100% dos cards existentes SEM dado novo e por
isso derrubou banda no dia do merge.

Run: pytest tests/test_sujeito_da_decisao_l1_l2.py -q
"""
from __future__ import annotations

import pytest

from src.agents.processo_synthesis.prompts import _summarize_factsheet


class _FS:
    """MovFactSheetMin-like. `decisao` e `Optional[dict]` no schema real, entao a chave
    nova ATRAVESSA sem mudanca de schema no L2 — o que NAO atravessa e o render, que e
    montado chave a chave."""

    def __init__(self, **kw):
        base = dict(mov_id="m1", data="2026-01-02", origem="mov", tipo_doc="sentenca",
                    categoria=None, relevancia_merito=None, resumo_ato="",
                    decisao=None, evento_garantia=None, status_garantia_pos_mov=None,
                    delta_risco=None, peca_pivo=None, tipo_garantia=None,
                    relevante_garantia=False, valores=None)
        base.update(kw)
        for k, v in base.items():
            setattr(self, k, v)


def _fs(acao_julgada=None):
    d = {"tem_decisao": True, "natureza": "improcedente", "instancia": "1g",
         "sentido": "desfavoravel", "transito_certificado": False}
    if acao_julgada is not None:
        d["acao_julgada_cnj"] = acao_julgada
    return _FS(decisao=d)


PN = "50203029120184036182"


class TestORender:
    def test_COM_ponteiro_o_token_aparece_na_linha(self):
        """⭐ Sem esta linha o campo nasce INERTE: ele existiria no banco e nunca
        chegaria ao prompt. E exatamente o que aconteceu com o `dispositivo` da RAIZ A —
        ver `TestAAncoraDaRaizAEstaInerte` no fim deste arquivo."""
        assert f"acao_julgada={PN}" in _summarize_factsheet(_fs(PN))

    @pytest.mark.parametrize("ausente", [None, ""])
    def test_SEM_ponteiro_a_linha_e_BYTE_IDENTICA(self, ausente):
        """A neutralidade tem de valer nas DUAS formas: chave ausente (os 395.241 cards
        de hoje) e chave presente valendo None/vazio (o que o pydantic passa a emitir com
        o schema deste PR). Se so a 1a valesse, a neutralidade acabaria no dia do bump."""
        base = _summarize_factsheet(_fs())
        com_chave = _summarize_factsheet(_fs(ausente)) if ausente is not None else base
        assert com_chave == base
        assert "acao_julgada" not in base

    def test_o_token_entra_DENTRO_do_grupo_DECISAO(self):
        """Junto de natureza/sentido/(TRANSITO) — nao como campo solto, senao o L2 nao
        tem como saber que ele qualifica ESTA decisao."""
        linha = next(p for p in _summarize_factsheet(_fs(PN)).split(" | ")
                     if p.startswith("DECISAO"))
        assert "acao_julgada=" in linha

    def test_o_chunking_usa_a_MESMA_fn_de_render(self):
        """`_est_render_chars` estima com `_summarize_factsheet`. Se um dia alguem
        renderizar por outro caminho, a estimativa e o prompt divergem em silencio."""
        import inspect

        from src.agents.processo_synthesis import chunking
        assert "_summarize_factsheet" in inspect.getsource(chunking._est_render_chars)


class TestOSchemaDoL1:
    def test_o_campo_existe_e_e_OPCIONAL_com_default_None(self):
        from src.agents.mov_factsheet.schemas_v4 import DecisaoBlockV4
        f = DecisaoBlockV4.model_fields["acao_julgada_cnj"]
        assert f.default is None, "default != None faria o campo AFIRMAR por omissao"
        assert DecisaoBlockV4().acao_julgada_cnj is None

    def test_o_campo_e_TEXTO_livre_e_NAO_um_Literal_de_polo(self):
        """⛔ A licao do #180: `autor_polo` era `Literal['ativo','passivo']` e por isso
        FORCAVA o L1 a mentir em embargos de TERCEIRO (o embargante e terceiro, em polo
        nenhum). Ponteiro nao tem esse problema — ou o numero esta no texto, ou e null."""
        from src.agents.mov_factsheet.schemas_v4 import DecisaoBlockV4
        anot = str(DecisaoBlockV4.model_fields["acao_julgada_cnj"].annotation)
        assert "ativo" not in anot and "passivo" not in anot
        assert "str" in anot


class TestOPrompt:
    def test_o_L1_e_instruido_a_COPIAR_e_a_devolver_null_por_default(self):
        from src.agents.mov_factsheet.prompts_v4 import _REGRAS_CRUS
        assert "acao_julgada_cnj" in _REGRAS_CRUS
        low = _REGRAS_CRUS.lower()
        assert "literal" in low and "null" in low

    def test_a_clausula_do_L2_dispara_SO_com_o_token(self):
        import inspect
        import src.agents.processo_synthesis.prompts as P
        src = inspect.getsource(P)
        assert "acao_julgada=<CNJ>" in src, "a clausula tem de ancorar no TOKEN renderizado"
        # ⭐ e o token so existe quando o card traz o ponteiro: sem ele a clausula e
        # inerte por construcao. E a diferenca estrutural com o PASSO 0 do #180, que
        # mandava o LLM INFERIR a acao lendo prosa — logo agia sobre 100% dos cards.
        assert "Sem `acao_julgada=` na linha" in src

    def test_os_cabecalhos_que_os_guards_do_180_ancoram_NAO_mudaram(self):
        """⛔ `test_o_bucket_pela_CLASSE_continua_sendo_o_que_roda` exige as 2 strings, e
        `test_o_PASSO_0_saiu_do_prompt_do_L2` proibe ressuscitar o PASSO 0. A clausula
        nova entra DENTRO do PASSO 1 exatamente por isso."""
        import inspect
        import src.agents.processo_synthesis.prompts as P
        src = inspect.getsource(P)
        assert "PASSO 1 — Bucket pela classe:" in src
        assert "Embargos a Execucao, Excecao de Pre-Executividade:" in src
        assert "PASSO 0" not in src


class TestOQueNaoMuda:
    def test_NAO_ha_bump_de_summary_prompt_version(self):
        """⛔ Bump de `summary_prompt_version` e re-cascade do UNIVERSO
        (`supersede_other_versions`). O `prompt_identity` (sha) muda sozinho, e e isso
        que se quer: rastreabilidade sem custo."""
        import subprocess
        # ⛔ encoding EXPLICITO: no Windows o default do subprocess e cp1252 e o diff
        # (que tem ⛔/⭐) estoura UnicodeDecodeError — o teste morreria por ambiente.
        diff = subprocess.run(["git", "diff", "origin/master", "--unified=0"],
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout
        for proibido in ("summary_prompt_version", "PROMPT_VERSION ="):
            assert proibido not in diff, f"o diff mexe em {proibido}"

    def test_o_proxy_autor_polo_NAO_voltou(self):
        import inspect
        import src.agents.mov_factsheet.schemas_v4 as S
        assert "autor_polo" not in inspect.getsource(S)


class TestAAncoraDaRaizAEstaInerte:
    """🚨 ACHADO REGISTRADO, NAO CONSERTADO NESTE PR (869ep4gp1, comentario no card).

    O `dispositivo` — a ancora que a RAIZ A (869enpem7) entregou pra tornar o veredito
    VERIFICAVEL — existe no banco, atravessa o `card_to_row`/`_row_to_card`, chega ao
    `MovFactSheetMin`... e o `_summarize_factsheet` NAO o renderiza. Ele nunca chega ao
    prompt do L2.

    ⛔ Ligar aqui de carona seria errado: mudaria a linha de TODOS os 395.241 cards, o
    tamanho do prompt do L2 e o `_est_render_chars` do chunking — ou seja, destruiria
    exatamente a byte-neutralidade que este PR precisa provar. Card proprio.

    Este teste EXISTE pra que o achado nao se perca: quando alguem ligar o render, ele
    fica vermelho e obriga a atualizar a lapide junto.
    """

    def test_o_dispositivo_NAO_chega_ao_prompt_do_L2_hoje(self):
        fs = _FS(decisao={"tem_decisao": True, "natureza": "improcedente",
                          "dispositivo": "JULGO IMPROCEDENTES OS EMBARGOS"})
        render = _summarize_factsheet(fs)
        assert "IMPROCEDENTES OS EMBARGOS" not in render, (
            "o `dispositivo` passou a ser renderizado — otimo, mas isso muda a linha de "
            "TODOS os cards: atualize esta lapide e re-meca o chunking do L2."
        )
