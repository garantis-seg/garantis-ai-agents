"""STEERING dos anexos (v1.5): o parágrafo que só existe quando há PDF na chamada.

A raiz que ele corrige, PROVADA por repro offline (8 chamadas Gemini reais, mesmos
bytes, mesmo endpoint Vertex, temp 0 — MS 1012150-95.2026.8.26.0224): o prompt nunca
declarava que há PDFs anexados, apresentava o texto concatenado como sendo A peça
inteira e fechava com "Preencha SÓ o que o TEXTO sustenta". O modelo LIA os PDFs (a CDA
que ele devolveu não existe em texto nenhum do payload) mas ANCORAVA no texto: o par
"Processo Administrativo nº X (AIIM nº Y)" saía pela metade, 2 runs iguais. Com o
parágrafo, o par sai completo, 2 runs iguais.

⚠️ O invariante que ESTES testes prendem não é "o LLM acerta" (isso é o eval, que custa
dinheiro e roda à parte) — é o que dá pra provar de graça e é onde a regressão se
esconderia:

  1. sem anexo, o prompt NÃO muda (99,7% do volume é o caminho texto);
  2. o bloco entra na posição EXATA que a repro validou (depois do texto, antes da
     linha final) — recência importa e a variante que funcionou tem uma posição;
  3. quem escolhe entre os 2 prompts é o ramo VISION, não o caller;
  4. se a Vision call FALHA e cai no texto, o steering NÃO vai junto — senão o prompt
     manda ler PDF que não está na chamada.
"""
from __future__ import annotations

import asyncio

from src.agents._utils import vision as V
from src.agents.mov_factsheet.prompts_v4 import (
    _STEER_PDF_ANEXADOS,
    build_mov_factsheet_prompt_v4,
)
from src.agents.mov_factsheet.schemas import DocAnexado, MovInput, ProcessoContext

_PROC = ProcessoContext(cnj="10121509520268260224", classe="Mandado de Seguranca Civel")
_MOV = MovInput(mov_id="peticao-10121509520268260224", texto="")
_DOC = DocAnexado(
    doc_key="jb-867158", tipo="1", titulo="PETICAO INICIAL",
    text_content="Processo Administrativo n 017.00100686/2026-51 instaurado. " * 40,
)


def _par(classe: str) -> tuple[str, str]:
    """(sem anexo, com anexo) do mesmo ramo."""
    return (
        build_mov_factsheet_prompt_v4(_PROC, _MOV, [_DOC], classe=classe),
        build_mov_factsheet_prompt_v4(_PROC, _MOV, [_DOC], classe=classe,
                                      pdfs_anexados=True),
    )


def test_sem_anexo_o_prompt_e_o_MESMO_nos_dois_ramos():
    """⛔ MUTANTE: fazer o bloco entrar sempre reprova aqui. O caminho texto é 99,7%
    do volume e não tem PDF nenhum na chamada — declarar anexo ali é instruir o modelo
    a procurar o que não existe."""
    for classe in ("peticao", "doc_incerto"):
        sem, _com = _par(classe)
        assert "PDF ANEXADOS" not in sem, classe
        assert "complementares" not in sem, classe


def test_a_UNICA_diferenca_e_o_bloco_e_ele_vem_ANTES_da_linha_final():
    """A posição é parte do fix, não estética: a repro injetou o parágrafo DEPOIS da
    seção de texto e ANTES de "Extraia no schema…" (que é a linha de recência, a que
    restringe ao "texto"). Este teste prende as duas coisas de uma vez — remover o
    bloco do prompt COM anexo devolve, byte a byte, o prompt SEM anexo."""
    for classe in ("peticao", "doc_incerto"):
        sem, com = _par(classe)
        steer = _STEER_PDF_ANEXADOS.format(
            da_peca="DA PETIÇÃO INICIAL" if classe == "peticao" else "DESTE DOCUMENTO")
        assert steer in com, classe
        assert com.replace("\n\n" + steer, "") == sem, (
            f"{classe}: o bloco não é a ÚNICA diferença")
        assert com.index(steer) < com.index("Extraia no schema"), classe
        assert com.index(steer) > com.index("017.00100686"), (
            f"{classe}: o bloco tem que vir DEPOIS do texto da peça")


def test_o_ramo_do_MOV_nao_recebe_steering_nem_pedindo():
    """O caminho do mov manda 1 doc por entry: o texto do prompt JÁ é o do documento
    cujo PDF foi anexado, então não existe a discrepância que o steering corrige (e o
    texto fala de "PARTES DA PETIÇÃO", que ali seria mentira)."""
    for classe in (None, "1D"):
        p = build_mov_factsheet_prompt_v4(_PROC, _MOV, [_DOC], classe=classe,
                                          pdfs_anexados=True)
        assert "PDF ANEXADOS" not in p, classe


# ── A fiação: quem escolhe é o ramo VISION ───────────────────────────────────

class _Prov:
    def __init__(self) -> None:
        self.texto_recebeu: str | None = None

    async def agenerate(self, *, prompt, **kw):
        self.texto_recebeu = prompt
        return "TEXTO"


def _roda(prompt_vision, *, vision_falha=False):
    """Retorna (prompt que foi pro Vision, prompt que foi pro fallback texto)."""
    visto: dict = {}

    async def _fake_fetch(urls):
        return [b"%PDF-1.4 fake"]

    async def _fake_vision(provider, *, prompt, pdf_bytes_list, **kw):
        visto["vision"] = prompt
        if vision_falha:
            raise RuntimeError("Gemini 400: document has no pages")
        return "OK"

    prov = _Prov()
    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(V, "fetch_pdfs_from_gcs", _fake_fetch)
        mp.setattr(V, "call_vision_l1", _fake_vision)
        mp.setenv("VISION_L1_ENABLED", "true")
        asyncio.run(V.call_l1_with_vision_fallback(
            prov, model="m", prompt="PROMPT_TEXTO", prompt_vision=prompt_vision,
            response_schema=None, gcs_urls=["gs://b/p.pdf"],
        ))
    return visto.get("vision"), prov.texto_recebeu


def test_o_ramo_vision_usa_o_prompt_COM_steering():
    """⛔ MUTANTE: ignorar `prompt_vision` no helper reprova aqui — e o modo de falha é
    mudo (a chamada sai, custa igual, e o fix simplesmente não acontece)."""
    vision, texto = _roda("PROMPT_COM_STEERING")
    assert vision == "PROMPT_COM_STEERING"
    assert texto is None, "não devia ter caído no fallback"


def test_sem_prompt_vision_o_comportamento_e_o_de_antes():
    """Caller legado (mov/day) não passa o campo — a rota dele não pode mudar."""
    vision, _ = _roda(None)
    assert vision == "PROMPT_TEXTO"


def test_fallback_text_only_NAO_leva_o_steering():
    """Se a Vision call falha, não há anexo na chamada: o steering viraria instrução
    sobre PDF inexistente. O fallback usa SEMPRE o prompt de texto."""
    vision, texto = _roda("PROMPT_COM_STEERING", vision_falha=True)
    assert vision == "PROMPT_COM_STEERING"
    assert texto == "PROMPT_TEXTO"
