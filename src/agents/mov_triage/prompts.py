"""Prompt CURTO da triagem L1 v7 (1o estagio do desenho de 2 estagios).

PORTE de build_triagem_prompt do POC
/Users/alfredocavalcanteneto/Documents/prompt_monit_reader/l1_triagem.py.

CURTO DE PROPOSITO (~5k chars): a triagem e a 1a chamada BARATA. O prompt
juridico pesado (sentido/polos/recursos/extincao, ~21k chars) so roda no passe
COMPLETO (/mov-factsheet/classify) quando algum portao dispara. Aqui so persona
de triagem + taxonomia tipo_doc + os 2 portoes + a regra de ouro.

A taxonomia tipo_doc e o contexto de familia foram inlinados aqui (no POC vinham
de l1_comum) — codigo identico ao original, sem reescrita.
"""

from .schemas import DocAnexado, FallbackContext, MovInput, ProcessoContext

# Caps de corpo — triagem nao precisa do doc inteiro pra rotear.
_MOV_CAP = 3000
_DOC_CAP = 8000


# ── Taxonomia tipo_doc (v1) — inlinada do POC l1_comum._TAXONOMIA_TIPO_DOC ──────
_TAXONOMIA_TIPO_DOC = """tipo_doc — classifique em UMA destas opcoes (use 'outros' so se nada se encaixar):
  sentenca                   — decisao que julga o merito e encerra a fase de conhecimento em 1o grau
  acordao                    — decisao colegiada de tribunal (2o grau ou superior)
  decisao_interlocutoria     — decisao que RESOLVE/DETERMINA algo com conteudo decisorio
                               sem encerrar o feito (defere/indefere, determina liberacao
                               de credito, fixa honorarios, ordena penhora, concede/nega
                               liminar). Se o ato DECIDE/DETERMINA (nao so encaminha) e
                               assinado por JUIZ/RELATOR => decisao_interlocutoria, NAO despacho.
  despacho                   — ato de MERO expediente/ordinatorio que SO impulsiona o processo
                               sem decidir nada de fundo (abra-se vista, intime-se, conclusos,
                               cumpra-se, junte-se). Na DUVIDA entre despacho e
                               decisao_interlocutoria: se ha qualquer determinacao de conteudo
                               (valor, direito, garantia) => decisao_interlocutoria.
  voto                       — voto de relator/revisor que compoe um acordao
  peticao_inicial            — peca que inaugura a acao: narra fatos, fundamenta e pede
  peticao                    — manifestacao de parte no curso do processo (intercorrente)
  contestacao                — defesa do reu contra o pedido inicial
  recurso                    — irresignacao contra decisao (apelacao, agravo, RE, REsp)
  embargos                   — embargos (declaracao, execucao, terceiro)
  contrarrazoes              — resposta de parte contra recurso da adversaria
  certidao                   — ato de fe publica da serventia/cartorio atestando fato processual
  intimacao                  — comunicacao a parte/advogado de ato processual ou prazo
  citacao                    — chamamento inicial do reu para integrar a relacao processual
  oficio                     — comunicacao formal entre orgaos/autoridades
  mandado                    — ordem judicial para cumprimento por oficial de justica
  carta_precatoria           — deprecacao de ato a juizo de outra comarca
  ata_audiencia              — registro do que ocorreu em audiencia (incl. acordo)
  procuracao                 — instrumento de mandato que outorga poderes a advogado
  substabelecimento          — transferencia de poderes ja recebidos a outro advogado
  apolice_seguro_garantia    — apolice de seguro-garantia apresentada como garantia nos autos
  fianca_bancaria            — carta de fianca bancaria oferecida como garantia
  deposito_judicial          — comprovante/guia de deposito judicial em garantia ou pagamento
  penhora                    — auto/termo de penhora, arresto ou bloqueio (sisbajud/bacenjud)
  recusa_aceitacao_garantia  — manifestacao do juizo aceitando ou recusando a garantia ofertada
  cda                        — certidao de divida ativa / titulo executivo fiscal
  guia_recolhimento          — guia de arrecadacao/recolhimento (DARE, DARF, GRU, custas)
  comprovante_pagamento      — comprovante de pagamento/transferencia/extrato como prova
  planilha_calculo           — memoria/planilha de calculo de valores (debito, honorarios, atualizacao)
  parecer                    — manifestacao tecnica/opinativa (MP, juridico, contabil)
  laudo_pericial             — laudo de pericia tecnica produzida nos autos
  prova_anexa                — documento juntado como PROVA/anexo sem ato proprio (contrato,
                               fatura, nota fiscal, extrato, CTPS, ato societario, RG, print, foto)
  ilegivel                   — documento sem texto util / OCR corrompido / so carimbo de assinatura
  outros                     — nao se encaixa em nenhum tipo acima"""


