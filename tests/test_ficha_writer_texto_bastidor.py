"""O prompt do redator traz as 4 regras de texto da rodada 11 do loop (23/11/2026).

A S5 do shared (A64 a A67) devolve o texto que quebra a regra. O prompt diz a
regra antes, para o redator acertar na 1ª rodada.
"""
from src.agents.ficha_writer.prompts_v4 import _bloco_regras


def test_regras_de_texto_da_rodada_11_no_prompt():
    p = _bloco_regras([])
    assert p.rstrip().endswith("</regras_de_redacao>")
    for trecho in ('"triagem"', '"CENCOP"', '"MULDI"', "Data não disponível na fonte",
                   "não cita pessoa física", "fica definitiva se a empresa não apresentar agravo",
                   "RE recebido no CARF em DD/MM/AAAA"):
        assert trecho in p, trecho
