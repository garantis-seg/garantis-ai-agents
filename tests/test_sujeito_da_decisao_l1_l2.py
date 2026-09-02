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
        que se quer: rastreabilidade sem custo.

        ⚰️ **Ate 2026-09-01 este teste rodava `git diff origin/master` por subprocess, e
        era INERTE DE DUAS FORMAS:**
        (a) a imagem do step de unit-tests e `python:3.11-slim` e **nao tem o binario
            `git`** -> `FileNotFoundError` -> `1 failed` -> o DEPLOY inteiro reprovava.
            Ficou vermelho de 01/09 17:45 ate o conserto, e a `acao_julgada_cnj` ficou
            PELA METADE em prod (a coluna do fe-api subiu; o emissor, nao).
        (b) mesmo COM git, o predicado e vazio depois do merge — `git diff origin/master`
            contra o proprio commit nao devolve nada, entao ele passaria verde sem olhar
            coisa nenhuma. ⛔ Guarda que le zero POR CONSTRUCAO e pior que guarda nenhuma:
            parece proteger.

        ⭐ Hoje ele fixa o **ROTULO** das duas versoes que carimbam a coluna — os
        materializers do shared gravam `summary_prompt_version=versao` a partir destes
        `PROMPT_VERSION`. Bumpar exige editar esta linha, que e exatamente a decisao que se
        quer explicita.
        ⛔ **NAO asserte o `PROMPT_VERSION` INTEIRO do L2:** o sufixo e `sha256[:12]` de
        (prompt + schema) e muda de proposito a cada edicao de prompt — era esse o ponto de
        `versao_com_identidade`.
        """
        import src.agents.mov_factsheet.agent as L1
        import src.agents.processo_synthesis.agent as L2
        assert L1.PROMPT_VERSION == "mov_factsheet.v3.1"
        assert L2.PROMPT_VERSION.startswith("processo_synthesis.v2.5")

    def test_o_proxy_autor_polo_NAO_voltou(self):
        import inspect
        import src.agents.mov_factsheet.schemas_v4 as S
        assert "autor_polo" not in inspect.getsource(S)


class TestAAncoraDaRaizAChegaAoL2:
    """✅ A ancora da RAIZ A (869enpem7) DEIXOU DE SER INERTE em 2026-09-02 (OK Elton, 869ep4gp1).

    ⚰️ Esta classe se chamava `TestAAncoraDaRaizAEstaInerte` e assertava o OPOSTO: que o
    `dispositivo` NAO chegava ao prompt do L2. Ela era um sensor deliberado — *"quando alguem
    ligar o render, ele fica vermelho e obriga a atualizar a lapide junto"*. Foi o que houve.

    🚨 As TRES razoes escritas pra adiar caíram, todas MEDIDAS em 2026-09-02, e ficam aqui
    porque cada uma errava na direcao CARA (fazia o conserto parecer maior do que e):

      1. *"mudaria a linha de TODOS os 395.241 cards"* -> `dispositivo` e nao-nulo em
         **3.112 de 395.241 (0,79%)**, e os 3.112 ja tem `tem_decisao=TRUE`. Render
         condicional deixa 392.129 linhas (99,21%) byte-identicas.
      2. *"o tamanho do prompt do L2"* -> o pior processo do acervo ganha ~29k chars contra
         `_L2_CHUNK_DETECT_CHARS = 800.000`. So 3 processos passam de +20k.
      3. *"o `_est_render_chars` do chunking"* -> ele CHAMA `_summarize_factsheet`. Detector e
         render nao podem divergir por construcao; este pe nunca existiu.

    ⚠️ O que MUDA o tamanho daqui pra frente, e o card nao dizia: `L1_DECISAO_EXIGE_DISPOSITIVO`
    esta ON em prod, entao todo card que afirmar decisao PRECISA de dispositivo por construcao —
    da proxima rodada do L1 em diante a populacao sai de 3.112 pra a ordem de 25.613.

        SELECT count(*) total,
               count(*) FILTER (WHERE dispositivo IS NOT NULL AND dispositivo <> '') com_disp,
               count(*) FILTER (WHERE tem_decisao) tem_dec
          FROM leitura_conexos.mov_factsheet
        -- 2026-09-02: 395241 | 3112 | 25613
    """

    def test_o_dispositivo_CHEGA_ao_prompt_do_L2(self):
        fs = _FS(decisao={"tem_decisao": True, "natureza": "improcedente",
                          "dispositivo": "JULGO IMPROCEDENTES OS EMBARGOS"})
        render = _summarize_factsheet(fs)
        assert "IMPROCEDENTES OS EMBARGOS" in render

    def test_sem_dispositivo_a_linha_e_BYTE_IDENTICA(self):
        """Os 99,21% que nao tem dispositivo nao podem se mexer — e a byte-neutralidade.

        🚨 A assercao e ABSOLUTA (`"disp=" not in render`), nao uma comparacao entre dois
        renders. Mutante verificado: com `d_parts.append(f'disp="{... or ""}"')` — render
        INCONDICIONAL, que emite `disp=""` em 392.129 cards — a versao relativa passava
        VERDE, porque os DOIS lados da igualdade ganhavam o mesmo sufixo. Comparar mutante
        com mutante nao mede nada.
        """
        base = {"tem_decisao": True, "natureza": "improcedente", "instancia": "1a"}
        for extra in ({}, {"dispositivo": None}, {"dispositivo": ""}):
            render = _summarize_factsheet(_FS(decisao={**base, **extra}))
            assert "disp=" not in render, (
                f"card sem dispositivo ganhou token no prompt do L2 ({extra}): {render!r}. "
                "Isso muda a linha de 392.129 cards e o `_est_render_chars` do chunking."
            )
        # e os 3 renderizam a MESMA coisa entre si
        assert len({_summarize_factsheet(_FS(decisao={**base, **e}))
                    for e in ({}, {"dispositivo": None}, {"dispositivo": ""})}) == 1

    def test_o_dispositivo_e_CLIPADO_em_300_chars(self):
        """Sem clip, um dispositivo longo sozinho domina o chunk do L2."""
        fs = _FS(decisao={"tem_decisao": True, "natureza": "improcedente",
                          "dispositivo": "X" * 5000})
        render = _summarize_factsheet(fs)
        assert "X" * 300 in render
        assert "X" * 301 not in render

    def test_sem_decisao_o_dispositivo_NAO_vaza(self):
        """O render inteiro e gateado por `tem_decisao` — card sem decisao nao ganha linha."""
        fs = _FS(decisao={"tem_decisao": False, "dispositivo": "JULGO IMPROCEDENTE"})
        assert "JULGO IMPROCEDENTE" not in _summarize_factsheet(fs)
