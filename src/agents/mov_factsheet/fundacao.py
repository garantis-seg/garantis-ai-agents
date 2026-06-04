"""Fundação resolvida + família + taxonomia + mapas de derivação (L1 v7).

Porte fiel do POC (prompt_monit_reader: l1_fundacao.py + l1_comum.py), adaptado
pra ler ProcessoContext (objeto pydantic) OU dict via _get.

- bloco_fundacao: texto mastigado pro prompt (Tomador no polo X / INFIRA grupo
  econômico quando o nome não casa — caso Casas Bahia/Via S.A). Antes a fundação
  era descartada no boundary do ProcessoContext (fix em schemas.py).
- _familia_block: contexto por matéria (tributário/trabalhista/cível).
- TAXONOMIA_TIPO_DOC + RELEVANTE_GARANTIA: prosa pro prompt (34 tipos).
- derivar_categoria / derivar_status_garantia: o LLM emite tipo_doc(34) e
  evento_garantia.tipo; o agent DERIVA por código categoria(14) e
  status_garantia_pos_mov (campos que a L2 lê). Ver memory l1-invariante-fundacao.

NÃO porta validar_fundacao/FundacaoInvalida: a validação de fundação é do shared
(validar_fundacao_step no dbos_workflow); o agent recebe o que vier.
"""
from __future__ import annotations

import re
from typing import Any


def _get(processo: Any, campo: str):
    """Lê de objeto (pydantic) OU dict."""
    if isinstance(processo, dict):
        return processo.get(campo)
    return getattr(processo, campo, None)


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return (s.lower().replace("á", "a").replace("ã", "a").replace("â", "a")
            .replace("é", "e").replace("ê", "e").replace("í", "i").replace("ó", "o")
            .replace("ô", "o").replace("ú", "u").replace("ç", "c"))


# ── normalização de nome de empresa pra match com os polos ────────────────────
_SUFIXOS = re.compile(
    r"\b(S/?A|S\.A\.?|LTDA|EIRELI|ME|EPP|CIA|GRUPO|DO BRASIL|"
    r"PARTICIPACOES|EM RECUPERACAO JUDICIAL|HOLDING)\b"
)


def _nome_tokens(s: str | None) -> set[str]:
    if not s:
        return set()
    s = _SUFIXOS.sub("", s.upper())
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    return {t for t in s.split() if len(t) > 2}


def _as_list(x) -> list[str]:
    if not x:
        return []
    if isinstance(x, (list, tuple)):
        return [str(i) for i in x if str(i).strip()]
    return [p.strip() for p in str(x).split(";") if p.strip()]


def polo_do_tomador(nm_tomador, polo_ativo, polo_passivo) -> str:
    """'ativo' | 'passivo' | 'incerto'. 'incerto' NÃO é erro — é inferência de grupo (LLM)."""
    tt = _nome_tokens(nm_tomador)
    if not tt:
        return "incerto"
    pa_l, pp_l = _as_list(polo_ativo), _as_list(polo_passivo)
    pa = set().union(*[_nome_tokens(x) for x in pa_l]) if pa_l else set()
    pp = set().union(*[_nome_tokens(x) for x in pp_l]) if pp_l else set()
    in_a, in_p = bool(tt & pa), bool(tt & pp)
    if in_a and not in_p:
        return "ativo"
    if in_p and not in_a:
        return "passivo"
    return "incerto"


def bloco_fundacao(processo: Any) -> str:
    """Texto MASTIGADO pro prompt: classe + polos + polo do Tomador resolvido
    (ou instrução de inferir grupo quando incerto)."""
    tom = _get(processo, "nm_tomador")
    pa = _as_list(_get(processo, "polo_ativo"))
    pp = _as_list(_get(processo, "polo_passivo"))
    pa_s = "; ".join(pa) if pa else "(vazio)"
    pp_s = "; ".join(pp) if pp else "(vazio)"
    lado = polo_do_tomador(tom, pa, pp)

    L = ["=== FUNDACAO DO PROCESSO (dados da base — confie nestes) ==="]
    L.append(f"Classe: {_get(processo, 'classe')}")
    L.append(f"Materia: {_get(processo, 'materia')}")
    L.append(f"Polo ATIVO:   {pa_s}")
    L.append(f"Polo PASSIVO: {pp_s}")
    if tom:
        cnpj = _get(processo, "cnpj_tomador")
        L.append(f"TOMADOR (nosso cliente): {tom}" + (f" (CNPJ {cnpj})" if cnpj else ""))
        if lado == "ativo":
            L.append(">>> O TOMADOR esta no POLO ATIVO (autor/exequente/embargante/"
                     "impetrante conforme a classe). Procedente do PEDIDO DELE = FAVORAVEL.")
        elif lado == "passivo":
            L.append(">>> O TOMADOR esta no POLO PASSIVO (reu/executado/reclamada). "
                     "Procedente contra ele = DESFAVORAVEL; improcedente = favoravel.")
        else:
            L.append(">>> O nome do Tomador NAO bate exatamente com os polos acima. "
                     "ISSO E COMUM (mesmo GRUPO ECONOMICO com nome diferente — ex: matriz "
                     "vs subsidiaria/distribuidora). INFIRA se o Tomador e o MESMO GRUPO de "
                     "uma das partes (pela razao social/CNPJ/contexto) e use ESSE polo. "
                     "So deixe o polo indefinido (sentido=neutro, confianca<=0.5) se "
                     "realmente nao der pra ligar o Tomador a nenhuma parte.")
    return "\n".join(L) + "\n"


