"""Prompt do AUDITOR DE FICHA (S6), versao 3: o auditor que abre os autos.

Decisao do Alfredo de 23/10/2026: "nucleo obrigatorio + indice navegavel; o
auditor vira v3 como agente". O v2 nao tinha ferramenta, de proposito: o
verificador com ferramenta deu mais falso-positivo. O v3 contem esse risco com 2
regras do CODIGO (`agent_v3.py`):

1. Cada item dos baldes traz `prova` {doc_id, pagina, trecho} ou
   `sem_prova_no_doc: true`. O codigo confere o trecho no documento.
2. Um fato "contradito" sem prova de documento NAO fica no balde 1. O codigo
   move o item ao balde 2 com grau `media`.

Dois prompts:

- Fase A (navegacao): o auditor escolhe UMA ferramenta por turno, sem schema.
- Fase B (veredito): o JSON do v2, com prova em cada item e `fatos_conferidos`.

O v3 REUSA os blocos do v2 (`prompts.py`) por import: persona, dossie,
esqueleto, ficha, contexto, S5, alertas, licoes, checklist, baldes e regra de
decisao. O gabarito NUNCA entra no v3 (Livro §10.2): o schema recusa o request.

Anti prompt-injection: o nucleo, o indice, a trilha e as leituras vao em cercas
com o token aleatorio da requisicao, como o dossie do v2.
"""

import json
from typing import Any, Optional

from .._utils.prompt_fence import gerar_fence_token
from .._utils.prompt_fence import json_sanitizado as _json_sanitizado
from .prompts import (
    _AVISO_DADO,
    _build_alertas,
    _build_baldes,
    _build_checklist,
    _build_contexto,
    _build_dossie_block,
    _build_esqueleto_block,
    _build_ficha_block,
    _build_licoes,
    _build_persona,
    _build_regra_de_decisao,
    _build_relatorio_s5,
    _fence,
)
from .schemas import MAX_CORRECAO_SUGERIDA, MAX_TRECHO_PROVA, AuditarFichaRequest

PROMPT_VERSION = "auditor_ficha_v3"


# ── Persona ────────────────────────────────────────────────────────────────


def _build_persona_v3() -> str:
    return _build_persona() + (
        "\n\nNESTA AUDITORIA VOCE ABRE OS AUTOS. Voce recebe o NUCLEO (os acordaos, a "
        "peticao inicial e a ultima decisao, com o texto inteiro), o INDICE (o que mais "
        "existe nos autos) e a TRILHA DE LEITURA do redator (o documento e o trecho que "
        "ele diz que sustentam cada slot). Para cada fato da ficha, abra o documento "
        "que o redator citou e tente REFUTAR o fato. Uma acusacao sem trecho de "
        "documento nao derruba a ficha: ela vira pendencia."
    )


# ── Blocos novos ───────────────────────────────────────────────────────────


def _build_nucleo_block(nucleo: dict[str, Any], token: str) -> str:
    return _fence(
        "nucleo",
        "NUCLEO (LEITURA OBRIGATORIA: texto inteiro, ja lido)",
        "Um documento do nucleo ja esta lido: cite o doc_id dele na prova sem abrir o "
        "documento com ferramenta. " + _AVISO_DADO,
        _json_sanitizado(nucleo),
        token,
    )


def _build_indice_block(indice: list[dict[str, Any]], token: str) -> str:
    return _fence(
        "indice",
        "INDICE (o que mais existe nos autos, sem o texto)",
        "`legivel=true`: voce pode abrir o documento com uma ferramenta. Um documento "
        "do indice so vai a uma prova depois que voce o abriu. " + _AVISO_DADO,
        _json_sanitizado(indice),
        token,
    )


def _build_trilha_block(req: AuditarFichaRequest, token: str) -> str:
    trilha = [t.model_dump() for t in (req.trilha_leitura or [])]
    return _fence(
        "trilha",
        "TRILHA DE LEITURA DO REDATOR (o que ele diz que leu para cada slot)",
        "A trilha e a ALEGACAO do redator, nao a verdade. Confira cada trecho no "
        "documento citado. " + _AVISO_DADO,
        _json_sanitizado(trilha),
        token,
    )


def _build_leituras_block(achados: list[dict[str, Any]], token: str) -> str:
    return _fence(
        "leituras",
        "O QUE VOCE LEU COM AS FERRAMENTAS",
        "Os trechos em `trechos[].texto` sao copia literal do documento, com a "
        "pagina. Use esses trechos nas provas. " + _AVISO_DADO,
        _json_sanitizado(achados or []),
        token,
    )


def _build_regras_de_prova() -> str:
    return f"""<regras_de_prova>
1. Cada item do balde 1 e do balde 2 traz `prova` OU `sem_prova_no_doc: true`. Nunca os
   dois. Nunca nenhum.
2. `prova` = {{doc_id, pagina, trecho}}. O `doc_id` e um documento do NUCLEO ou um
   documento do INDICE que voce ABRIU com uma ferramenta. O `trecho` e copia LITERAL do
   documento, no maximo {MAX_TRECHO_PROVA} caracteres. Use "..." para juntar 2 pedacos.
   A `pagina` e a pagina do trecho. Para documento do nucleo, use 1.
3. Um fato que voce acha CONTRADITO, mas sem trecho de documento que o contradiga, NAO
   e balde 1. Marque `sem_prova_no_doc: true`. O codigo move o item ao balde 2.
4. `fatos_conferidos`: um item para CADA slot da trilha do redator, com o doc_id que
   voce conferiu. `confere=false` quando o documento nao sustenta o slot. Todo
   `confere=false` tem um item no balde 1 ou no balde 2 no MESMO campo.
5. Nao ha gabarito nesta auditoria: `divergencias_gabarito` fica vazio.
</regras_de_prova>"""