# ── Contexto de familia por materia — inlinado do POC l1_comum._FAMILIA_CTX ─────
_FAMILIA_CTX = {
    "tributario": (
        "MATERIA (ramo do direito): TRIBUTARIO/FISCAL. Aqui o Tomador e o "
        "CONTRIBUINTE: figura como EXECUTADO (Execucao Fiscal) ou como AUTOR "
        "(Anulatoria, Mandado de Seguranca, Tutela Cautelar/Antecedente, Embargos "
        "a Execucao). Parte adversa: a FAZENDA PUBLICA. Discute-se a exigibilidade "
        "de credito tributario (CDA)."
    ),
    "trabalhista": (
        "MATERIA (ramo do direito): TRABALHISTA. Aqui o Tomador e a EMPRESA: figura "
        "como RECLAMADA/executada. Parte adversa: o reclamante (empregado). A "
        "garantia costuma cobrir deposito recursal ou execucao trabalhista."
    ),
    "civel": (
        "MATERIA (ramo do direito): CIVEL (generica). O Tomador pode estar em "
        "QUALQUER polo — depende do objeto da acao e de quem a propos. NAO assuma "
        "um lado por padrao."
    ),
}


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return (
        s.lower().replace("á", "a").replace("ã", "a").replace("â", "a")
        .replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o")
        .replace("ô", "o").replace("ú", "u").replace("ç", "c")
    )


def _familia_block(processo: ProcessoContext) -> str:
    """Bloco de familia por materia. materia vem de
    monitoramento.apolices_monitoradas.materia (fiscal/trabalhista/civel) e e
    passada via ProcessoContext.materia quando disponivel."""
    materia = getattr(processo, "materia", None)
    if not materia:
        return (
            "MATERIA (ramo do direito) NAO INFORMADA — deduza pelo proprio texto; "
            "se faltar base, NAO chute."
        )
    return _FAMILIA_CTX.get(_norm(materia), f"FAMILIA: {materia}.")


# ── Persona + regra de ouro (porte direto do POC) ──────────────────────────────
_TRIAGEM_PERSONA = (
    "Voce e um especialista em direito brasileiro fazendo a TRIAGEM RAPIDA de um "
    "ato processual, pela lente de uma SEGURADORA DE SEGURO GARANTIA JUDICIAL. O "
    "TOMADOR e o nosso cliente (a parte por quem prestamos a garantia). Sua tarefa "
    "NAO e analisar a fundo — e classificar o ato e responder DUAS perguntas de "
    "roteamento (abaixo), pra decidir se ele merece uma analise juridica completa."
)

_TRIAGEM_REGRA = (
    "REGRA DE OURO DA TRIAGEM: na MENOR duvida, responda 'true' (sim) aos portoes "
    "mov_merito / mov_garantia_exec. Marcar 'sim' a mais custa pouco; deixar passar "
    "um ato de risco (ex: acionamento da garantia) e o pior erro possivel. Prefira "
    "errar mandando pra analise completa."
)