# ── família por matéria ───────────────────────────────────────────────────────
_FAMILIA_CTX = {
    "tributario": ("MATERIA (ramo do direito): TRIBUTARIO/FISCAL. Aqui o Tomador e o "
                   "CONTRIBUINTE: figura como EXECUTADO (Execucao Fiscal) ou como AUTOR "
                   "(Anulatoria, Mandado de Seguranca, Tutela Cautelar/Antecedente, "
                   "Embargos a Execucao). Parte adversa: a FAZENDA PUBLICA. Discute-se a "
                   "exigibilidade de credito tributario (CDA)."),
    "trabalhista": ("MATERIA (ramo do direito): TRABALHISTA. Aqui o Tomador e a EMPRESA: "
                    "figura como RECLAMADA/executada. Parte adversa: o reclamante "
                    "(empregado). A garantia costuma cobrir deposito recursal ou execucao "
                    "trabalhista."),
    "civel": ("MATERIA (ramo do direito): CIVEL (generica). O Tomador pode estar em QUALQUER "
              "polo — depende do objeto da acao e de quem a propos. NAO assuma um lado por padrao."),
}


def familia_block(processo: Any) -> str:
    materia = _get(processo, "materia")
    if not materia:
        return ("MATERIA (ramo do direito) NAO INFORMADA — deduza pelo proprio texto; "
                "se faltar base, NAO chute.")
    return _FAMILIA_CTX.get(_norm(materia), f"FAMILIA: {materia}.")


# ── taxonomia tipo_doc (34) + relevante_garantia — prosa pro prompt ───────────
TAXONOMIA_TIPO_DOC = """tipo_doc — classifique em UMA destas opcoes (use 'outros' so se nada se encaixar):
  sentenca                   — decisao que julga o merito e encerra a fase de conhecimento em 1o grau
  acordao                    — decisao colegiada de tribunal (2o grau ou superior)
  decisao_interlocutoria     — decisao que RESOLVE/DETERMINA algo com conteudo decisorio sem encerrar
                               o feito. Se o ato DECIDE/DETERMINA (nao so encaminha) e assinado por
                               JUIZ/RELATOR => decisao_interlocutoria, NAO despacho.
  despacho                   — ato de MERO expediente/ordinatorio que SO impulsiona o processo sem
                               decidir nada de fundo. Na DUVIDA entre despacho e decisao_interlocutoria:
                               se ha qualquer determinacao de conteudo (valor, direito, garantia) =>
                               decisao_interlocutoria.
  voto                       — voto de relator/revisor que compoe um acordao
  peticao_inicial            — peca que inaugura a acao: narra fatos, fundamenta e pede
  peticao                    — manifestacao de parte no curso do processo (intercorrente)
  contestacao                — defesa do reu contra o pedido inicial
  recurso                    — irresignacao contra decisao (apelacao, agravo, RE, REsp)
  embargos                   — embargos (declaracao, execucao, terceiro)
  contrarrazoes              — resposta de parte contra recurso da adversaria
  certidao                   — ato de fe publica da serventia atestando fato processual
  intimacao                  — comunicacao a parte/advogado de ato processual ou prazo
  citacao                    — chamamento inicial do reu
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
  planilha_calculo           — memoria/planilha de calculo de valores
  parecer                    — manifestacao tecnica/opinativa (MP, juridico, contabil)
  laudo_pericial             — laudo de pericia tecnica produzida nos autos
  prova_anexa                — documento juntado como PROVA/anexo sem ato proprio
  ilegivel                   — documento sem texto util / OCR corrompido / so carimbo de assinatura
  outros                     — nao se encaixa em nenhum tipo acima"""

