"""Gera `src/agents/ficha_writer/livro_guidance.json`: a guidance da S4 por slot × tipo.

Uso (na raiz do repo):

    python scripts/gerar_livro_guidance.py            # escreve o JSON
    python scripts/gerar_livro_guidance.py --checar   # sai com 1 se o JSON no git está velho

O script é idempotente. A mesma fonte dá o mesmo arquivo, byte a byte. Ele não lê o
relógio nem a rede.

## A fonte

1. O compilado do Livro da Ficha (`livro_fonte/guidance-por-slot-tipo.json`). É uma
   cópia de `carf-pipeline@origin/main:docs/livro-da-ficha/compilado/`, versão 1.0.0
   de 13/08/2026. O compilado usa os tipos antigos (`nova_apolice_carf|tit|ef`,
   `substituicao_fianca`, `renovacao`, `triagem`).
2. O Livro da Ficha de 19/10/2026 (carf-pipeline@8c53e87). O compilado não cobre a
   renovação de congênere (§5.4 e §6.2, de 10/09/2026). Este script escreve essa
   guidance a partir do Livro, em `_RENOVACAO_CONGENERE`.
3. As decisões do Alfredo de 22/10/2026 (caderno do plano, Parte 7) e de 23/10/2026
   (diagnóstico da ficha Claro), em `_DECISOES`.
4. O exemplar canônico IRB (lote `carf_esgotados_2026-09-23`) e o BRIEF-BUILDER de
   01/10/2026. Eles dão exemplos que já seguem a regra de zero cifra.

## O que o script faz

- Troca a chave do compilado pela chave do CÓDIGO (`_MAPA`).
- Herda a guidance onde o Livro não cobre. O slot herdado leva
  `fonte="herdado_de:<chave>"`.
- Aplica as decisões de 22/10/2026: bullets por tipo, resumo até 500 chars, zero
  cifra em `valor.descricao`, razão social completa, sem prêmio na renovação.
- Aplica as decisões de 23/10/2026: o mérito da renovação e da EF traz a tese,
  `divida_ativa.detalhe` deixa de ser slot (regra 26), `valor.descricao` com origem fixa
  copia a descrição do esqueleto (regra 25), o bullet 2 da renovação lê o bloco
  `renovacao` e o status da dívida fica fora do texto.
- Descarta o exemplo que viola uma regra nova (`_viola`). O número de descartes fica
  em `exemplos_descartados`. Um exemplo velho que ensina o erro é pior que nenhum.

Decisão de 22/10/2026 (DECIDI-SOZINHO, classe A): a cópia da fonte fica no repo. Sem
ela, o CI não prova que o JSON vendorizado é o resultado do script.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "src" / "agents" / "ficha_writer"
FONTE_PADRAO = PASTA / "livro_fonte" / "guidance-por-slot-tipo.json"
SAIDA_PADRAO = PASTA / "livro_guidance.json"

VERSAO = "2026-10-23"
LIVRO_REF = "carf-pipeline@8c53e87 docs/livro-da-ficha/LIVRO-DA-FICHA.md (19/10/2026)"

SLOTS: tuple[str, ...] = (
    "descricao_infracao",
    "valor.descricao",
    "processo_administrativo.resumo",
    "ultima_decisao.texto",
    "ultima_ocorrencia.texto",
    "bullets[0]",
    "bullets[1]",
    "bullets[2]",
    "bullets[3]",
    "merito.p1",
    "merito.p2",
    "observacao",
    "divida_ativa.detalhe",
)

# ─────────────────────────────────────────────────────────────────────────────
# Chaves do código × fonte
# ─────────────────────────────────────────────────────────────────────────────

#: Chave do código -> (origem, descrição do tipo).
#: origem = "compilado:<tipo>" | "herdado_de:<chave>" | "livro:<seção>".
_MAPA: dict[str, tuple[str, str]] = {
    "nova_apolice@carf": (
        "compilado:nova_apolice_carf",
        "Nova apólice, trilho CARF: via administrativa esgotada (ou barrada) e bola com o "
        "contribuinte. Slot central: termômetro.",
    ),
    "nova_apolice@estadual": (
        "compilado:nova_apolice_tit",
        "Nova apólice, trilho estadual (TIT-SP e afins): via administrativa esgotada. "
        "\"Enviado para a Unidade Fiscal da Cobrança\" já sinaliza. Slot central: termômetro.",
    ),
    "nova_apolice@ef": (
        "compilado:nova_apolice_ef",
        "Nova apólice, trilho EF: execução fiscal ajuizada sem garantia. A ficha mostra EF, "
        "processo administrativo e CDA. Slot central: termômetro.",
    ),
    "nova_apolice@acoes_contribuinte": (
        "herdado_de:nova_apolice@ef",
        "Nova apólice, trilho ações do contribuinte (anulatória, mandado de segurança): a "
        "empresa é a autora e discute o débito em juízo. O Livro não tem seção própria. A "
        "guidance vem da EF, o trilho judicial mais próximo.",
    ),
    "substituicao_fianca": (
        "compilado:substituicao_fianca",
        "Substituição de carta de fiança bancária vigente nos autos. Sem termômetro: o slot "
        "central é o bloco CARTA DE FIANÇA ATUAL. A tese é eficiência, nunca insuficiência "
        "da carta.",
    ),
    "substituicao_deposito": (
        "herdado_de:substituicao_fianca",
        "Substituição de depósito judicial vivo nos autos. A tese é liberar caixa (TIP-10). "
        "O Livro não tem seção própria. A guidance vem da fiança, com o ajuste do tipo.",
    ),
    "substituicao_penhora": (
        "herdado_de:substituicao_fianca",
        "Substituição de penhora viva nos autos. A tese é liberar o bem ou o caixa "
        "penhorado (TIP-10). O Livro não tem seção própria. A guidance vem da fiança, com o "
        "ajuste do tipo.",
    ),
    "renovacao_congenere": (
        "livro:§5.4+§6.2",
        "Renovação de congênere: seguro garantia de outra seguradora vigente, com vencimento "
        "à vista. Sem termômetro: o slot central é o bloco RENOVAÇÃO DE CONGÊNERE. O texto "
        "nunca cita prêmio, limite nem taxa.",
    ),
    "renovacao_interna": (
        "herdado_de:renovacao_congenere",
        "Renovação interna: a apólice vigente é da casa. O Livro não tem seção própria. A "
        "guidance vem da renovação de congênere, com o ajuste do tipo.",
    ),
}

#: O ajuste que a chave herdada põe na frente da guidance da origem.
_AJUSTE_HERDADO: dict[str, str] = {
    "nova_apolice@acoes_contribuinte": (
        "Ajuste do tipo: a ação é da empresa (anulatória ou mandado de segurança), não uma "
        "execução. Onde a guidance fala da execução fiscal, leia a ação da empresa e a "
        "exigibilidade do débito."
    ),
    "substituicao_deposito": (
        "Ajuste do tipo: a garantia viva é um depósito judicial, não uma carta de fiança. "
        "Onde a guidance fala da carta, leia o depósito (data, juízo, saldo). A tese é "
        "liberar caixa."
    ),
    "substituicao_penhora": (
        "Ajuste do tipo: a garantia viva é uma penhora, não uma carta de fiança. Onde a "
        "guidance fala da carta, leia a penhora (bem, data, juízo). A tese é liberar o bem "
        "ou o caixa penhorado."
    ),
    "renovacao_interna": (
        "Ajuste do tipo: a apólice vigente é da casa. Não fale de disputa com outra "
        "seguradora."
    ),
}

#: Bullets por tipo (decisão de 22/10/2026, plano S4): nova 4, substituição 2 a 4,
#: renovação 3. `min` slots são obrigatórios. Entre `min` e `max`, o slot é opcional.
_BULLETS: dict[str, tuple[int, int]] = {
    "nova_apolice@carf": (4, 4),
    "nova_apolice@estadual": (4, 4),
    "nova_apolice@ef": (4, 4),
    "nova_apolice@acoes_contribuinte": (4, 4),
    "substituicao_fianca": (2, 4),
    "substituicao_deposito": (2, 4),
    "substituicao_penhora": (2, 4),
    "renovacao_congenere": (3, 3),
    "renovacao_interna": (3, 3),
}

#: Limite por slot quando o compilado está velho. Decisão de 22/10/2026, item 5.
_MAX_NOVO: dict[str, int] = {"processo_administrativo.resumo": 500}

# ─────────────────────────────────────────────────────────────────────────────
# Decisões de 22/10/2026
# ─────────────────────────────────────────────────────────────────────────────

_DECISOES: list[str] = [
    "22/10/2026, item 5: processo_administrativo.resumo vai até 500 chars.",
    "22/10/2026, plano S4: bullets por tipo. Nova apólice 4. Substituição 2 a 4. Renovação 3.",
    "09/10/2026 e 22/10/2026, itens 3 e 4: zero cifra em valor.descricao. O box mostra um "
    "número só.",
    "22/10/2026, item 8: razão social completa. CNPJ da matriz. Filial só na nota interna.",
    "22/10/2026, item 7: na renovação, o texto nunca cita prêmio nem limite. A taxa fica no "
    "bloco, fora do texto.",
    "01/10/2026, BRIEF-BUILDER: ultima_decisao é o acórdão de mérito. A admissibilidade do "
    "recurso especial é da Presidência, não da Câmara Superior.",
    "28/09/2026: processo de outra empresa fica fora dos lugares que citam número.",
    "23/10/2026 (Alfredo, ficha Claro): na renovação, merito.p1 é a tese em discussão e "
    "merito.p2 é a garantia atual e a eficiência da renovação. Na nova apólice EF, p1 é a "
    "tese e p2 é a situação da EF.",
    "23/10/2026, regra 26: divida_ativa.detalhe deixa de ser slot. O status da dívida "
    "(SERPRO) é fato do código e não vai ao texto.",
    "23/10/2026, regra 25: com o valor de origem cda ou apolice_ou_fianca, valor.descricao "
    "copia a descrição fixa do esqueleto, sem \"estimado\" nem \"pode variar\".",
    "23/10/2026: o bullet 2 da renovação lê o bloco renovacao do esqueleto. Sem o bloco, "
    "\"corretagem não identificada na base\". Nunca inventar corretor.",
]

_GUIA_VALOR_DESCRICAO = (
    "Decisão de 09/10/2026 e de 22/10/2026 (itens 3 e 4): ZERO cifra neste slot. O box já "
    "mostra o número, e o box mostra um número só. Não escreva R$, nem faixa, nem segundo "
    "total. A 1ª frase diz o que o número é, em palavras (auto integral, saldo mantido, CDA "
    "consolidada, valor de referência). Depois diga a origem auditável (CDA, acórdão, "
    "posição datada) e o que o número não inclui. Sem memória de cálculo. "
    "Regra 25 (23/10/2026): quando os FATOS FIXOS trazem valor.origem = cda ou "
    "apolice_ou_fianca, o valor é exato e a descrição é fixa. Copie valor.descricao_fixa "
    "dos FATOS FIXOS, letra por letra. Não acrescente \"valor estimado\" nem \"pode "
    "variar\". "
)

#: A guidance de valor.descricao do compilado manda citar a composição em reais (R$,
#: centavos, Selic). A regra de 09/10/2026 proíbe isso. Por isso a guidance do slot é
#: TROCADA, não somada: duas ordens que se contradizem no mesmo prompt dão texto ruim.
#: A parte que não conflita fica, com a seção do Livro.
_GUIA_VALOR_POR_ORIGEM: dict[str, str] = {
    "nova_apolice_carf": (
        "Nomeie o degrau da cascata que sustentou o número: CDA inscrita, acórdão, recálculo "
        "próprio [§2.1 · VAL-01]. Diga a natureza do débito em palavras (tributo, período, "
        "multa nomeada, juros) [§2.3]. Se o valor não é cravável, diga que ele não consta das "
        "decisões públicas e como será confirmado (molde do BRIEF-BUILDER de 01/10/2026). Nunca "
        "fator, fórmula nem nome de esteira [§7 · S14]."
    ),
    "nova_apolice_tit": (
        "Nomeie a multa pela alínea do art. 85 da Lei 6.374/89 e a base sobre a qual ela "
        "incide, em palavras, sem cifra [§2.6 · S27]. Quando a CDA da PGE-SP casa pelo número "
        "do processo, ela é a âncora e vence o cálculo [§8 · TIP-13; §2.1 · VAL-02]. Diga a "
        "data da consulta."
    ),
    "nova_apolice_ef": (
        "Na EF o valor é o da CDA em execução [§0.2]. Ancore no número da CDA e na data da "
        "posição, e diga a relação com o processo administrativo de origem quando ele existe "
        "[§1.3 · CON-01]. Se a origem administrativa não consta na base, diga isso: é "
        "informação comercial [§1.4 · A04]."
    ),
    "substituicao_fianca": (
        "O número do box é o VALOR DE REFERÊNCIA DA OPORTUNIDADE, não a face da carta [§5.3 · "
        "A12/A13]. A 1ª frase diz isso e ancora na fonte do consolidado (CDA/PGFN datada). "
        "Depois cite a garantia vigente: emissor, número e vigência, sem a face em reais "
        "[§2.8 · VAL-11]. Sem hedge e sem dizer que o valor atual está errado [§2.8 · A14]. "
        "Proibido afirmar que a garantia atual é insuficiente: a tese é eficiência [§5.3 · A45]."
    ),
}

_GUIA_RAZAO_SOCIAL = (
    " Quando nomear a empresa, use a razão social completa dos FATOS FIXOS (22/10/2026, "
    "item 8)."
)

#: Proibições que as decisões novas somam por slot × família de tipo.
_PROIBICOES_NOVAS: dict[str, list[str]] = {
    "valor.descricao": ["R$ (qualquer cifra)", "faixa de valor", "segundo total", "Selic"],
}
_PROIBICOES_RENOVACAO = ["prêmio", "limite da apólice", "LMG", "taxa"]
_PROIBICOES_CARF = ["não admitido pela Câmara Superior", "segue para cobrança (como fecho)"]

#: Guidance extra por chave × slot, das regras de 01/10/2026 (BRIEF-BUILDER) e do Livro.
_GUIA_EXTRA: dict[tuple[str, str], str] = {
    ("nova_apolice@carf", "ultima_decisao.texto"): (
        " Regra de 01/10/2026: este slot é o ACÓRDÃO DE MÉRITO do CARF (data da sessão, número "
        "do acórdão, o que decidiu). A inadmissão do recurso especial ou do agravo vai em "
        "ultima_ocorrencia. A admissibilidade é da Presidência da Câmara de origem (recurso "
        "especial) ou da Presidência da CSRF (agravo): escreva \"à Câmara Superior\" ou \"por "
        "despacho da Presidência da Câmara Superior\", nunca \"não admitido pela Câmara "
        "Superior\"."
    ),
    ("nova_apolice@carf", "ultima_ocorrencia.texto"): (
        " Regra de 01/10/2026: quando a via esgotou, este slot diz a inadmissão do recurso "
        "especial ou do agravo, com a data, e que nenhum recurso foi registrado desde então, "
        "com a data da posição."
    ),
    ("nova_apolice@carf", "merito.p2"): (
        " Regra de 01/10/2026: o p2 não fecha com \"segue para cobrança\", \"inscrição\" ou "
        "\"execução\". O esgotamento aparece uma vez só no corpo."
    ),
    ("nova_apolice@carf", "bullets[0]"): (
        " Regra de 01/10/2026: o esgotamento aparece UMA vez, aqui, com a data."
    ),
    ("nova_apolice@carf", "bullets[3]"): (
        " Regra de 01/10/2026: quando a via já esgotou e não há evento futuro datado, o 4º "
        "bullet é um fato específico do caso, nunca um aviso genérico de cobrança."
    ),
}

#: Guidance que TROCA a do compilado (decisão de 23/10/2026, diagnóstico da ficha Claro).
#: A guidance velha da EF mandava descrever a execução no p1. O Alfredo quer a tese.
_GUIA_TESE_FONTES = (
    "As fontes ficam no dossiê: premissas_v3, qualificacao_s2c e "
    "documentos_indexados[].resumo."
)
_GUIA_CONEXO_CITAVEL = (
    "Identifique cada processo citado pela classe (\"Ação Anulatória\", \"Embargos à "
    "Execução Fiscal\", \"PA\"). Cite o número só se ele está na lista de PROCESSOS QUE O "
    "TEXTO PODE CITAR."
)
_GUIA_TROCA: dict[tuple[str, str], str] = {
    ("nova_apolice@ef", "merito.p1"): (
        "P1 na EF = a TESE (decisão do Alfredo, 23/10/2026). A tese vem do processo "
        "administrativo de origem da CDA: o tributo, a infração ou a autuação e o que o "
        "contribuinte contestou. Diga onde a discussão correu ou corre (PA no CARF ou ação "
        "conexa). " + _GUIA_TESE_FONTES + " A execução e a CDA entram só para situar, em uma "
        "frase. " + _GUIA_CONEXO_CITAVEL + " Se o dossiê não traz a tese, diga o débito de "
        "origem em palavras e não invente argumento [§1.3 · CON-01; §7 · S41]."
    ),
    ("nova_apolice@ef", "merito.p2"): (
        "P2 na EF = a SITUAÇÃO DA EF (decisão do Alfredo, 23/10/2026): a marcha da execução "
        "(citação, embargos, penhora, suspensão) e o estado da garantia, com datas. Situe a "
        "oportunidade pela fase (antes da citação, antes da penhora), sem prazo numérico. O "
        "status da dívida ativa não vai ao texto: é fato do código (regra 26). Achado judicial "
        "só contradiz a ficha se o polo passivo é a empresa E o processo se vincula àquele "
        "crédito [§8.3 · S19]."
    ),
}

#: Trechos do compilado que a regra 26 (23/10/2026) derruba: o status da dívida não vai
#: ao texto. O trecho sai da guidance e a proibição que o exigia sai da lista.
_TRECHOS_REGRA_26: list[tuple[str, str]] = [
    (", mais o status da dívida [§1.3 · CON-01].",
     " [§1.3 · CON-01]. O status da dívida não vai ao texto (regra 26, 23/10/2026)."),
]
_PROIBICOES_REGRA_26 = {"apresentar a EF sem dizer o status da dívida", "omitir o status da dívida"}

#: Exemplos que TROCAM os do compilado e os de `_EXEMPLOS_NOVOS` (23/10/2026).
_MOLDE_2310 = "molde de 23/10/2026 (forma; os fatos são ilustrativos)"
_EXEMPLOS_TROCA: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("nova_apolice@ef", "merito.p1"): [
        ("A CDA em execução vem de auto de infração de CIDE sobre remessas ao exterior por "
         "contratos de licença de software. A fiscalização entendeu que as remessas pagam "
         "transferência de tecnologia. A empresa sustenta que a licença de uso não transfere "
         "tecnologia e contestou o lançamento no CARF, que manteve a exigência; a discussão "
         "segue na Ação Anulatória conexa.", _MOLDE_2310)],
}

#: Substituição: a decisão de 22/10/2026 permite 2 a 4 bullets. O compilado fecha o
#: bullets[3] da fiança (o acervo pratica 2 a 3). O slot volta como opcional.
_GUIA_BULLET_OPCIONAL = (
    "Bullet OPCIONAL neste tipo. Escreva só quando o caso tem um fato que responde a uma "
    "das 6 perguntas canônicas (§6.1) e que os bullets anteriores não cobrem. Sem esse "
    "fato, devolva a string vazia \"\". Nunca repita um bullet anterior."
)

# ─────────────────────────────────────────────────────────────────────────────
# Exemplos que seguem as regras novas
# ─────────────────────────────────────────────────────────────────────────────

_IRB = "exemplar canônico IRB (lote carf_esgotados_2026-09-23)"
_BRIEF = "BRIEF-BUILDER de 01/10/2026 (lote resp_agravo_2s_2026-10-01)"
_FELICE = "ficha FELICE-ROSSO-DEPOSITO (fichas_output do carf-pipeline)"
_TOYOTA = "ficha TOYOTA-BR-RENOVACAO (LOTE_TOYOTA_2026-08-25), ajustada às regras de 10/09 e 22/10/2026"
_AMPLA = "ficha AMPLA-CARF-10872720163 (carf_novas_2026-08-27), ajustada às regras de 22/10/2026"
_ADAPTADO = "exemplo do compilado sem as cifras (regra de 09/10/2026)"

#: Exemplos novos por chave × slot: (texto, origem). Entram ANTES dos do compilado.
_EXEMPLOS_NOVOS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("nova_apolice@carf", "descricao_infracao"): [
        ("Receitas financeiras de reservas técnicas", _IRB)],
    ("nova_apolice@carf", "valor.descricao"): [
        ("PIS e COFINS cumulativos de 01/2015 a 12/2016 sobre receitas financeiras de ativos "
         "garantidores e variações cambiais, com multa de ofício de 75% e juros. Atualização "
         "do crédito consolidado na lavratura, mantido por inteiro no julgamento.", _IRB),
        ("Valor não consta das decisões públicas. Faixa estimada a partir de dados públicos da "
         "empresa e das alíquotas em discussão, com multa e juros até 02/2026; confirmação pelo "
         "auto de infração ou pela inscrição em dívida ativa.", _BRIEF),
    ],
    ("nova_apolice@carf", "processo_administrativo.resumo"): [
        ("Autos de infração exigindo PIS e COFINS no regime cumulativo sobre receitas "
         "financeiras dos ativos garantidores das reservas técnicas e sobre variações cambiais "
         "dos anos de 2015 e 2016. A DRJ manteve a exigência e o CARF negou provimento integral "
         "ao recurso voluntário.", _IRB)],
    ("nova_apolice@carf", "ultima_decisao.texto"): [
        ("O CARF negou provimento integral ao recurso voluntário (acórdão 3102-004.203): unânime "
         "quanto às variações cambiais de prêmios, e por voto de qualidade — desempate a favor "
         "da Fazenda — quanto às receitas financeiras dos ativos garantidores.", _IRB)],
    ("nova_apolice@carf", "ultima_ocorrencia.texto"): [
        ("Recurso especial à Câmara Superior não admitido; encerrada a discussão administrativa "
         "e aberta a fase de cobrança do crédito.", _IRB)],
    ("nova_apolice@carf", "bullets[0]"): [
        ("Via administrativa esgotada em 01/09/2026: a empresa não tem mais recurso a interpor "
         "dentro do CARF.", _IRB)],
    ("nova_apolice@carf", "bullets[1]"): [
        ("Exigência mantida por inteiro nas três instâncias, sem redução de nenhuma parcela.",
         _IRB)],
    ("nova_apolice@carf", "bullets[2]"): [
        ("A parcela dos ativos garantidores foi mantida por voto de qualidade, com três "
         "conselheiros vencidos a favor da empresa.", _IRB)],
    ("nova_apolice@carf", "bullets[3]"): [
        ("Autuação de dois anos-calendário (2015 e 2016) em processo único, sem parcela "
         "destacada em discussão à parte.", _IRB)],
    ("nova_apolice@carf", "merito.p1"): [
        ("A tese é a incidência de PIS e COFINS sobre o rendimento financeiro das reservas "
         "técnicas — o patrimônio que a resseguradora é obrigada por lei a manter aplicado para "
         "honrar sinistros futuros. A fiscalização entendeu que os rendimentos dos ativos que "
         "garantem as reservas técnicas, e também as variações cambiais das operações de "
         "resseguro, são receitas operacionais ligadas ao objeto social — logo, base de cálculo "
         "das contribuições. Foram lavrados autos de infração de PIS e COFINS dos "
         "anos-calendário de 2015 e 2016, com multa de ofício de 75%.", _IRB)],
    ("nova_apolice@carf", "merito.p2"): [
        ("A DRJ julgou a impugnação improcedente. Em 17/06/2026, o CARF negou provimento "
         "integral ao recurso voluntário (acórdão 3102-004.203): unânime quanto às variações "
         "cambiais de prêmios, por voto de qualidade quanto às receitas financeiras dos ativos "
         "garantidores e por maioria quanto às demais variações cambiais. O recurso especial à "
         "Câmara Superior não foi admitido em 01/09/2026, encerrando a via administrativa.",
         _IRB)],
    ("nova_apolice@estadual", "valor.descricao"): [
        ("Saldo consolidado da CDA PGE-SP 1466040244 (inscrita em 16/06/2026, consulta de "
         "03/08/2026). Origem: creditamento indevido de ICMS, com multa e juros.", _ADAPTADO),
        ("Imposto exigido no AIIM mais as multas legais do art. 85 da Lei 6.374/89: 100% sobre "
         "créditos indevidos, 75% sobre a falta de pagamento e 10% sobre obrigações acessórias. "
         "Não inclui juros; a CDA definirá o exigível.", _ADAPTADO),
    ],
    ("substituicao_fianca", "valor.descricao"): [
        ("Valor de referência da oportunidade — dívida ativa consolidada pela PGFN (CDA 80 6 17 "
         "007637-70, 03/08/2026). Carta de fiança Safra nº 422.010-6, vigente até 15/02/2027.",
         _ADAPTADO),
        ("Valor de referência da oportunidade — dívida ativa consolidada pela PGFN (CDA 70 2 02 "
         "001791-04, 03/08/2026). Carta de fiança Bradesco por prazo indeterminado, apresentada "
         "em 2011 e aditada em 2014.", _ADAPTADO),
    ],
    ("substituicao_fianca", "bullets[3]"): [
        ("Hospital vendido pelo grupo DASA em 12/2025 (fato público) — a fiança veio da gestão "
         "anterior; momento natural de rever a garantia.",
         "compilado: bullets[0] de substituicao_fianca"),
    ],
}

#: Exemplos que SUBSTITUEM os herdados (a chave tem acervo próprio).
_EXEMPLOS_PROPRIOS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("substituicao_deposito", "descricao_infracao"): [
        ("Depósito judicial em ação declaratória", _FELICE)],
    ("substituicao_deposito", "valor.descricao"): [
        ("Saldo dos depósitos judiciais nas demonstrações financeiras de 2025: depósito inicial "
         "em 11/2016, seguido de aportes mensais até 03/2020.", _FELICE + ", sem as cifras")],
    ("substituicao_deposito", "bullets[0]"): [
        ("Ação ajuizada em 08/11/2016; sentença de procedência em 07/06/2021, confirmada pelo "
         "TRF6.", _FELICE)],
    ("substituicao_deposito", "bullets[1]"): [
        ("STJ negou provimento ao agravo da Fazenda em 25/02/2026, com acórdão publicado em "
         "03/03/2026.", _FELICE)],
    ("substituicao_deposito", "bullets[2]"): [
        ("Autos remetidos ao STF em 07/05/2026; recurso extraordinário da Fazenda sobrestado "
         "pelo Tema 1255.", _FELICE)],
    ("substituicao_deposito", "bullets[3]"): [
        ("Em 04/09/2026, ambas as partes requereram o levantamento do sobrestamento.", _FELICE)],
    ("substituicao_deposito", "merito.p1"): [
        ("A Fundação é a mantenedora do Hospital Felício Rocho e era isenta de contribuições "
         "previdenciárias por ser entidade beneficente. Em 31/10/2014 o Ministério da Saúde "
         "cancelou o CEBAS, certificado que atesta essa condição, com efeito retroativo a "
         "01/01/2011, sob o fundamento de que o hospital não atingia o percentual mínimo de "
         "atendimentos ao SUS. Sem o certificado, a Receita Federal passou a exigir as "
         "contribuições patronais, o RAT e as destinadas a terceiros.", _FELICE)],
    ("substituicao_deposito", "ultima_decisao.texto"): [
        ("STJ, Segunda Turma, por unanimidade, negou provimento ao agravo interno da Fazenda "
         "Nacional (AgInt no AREsp 2.848.973/MG, Rel. Min. Afrânio Vilela), mantendo a "
         "imunidade reconhecida para os fatos geradores de 2011 a 16/12/2021.", _FELICE)],
    ("substituicao_deposito", "ultima_ocorrencia.texto"): [
        ("Fundação e Fazenda Nacional requereram o levantamento do sobrestamento para "
         "prosseguimento do recurso extraordinário no STF.", _FELICE)],
    ("substituicao_deposito", "observacao"): [
        ("O recurso pendente no STF discute honorários advocatícios, não o mérito da imunidade. "
         "Enquanto tramita, os valores permanecem depositados.", _FELICE)],
}

# ─────────────────────────────────────────────────────────────────────────────
# Renovação de congênere — do Livro §5.4 e §6.2 (10/09/2026)
# ─────────────────────────────────────────────────────────────────────────────

_REN = "Livro §5.4 e §6.2 (10/09/2026)"

#: slot -> (guidance, exemplos[(texto, origem)], livro_ids)
_RENOVACAO_CONGENERE: dict[str, tuple[str, list[tuple[str, str]], list[str]]] = {
    "descricao_infracao": (
        "A legenda nomeia a dívida garantida (tributo e matéria), como na nova apólice. O header "
        "já diz RENOVAÇÃO DE CONGÊNERE: não repita \"Renovação\" nem a data de vencimento aqui.",
        [("Glosa de custos de aquisição de energia", _AMPLA)],
        ["§5.4", "§1"],
    ),
    "valor.descricao": (
        "O valor estampado é o consolidado da(s) CDA(s) garantida(s) pela apólice (§5.4). A 1ª "
        "frase diz isso. Diga a fonte e a data da posição. O texto nunca cita prêmio, limite "
        "(LMG) nem taxa: a taxa fica no bloco roxo (22/10/2026, item 7).",
        [("Consolidado das quatro CDAs que a apólice de seguro garantia garante na execução "
          "fiscal, conforme registro da PGFN (posição de 05/08/2026).", _AMPLA)],
        ["§5.4", "§2.8"],
    ),
    "processo_administrativo.resumo": (
        "Trâmite do processo administrativo de origem, quando ele existe: autuação, julgamentos "
        "e o ponto em que o contencioso parou. É resumo de rito, não de mérito.",
        [("Auto de infração de IRPJ, CSLL, PIS e COFINS do ano-calendário de 2014, por glosa de "
          "custos de aquisição de energia não comprovados. A DRJ e o CARF reduziram a exigência "
          "em parte e o núcleo do lançamento foi mantido.", _AMPLA)],
        ["§7"],
    ),
    "ultima_decisao.texto": (
        "O último ato decisório da execução fiscal que a apólice garante (suspensão, decisão "
        "sobre a garantia, sentença de embargos). Todo CNJ citado vem com a classe "
        "(\"Embargos à Execução Fiscal 0017192-09.2017.4.03.6182\"). A V1 não narra o desfecho "
        "dos conexos.",
        [("Execução suspensa em 07/08/2026 até o julgamento dos Embargos à Execução Fiscal, "
          "depois da impugnação da Fazenda em 14/07/2026.", _TOYOTA)],
        ["§6.2", "§4"],
    ),
    "ultima_ocorrencia.texto": (
        "O último andamento datado da execução ou da dívida garantida, sem interpretação "
        "comercial. O status da dívida ativa não vai ao texto (regra 26, 23/10/2026).",
        [("Fazenda impugnou os embargos em 14/07/2026; nenhum andamento posterior até a "
          "posição de 05/08/2026.", _MOLDE_2310)],
        ["§4"],
    ),
    "bullets[0]": (
        "BULLET 1 = a APÓLICE: emissão, seguradora e o último endosso que mexeu no limite, sem "
        "citar o valor do limite. Nada que o bloco roxo já mostra (seguradora em destaque, "
        "vencimento, taxa). Nenhum bullet fala da janela: o vencimento já está no bloco "
        "(§6.2).",
        [("Apólice da Tokio Marine emitida em 24/09/2024, ainda em tutela cautelar antecedente, "
          "e aceita nos autos da execução fiscal.", _TOYOTA)],
        ["§6.2"],
    ),
    "bullets[1]": (
        "BULLET 2 = a CORRETAGEM: quem entrou, quem saiu e desde quando. A fonte é o bloco "
        "renovacao dos FATOS FIXOS: corretores, seguradora e fim_vigencia (23/10/2026). A "
        "taxa_fmt fica no bloco roxo, fora do texto (22/10/2026, item 7). Corretor novo num "
        "endosso recente costuma significar conta em disputa. Nome curto do corretor, sem "
        "razão social (§5.4). Sem o bloco renovacao, ou com a lista de corretores vazia, "
        "escreva \"Corretagem não identificada na base.\" Nunca invente corretor.",
        [("Corretor atual da conta: Toyota Tsusho, corretora do próprio grupo.", _TOYOTA)],
        ["§6.2", "§5.4"],
    ),
    "bullets[2]": (
        "BULLET 3 = o ESTADO DO PROCESSO: o fato que explica por que a garantia continua "
        "exigida. Fatos com datas, nunca veredito (\"ainda vai demorar\" é proibido).",
        [("Embargos em curso e execução suspensa desde 07/08/2026, à espera do julgamento; a "
          "garantia segue exigida nos autos.", _TOYOTA)],
        ["§6.2"],
    ),
    # 23/10/2026 (Alfredo, ficha Claro: "a descrição não traz nenhuma substância sobre o
    # mérito"): o mérito passa ao V2. A proibição de narrar conexos (§6.2, V1) sai daqui.
    "merito.p1": (
        "P1 = a TESE em discussão (decisão do Alfredo, 23/10/2026). Diga o tributo, a "
        "infração ou a autuação, o que o contribuinte contesta e onde ele contesta (PA no "
        "CARF ou ação conexa). " + _GUIA_TESE_FONTES + " " + _GUIA_CONEXO_CITAVEL + " Se o "
        "dossiê não traz a tese, diga o débito garantido em palavras e não invente argumento.",
        [("A dívida garantida vem de auto de infração de IRPJ e CSLL de 2016 por glosa da "
          "amortização de ágio de uma incorporação. A fiscalização entendeu que o ágio não tinha "
          "propósito negocial. A empresa sustenta que a operação foi real e contesta a glosa no "
          "PA, com recurso especial pendente na Câmara Superior do CARF.", _MOLDE_2310)],
        ["§6.2", "§7"],
    ),
    "merito.p2": (
        "P2 = a GARANTIA ATUAL e a eficiência da renovação (decisão do Alfredo, 23/10/2026). "
        "Diga a seguradora, a vigência e como a apólice entrou nos autos (em que execução ou "
        "ação, aceita em que data). Depois diga por que renovar é eficiente: a Lei 13.043/2014 "
        "pôs o seguro garantia no art. 9º da Lei 6.830/1980, com o mesmo efeito da penhora, e "
        "a renovação mantém o débito garantido sem bloqueio de caixa. Fatos com datas, nunca "
        "veredito. Sem prêmio, limite nem taxa. O status da dívida ativa não vai ao texto "
        "(regra 26).",
        [("A apólice da Tokio Marine, vigente até 24/09/2027, foi aceita nos autos da execução "
          "fiscal em 15/10/2024. A Lei 13.043/2014 pôs o seguro garantia no art. 9º da Lei "
          "6.830/1980, com o mesmo efeito da penhora: renovar antes do fim da vigência mantém "
          "o débito garantido sem bloqueio de caixa.", _MOLDE_2310)],
        ["§6.2", "§5.4"],
    ),
    "observacao": (
        "Default vazio. Só para fato atípico do caso que o leitor precisa saber e que nenhum "
        "outro slot cobre. Sem fato assim, devolva a string vazia \"\".",
        [("A execução cobra também a multa moratória, discutida em ação própria do contribuinte.",
          "molde do Livro §7 (fato atípico, sem conexo narrado)")],
        ["§7"],
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Variante acompanhamento (PROMPT-CONSTRUTOR, regra 5, e BRIEF-BUILDER de 01/10/2026)
# ─────────────────────────────────────────────────────────────────────────────

_ACOMPANHAMENTO: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "bullets[0]": (
        "Variante acompanhamento: o bullet 1 começa por \"Desde a apresentação de "
        "DD/MM/AAAA…\" (a data do envio anterior) e diz o fato novo com data, ou confirma que o "
        "estado se manteve. Não prometa mais do que a posição dos dados sustenta.",
        [("Desde a apresentação de 03/09/2026, o agravo foi não admitido em 23/09/2026; "
          "encerrada a via administrativa.", _BRIEF)],
    ),
    "valor.descricao": (
        "Variante acompanhamento: mesmo valor e mesma explicação do valor da ficha anterior. "
        "Só muda o que mudou de fato.",
        [("PIS e COFINS cumulativos de 01/2015 a 12/2016 sobre receitas financeiras de ativos "
          "garantidores e variações cambiais, com multa de ofício de 75% e juros. Atualização "
          "do crédito consolidado na lavratura, mantido por inteiro no julgamento.",
          _IRB + " (a explicação fica igual à da ficha anterior)")],
    ),
    "ultima_decisao.texto": (
        "Variante acompanhamento: reflete o estado de hoje, não o da ficha anterior.",
        [("O CARF negou provimento integral ao recurso voluntário (acórdão 3102-004.203): "
          "unânime quanto às variações cambiais de prêmios, e por voto de qualidade — desempate "
          "a favor da Fazenda — quanto às receitas financeiras dos ativos garantidores.", _IRB)],
    ),
    "ultima_ocorrencia.texto": (
        "Variante acompanhamento: reflete o estado de hoje, não o da ficha anterior.",
        [("Recurso especial à Câmara Superior não admitido; encerrada a discussão administrativa "
          "e aberta a fase de cobrança do crédito.", _IRB)],
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# Filtro de exemplos (as regras que reprovam um exemplo velho)
# ─────────────────────────────────────────────────────────────────────────────

#: Espelha os regex da S5 (garantis_shared/fichas/validadores/apendice_a.py, 22/10/2026):
#: A28, A29, A30, A50 a A55. A56 vale só em valor.descricao.
_RE_TEXTO_PROIBIDO: list[tuple[str, re.Pattern]] = [
    ("A28 previsão", re.compile(r"tende[m]? a|dever[áa](?![a-zà-ú])|ser[áa] necess[áa]ri|certamente|s[óo] cresce", re.I)),
    ("A29 vocabulário interno", re.compile(
        r"ia_inferido|poc_v1|motor_v2|engine|serpro|watchlist|banda plaus[íi]vel|piso sem selic"
        r"|base ia-inferida|snapshot|at[ée] hoje|nosso sistema", re.I)),
    ("A30 taxa/prêmio", re.compile(
        r"taxa (de refer[êe]ncia|de mercado|do pr[êe]mio|comercial)|pr[êe]mio de seguro|cosseguro"
        r"|\d+[.,]\d+\s*%\s*a\.?\s*a\.?", re.I)),
    ("A50 Garantis", re.compile(r"garantis", re.I)),
    ("A51 fornecedor", re.compile(r"predictus|escavador|jusbrasil|serpro|bigquery|\bleads\.", re.I)),
    ("A52 dificuldade nossa", re.compile(
        r"n[ãa]o localizad\w*|\ba apurar\b|documentos? n[ãa]o dispon[íi]ve\w*|n[ãa]o consta(m)? dos autos", re.I)),
    ("A53 mecânica de cálculo", re.compile(
        r"\bselic\b|capitaliz\w*|multiplicad[oa]s? por|\d+(?:[.,]\d+)?\s*%\s*a\.?\s*m\.?", re.I)),
    ("A54 remanescente", re.compile(r"remanescente", re.I)),
    ("A55 não consultada", re.compile(r"n[ãa]o consultad[oa]s?", re.I)),
]
_RE_A56 = re.compile(r"R\$\s*\d[\d.,]*(?:\s*(?:mil|milh[ãõ]o|milh[õo]es|bilh[ãõ]o|bilh[õo]es)\b)?")
_RE_RENOVACAO = re.compile(r"pr[êe]mio|\blimite\b|\bLMG\b|\btaxa\b", re.I)
#: Espelha `RE_STATUS_DIVIDA` de `validacao.py` (regra 26, 23/10/2026).
_RE_STATUS_DIVIDA = re.compile(
    r"\b(ativa\s+ajuizada|ativa\s+n[aã]o\s+ajuizada|garantida\s+por\s+seguro|serpro|regularize)\b",
    re.I)
_RE_CARF_BRIEF = re.compile(r"n[ãa]o admitid[oa] pela C[âa]mara Superior|segue para cobran[çc]a", re.I)


def _viola(texto: str, slot: str, chave: str, max_chars: int) -> str | None:
    """O motivo pelo qual o exemplo não serve mais, ou None."""
    if len(texto) > max_chars:
        return f"maior que {max_chars} chars"
    for nome, rx in _RE_TEXTO_PROIBIDO:
        if rx.search(texto):
            return nome
    if _RE_STATUS_DIVIDA.search(texto):
        return "regra 26: status da dívida no texto"
    if slot == "valor.descricao" and _RE_A56.search(texto):
        return "A56 cifra em valor.descricao"
    if chave.startswith("renovacao") and _RE_RENOVACAO.search(texto):
        return "renovação: prêmio, limite ou taxa"
    if chave == "nova_apolice@carf" and _RE_CARF_BRIEF.search(texto):
        return "regra de 01/10/2026 (BRIEF-BUILDER)"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Montagem
# ─────────────────────────────────────────────────────────────────────────────


def _uniq(itens: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in itens if i))


def _filtra_exemplos(exemplos: list[tuple[str, str]], slot: str, chave: str, max_chars: int):
    bons: list[str] = []
    origens: list[str] = []
    descartados: list[str] = []
    for texto, origem in exemplos:
        motivo = _viola(texto, slot, chave, max_chars)
        if motivo:
            descartados.append(motivo)
            continue
        if texto not in bons:
            bons.append(texto)
            origens.append(origem)
    return bons, _uniq(origens), descartados


def _slot_do_compilado(compilado: dict, slot: str, tipo_compilado: str) -> dict:
    s = compilado["slots"][slot]
    return {"max": s["max_chars"], **s["por_tipo"][tipo_compilado]}


def _monta_slot(chave: str, slot: str, base: dict, origem: str) -> dict:
    """Aplica as decisões de 22/10/2026 sobre o slot `base` (formato do compilado)."""
    max_chars = _MAX_NOVO.get(slot, base["max"])
    aplicavel = bool(base.get("aplicavel"))
    guidance = (base.get("guidance") or "").strip()
    proibicoes = list(base.get("proibicoes") or [])
    livro_ids = list(base.get("livro_ids") or [])

    if (chave, slot) in _GUIA_TROCA:
        guidance = _GUIA_TROCA[(chave, slot)]
    for velho, novo in _TRECHOS_REGRA_26:
        guidance = guidance.replace(velho, novo)
    proibicoes = [x for x in proibicoes if x not in _PROIBICOES_REGRA_26]
    if (chave, slot) in _EXEMPLOS_TROCA:
        exemplos_brutos = list(_EXEMPLOS_TROCA[(chave, slot)])
    else:
        exemplos_brutos = list(_EXEMPLOS_NOVOS.get((chave, slot), []))
        exemplos_brutos += [(e, "compilado:" + origem.split(":", 1)[-1])
                            for e in base.get("exemplos_bons") or []]

    obrigatorio = slot != "observacao"
    m = re.match(r"bullets\[(\d)\]", slot)
    if m:
        idx = int(m.group(1))
        bmin, bmax = _BULLETS[chave]
        aplicavel = idx < bmax
        obrigatorio = idx < bmin
        if aplicavel and not obrigatorio:
            guidance = (_GUIA_BULLET_OPCIONAL + " " + guidance).strip()

    if slot == "valor.descricao":
        tc = origem.split(":", 1)[1] if origem.startswith("compilado:") else ""
        guidance = _GUIA_VALOR_DESCRICAO + _GUIA_VALOR_POR_ORIGEM.get(tc, guidance)
    if slot in ("merito.p1", "bullets[0]"):
        guidance += _GUIA_RAZAO_SOCIAL
    guidance += _GUIA_EXTRA.get((chave, slot), "")

    proibicoes += _PROIBICOES_NOVAS.get(slot, [])
    if chave.startswith("renovacao"):
        proibicoes += _PROIBICOES_RENOVACAO
    if chave == "nova_apolice@carf":
        proibicoes += _PROIBICOES_CARF

    exemplos, origens, descartados = _filtra_exemplos(exemplos_brutos, slot, chave, max_chars)
    out = {
        "aplicavel": aplicavel,
        "obrigatorio": obrigatorio if aplicavel else False,
        "max": max_chars,
        "guidance": guidance.strip() if aplicavel else "",
        "exemplos": exemplos if aplicavel else [],
        "exemplos_origem": origens if aplicavel else [],
        "exemplos_descartados": len(descartados) if aplicavel else 0,
        "proibicoes": _uniq(proibicoes) if aplicavel else [],
        "livro_ids": livro_ids,
        "fonte": origem,
    }
    if not aplicavel:
        out["motivo"] = base.get("motivo") or (
            f"Fora da contagem de bullets do tipo ({_BULLETS[chave][1]} no máximo)."
            if m else "O Livro não usa este slot neste tipo.")
    return out


def _slot_renovacao(compilado: dict, slot: str) -> dict:
    # bullets[3] não existe na renovação (3 bullets, §6.2): _monta_slot o fecha.
    guidance, exemplos, livro_ids = _RENOVACAO_CONGENERE.get(slot, ("", [], ["§6.2"]))
    base = {
        "max": compilado["slots"][slot]["max_chars"],
        "aplicavel": True,
        "guidance": guidance,
        "exemplos_bons": [],
        "proibicoes": [],
        "livro_ids": livro_ids,
    }
    out = _monta_slot("renovacao_congenere", slot, base, f"livro:{_REN}")
    if out["aplicavel"]:
        bons, origens, desc = _filtra_exemplos(exemplos, slot, "renovacao_congenere", out["max"])
        out["exemplos"], out["exemplos_origem"] = bons, origens
        out["exemplos_descartados"] = len(desc)
    return out


def _herda(gerado: dict, chave: str, origem_chave: str) -> dict:
    """Copia o tipo `origem_chave` já gerado e aplica o ajuste e os exemplos próprios."""
    slots: dict[str, dict] = {}
    ajuste = _AJUSTE_HERDADO[chave]
    for slot in SLOTS:
        base = copy.deepcopy(gerado[origem_chave]["slots"][slot])
        m = re.match(r"bullets\[(\d)\]", slot)
        if m:
            bmin, bmax = _BULLETS[chave]
            idx = int(m.group(1))
            if base["aplicavel"] != (idx < bmax) or base["obrigatorio"] != (idx < bmin):
                raise ValueError(f"{chave}: contagem de bullets diverge de {origem_chave}")
        base["fonte"] = f"herdado_de:{origem_chave}"
        if base["aplicavel"]:
            base["guidance"] = f"{ajuste} {base['guidance']}"
            proprios = _EXEMPLOS_PROPRIOS.get((chave, slot))
            if proprios:
                bons, origens, desc = _filtra_exemplos(proprios, slot, chave, base["max"])
                base["exemplos"], base["exemplos_origem"] = bons, origens
                base["exemplos_descartados"] = len(desc)
                base["exemplos_herdados"] = False
            else:
                base["exemplos_herdados"] = True
        slots[slot] = base
    return slots


#: Regra 26 (Alfredo, 23/10/2026): o shared não pede mais `divida_ativa.detalhe`. O
#: código escreve o fato da dívida ativa. O slot fica no JSON com aplicavel=false: um
#: shared velho que ainda mande o slot recebe o nome em `campos_nao_aplicaveis`, sem erro.
_FONTE_REGRA_26 = "regra 26, 23/10/2026: fato do código"
_SLOTS_FORA: dict[str, str] = {
    "divida_ativa.detalhe": (
        "Regra 26 (23/10/2026): o código escreve o fato da dívida ativa. O shared não pede "
        "mais este slot."
    ),
}


def _fecha_slots(tipos: dict[str, dict]) -> None:
    for tipo in tipos.values():
        for slot, motivo in _SLOTS_FORA.items():
            velho = tipo["slots"][slot]
            tipo["slots"][slot] = {
                "aplicavel": False, "obrigatorio": False, "max": velho["max"],
                "guidance": "", "exemplos": [], "exemplos_origem": [],
                "exemplos_descartados": 0, "proibicoes": [], "livro_ids": [],
                "fonte": _FONTE_REGRA_26, "motivo": motivo,
            }


def gerar(compilado: dict, sha256: str) -> dict:
    tipos: dict[str, dict] = {}
    # 1ª passada: compilado e Livro. 2ª passada: herdados (a origem já existe).
    for chave, (origem, descricao) in _MAPA.items():
        if origem.startswith("compilado:"):
            tc = origem.split(":", 1)[1]
            slots = {s: _monta_slot(chave, s, _slot_do_compilado(compilado, s, tc), origem)
                     for s in SLOTS}
        elif origem.startswith("livro:"):
            slots = {s: _slot_renovacao(compilado, s) for s in SLOTS}
        else:
            continue
        tipos[chave] = {"descricao": descricao, "fonte": origem,
                        "bullets": {"min": _BULLETS[chave][0], "max": _BULLETS[chave][1]},
                        "slots": slots}
    for chave, (origem, descricao) in _MAPA.items():
        if origem.startswith("herdado_de:"):
            origem_chave = origem.split(":", 1)[1]
            tipos[chave] = {"descricao": descricao, "fonte": origem,
                            "bullets": {"min": _BULLETS[chave][0], "max": _BULLETS[chave][1]},
                            "slots": _herda(tipos, chave, origem_chave)}
    tipos = {chave: tipos[chave] for chave in _MAPA}  # ordem estável = ordem do _MAPA
    _fecha_slots(tipos)

    variante: dict[str, dict] = {}
    for slot in SLOTS:
        if slot in _ACOMPANHAMENTO:
            guidance, exemplos = _ACOMPANHAMENTO[slot]
            max_chars = _MAX_NOVO.get(slot, compilado["slots"][slot]["max_chars"])
            bons, origens, desc = _filtra_exemplos(exemplos, slot, "acompanhamento", max_chars)
            variante[slot] = {"guidance": guidance, "exemplos": bons,
                              "exemplos_origem": origens, "exemplos_descartados": len(desc),
                              "fonte": "PROMPT-CONSTRUTOR regra 5 + BRIEF-BUILDER (01/10/2026)"}
        else:
            variante[slot] = {"guidance": "", "exemplos": [], "exemplos_origem": [],
                              "exemplos_descartados": 0, "fonte": "herdado_de:<tipo base>"}

    globais = compilado["proibicoes_globais"]
    proibicoes_globais = []
    for grupo, bloco in globais.items():
        if grupo.startswith("_"):
            continue
        frases = bloco.get("frases") or bloco.get("frases_nuas_proibidas") or []
        proibicoes_globais.append({"grupo": grupo, "trava": bloco.get("trava", ""),
                                   "frases": list(frases),
                                   "forma_correta": bloco.get("forma_correta", ""),
                                   "excecao": bloco.get("excecao", "")})
    proibicoes_globais.append({
        "grupo": "licoes_do_alfredo_A50_A57", "trava": "A50-A57 (S5, 22/10/2026)",
        "frases": ["Garantis", "Predictus", "Escavador", "Jusbrasil", "SERPRO", "BigQuery",
                   "não localizado", "a apurar", "documentos não disponíveis",
                   "não constam dos autos", "Selic (no corpo)", "capitalização",
                   "multiplicado por", "remanescente", "não consultada",
                   "frase da nota interna"],
        "forma_correta": "Escreva o fato pelo processo: \"não constam das informações "
                         "processuais públicas\", \"será conhecido com a publicação do acórdão\".",
        "excecao": "",
    })

    return {
        "_meta": {
            "artefato": "livro_guidance",
            "versao": VERSAO,
            "gerado_por": "scripts/gerar_livro_guidance.py",
            "fonte": {
                "compilado": "src/agents/ficha_writer/livro_fonte/guidance-por-slot-tipo.json",
                "compilado_versao": compilado["_meta"].get("versao"),
                "compilado_gerado_em": compilado["_meta"].get("gerado_em"),
                "compilado_sha256": sha256,
                "livro": LIVRO_REF,
            },
            "decisoes": _DECISOES,
            "como_usar": (
                "O agente lê tipos[<chave>].slots[<slot>]. O CampoSpec do request vence campo "
                "a campo: guidance, exemplos e proibicoes vazios usam estes. Slot com "
                "aplicavel=false não vai ao prompt. A variante acompanhamento soma a sua "
                "guidance à do tipo base quando a tag acompanhamento está no esqueleto."
            ),
            "transversais": compilado["_meta"].get("transversais", {}),
        },
        "proibicoes_globais": proibicoes_globais,
        "tipos": tipos,
        "variantes": {"acompanhamento": {"tags": ["acompanhamento"], "slots": variante}},
    }


def serializar(dados: dict) -> str:
    return json.dumps(dados, ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--fonte", type=Path, default=FONTE_PADRAO)
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument("--checar", action="store_true",
                    help="não escreve; sai com 1 se a saída atual difere da gerada")
    args = ap.parse_args(argv)

    bruto = args.fonte.read_bytes()
    texto = serializar(gerar(json.loads(bruto), hashlib.sha256(bruto).hexdigest()))
    if args.checar:
        atual = args.saida.read_text(encoding="utf-8") if args.saida.exists() else ""
        if atual != texto:
            print(f"{args.saida} está velho. Rode scripts/gerar_livro_guidance.py.",
                  file=sys.stderr)
            return 1
        return 0
    args.saida.write_text(texto, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
