"""Prompts pro endorsement_classifier agent."""

from typing import Any, Optional


PROMPT_VERSION = "endorsement_classifier.v1.0"


def _fmt_payload(payload: Optional[dict[str, Any]]) -> str:
    """Render payload compacto pra prompt."""
    if not payload:
        return "(none)"
    lines = []
    for k in (
        "current_sum_insured",
        "termination_date",
        "accumulated_premium",
        "policyholder_cnpj",
        "policyholder_name",
    ):
        v = payload.get(k)
        if v is not None and v != "":
            lines.append(f"  {k}: {v}")
    return "\n".join(lines) if lines else "(empty)"


def build_endorsement_classifier_prompt(
    objeto_segurado: Optional[str],
    prior_payload: Optional[dict[str, Any]],
    new_payload: dict[str, Any],
    diff_fields: list[str],
    apolice_numero: Optional[str] = None,
) -> str:
    """Build the endorsement classification prompt.

    Single-step: LLM lê objeto segurado + prior/new payload + diff e
    classifica em {cancellation, extension, sum_insured_change, other}.
    """
    objeto = (objeto_segurado or "").strip()
    if len(objeto) > 2000:
        objeto = objeto[:2000] + "..."
    if not objeto:
        objeto = "(sem texto disponível em objetoSegurado)"

    diff_str = ", ".join(sorted(diff_fields)) if diff_fields else "(nenhum)"
    apolice_line = f"Apólice: {apolice_numero}\n" if apolice_numero else ""

    return f"""Você é um analista securitário brasileiro especializado em endossos de seguro garantia judicial.

Tarefa: classificar o TIPO de um endosso emitido sobre uma apólice de seguro garantia,
combinando o texto livre do "objeto segurado" com o diff entre o estado anterior e
o novo estado da apólice.

{apolice_line}=== TEXTO LIVRE (observed_data.objetoSegurado) ===
{objeto}

=== PAYLOAD ANTERIOR (último endorsement antes deste evento) ===
{_fmt_payload(prior_payload)}

=== NOVO PAYLOAD (observation atual) ===
{_fmt_payload(new_payload)}

=== CAMPOS QUE MUDARAM ===
{diff_str}

=== TIPOS POSSÍVEIS ===

cancellation:
  - Texto contém: "FICA CANCELADA", "APÓLICE CANCELADA", "CANCELAMENTO",
    "CESSAÇÃO DO RISCO", "EXTINÇÃO DO RISCO".
  - Costuma vir com termination_date = data do cancelamento (antecipa o término original).
  - É o tipo mais forte — keyword explícita SEMPRE vence sobre outras pistas.

extension:
  - Texto contém: "PRORROGAÇÃO", "EXTENSÃO DE PRAZO", "NOVO PRAZO",
    "AMPLIAÇÃO DE VIGÊNCIA".
  - termination_date mudou pra UMA DATA FUTURA mais distante que a anterior.
  - Pode ser inferido só por diff (termination_date estendido) mesmo sem keyword,
    com confidence MÉDIA (~0.6).

sum_insured_change:
  - Texto contém: "ALTERAÇÃO DE VALOR/IS/IMPORTÂNCIA/GARANTIA", "REDUÇÃO DE VALOR",
    "AUMENTO DE VALOR", "MAJORAÇÃO".
  - current_sum_insured mudou. Pode ser pra cima ou pra baixo.

other:
  - Nenhuma das categorias acima se aplica claramente.
  - Exemplos: alteração de tomador, alteração de beneficiário, alteração de
    cláusulas, prêmio recalculado sem mudar IS/prazo.

=== REGRAS DE OURO ===

1. PRIORIDADE: keyword explícita > tipo de campo que mudou > fallback "other".
2. Se há cancellation keyword, classifica como cancellation INDEPENDENTE
   de qualquer outro diff (ex: cancellation que também ajusta IS final).
3. Se há sum_insured_change keyword + current_sum_insured no diff →
   sum_insured_change (confidence alta).
4. Se há extension keyword + termination_date no diff → extension (confidence alta).
5. Se SÓ termination_date mudou (sem keyword), prefira extension com
   confidence ~0.6 (inferido).
6. Se SÓ current_sum_insured mudou (sem keyword), prefira sum_insured_change
   com confidence ~0.6.
7. Quando ambíguo (multi-campo diff sem keyword), pondere pela mudança mais
   relevante. Se nada se encaixa → other.

=== FORMATO DE SAÍDA ===

Retorne APENAS um JSON válido:

{{
  "endorsement_type": "cancellation"|"extension"|"sum_insured_change"|"other",
  "confidence": 0.0-1.0,
  "reasoning": "trecho citando keyword + campos do diff que justificam (até 300 chars)"
}}
"""
