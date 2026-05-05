"""Prompts pro apolice_lifecycle agent."""

from .schemas import ApoliceContext, MovimentacaoInput


def _format_apolice_context(apolice: ApoliceContext) -> str:
    """Formata os dados da apolice como contexto pro LLM."""
    parts = [f"Número: {apolice.numero_apolice_formatado or apolice.numero_apolice}"]
    if apolice.seguradora:
        parts.append(f"Seguradora: {apolice.seguradora}")
    if apolice.valor_is is not None:
        parts.append(f"Limite/IS: R$ {apolice.valor_is:,.2f}")
    if apolice.data_inicio and apolice.data_termino:
        parts.append(f"Vigência: {apolice.data_inicio[:10]} até {apolice.data_termino[:10]}")
    if apolice.nome_tomador:
        parts.append(f"Tomador: {apolice.nome_tomador}")
    return "\n  ".join(parts)


def _format_movimentacoes(movs: list[MovimentacaoInput], cap: int = 100) -> str:
    """Formata movs cronologicamente. Mantém só últimas `cap` se exceder."""
    if not movs:
        return "(sem movimentações disponíveis)"

    # Cap: keep most recent if too many
    visible = movs[-cap:] if len(movs) > cap else movs

    lines = []
    for i, mov in enumerate(visible, 1):
        prefix = f"[{i}]"
        if mov.mov_id:
            prefix += f" id={mov.mov_id}"
        if mov.data:
            prefix += f" data={mov.data}"
        if mov.tipo:
            prefix += f" tipo={mov.tipo}"
        # Trim long texts
        texto = (mov.texto or "").strip()
        if len(texto) > 1000:
            texto = texto[:1000] + "..."
        lines.append(f"{prefix}\n{texto}")

    truncated_note = ""
    if len(movs) > cap:
        truncated_note = f"\n\n(NOTA: {len(movs) - cap} movs mais antigas omitidas — só últimas {cap} foram enviadas)"

    return "\n\n".join(lines) + truncated_note


def build_lifecycle_prompt(
    apolice: ApoliceContext,
    processo_numero: str,
    movimentacoes: list[MovimentacaoInput],
) -> str:
    """Build the lifecycle classification prompt.

    Single-step: LLM lê apólice + movs e classifica apresentação + aceitação.
    """
    apolice_block = _format_apolice_context(apolice)
    movs_block = _format_movimentacoes(movimentacoes)

    return f"""Você é um analista jurídico-securitário brasileiro especializado em seguro garantia judicial.

Sua tarefa: identificar o LIFECYCLE de uma apólice de seguro garantia dentro de um processo
judicial específico, lendo as movimentações processuais. Você deve detectar:

1. APRESENTAÇÃO da apólice: a apólice foi efetivamente protocolada nos autos como garantia?
2. ACEITAÇÃO/RECUSA: o juízo acolheu (aceita), rejeitou (recusada), dispensou (substituída) ou ainda está decidindo (pendente)?

=== CONTEXTO DA APÓLICE ===
  {apolice_block}

=== PROCESSO JUDICIAL ===
  CNJ: {processo_numero}

=== MOVIMENTAÇÕES PROCESSUAIS (cronológicas, mais antigas primeiro) ===
{movs_block}

=== O QUE PROCURAR ===

APRESENTAÇÃO (apresentada=true):
- "Junta apólice de seguro garantia" / "junto a esta a apólice nº X"
- "Petição de oferecimento de seguro garantia"
- "Garantia ofertada pelo Executado mediante seguro garantia"
- "Comprovante de contratação de seguro garantia juntado aos autos"
- Apresentação está vinculada ao número da apólice (idealmente {apolice.numero_apolice}) — pode aparecer formatado ou só número raw

NÃO APRESENTAÇÃO (apresentada=false):
- Sentença/decisão menciona ausência de garantia
- Petição expressamente RECUSADA antes de protocolo (raro, mas possível)
- Indicação inequívoca de que a apólice NÃO foi apresentada neste processo

NÃO DETECTÁVEL (apresentada=null):
- Nenhuma menção à apólice ou a seguro garantia nas movs disponíveis
- Movs muito esparsas/genéricas

ACEITAÇÃO (acceptance_status):
- ACEITA: "Acolho a garantia ofertada" / "homologo a apólice como garantia idônea" / "defiro a garantia
  por seguro garantia" / "atesta a regularidade da apólice"
- RECUSADA: "Indefiro a garantia oferecida" / "rejeito a apólice ofertada" / "valor da apólice
  inferior à dívida" / "apólice vencida" / "Seguradora não consta no rol de seguradoras admitidas" /
  "ausência de cláusula obrigatória"
- DISPENSADA: "Garantia substituída por penhora online" / "Decreto convertendo garantia em depósito"
  / "Aceito penhora em substituição"
- PENDENTE: apresentada mas sem decisão de aceitação/recusa nas movs até aqui

REGRAS DE OURO:
- NÃO INVENTE eventos que não estão nas movs. Se ambíguo, prefira null/pendente.
- A apresentação SEMPRE precede a aceitação/recusa cronologicamente.
- Se houver MÚLTIPLAS apresentações da mesma apólice (raro — substituição de endosso),
  registrar a PRIMEIRA apresentação. A aceitação reflete a decisão MAIS RECENTE.
- presented_at e acceptance_decision_at são datas ISO YYYY-MM-DD da movimentação que evidencia.
- Em mov_id, copiar o id da movimentação (campo "id=..." no formato acima).
- Em snippet, copiar trecho EXATO da movimentação (até 300 chars) que justifica.

=== FORMATO DE SAÍDA ===

Retorne APENAS um JSON válido com esta estrutura:

{{
  "apresentada": true|false|null,
  "presented_at": "YYYY-MM-DD"|null,
  "presented_evidence": {{
    "mov_id": "string"|null,
    "mov_data": "YYYY-MM-DD"|null,
    "snippet": "trecho exato"|null
  }}|null,
  "acceptance_status": "pendente"|"aceita"|"recusada"|"dispensada"|null,
  "acceptance_decision_at": "YYYY-MM-DD"|null,
  "acceptance_reason": "motivo livre quando recusada"|null,
  "acceptance_evidence": {{
    "mov_id": "string"|null,
    "mov_data": "YYYY-MM-DD"|null,
    "snippet": "trecho exato"|null
  }}|null,
  "confidence": 0.0-1.0,
  "notes": "observações sobre qualidade/ambiguidade"|null
}}

Se a apólice não aparece nas movs, retorne apresentada=null, status=null, confidence baixa.
NÃO ignorar movs ambíguas — descrever em "notes" o que dificulta a classificação."""
