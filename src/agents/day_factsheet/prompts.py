"""Prompt pro day_factsheet agent (engine v6_meritos camada 1, tier Degradado-Dia).

Diferente do mov_factsheet (que processa 1 mov por vez com DD4 doc-texto FK):
aqui o LLM recebe TODAS as movs + TODOS os docs de UM DIA e correlaciona
cognitivamente. Tier Degradado-Dia eh regra de jogo quando fonte de autos
nao entrega vinculo doc-mov nativo (Judit, jusbrasil sem id).

Spec: memory engine-v6-pipeline-quality-tiers.
"""
from .schemas import DayDocInput, DayMovInput, ProcessoContextMin

# Caps de cada bloco no prompt (Flash 1M context aguenta mas economiza tokens)
_DOC_TEXT_CAP_CHARS = 6000
_DOC_LIST_CAP = 8
_MOV_LIST_CAP = 20
_MOV_TEXT_CAP_CHARS = 800


def _format_mov(mov: DayMovInput, idx: int, total: int) -> str:
    texto = (mov.texto or "").strip()
    if len(texto) > _MOV_TEXT_CAP_CHARS:
        texto = texto[:_MOV_TEXT_CAP_CHARS] + "..."
    head = f"--- MOV {idx + 1}/{total} (id={mov.mov_id}"
    if mov.tipo:
        head += f", tipo={mov.tipo}"
    head += ") ---"
    return f"{head}\n  {texto}"


def _format_doc(doc: DayDocInput, idx: int, total: int) -> str:
    text = (doc.text_content or "").strip()
    truncated = ""
    if len(text) > _DOC_TEXT_CAP_CHARS:
        text = text[:_DOC_TEXT_CAP_CHARS]
        truncated = f"\n  [TRUNCADO a {_DOC_TEXT_CAP_CHARS} chars]"
    head = f"--- DOC {idx + 1}/{total} (doc_key={doc.doc_key}"
    if doc.tipo:
        head += f", tipo={doc.tipo}"
    if doc.titulo:
        head += f", titulo={doc.titulo[:80]}"
    head += ") ---"
    body = "  " + text.replace("\n", "\n  ")
    return f"{head}\n{body}{truncated}"


