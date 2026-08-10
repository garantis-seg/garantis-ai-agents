"""O piso de TEOR — o que faz o Sinal 1 (área de imagem) ficar ALCANÇÁVEL.

O bug: o caller (`vision.py`) pulava o download do PDF quando `not texto_lixo(txt)`.
rmgarbage mede corrupção de caractere, então carimbo do PJe e rodapé do ESAJ — texto
limpo, conteúdo preso na imagem — passavam como "texto usável" e o scan nunca era
lido. As formas abaixo são LITERAIS de prod (2026-08-10): 5.339 docs com o rodapé do
ESAJ, 3.258 com o carimbo do PJe, 182 com a página de erro da Akamai.
"""
from src.agents._utils.ocr_gate import TEOR_MIN_CHARS, texto_decide_sozinho, texto_lixo

RODAPE_ESAJ = (
    "Para conferir o original, acesse o site https://esaj.tjsp.jus.br/pastadigital/pg/"
    "abrirConferenciaDocumento.do, informe o processo 1004758-35.2026.8.26.0053 e código "
    "A1B2C3D."
)
CARIMBO_PJE = (
    "Num. 123456789 - Pág. 1\nAssinado eletronicamente por: TRIBUNAL REGIONAL FEDERAL DA "
    "3 REGIAO\nhttps://pje1g.trf3.jus.br/pje/Processo/ConsultaDocumento/listView.seam"
)
ERRO_AKAMAI = (
    "Access Denied Access Denied You don't have permission to access "
    '"http://pje1g.trf3.jus.br/pje/ConsultaPublica/DetalheProcessoConsultaPublica/'
    'documentoSemLoginHTML.seam?" on this server. Reference #18.ece0c417.1781556572.254547b7'
)


def test_as_3_formas_de_prod_sao_texto_limpo_para_o_rmgarbage():
    # Se alguma virar 'lixo' pro rmgarbage, o bug original teria se resolvido sozinho
    # e este gate perde a razão de existir. Prende o pressuposto.
    for txt in (RODAPE_ESAJ, CARIMBO_PJE, ERRO_AKAMAI):
        assert not texto_lixo(txt), f"rmgarbage passou a pegar: {txt[:40]!r}"


def test_carimbo_e_rodape_nao_decidem_sozinhos():
    # É isto que faz o PDF ser baixado e o Sinal 1 (área) julgar o scan.
    for txt in (RODAPE_ESAJ, CARIMBO_PJE, ERRO_AKAMAI):
        assert len(txt) < TEOR_MIN_CHARS
        assert not texto_decide_sozinho(txt)


def test_texto_de_peca_real_decide_sozinho_e_nao_baixa_pdf():
    peca = (
        "Trata-se de ação anulatória de débito fiscal em que a autora pretende afastar a "
        "exigibilidade do crédito tributário lançado. " * 6
    )
    assert len(peca) >= TEOR_MIN_CHARS
    assert texto_decide_sozinho(peca)


def test_vazio_e_garbage_continuam_indo_pro_pdf():
    for txt in (None, "", "   ", "|||| ~~~~ %%%% @@@@ #### ^^^^ &&&& ****"):
        assert not texto_decide_sozinho(txt)


if __name__ == "__main__":  # smoke sem pytest
    test_as_3_formas_de_prod_sao_texto_limpo_para_o_rmgarbage()
    test_carimbo_e_rodape_nao_decidem_sozinhos()
    test_texto_de_peca_real_decide_sozinho_e_nao_baixa_pdf()
    test_vazio_e_garbage_continuam_indo_pro_pdf()
    print("ok")
