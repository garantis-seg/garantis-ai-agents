"""Prompt pro mov_summarizer agent."""

from .schemas import MovInput, ProcessoContext


def build_mov_prompt(processo: ProcessoContext, mov: MovInput) -> str:
    """Single-step prompt pra classificar + resumir uma movimentação."""
    proc_block_lines = [f"CNJ: {processo.cnj}"]
    if processo.classe:
        proc_block_lines.append(f"Classe: {processo.classe}")
    if processo.polo_ativo:
        proc_block_lines.append(f"Polo ativo: {processo.polo_ativo}")
    if processo.polo_passivo:
        proc_block_lines.append(f"Polo passivo: {processo.polo_passivo}")
    proc_block = "\n  ".join(proc_block_lines)

    mov_block_lines = [f"id: {mov.mov_id}"]
    if mov.data:
        mov_block_lines.append(f"data: {mov.data}")
    if mov.tipo:
        mov_block_lines.append(f"tipo_origem: {mov.tipo}")
    mov_meta = "\n  ".join(mov_block_lines)

    texto = (mov.texto or "").strip()
    if len(texto) > 3000:
        texto = texto[:3000] + "..."

    return f"""Você é um analista jurídico-securitário brasileiro. Classifique e resuma UMA movimentação processual.

=== PROCESSO ===
  {proc_block}

=== MOVIMENTAÇÃO ===
  {mov_meta}

  texto:
  {texto}

=== CLASSIFICAÇÃO TIPO_CANONICO ===

Mapeie pra UM dos seguintes (use 'outros' apenas se nada se encaixar):
- sentenca: decisão final de mérito de 1ª instância (procedente/improcedente/extinto)
- acordao: decisão de tribunal (TJ, TRF, STJ, STF) — apelação, agravo, embargos, RE/REsp julgados
- despacho: ato sem conteúdo decisório (ex: "Vista ao MP", "Conclusos", "Aguarde-se")
- decisao_interlocutoria: decisões durante o processo que não são sentença (ex: "concedo liminar", "indefiro tutela")
- peticao: petição da parte (inicial, incidental, recursal)
- certidao: certidão do cartório (publicação, baixa, juntada)
- intimacao: ato comunicando parte
- publicacao: publicação no DJe sem juízo de valor
- ato_ordinatorio: ato meramente burocrático
- carga: registro de retirada/devolução de autos
- baixa: baixa do processo
- conclusao: conclusão pra juiz
- outros: outros casos

=== FLAGS — booleanos a detectar ===

- menciona_apolice: texto cita "apólice", "seguro garantia", número de apólice, "garantia ofertada"
- menciona_cda: cita "CDA", "Certidão de Dívida Ativa", número de CDA
- menciona_aiim: cita "AIIM", "auto de infração"
- menciona_acordo: "acordo", "homologo o acordo", "transação", "parcelamento"
- menciona_recurso: "apelação", "agravo", "embargos", "recurso"
- menciona_transito: "trânsito em julgado", "transitou", "certifico o trânsito"
- menciona_suspensao: "suspendo", "suspenso", "sobrestado"
- menciona_recuperacao_judicial: "RJ", "recuperação judicial", "Lei 11.101"
- menciona_processo_conexo: lista de CNJs (formato 7-2.4.1.2.4 ou 20 dígitos) mencionados — extrair literais

=== DECISAO_DE_MERITO ===

Preencher APENAS quando tipo_canonico ∈ {{sentenca, acordao}} E houver decisão de mérito clara.
- natureza: procedente | improcedente | parcialmente_procedente | extinto_sem_merito | homologatoria
- instancia: 1g (1ª inst), 2g (TJ/TRF), stj, stf
- favoravel_tomador: True se favorece o EXECUTADO/EMBARGANTE/IMPETRANTE (parte que contratou apólice). False se favorece a Fazenda. null se ambíguo.
- transito_certificado: true só se a mov certifica trânsito em julgado

Para outros tipo_canonico, deixar decisao_de_merito = null.

=== TEXTO_RESUMO ===

1-3 frases em PT-BR descrevendo:
1. O que aconteceu (decisão / ato / publicação)
2. Doc anexo se mencionado (sentença, certidão, apólice)
3. Próximo passo se claro (recurso, conclusão, baixa)

NÃO copie literalmente — sintetize. Use técnico-jurídico mas direto.

=== FORMATO DE SAÍDA ===

Retorne APENAS JSON com esta estrutura:

{{
  "mov_id": "{mov.mov_id}",
  "data": "{mov.data or 'null'}",
  "tipo_origem": "{mov.tipo or 'null'}",
  "tipo_canonico": "...",
  "subtipo": null,
  "texto_resumo": "...",
  "flags": {{
    "menciona_apolice": false,
    "menciona_cda": false,
    "menciona_aiim": false,
    "menciona_acordo": false,
    "menciona_recurso": false,
    "menciona_transito": false,
    "menciona_suspensao": false,
    "menciona_recuperacao_judicial": false,
    "menciona_processo_conexo": []
  }},
  "decisao_de_merito": null
}}

NÃO INVENTE flags — só marcar true quando o texto justifica."""