def _build_output_shape_v3() -> str:
    return """=== FORMATO DA SAIDA (obrigatorio) ===
Responda ESTRITAMENTE com UM objeto JSON com estas chaves e nenhuma outra:

{
  "veredito": "aprovada | aprovada_com_correcoes | retida",
  "balde1": [
    {"campo": "<slot achatado: merito.p1 | bullets[0] | ultima_decisao.texto>",
     "motivo": "<UMA frase: o que esta errado e o que o documento diz>",
     "regra": "<ID do checklist, ex.: D-01>",
     "correcao_sugerida": "<o fato certo, curto, ate %d caracteres>",
     "prova": {"doc_id": "<do nucleo ou do indice lido>", "pagina": 3,
               "trecho": "<copia literal>"},
     "sem_prova_no_doc": false}
  ],
  "balde2": [
    {"campo": "<slot>", "pendencia": "<afirmacao em disputa>",
     "grau": "alta | media | baixa", "evidencia": "<citacao + fonte>",
     "recomendacao": "<acao acionavel>",
     "prova": null, "sem_prova_no_doc": true}
  ],
  "nao_confirmado": ["<o que nao deu para conferir e por que>"],
  "alertas_respondidos": [
    {"codigo": "<codigo do alerta>", "resposta": "confirmado | refutado",
     "motivo": "<prova>"}
  ],
  "divergencias_gabarito": [],
  "fatos_conferidos": [
    {"slot": "<slot da trilha>", "doc_id": "<doc_id conferido>", "confere": true,
     "motivo": "<frase curta>"}
  ]
}

Ficha sem defeito: balde1 e balde2 vazios. NAO escreva texto fora do JSON.""" % (
        MAX_CORRECAO_SUGERIDA
    )


# ── Fase A — navegacao ─────────────────────────────────────────────────────


def build_prompt_navegacao_v3(
    req: AuditarFichaRequest,
    *,
    nucleo: dict[str, Any],
    indice: list[dict[str, Any]],
    achados: list[dict[str, Any]],
    menu: list[str],
    budget_restante: int,
    budget_por_doc: int,
    fence_token: Optional[str] = None,
) -> str:
    """O turno de decisao: UMA ferramenta por turno, ou o fim da leitura."""
    token = fence_token or gerar_fence_token()
    return "\n\n".join([
        _build_persona_v3(),
        _build_ficha_block(req.ficha, token),
        _build_esqueleto_block(req.esqueleto, token),
        _build_trilha_block(req, token),
        _build_nucleo_block(nucleo, token),
        _build_indice_block(indice, token),
        _build_leituras_block(achados, token),
        f"""<ferramentas>
AGORA VOCE SO LE. O veredito vem depois, em outro turno.
Escolha UMA acao por turno. Responda SO com um JSON:

- {{"tool": "resumir_com_missao", "args": {{"doc_id": "...", "missao": "...", "slot": "<slot>"}}}}
- {{"tool": "perguntar_ao_documento", "args": {{"doc_id": "...", "pergunta": "...", "slot": "<slot>"}}}}
  A resposta traz os trechos literais, com a pagina.
- {{"tool": "pedir_pagina", "args": {{"doc_id": "...", "pagina": 3, "slot": "<slot>"}}}}
  Texto cru de uma pagina. No maximo 3 paginas por documento.
- {{"fim": true}}

Comece pelos documentos da trilha do redator e pelos fatos de merito, de decisao e de
valor. Procure o trecho que CONTRADIZ a ficha. O nucleo nao precisa de ferramenta.
`doc_id` e um item do INDICE com legivel=true.
Ferramentas disponiveis agora: {json.dumps(menu, ensure_ascii=False)}.
Chamadas restantes na ficha: {budget_restante}. Teto por documento: {budget_por_doc}.
</ferramentas>""",
    ])


# ── Fase B — veredito ──────────────────────────────────────────────────────


def build_prompt_v3(
    req: AuditarFichaRequest,
    *,
    nucleo: dict[str, Any],
    indice: list[dict[str, Any]],
    achados: list[dict[str, Any]],
    fence_token: Optional[str] = None,
) -> str:
    """O turno do veredito. A regra de decisao fica por ULTIMO (recency anchor)."""
    token = fence_token or gerar_fence_token()
    parts = [
        _build_persona_v3(),
        _build_dossie_block(req.dossie or "(sem dossie: use o nucleo)", token),
        _build_esqueleto_block(req.esqueleto, token),
        _build_ficha_block(req.ficha, token),
        _build_trilha_block(req, token),
        _build_nucleo_block(nucleo, token),
        _build_indice_block(indice, token),
        _build_leituras_block(achados, token),
        _build_contexto(req),
    ]
    if req.relatorio_s5:
        parts.append(_build_relatorio_s5(req, token))
    if req.alertas:
        parts.append(_build_alertas(req, token))
    if req.licoes:
        parts.append(_build_licoes(req, token))
    parts += [
        _build_output_shape_v3(),
        _build_checklist(),
        _build_baldes(),
        _build_regras_de_prova(),
        _build_regra_de_decisao(),
    ]
    return "\n\n".join(parts)


__all__ = [
    "PROMPT_VERSION",
    "build_prompt_navegacao_v3",
    "build_prompt_v3",
]