def build_mov_triage_prompt(
    processo: ProcessoContext,
    mov: MovInput,
    documentos_anexados: list[DocAnexado] | None = None,
    fallback_context: FallbackContext | None = None,
) -> str:
    """Monta o prompt curto da triagem pra uma unidade (mov e/ou docs).

    Funciona pras 4 classes de input: 1A (so mov), 1B/1C (mov+doc), 1D (so doc).
    fallback_context aceito pela paridade de assinatura com o factsheet (a triagem
    nao o consome — o roteamento e barato e nao precisa de contexto anterior).
    """
    documentos_anexados = documentos_anexados or []

    fam = _familia_block(processo)

    tom = getattr(processo, "nm_tomador", None)
    tom_linha = ""
    if tom:
        cnpj = getattr(processo, "cnpj_tomador", None)
        tom_linha = f"TOMADOR (nosso cliente) neste processo: {tom}"
        tom_linha += f" (CNPJ {cnpj})" if cnpj else ""
        tom_linha += ".\n"

    # corpo: mov + docs anexados
    blocos = []
    txt = (mov.texto or "").strip()[:_MOV_CAP]
    tipo_origem = mov.tipo or "?"
    blocos.append(f"=== MOVIMENTACAO ===\n  tipo_origem: {tipo_origem}\n  texto:\n  {txt}")
    for doc in documentos_anexados:
        d = (doc.text_content or "").strip()
        trunc = "\n  [TRUNCADO]" if len(d) > _DOC_CAP else ""
        d = d[:_DOC_CAP].replace("\n", "\n  ")
        rotulo = doc.tipo or doc.titulo or "?"
        blocos.append(f"=== DOCUMENTO ===\n  tipo: {rotulo}\n  texto:\n  {d}{trunc}")
    corpo = "\n\n".join(blocos)

    return f"""{_TRIAGEM_PERSONA}

=== CONTEXTO DA GARANTIA ===
{tom_linha}{fam}

{corpo}

=== O QUE RESPONDER ===
- resumo_ato (~40 palavras, PORTUGUES ACENTUADO): o que aconteceu aqui.
- {_TAXONOMIA_TIPO_DOC}

PORTOES DE ROTEAMENTO (responda sim/nao):
- mov_merito: este ato DECIDE algo OU traz tese/pedido/prova/desfecho que move o
  rumo do processo? (peticao inicial, recurso, embargos, excecao, contestacao,
  manifestacao sobre prova, laudo, transito em julgado, pedido de cumprimento =
  SIM, mesmo sem julgamento). So 'nao' para ato puramente administrativo.
- tem_decisao: houve um JULGAMENTO/pronunciamento que decide (sentenca, acordao,
  liminar, interlocutoria, despacho decisorio)? Uma peticao/recurso da PARTE NAO
  e decisao (false), embora mov_merito seja true.
- mov_garantia_exec: REGRA DURA (este e o NOSSO ativo — nunca deixe passar):
  marque SEMPRE 'true' se o ato MENCIONA, de qualquer forma, QUALQUER um destes —
  seguro garantia / seguro-garantia judicial, APOLICE, FIANCA (bancaria), DEPOSITO
  (judicial/recursal/em garantia), CAUCAO, garantia (oferecida/aceita/recusada/
  substituida/reforcada/levantada/executada), ACIONAMENTO da garantia (incl.
  linguagem administrativa: 'intime-se a garantidora/seguradora', 'expeca-se a
  seguradora', 'converta-se o seguro em pagamento', 'execute-se a garantia') —
  OU avanca a cobranca/execucao CONTRA O TOMADOR (cumprimento de sentenca,
  execucao, intimacao pra pagar, penhora de bens dele). NA DUVIDA, marque 'true':
  perder um ato de garantia e o pior erro possivel; mandar a mais custa pouco.
- confianca (0-1).

{_TRIAGEM_REGRA}

Output: JSON conforme o schema da triagem (MovTriageCard, enforced via
response_schema do Gemini).
"""