RELEVANTE_GARANTIA = (
    "relevante_garantia (bool) — true se o ato TRATA do risco de acionamento da apolice: "
    "apolice, fianca, deposito judicial, penhora, aceite/recusa de garantia (caucao/idoneidade), "
    "intimacao de pagamento ou de cumprimento de sentenca. MARQUE true MESMO que o tipo seja uma "
    "peca processual comum (ex: um despacho que defere o seguro-garantia e tipo=despacho, mas "
    "relevante_garantia=true)."
)


# ── derivação por código (o LLM emite tipo_doc; o agent deriva categoria) ─────
# categoria (14 valores que a L2 lê) ← tipo_doc (34). Mapa duro.
_TIPO_DOC_TO_CATEGORIA = {
    "sentenca": "sentenca",
    "acordao": "acordao",
    "decisao_interlocutoria": "decisao_interlocutoria",
    "despacho": "despacho",
    "voto": "acordao",
    "peticao_inicial": "peticao",
    "peticao": "peticao",
    "contestacao": "peticao",
    "recurso": "peticao",
    "embargos": "peticao",
    "contrarrazoes": "peticao",
    "certidao": "certidao",
    "intimacao": "intimacao",
    "citacao": "intimacao",
    "oficio": "outros",
    "mandado": "outros",
    "carta_precatoria": "outros",
    "ata_audiencia": "outros",
    "procuracao": "outros",
    "substabelecimento": "outros",
    "apolice_seguro_garantia": "outros",
    "fianca_bancaria": "outros",
    "deposito_judicial": "outros",
    "penhora": "decisao_interlocutoria",
    "recusa_aceitacao_garantia": "decisao_interlocutoria",
    "cda": "outros",
    "guia_recolhimento": "outros",
    "comprovante_pagamento": "outros",
    "planilha_calculo": "outros",
    "parecer": "outros",
    "laudo_pericial": "outros",
    "prova_anexa": "outros",
    "ilegivel": "outros",
    "outros": "outros",
}


def derivar_categoria(tipo_doc: str | None) -> str:
    """categoria canônica (14, lida pela L2) a partir de tipo_doc (34). Fallback 'outros'."""
    if not tipo_doc:
        return "outros"
    return _TIPO_DOC_TO_CATEGORIA.get(tipo_doc, "outros")


# status_garantia_pos_mov ← evento_garantia.tipo
_EVENTO_GAR_TO_STATUS = {
    "apresentacao": "apresentado",
    "aceitacao": "aceito",
    "recusa": "recusado",
    "levantamento": "levantado",
    "substituicao": "substituido",
    "reforco": "apresentado",
    "nenhum": "nenhum",
}


def derivar_status_garantia(evento_garantia_tipo: str | None) -> str:
    """status_garantia_pos_mov (lido pela L2) a partir de evento_garantia.tipo."""
    if not evento_garantia_tipo:
        return "nenhum"
    return _EVENTO_GAR_TO_STATUS.get(evento_garantia_tipo, "nenhum")


# ── CIRURGIAS do POC (l1_prompt_v2) — as melhorias COMPROVADAS sobre o v2.3 ────
# A memória l1-teste-reprova: v2.3 PURO reprovou; estas cirurgias resolvem os erros
# críticos. Injetadas no fim de <regras_criticas> (recência). Porte fiel do POC.

# A1/A3/A4 — trava de decisão (mero expediente ≠ decisão; acionamento = risco máximo)
TRAVA_DECISAO = """
<trava_decisao>
REGRA DURA DE CONSISTENCIA (a mais importante): tem_decisao e o portao.
- Se NAO ha julgamento/decisao real nesta mov, tem_decisao=FALSE e ENTAO
  sentido=null, instancia=null, natureza=null OBRIGATORIAMENTE. NUNCA emita
  sentido/instancia/natureza junto com tem_decisao=false — sao mutuamente
  exclusivos. Preencher sentido sem decisao FABRICA risco falso.
- ATOS DE MERO EXPEDIENTE / ANDAMENTO que NAO sao decisao (tem_decisao=false,
  sentido=null): penhora/bloqueio online (sisbajud/bacenjud), vista a parte,
  processamento/admissibilidade/encaminhamento de recurso, redistribuicao,
  remessa/baixa, juntada, conclusao, confirmacao de leitura, contrarrazoes/
  contraminuta/manifestacao de parte, intimacao, certidao. Penhora NAO e derrota
  de merito; processar um recurso NAO e julga-lo.
- TERMINATIVA: extinto_sem_merito SO quando o feito e EFETIVAMENTE extinto (CPC
  485). Declinar/redistribuir competencia, remeter a outro juizo => o processo
  CONTINUA => natureza=interlocutoria, NAO extinto_sem_merito.
- ACIONAMENTO DA GARANTIA (EVENTO DE RISCO MAXIMO): ordem pra EXECUTAR a garantia /
  intimar a seguradora/garantidora a PAGAR/DEPOSITAR o valor segurado / CONVERTER o
  seguro-garantia em pagamento/penhora => isto e o pior evento pra seguradora. Mesmo
  vindo em linguagem administrativa ('intime-se a garantidora', 'expeca-se'),
  trate como tem_decisao=true, sentido=DESFAVORAVEL ao Tomador, relevante_garantia=
  true. NUNCA classifique como mero expediente.
</trava_decisao>"""

