"""Prompt pro monolith_factsheet agent (engine v6_meritos camada 1, tier monolitico).

Recebe texto do PDF monolitico inteiro (cap'd) e sintetiza em 1 card por proc.
Substitui o uso direto de autos_raw_excerpt no L2 — L2 agora consome SO cards
estruturados, mantendo a arquitetura RAG.

Spec: memory engine-v6-pipeline-quality-tiers.
"""
from .schemas import MonolithFactsheetRequest, ProcessoContextMin

_AUTOS_TEXT_CAP_CHARS = 60_000


def build_monolith_factsheet_prompt(req: MonolithFactsheetRequest) -> str:
    """Single LLM call que sintetiza PDF monolitico inteiro em 1 card estruturado.

    Tier monolitico: temos so o PDF blob (lawsuit_pdfs.pre_extracted_text),
    sem per-doc nem FK. Cap 60k chars (primeiras 10 pgs + ultimas 50 do PDF
    inteiro, ja preparado pelo caller).
    """
    proc = req.processo if isinstance(req.processo, ProcessoContextMin) else ProcessoContextMin(**req.processo)

    proc_lines = [f"CNJ: {proc.cnj}"]
    if proc.classe:
        proc_lines.append(f"Classe: {proc.classe}")
    if proc.polo_ativo:
        proc_lines.append(f"Polo ativo (exequente): {proc.polo_ativo}")
    if proc.polo_passivo:
        proc_lines.append(f"Polo passivo (executado/tomador): {proc.polo_passivo}")
    proc_block = "\n  ".join(proc_lines)

    text = (req.autos_text or "").strip()
    if len(text) > _AUTOS_TEXT_CAP_CHARS:
        text = text[:_AUTOS_TEXT_CAP_CHARS] + f"\n\n[TRUNCADO a {_AUTOS_TEXT_CAP_CHARS} chars]"

    pages_note = ""
    if req.pages_used and req.total_pages:
        pages_note = f" ({req.pages_used} de {req.total_pages} pgs)"
    elif req.truncated:
        pages_note = " (truncado)"

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: sintetizar o estado de UM PROCESSO a partir do TEXTO DO PDF
MONOLITICO inteiro dos autos. Este eh o tier 'monolitico' do pipeline v6 — nao
ha vinculo doc<->mov estruturado, so o blob.

Sua sintese vai pra Camada 2 (processo_synthesis) como 1 card de input ESTRUTURADO.
A camada 2 NUNCA recebe o texto raw — voce eh a unica ponte. Faca um trabalho
LIMPO e FACTUAL: o LLM da camada 2 vai confiar no seu output como verdade.

=== PROCESSO ===
  {proc_block}

=== TEXTO DO PDF MONOLITICO{pages_note} ===
{text}

=== INSTRUCOES POR CAMPO ===

1. resumo_executivo (2-4 frases PT-BR): O estado ATUAL do processo:
   - Em que instancia esta + fase (instrucao/sentenca/recurso/execucao/transito)
   - Decisao mais recente que governa o processo (sentido + natureza)
   - Status da garantia (apresentada? aceita? recusada?)
   - Use linguagem tecnico-juridica direta. NAO copie do PDF — sintetize.

2. decisao_vigente: a decisao MAIS RECENTE que governa o processo HOJE.
   - tem_decisao: true se ha qualquer decisao identificada no PDF
   - sentido (DO PONTO DE VISTA DO TOMADOR = executado/embargante/impetrante):
     - favoravel: julga procedente embargos, improcedente execucao, concede liminar
     - desfavoravel: rejeita defesa, mantem execucao, julga improcedente embargos
     - parcial: parte favoravel, parte nao
     - neutro: meramente processual sem ganhador
   - instancia: 1g (juizo) | 2g (TJ/TRF) | stj | stf
   - natureza: procedente | improcedente | parcialmente_procedente |
     extinto_sem_merito | homologatoria | interlocutoria
   - data: YYYY-MM-DD se identificavel no texto
   - transito_certificado: true SO se ha CERTIDAO de transito em julgado
     no PDF (texto explicito "certifico o transito" ou similar)
   - recorrida: true se ha recurso interposto contra essa decisao

3. eventos_principais (lista de EventoTimelineMonolitica, 5-10 items):
   Top eventos identificados, cronologico ASC.
   - tipo: decisao | peticao | anexo | despacho | intimacao | publicacao | certidao | outros
   - descricao: 1 frase curta
   - data: YYYY-MM-DD quando identificavel
   PRIORIZE: decisoes de merito > eventos de garantia > peticoes recursais.
   IGNORE: atos ordinatorios, certidoes burocraticas, intimacoes de prazo.

4. lifecycle_garantia (lista): eventos da garantia/apolice no processo.
   - evento: apresentacao | aceitacao | recusa | levantamento | substituicao | reforço
   - tipo_garantia: seguro_garantia | fianca_bancaria | carta_fianca |
     deposito_judicial | penhora | fiduciaria
   - data: YYYY-MM-DD
   - motivo_recusa: se evento=recusa, motivo identificado

5. valor_em_disputa (BRL, ex: 747064569.24):
   Melhor evidencia de valor em disputa do texto. Pode ser:
   - valor_causa explicito (raro no monolito)
   - debito executado em CDA citada
   - condenacao em sentenca
   NULL se nao identificavel.

6. valor_garantia (BRL): valor da apolice/deposito/penhora.
   NULL se nao identificavel.

7. peca_pivo: a movimentacao/peca mais DECISIVA identificada no PDF.
   - {{"data": "YYYY-MM-DD", "descricao": "1 frase explicando porque eh pivo"}}
   - NULL se nada se destaca como pivo claro.

8. proximos_passos_provaveis: 2-3 acoes esperadas (ex: "aguardar manifestacao
   da exequente", "execucao da garantia", "recurso de apelacao").

9. confianca (0.4-0.7): refletir limitacao do tier monolitico.
   - 0.6-0.7: PDF claro, decisoes evidentes, valores presentes
   - 0.4-0.5: PDF ambiguo OU truncado OU texto fragmentado

=== REGRAS GERAIS ===

- NAO INVENTE. Se nao da pra dizer, deixe campo vazio/null.
- O texto pode estar TRUNCADO (primeiras pgs + ultimas pgs). Se evidencia
  importante parece estar no "meio" omitido, registre incerteza na confianca.
- Tier monolitico eh por definicao menos confiavel que mov-by-mov; isso
  eh esperado, nao um bug — sua confianca deve refletir isso.
- A camada 2 que consome este card NAO terah acesso ao raw — voce eh
  responsavel por extrair TUDO que importa.

Devolva APENAS o JSON do MonolithFactsheetCard, sem prefixo/wrapping markdown.
"""