def build_day_factsheet_prompt(
    processo: ProcessoContextMin,
    date: str,
    movs_no_dia: list[DayMovInput],
    docs_no_dia: list[DayDocInput],
) -> str:
    """Prompt pra sintetizar 1 dia inteiro de UM processo.

    Recebe N movs + M docs do mesmo dia. LLM correlaciona cognitivamente
    (sem FK explícita) e devolve resumo_dia + eventos atomicos + decisao
    + evento_garantia.
    """
    proc_lines = [f"CNJ: {processo.cnj}"]
    if processo.classe:
        proc_lines.append(f"Classe: {processo.classe}")
    if processo.polo_ativo:
        proc_lines.append(f"Polo ativo (exequente): {processo.polo_ativo}")
    if processo.polo_passivo:
        proc_lines.append(f"Polo passivo (executado/tomador): {processo.polo_passivo}")
    proc_block = "\n  ".join(proc_lines)

    movs_capped = movs_no_dia[:_MOV_LIST_CAP]
    if movs_capped:
        movs_block = "\n\n".join(
            _format_mov(m, i, len(movs_capped)) for i, m in enumerate(movs_capped)
        )
        if len(movs_no_dia) > _MOV_LIST_CAP:
            movs_block += f"\n\n[+ {len(movs_no_dia) - _MOV_LIST_CAP} movs omitidas]"
    else:
        movs_block = "(nenhuma mov registrada neste dia)"

    docs_capped = docs_no_dia[:_DOC_LIST_CAP]
    if docs_capped:
        docs_block = "\n\n".join(
            _format_doc(d, i, len(docs_capped)) for i, d in enumerate(docs_capped)
        )
        if len(docs_no_dia) > _DOC_LIST_CAP:
            docs_block += f"\n\n[+ {len(docs_no_dia) - _DOC_LIST_CAP} docs omitidos]"
    else:
        docs_block = "(nenhum doc juntado neste dia com texto disponivel)"

    return f"""Voce e analista juridico-securitario brasileiro especializado em SEGURO GARANTIA JUDICIAL.

Sua tarefa: sintetizar TUDO QUE ACONTECEU EM UM DIA de um processo judicial
correlacionando as movimentacoes do dia com os documentos juntados no mesmo dia.

Contexto: esta sintese-do-dia substitui a sintese mov-by-mov quando a fonte
dos autos nao entrega vinculo doc->mov nativo (caso tipico: Judit, jusbrasil
sem id de anexo). Sua granularidade eh o DIA, nao a mov.

=== PROCESSO ===
  {proc_block}

=== DATA (anchor deste card) ===
  {date}

=== MOVIMENTACOES DO DIA ({len(movs_no_dia)} total) ===
{movs_block}

=== DOCUMENTOS JUNTADOS NO DIA ({len(docs_no_dia)} total, com texto disponivel) ===
{docs_block}

=== INSTRUCOES POR CAMPO ===

1. resumo_dia (1-3 frases PT-BR): O que aconteceu no dia, em prosa tecnica.
   - Se ha decisao: cite-a primeiro
   - Se ha apenas atos burocraticos: resumo curto
   - NAO copie literalmente; sintetize

2. eventos (lista de EventoDoDia): identifique ATOS ATOMICOS do dia.
   Pra cada evento, traga:
   - tipo: decisao | peticao | anexo | despacho | intimacao | publicacao | certidao | outros
   - descricao: 1 frase
   - referencias: mov_ids OU doc_keys que sustentam o evento. SO inclua
     referencias que voce TEM CERTEZA da correlacao (data + conteudo bate).
     Se nao da pra correlacionar, deixe lista vazia.

3. decisao_do_dia: SO preencha se ha decisao judicial neste dia.
   - tem_decisao: true | false
   - sentido (DO PONTO DE VISTA DO TOMADOR = executado/embargante/impetrante):
     favoravel | desfavoravel | parcial | neutro
   - instancia: 1g | 2g | stj | stf
   - natureza: procedente | improcedente | parcialmente_procedente |
     extinto_sem_merito | homologatoria | interlocutoria
   - transito_certificado: true SO se ha CERTIFICAO de transito em julgado

4. evento_garantia_do_dia: SO preencha se ha evento envolvendo apolice/garantia.
   - tipo: apresentacao | aceitacao | recusa | levantamento | substituicao | reforço | nenhum
   - motivo: quando recusa, explicite

5. relevancia_para_merito:
   - alta: decisao de merito, sentenca, acordao, transito, evento de garantia
   - media: despachos saneadores, peticoes recursais
   - baixa: despachos ordinatorios, publicacoes
   - ruido: cargas, baixas, intimacoes burocraticas

6. docs_considerados: lista flat de doc_keys que voce USOU pra sintese
   (nao precisa mapear per-evento). Audit-trail simples.

7. confianca (0-1): reflita a qualidade da correlacao:
   - 0.7-0.9 quando movs + docs claramente se referem ao mesmo ato
   - 0.4-0.6 quando ha incerteza na correlacao (5+ movs e 5+ docs sem hint claro)
   - 0.2-0.4 quando so deu pra resumir 'aconteceu X' sem decidir o que

=== REGRAS GERAIS ===

- NAO INVENTE. Se nao da pra dizer, deixe campo vazio/null.
- Tier Degradado-Dia eh por definicao menos confiavel que mov-by-mov; isso
  eh esperado, nao um bug.
- O objetivo da camada 2 (processo_synthesis) ao consumir este card eh ter
  "o que aconteceu" no dia, nao mapeamento exato mov<->doc.

Devolva APENAS o JSON do DayFactsheetCard, sem prefixo/wrapping markdown.
"""
