"""Prompts pro court_state_classifier agent."""

from typing import Optional


PROMPT_VERSION = "court_state_classifier.v1.0"


# Estados terminais — não podem transicionar
TERMINAL_STATES = {"accepted", "rejected", "closed", "replaced"}


def build_court_state_classifier_prompt(
    movement_text: str,
    current_state: str,
    presentation_kind: str = "judicial",
    data_movimento: Optional[str] = None,
    processo_numero: Optional[str] = None,
) -> str:
    """Build the court state classification prompt.

    Single-step: LLM lê movement_text + current_state + presentation_kind e
    classifica new_state em {offered, presumed_accepted, accepted, rejected,
    replaced, closed} + closed_reason (4-enum) quando closed.
    """
    texto = (movement_text or "").strip()
    if len(texto) > 4000:
        texto = texto[:4000] + "..."
    if not texto:
        texto = "(sem texto disponível)"

    contexto_lines = []
    if processo_numero:
        contexto_lines.append(f"Processo: {processo_numero}")
    if data_movimento:
        contexto_lines.append(f"Data do movimento: {data_movimento}")
    contexto_lines.append(f"Tipo de apresentação: {presentation_kind}")
    contexto_lines.append(f"Estado atual: {current_state}")
    contexto = "\n".join(contexto_lines)

    return f"""Você é um analista judicial brasileiro especializado em transições de estado de apresentação de garantia (seguro garantia / fiança bancária / depósito judicial) em execução fiscal e correlatos.

Tarefa: dado o texto de um movimento processual + o estado atual da apresentação da garantia, classificar o NOVO estado (transição) usando o enum abaixo. Se o texto não justifica transição, retorne o current_state (no-op).

=== CONTEXTO ===
{contexto}

=== TEXTO DO MOVIMENTO ===
{texto}

=== ESTADOS POSSÍVEIS (enum new_state) ===

offered:
  - Apólice oferecida ao juízo (estado inicial pós-protocolo).
  - Raramente é o destino de uma transição — quase sempre estado de partida.

presumed_accepted:
  - Aceite presumido pelo decurso de prazo sem manifestação contrária.
  - Costuma vir de movimento que decorreu prazo sem decisão expressa.

accepted:
  - Juiz ACOLHEU / DEFERIU / HOMOLOGOU a garantia.
  - Keywords explícitas: acolho, acolheu, defiro, deferiu, homologo, homologou,
    homologada, homologado.
  - Qualificador OBRIGATÓRIO: deve mencionar 'apólice', 'seguro garantia' ou
    'garantia judicial' / 'garantia de seguro' — NÃO conta com 'garantia
    constitucional' ou 'garantia processual'.

rejected:
  - Juiz INDEFERIU / RECUSOU / REJEITOU a garantia.
  - Keywords: indefiro, indeferiu, recuso, recusou, rejeito, rejeitou.
  - Mesmo qualificador da accepted.

replaced:
  - Garantia substituída por outra (apólice nova, dinheiro, fiança).
  - Keywords: substitui + garantia/apólice/seguro garantia.
  - Worker MVP loga mas não auto-aplica (precisa successor lookup) —
    classifier pode retornar replaced; worker decide o que fazer.

closed:
  - Apresentação encerrada. closed_reason é OBRIGATÓRIO.
  - closed_reason='extinto_processo': processo principal extinto sem
    julgamento de mérito. Keywords: 'julgo extinto', 'declaro extinto',
    'decreto extinto', 'extinto sem julgamento', 'extinção do processo'.
    REGRA: exige verbo positivo — 'processo não foi extinto' NÃO conta.
  - closed_reason='sinistro_pago': pagamento da indenização securitária.
    Keywords: 'sinistro pago', 'pagamento do sinistro', 'indenização do
    sinistro / do seguro / securitária'. 'Indenização por danos morais'
    NÃO é sinistro.
  - closed_reason='liberada': baixa/liberação da garantia sem sinistro.
    Keywords: 'libero', 'liberada', 'libera a garantia', 'baixa da
    garantia', 'liberação da garantia/apólice'.
  - closed_reason='outra': qualquer outro encerramento não enquadrado.

=== REGRA DE ELEGIBILIDADE ===

Só apresentações com current_state='offered' OU 'presumed_accepted' podem
transicionar. Os outros 4 estados ('accepted', 'rejected', 'replaced',
'closed') são TERMINAIS — preserve audit trail.

⚠️ Se current_state já é terminal ({sorted(TERMINAL_STATES)}):
   - Retorne new_state = current_state.
   - confidence = 1.0.
   - reasoning = 'estado terminal — sem transição'.
   - closed_reason = NULL (mesmo se current_state='closed').

=== KEYWORD CUES (positivos por estado) ===

ACCEPT:
  'acolho a apólice', 'defiro a garantia judicial', 'homologo o seguro
  garantia', 'homologada a apólice oferecida'.

REJECT:
  'indefiro a apólice apresentada', 'recuso a garantia de seguro',
  'rejeito o seguro garantia'.

CLOSED (extinto):
  'julgo extinto o processo', 'declaro extinto sem julgamento',
  'extinção do processo nos termos do art. ...'.

CLOSED (sinistro_pago):
  'sinistro pago em ...', 'pagamento do sinistro', 'indenização
  securitária paga'.

CLOSED (liberada):
  'libero a garantia', 'baixa da garantia ofertada', 'liberação da
  apólice', 'libera a garantia em favor do tomador'.

REPLACED:
  'substitui a garantia judicial por depósito', 'apólice substituída por
  nova apólice', 'substituição do seguro garantia'.

=== ANTI-PATTERNS (negativos — NÃO classificar como transição) ===

1. 'garantia constitucional', 'garantia processual', 'garantias do
   contraditório' — não é apresentação de garantia.
2. 'processo NÃO foi extinto', 'não houve extinção' — negação.
3. 'indenização por danos morais', 'indenização trabalhista' — não é
   sinistro de seguro garantia.
4. 'substituição' sem qualificador garantia/apólice — pode ser substituição
   de qualquer ato processual.
5. Mero despacho de saneamento / intimação genérica que MENCIONA apólice
   sem decidir nada — manter current_state.

=== REGRAS DE OURO ===

1. PRIORIDADE: keyword explícita > inferência contextual > no-transition.
2. closed (qualquer reason) DOMINA sobre accept/reject quando coexistem
   ('homologo a garantia e julgo extinto' → closed/extinto_processo).
3. Ordem de match: closed (sinistro_pago) > closed (liberada) > closed
   (extinto_processo) > accept > reject > replaced > no-transition.
   Mesma ordem do regex MVP — preserva backward-compatibility nos
   benchmarks.
4. Se há accept keyword + sinistro keyword no mesmo movimento, prefira
   closed/sinistro_pago (mais terminal).
5. Quando ambíguo, MANTENHA current_state e marque confidence < 0.5.

=== PRESENTATION_KIND HINT ===

V1 calibrado pra 'judicial'. Pros outros kinds ('carf', 'pgfn', 'tit_sp',
'aiim_tit_sp'), o classifier faz best-effort com o mesmo vocabulário — a
linguagem administrativa é parecida. Worker hoje filtra
case_kind='judicial' no SQL, então na prática esse caso não chega — mas o
modelo aceita pra suportar Fase 3.

=== CONFIDENCE CALIBRATION ===

  >= 0.9 : keyword explícita + qualificador + contexto coerente.
  0.7-0.9: keyword explícita sem qualificador forte, mas contexto OK.
  0.5-0.7: inferência indireta (ex: 'baixa dos autos' → liberada).
  < 0.5  : texto ambíguo — prefira no-transition.

=== FORMATO DE SAÍDA ===

Retorne APENAS um JSON válido:

{{
  "new_state": "offered"|"presumed_accepted"|"accepted"|"rejected"|"replaced"|"closed",
  "confidence": 0.0-1.0,
  "reasoning": "trecho citando keyword detectada + por que esse estado (até 300 chars)",
  "closed_reason": "extinto_processo"|"sinistro_pago"|"liberada"|"outra"|null
}}

closed_reason DEVE ser NULL quando new_state != 'closed'.
"""
