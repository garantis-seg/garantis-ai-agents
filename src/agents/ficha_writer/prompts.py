"""Prompt do ficha_writer — escreve os slots de texto de uma ficha (FichaJSON v2).

"Codigo decide os numeros; o LLM so redige texto." Este passe NUNCA produz
numero/data/status — so texto dentro do limite DURO (`max`) de cada slot. As
regras de redacao (persona + <regras_de_redacao>) sao embutidas VERBATIM abaixo;
a saida e ESTRITAMENTE um objeto JSON PLANO nome -> string, com exatamente os
nomes pedidos.

Retry cirurgico: quando campos_com_erro esta presente, o prompt so pede os slots
com erro (specs deles seguem em campos) e ecoa erro + valor_anterior de cada um.
"""

import json

from .schemas import CampoSpec, FichaWriteFieldsRequest

PROMPT_VERSION = "ficha_writer_v2"


# ── Persona + regras de redacao (VERBATIM) ─────────────────────────────────


def _build_persona() -> str:
    return (
        "Voce e um SUBSCRITOR SENIOR escrevendo para OUTRO subscritor — que le "
        "cada palavra e conhece o cliente melhor do que nos. Escreva com a "
        "precisao de quem sabe que sera lido de perto por um par tecnico.\n\n"
        "TESTE DE OURO (aplique a CADA frase que escrever): toda frase deve "
        "sobreviver a pergunta \"como voce sabe disso?\" com uma resposta que se "
        "possa dar NA FRENTE do cliente. A fonte de cada afirmacao e um fato "
        "verificavel: o acordao publicado, a consulta PGFN datada, o andamento "
        "do tribunal. Se uma frase nao passa nesse teste, reescreva-a."
    )


def _build_regras_redacao() -> str:
    """<regras_de_redacao> — os NUNCAS + limite duro. Vem por ULTIMO no prompt
    (recency anchor), como o filtro do merito_synthesis."""
    return """<regras_de_redacao>
NUNCA faca o seguinte (sao erros que reprovam o texto):

1. AFIRMAR ABSOLUTOS sobre o mundo do cliente. Nao temos onisciencia — temos
   consultas datadas. Errado: "o cliente nao tem apolice". Certo: "apolice nao
   identificada em consulta publica". Sempre ancore o absoluto na fonte/consulta.

2. CITAR ENCANAMENTO INTERNO. Nunca mencione engine, watchlist, snapshot,
   sistema, pipeline, score, modelo, ou qualquer nome de infraestrutura nossa.
   O leitor quer o FATO JURIDICO, nao como o obtivemos.

3. ESCREVER "ate hoje" ou "atualmente" para andamentos. O andamento do tribunal
   tem delay — nunca sabemos o "hoje" real. Sempre: "na ultima posicao
   disponivel (DD/MM)". Use a data que o dossie fornece; nao invente data.

4. PRAZO NUMERICO ESPECULATIVO. Nao estime "em 30 dias", "nos proximos meses"
   com numero inventado. So cite prazo se estiver EXPLICITO no dossie.

5. MEMORIA DE CALCULO NO TEXTO. Nada de "somando X + Y", "media ponderada",
   decimais de score, formula. O numero ja foi decidido em codigo; voce so
   descreve o estado em portugues corrente.

ALEM DISSO:
- Respeite o limite `max` de caracteres de CADA slot como restricao DURA. O
  layout do PDF QUEBRA se o texto estourar. Conte os caracteres e fique DENTRO
  do limite.
- Escreva em portugues do Brasil, CORRETAMENTE ACENTUADO.
- Voce NAO cria numeros, datas nem status: use SO os que o dossie ja traz. Se
  um fato nao esta no dossie, nao o afirme.
</regras_de_redacao>"""


# ── Blocos de contexto ─────────────────────────────────────────────────────


def _build_dossie_block(dossie: dict) -> str:
    """Serializa o dossie de fatos (JSON legivel, PT-BR preservado)."""
    body = json.dumps(dossie, ensure_ascii=False, indent=2, default=str)
    return f"=== DOSSIE (os FATOS — unica fonte de verdade) ===\n{body}"


def _build_campo_spec_block(spec: CampoSpec) -> str:
    header = f"- slot \"{spec.nome}\" (string; <= {spec.max} chars"
    if spec.path and spec.path != spec.nome:
        header += f"; path: {spec.path}"
    header += ")"
    parts = [header]
    if spec.guidance:
        parts.append(f"    guidance: {spec.guidance}")
    if spec.exemplos:
        exs = "; ".join(repr(e) for e in spec.exemplos)
        parts.append(f"    exemplos: {exs}")
    return "\n".join(parts)


def _build_campos_block(campos: list[CampoSpec]) -> str:
    specs = "\n".join(_build_campo_spec_block(c) for c in campos)
    return f"=== SLOTS A ESCREVER ===\n{specs}"


def _build_output_shape_block(campos: list[CampoSpec]) -> str:
    """Descreve o JSON de saida EXATO: objeto PLANO nome -> string, so com os
    nomes pedidos."""
    lines = [f'  "{c.nome}": "..."' for c in campos]
    body = "{\n" + ",\n".join(lines) + "\n}"
    nomes = ", ".join(f'"{c.nome}"' for c in campos)
    return (
        "=== FORMATO DA SAIDA (obrigatorio) ===\n"
        "Responda ESTRITAMENTE com UM objeto JSON PLANO onde cada valor e uma "
        "STRING simples (nunca lista, nunca objeto aninhado), contendo EXATAMENTE "
        f"estas chaves (nenhuma a mais, nenhuma a menos): {nomes}.\n"
        "Shape:\n" + body
    )


def _build_retry_block(campos_com_erro) -> str:
    """Bloco de correcao cirurgica (retry): ecoa erro + valor_anterior de cada
    slot reprovado. A saida pedida ja e SO estes slots (output shape acima)."""
    lines = ["=== CORRECAO OBRIGATORIA (retry) ==="]
    lines.append(
        "Os slots abaixo REPROVARAM na validacao. Gere/corrija SOMENTE estes "
        "slots — nenhum outro. Para cada um, o erro e o valor que falhou:"
    )
    for ce in campos_com_erro:
        prev = json.dumps(ce.valor_anterior, ensure_ascii=False, default=str)
        lines.append(f'- "{ce.nome}": ERRO = {ce.erro} | valor_anterior = {prev}')
    lines.append(
        "Reescreva cada um respeitando o erro apontado (tipicamente o limite de "
        "caracteres) sem perder o sentido. Devolva o objeto JSON SO com as chaves "
        "listadas no FORMATO DA SAIDA."
    )
    return "\n".join(lines)


# ── Montagem ───────────────────────────────────────────────────────────────


def build_write_fields_prompt(
    req: FichaWriteFieldsRequest,
    campos_alvo: list[CampoSpec] | None = None,
) -> str:
    """Monta o prompt completo. Ordem: persona -> dossie -> slots -> shape ->
    (retry, se houver) -> <regras_de_redacao> (ultimo = recency anchor).

    `campos_alvo`: subset de req.campos a pedir (retry cirurgico). Default =
    todos os req.campos.
    """
    campos = campos_alvo if campos_alvo is not None else req.campos
    parts = [
        _build_persona(),
        "",
        _build_dossie_block(req.dossie),
        "",
        _build_campos_block(campos),
        "",
        _build_output_shape_block(campos),
    ]
    if req.campos_com_erro:
        parts += ["", _build_retry_block(req.campos_com_erro)]
    parts += ["", _build_regras_redacao()]
    return "\n".join(parts)


__all__ = ["build_write_fields_prompt", "PROMPT_VERSION"]