# A6 — regra de titularidade (verbo de resultado sem dono → neutro)
REGRA_TITULARIDADE = """
<regra_titularidade>
ANTES de definir o sentido, identifique A QUEM pertence a pretensao/pedido/recurso
decidido. Verbos de resultado ('deferido', 'concedido', 'provido', 'procedente',
'acolhido', 'rejeitado', 'negado') NAO determinam o sentido SOZINHOS — o sentido
depende de QUAL PARTE foi beneficiada/prejudicada:
- 'deferido o pedido' / 'procedente' SEM dizer de quem e o pedido => sentido=neutro
  (nao da pra atribuir; NUNCA assuma que favorece o Tomador). EXCECAO em EXECUCAO
  FISCAL: ali quem peticiona costuma ser a FAZENDA (exequente); um 'pedido deferido'
  generico tende a atender a Fazenda => NAO marque favoravel ao Tomador (use neutro,
  ou desfavoravel se o pedido deferido constringe o executado).
- provimento de recurso da PARTE CONTRARIA (Fazenda/exequente/reclamante) =>
  DESFAVORAVEL ao Tomador.
- 'embargos rejeitados': se os embargos eram do Tomador (embargante) => desfavoravel;
  se eram da parte contraria => favoravel. O mesmo verbo da sentidos OPOSTOS.
Na duvida sobre a titularidade: sentido=neutro + confianca<=0.5. Default seguro = neutro.
</regra_titularidade>"""

# A5 — módulo trabalhista (TST≠stj; Tomador pode ser reclamante) — injeção condicional
MODULO_TRABALHISTA = """
<regra_trabalhista>
Em materia TRABALHISTA: NAO presuma que o Tomador e a reclamada. CONFIRME pela
posicao do Tomador nos polos (pelo nome dele em polo_ativo/polo_passivo):
- Tomador = RECLAMADA (polo passivo, caso comum): reclamacao PROCEDENTE => condena a
  reclamada => DESFAVORAVEL ao Tomador. Improcedente => favoravel.
- Tomador = RECLAMANTE (polo ATIVO): reclamacao PROCEDENTE => o Tomador (autor) GANHOU
  => FAVORAVEL. Improcedente => desfavoravel.
RECURSOS/EMBARGOS DE DECLARACAO EM TRABALHISTA (erro comum): antes do sentido,
identifique DE QUEM e o recurso/embargos (reclamante=empregado, ou reclamada=empresa/
Tomador) e se foi PROVIDO/NEGADO. Embargos/recurso DO EMPREGADO (reclamante) NEGADOS/
IMPROVIDOS => a parte contraria do Tomador perdeu => FAVORAVEL ao Tomador (NAO
desfavoravel). Recurso do EMPREGADO provido => desfavoravel. Recurso da RECLAMADA
(Tomador) provido => favoravel; negado => desfavoravel. O mesmo verbo da sentidos
OPOSTOS conforme de QUEM e a peca — nunca mapeie sem saber o autor do recurso. Na
duvida sobre o autor: sentido=neutro. Recurso ao TST => instancia '2g'/superior,
NUNCA 'stj'. Agravo de Peticao e recurso na fase de execucao trabalhista.
</regra_trabalhista>"""


def eh_trabalhista(processo: Any) -> bool:
    """Decide se injeta o módulo trabalhista (viés a injetar: na dúvida, injeta)."""
    blob = _norm(f"{_get(processo, 'materia')} {_get(processo, 'classe')}")
    return "trabalh" in blob or "reclamac" in blob


__all__ = [
    "bloco_fundacao",
    "familia_block",
    "polo_do_tomador",
    "TAXONOMIA_TIPO_DOC",
    "RELEVANTE_GARANTIA",
    "derivar_categoria",
    "derivar_status_garantia",
    "TRAVA_DECISAO",
    "REGRA_TITULARIDADE",
    "MODULO_TRABALHISTA",
    "eh_trabalhista",
]
