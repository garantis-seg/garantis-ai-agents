# -*- coding: utf-8 -*-
"""Perfil de leitura por Tipo de doc (2026-06-19) — peça=completo / evidência=head+tail.

Resolve o timeout do L1 em doc grande LEGÍTIMO (demonstrativo de 567pg), não dup.
Trava: keyword legal vence (petição grande NÃO vira evidência); doc grande sem
título legal vira evidência; head+tail preserva início+fim.
"""
from src.agents.mov_factsheet.prompts_v4 import (
    _DOC_EVIDENCIA_HEAD,
    _DOC_EVIDENCIA_TAIL,
    _doc_reading_profile,
    _evidencia_head_tail,
)
from src.agents.mov_factsheet.schemas import DocAnexado


def _doc(titulo="", tipo=None, text="", paginas=None):
    return DocAnexado(doc_key="k", titulo=titulo, tipo=tipo,
                      text_content=text, paginas=paginas)


def test_peca_por_titulo_legal_vence_mesmo_grande():
    # Petição de 2M chars -> peça (NÃO evidência), porque a keyword legal vence.
    big = "x" * 2_000_000
    assert _doc_reading_profile(_doc(titulo="PETICAO INICIAL", text=big, paginas=500)) == "peca"
    assert _doc_reading_profile(_doc(titulo="SENTENCA", text=big)) == "peca"


def test_evidencia_por_tamanho_sem_titulo_legal():
    # "ANEXO INFORMACAO FISCAL" (caso real merito 20): sem keyword legal nem
    # tabular, mas > 200k CHARS -> evidência (chars, não páginas: é o input do LLM).
    assert _doc_reading_profile(_doc(titulo="ANEXO INFORMACAO FISCAL", text="y" * 1_900_000)) == "evidencia"
    assert _doc_reading_profile(_doc(titulo="DOCUMENTO", text="z" * 250_000)) == "evidencia"


def test_peca_quando_texto_curto_mesmo_com_muitas_paginas():
    # 500 páginas mas só 1000 chars extraídos = input trivial -> peça (lê completo).
    # Páginas não importam; o que conta é o nº de chars (input do Gemini).
    assert _doc_reading_profile(_doc(titulo="DOCUMENTO", text="z" * 1000, paginas=500)) == "peca"


def test_peca_default_pequeno():
    # Doc pequeno sem título claro -> peça (lê completo; default conservador).
    assert _doc_reading_profile(_doc(titulo="INFORMACAO FISCAL", text="x" * 40_000)) == "peca"


def test_head_tail_preserva_inicio_e_fim():
    head = "INICIO_MARCADOR" + "a" * 60_000
    tail = "b" * 40_000 + "FIM_MARCADOR"
    text = head + ("m" * 500_000) + tail
    out = _evidencia_head_tail(text)
    assert out.startswith("INICIO_MARCADOR")
    assert out.endswith("FIM_MARCADOR")
    assert "omitidos" in out
    assert len(out) < len(text)  # encolheu
    assert len(out) <= _DOC_EVIDENCIA_HEAD + _DOC_EVIDENCIA_TAIL + 300  # ~head+tail+marcador


def test_head_tail_doc_pequeno_intacto():
    text = "c" * 50_000  # < head+tail -> intacto
    assert _evidencia_head_tail(text) == text
