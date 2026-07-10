"""Prompt do ficha_writer — escreve os slots de texto de uma ficha (FichaJSON v2).

"Codigo decide os numeros; o LLM so redige texto." Este passe NUNCA produz
numero/data/status — so texto dentro de limite_chars DURO. As regras de redacao
(persona + <regras_de_redacao>) sao embutidas VERBATIM abaixo; a saida e
ESTRITAMENTE o JSON schema pedido (um objeto com exatamente os nomes de campo).
"""

import json

from .schemas import CampoSpec, FichaWriteFieldsRequest

PROMPT_VERSION = "ficha_writer_v1"


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
- Respeite o limite_chars de CADA campo como restricao DURA. O layout do PDF
  QUEBRA se o texto estourar. Conte os caracteres e fique DENTRO do limite.
- Escreva em portugues do Brasil, CORRETAMENTE ACENTUADO.
- Voce NAO cria numeros, datas nem status: use SO os que o dossie ja traz. Se
  um fato nao esta no dossie, nao o afirme.
</regras_de_redacao>"""


# ── Blocos de contexto ─────────────────────────────────────────────────────


def _build_dossie_block(dossie: dict) -> str:
    """Serializa o dossie de fatos (JSON legivel, PT-BR preservado)."""
    body = json.dumps(dossie, ensure_ascii=False, indent=2, default=str)
    return f"=== DOSSIE (os FATOS — unica fonte de verdade) ===\n{body}"


def _tipo_instrucao(spec: CampoSpec) -> str:
    """Descreve a forma do valor esperado p/ o campo, no JSON de saida."""
    if spec.tipo == "array_string":
        qtd = spec.quantidade if spec.quantidade is not None else "os itens necessarios"
        return (
            f"lista JSON de strings ({qtd} itens); cada item <= {spec.limite_chars} chars"
        )
    if spec.tipo == "objeto_p1_p2":
        return (
            'objeto JSON {"p1": "...", "p2": "..."}; cada parte (p1 e p2) '
            f"<= {spec.limite_chars} chars"
        )
    return f"string; <= {spec.limite_chars} chars"


def _build_campo_spec_block(spec: CampoSpec) -> str:
    parts = [f"- campo \"{spec.nome}\" ({_tipo_instrucao(spec)})"]
    if spec.guidance:
        parts.append(f"    guidance: {spec.guidance}")
    if spec.exemplos:
        exs = "; ".join(repr(e) for e in spec.exemplos)
        parts.append(f"    exemplos: {exs}")
    return "\n".join(parts)


def _build_campos_block(campos: list[CampoSpec]) -> str:
    specs = "\n".join(_build_campo_spec_block(c) for c in campos)
    return f"=== CAMPOS A ESCREVER ===\n{specs}"


def _build_output_shape_block(campos: list[CampoSpec]) -> str:
    """Descreve o JSON de saida EXATO: um objeto so com os nomes pedidos."""
    lines = []
    for c in campos:
        if c.tipo == "array_string":
            shape = "[...]  (lista de strings)"
        elif c.tipo == "objeto_p1_p2":
            shape = '{"p1": "...", "p2": "..."}'
        else:
            shape = '"..."'
        lines.append(f'  "{c.nome}": {shape}')
    body = "{\n" + ",\n".join(lines) + "\n}"
    nomes = ", ".join(f'"{c.nome}"' for c in campos)
    return (
        "=== FORMATO DA SAIDA (obrigatorio) ===\n"
        "Responda ESTRITAMENTE com UM objeto JSON contendo EXATAMENTE estas "
        f"chaves (nenhuma a mais, nenhuma a menos): {nomes}.\n"
        "Shape:\n" + body
    )


def _build_retry_block(campos_com_erro) -> str:
    """Bloco de correcao cirurgica (retry). Vem antes das <regras_de_redacao>
    mas depois do resto; ecoa o erro + o valor anterior de cada campo."""
    lines = ["=== CORRECAO OBRIGATORIA (retry) ==="]
    lines.append(
        "Sua resposta anterior REPROVOU nos campos abaixo. Corrija CIRURGICAMENTE "
        "SO estes campos — mantenha os demais como estavam. Para cada um, o erro e "
        "o valor que falhou:"
    )
    for ce in campos_com_erro:
        prev = json.dumps(ce.valor_anterior, ensure_ascii=False, default=str)
        lines.append(f'- "{ce.nome}": ERRO = {ce.erro} | valor_anterior = {prev}')
    lines.append(
        "Reescreva cada um desses campos respeitando o erro apontado (tipicamente "
        "o limite de caracteres) sem perder o sentido. Ainda assim, devolva o "
        "objeto JSON COMPLETO com TODAS as chaves pedidas."
    )
    return "\n".join(lines)


# ── Montagem ───────────────────────────────────────────────────────────────


def build_write_fields_prompt(req: FichaWriteFieldsRequest) -> str:
    """Monta o prompt completo. Ordem: persona -> dossie -> campos -> shape ->
    (retry, se houver) -> <regras_de_redacao> (ultimo = recency anchor)."""
    parts = [
        _build_persona(),
        "",
        _build_dossie_block(req.dossie),
        "",
        _build_campos_block(req.campos),
        "",
        _build_output_shape_block(req.campos),
    ]
    if req.campos_com_erro:
        parts += ["", _build_retry_block(req.campos_com_erro)]
    parts += ["", _build_regras_redacao()]
    return "\n".join(parts)


__all__ = ["build_write_fields_prompt", "PROMPT_VERSION"]
