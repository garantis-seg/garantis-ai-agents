"""VERIFICADOR CEGO (onda 9) — `verificar_par`, um par por vez, sem contexto.

Modo ADITIVO: o `auditar_evidencias` deste mesmo pacote continua existindo,
intacto e testado, porque o harness do shared o chama hoje. Este modulo e o
caminho novo (DESENHO §2.3), e o antigo so morre na onda 6.

O que o verificador cego ve: `{afirmacao, ancora, trecho}`. Nada mais. Sem
grafo, sem historico de construcao, sem os outros documentos, sem ferramenta de
lookup. A privacao e o produto: o HALLMARK mediu FP ~5x maiores com verificador
contextualizado (pesquisa §4.5).

## As tres travas de codigo (nenhuma e instrucao de prompt)

1. **`numeros_divergentes` sai do CODIGO.** `_assinatura_numerica` compara
   afirmacao x trecho, com as confusoes de OCR ja canonizadas. Se o codigo
   achou divergencia e o modelo respondeu `supported`, o agente REBAIXA para
   `contradicted` — prompt nao e enforcement. Alucinacao numerica de alta
   confianca e o risco nº 3 da pesquisa, e nao se defende dela pedindo ao
   modelo que se policie.
2. **Vocabulario fechado.** Rotulo fora dos quatro, ou `motivo_tipado` fora do
   enum, invalida a resposta (`success=false`, `error_tipo="vocabulario"`) em
   vez de virar um balde novo que o QA nunca agrega.
3. **Envelope validado pelo shared.** `validar_envelope` exige `confianca`
   numerica EM CAMPO e `objeto_da_confianca` nao-vazio. Resposta sem isso ganha
   UM retry que NOMEIA a falha; se falhar de novo, erro tipado — nunca um
   default silencioso, que seria confianca inventada pelo codigo.

## DINCO

Com `FICHAS_DINCO_ENABLED` ligada, o agente gera N-1 distractors EM CODIGO
(`gerar_distractors` do shared) e faz N chamadas INDEPENDENTES — uma por
variante, nenhuma sabendo das outras. E a independencia que remove a
sugestionabilidade: se o modelo visse as variantes juntas, saberia qual e "a"
alegacao e a confianca voltaria a saturar. `normalizar_dinco` faz
`conf(A) / Σ conf(variantes)` com desconto de redundancia.

Desligada, N efetivo = 1 e a confianca e a verbalizada crua — e o
`self_consistency_n=1` vai DECLARADO na resposta. Metrica de A/B sem o N
gravado e incomparavel, e sem os votos gravados nao ha recalibracao depois.
"""

import asyncio
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from garantis_shared.calculo_fichas.confianca import (
    EnvelopeInvalidoError,
    gerar_distractors,
    normalizar_dinco,
    validar_envelope,
)
from garantis_shared.llm_models import model_for

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from .verificador_prompts import (
    build_confianca_variante_prompt,
    build_verificar_par_prompt,
)
from .verificador_schemas import (
    MOTIVO_OK,
    MOTIVOS_TIPADOS,
    VEREDITOS,
    VerificarParRequest,
    VerificarParResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "gemini")

#: Modelo do VERIFICADOR — familia DIFERENTE do calculador (anti-conluio, §8.4).
#: O default sai do PAPEL (`llm_models.ROLES`), nunca de literal: papel tem UM
#: endereco, e foi a duplicacao de literais que deixou o calculador apontando
#: para um modelo fora do catalogo (preco 0/0 => custo invisivel no ledger).
DEFAULT_MODEL = os.getenv(
    "AUDITOR_EVIDENCIAS_MODEL",
    os.getenv("DEFAULT_MODEL") or model_for("ficha_auditoria_evidencias"),
)


def _dinco_ligado() -> bool:
    """Le a flag NA HORA da chamada, nao no import.

    Ler no import congelaria o valor no momento em que o modulo entra, o que
    torna a flag intestavel sem reload e — pior — faz o comportamento depender
    da ordem de import em producao.
    """
    return os.getenv("FICHAS_DINCO_ENABLED", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _n_efetivo(pedido: Optional[int]) -> int:
    """O N desta run. Flag OFF => 1, sempre, mesmo com `n_dinco` no request.

    A precedencia e deliberada: a flag e o interruptor de producao e o
    `n_dinco` e o ajuste fino. Um request nao liga o DINCO num ambiente onde
    o dono o desligou (custo N-vezes maior nao entra pela porta do payload).
    """
    if not _dinco_ligado():
        return 1
    if pedido is not None:
        return max(1, int(pedido))
    # Lido do ambiente a cada chamada pelo mesmo motivo da flag.
    return max(1, int(os.getenv("SELF_CONSISTENCY_N", "3")))


# ── numeros divergentes: CODIGO, nao modelo ─────────────────────────────────

#: As confusoes de OCR que viram digito. Vive aqui (e nao so no fallback do
#: import) porque a comparacao POR VALOR tambem precisa dela: `723.81O.827,57`
#: so pode ser parseado como quantia depois que o `O` vira `0`.
_OCR_PARA_DIGITO = str.maketrans({
    "o": "0", "O": "0", "d": "0", "D": "0", "l": "1", "i": "1", "I": "1",
    "L": "1", "|": "1", "z": "2", "Z": "2", "s": "5", "S": "5", "b": "8",
    "B": "8", "g": "9", "G": "9", "q": "9", "Q": "9",
})

try:  # pragma: no cover - o fallback so roda se o shared mudar de superficie
    from garantis_shared.calculo_fichas.evidencias import _assinatura_numerica
except ImportError:  # pragma: no cover
    _TOKEN = re.compile(r"(?<![a-zà-ÿA-ZÀ-Ÿ])[\d.,OoIiLlSsBbZzGgQqDd|]*\d[\d.,OoIiLlSsBbZzGgQqDd|]*")

    def _assinatura_numerica(texto: str) -> tuple[str, ...]:
        out = []
        for tok in _TOKEN.findall(texto):
            digitos = re.sub(r"[^0-9]", "", tok.translate(_OCR_PARA_DIGITO))
            if len(digitos) >= 2:
                out.append(digitos)
        return tuple(out)


#: Numero como ele aparece no texto, para devolver ao humano a forma ORIGINAL
#: ("723.910.827,57") e nao a assinatura canonizada ("72391082757").
_NUM_LITERAL_RE = re.compile(
    r"(?<![a-zà-ÿA-ZÀ-Ÿ])[\d.,OoIiLlSsBbZzGgQqDd|]*\d[\d.,OoIiLlSsBbZzGgQqDd|]*"
)


def _literais_por_assinatura(texto: str) -> dict[str, str]:
    """{assinatura canonizada -> primeiro literal que a produziu}."""
    out: dict[str, str] = {}
    for tok in _NUM_LITERAL_RE.findall(texto):
        for assin in _assinatura_numerica(tok):
            out.setdefault(assin, tok.strip(".,"))
    return out


# ── a mesma quantia escrita de duas formas ──────────────────────────────────
#
# A assinatura de DIGITOS sozinha nao basta para "e o mesmo valor?": ela apaga
# a posicao do separador. O shared serializa o valor com `repr()` de float
# (`f"vale {valor!r}"`), entao a afirmacao chega como `500000.0` e o documento
# traz `R$ 500.000,00` — mesma quantia, assinaturas `5000000` x `50000000`, e
# TODO valor monetario correto era reprovado como `numero_diferente`.
#
# Por isso a comparacao passa a ser por VALOR: cada token vira um conjunto de
# Decimals candidatos, e dois numeros casam se compartilham algum candidato.
# Candidatos no PLURAL porque `1.234` e genuinamente ambiguo (mil duzentos e
# trinta e quatro em pt-BR, um virgula duzentos e trinta e quatro em en-US) e
# escolher UMA leitura criaria falso positivo na outra. Divergencia real —
# 500.000 x 600.000 — nao tem candidato em comum em leitura nenhuma.
#
# A camada de valor e ADITIVA: a assinatura de digitos continua sendo a
# primeira prova (e a unica que tolera OCR em letra, `723.81O` == `723.810`).
# So quando a assinatura NAO casa e que se pergunta se o valor casa.

#: >= 3 digitos depois do separador nao e casa decimal: e grupo de milhar
#: (`1.234.567`). Com 1 ou 2, e ambiguo e vira candidato.
_MAX_CASAS_DECIMAIS = 2


def _valores_candidatos(literal: str) -> set[Decimal]:
    """As quantias que `literal` pode representar. Vazio = nao e quantia.

    Um separador so, com 1-2 digitos a direita, e ambiguo (`1,5` decimal;
    `1.234` milhar) e rende DOIS candidatos. Com 3 digitos a direita e milhar
    puro. Com varios separadores, o ULTIMO manda: `1.234.567,89` (BR) e
    `1,234,567.89` (US) sao a mesma quantia lida pela mesma regra.

    Sufixo `.0` cai naturalmente: `500000.0` vira `Decimal("500000.0")`, que
    `==` `Decimal("500000")` — Decimal compara por VALOR, nao por forma.
    """
    # Canoniza OCR em letra ANTES de olhar separadores: `723.81O.827,57` tem de
    # produzir os mesmos candidatos de `723.810.827,57`.
    txt = literal.translate(_OCR_PARA_DIGITO).strip(" .,")
    if not txt or not re.fullmatch(r"[\d.,]+", txt):
        return set()

    seps = [c for c in txt if c in ".,"]
    if not seps:
        return {Decimal(txt)} if txt.isdigit() else set()

    corpo, ultimo_sep = txt.rsplit(seps[-1], 1)
    if not corpo or not ultimo_sep.isdigit() or not ultimo_sep:
        return set()

    outros = [c for c in corpo if c in ".,"]
    inteiro_sem_sep = re.sub(r"[^0-9]", "", corpo)
    if not inteiro_sem_sep.isdigit():
        return set()

    cands: set[Decimal] = set()

    # Leitura A — o ultimo separador e DECIMAL. So faz sentido com <= 2 casas.
    if len(ultimo_sep) <= _MAX_CASAS_DECIMAIS:
        try:
            cands.add(Decimal(f"{inteiro_sem_sep}.{ultimo_sep}"))
        except InvalidOperation:  # pragma: no cover - regex ja garante digitos
            pass

    # Leitura B — o ultimo separador e MILHAR. Grupo de milhar tem 3 digitos
    # exatos; exigir isso evita ler `1,5` como quinze mil.
    if len(ultimo_sep) == 3:
        try:
            cands.add(Decimal(inteiro_sem_sep + ultimo_sep))
        except InvalidOperation:  # pragma: no cover
            pass

    # Separadores MISTOS (`1.234,56`) desfazem a ambiguidade: se o texto usa os
    # dois caracteres, o ultimo e decimal e os outros sao milhar — a leitura de
    # milhar-puro nao se sustenta e sai.
    if outros and len(set(seps)) > 1 and len(ultimo_sep) <= _MAX_CASAS_DECIMAIS:
        cands.discard(Decimal(inteiro_sem_sep + ultimo_sep))

    return cands


def _valores_por_assinatura(texto: str) -> dict[str, set[Decimal]]:
    """{assinatura -> quantias que o literal daquela assinatura pode valer}."""
    out: dict[str, set[Decimal]] = {}
    for tok in _NUM_LITERAL_RE.findall(texto):
        vals = _valores_candidatos(tok)
        if not vals:
            continue
        for assin in _assinatura_numerica(tok):
            out.setdefault(assin, set()).update(vals)
    return out


def _numeros_divergentes(afirmacao: str, trecho: str) -> list[dict[str, str]]:
    """Os numeros da AFIRMACAO que o trecho nao confirma — em codigo.

    Direcao deliberadamente assimetrica: um trecho pode (e costuma) trazer
    numeros que a afirmacao nao cita — folha, artigo, percentual, a outra linha
    da tabela — e isso NAO e divergencia. O que e divergencia e a afirmacao
    afirmar um numero que o trecho citado nao sustenta.

    DUAS provas de igualdade, nesta ordem, e basta UMA passar:

    1. **Assinatura de digitos** — tolera ruido de OCR em LETRA (`723.81O` casa
       com `723.810`), que e o gate G2 do shared reusado contra outro alvo.
    2. **Valor numerico** (`_valores_candidatos`) — tolera FORMA: `500000.0`
       (repr de float, como o shared serializa) e `R$ 500.000,00` sao a mesma
       quantia, e a assinatura de digitos sozinha dizia que nao (`5000000` x
       `50000000`), reprovando todo valor monetario correto do calculo.

    O que NENHUMA das duas tolera e digito diferente: `500.000` x `600.000` nao
    casa em assinatura nem em valor, e continua divergencia.

    Emparelhamento por PREFIXO/SUFIXO comum: `72391082757` na afirmacao e
    `72381082757` no trecho sao o mesmo valor mal lido, e o par so e util ao
    humano se apontar o vizinho certo. Sem numero parecido, o campo `no_trecho`
    fica vazio — "o trecho nao tem numero nenhum que corresponda" tambem e uma
    resposta.
    """
    assin_af = _assinatura_numerica(afirmacao)
    assin_tr = set(_assinatura_numerica(trecho))
    if not assin_af:
        return []

    lit_af = _literais_por_assinatura(afirmacao)
    lit_tr = _literais_por_assinatura(trecho)

    val_af = _valores_por_assinatura(afirmacao)
    # As quantias do TRECHO num conjunto so: a pergunta e "o trecho tem esta
    # quantia em ALGUM lugar?", nao "em qual token".
    vals_tr: set[Decimal] = set()
    for vals in _valores_por_assinatura(trecho).values():
        vals_tr.update(vals)

    out: list[dict[str, str]] = []
    vistos: set[str] = set()
    for a in assin_af:
        if a in assin_tr or a in vistos:
            continue
        # Assinatura nao casou: pode ser so a FORMA. Se alguma quantia que este
        # numero pode valer aparece no trecho, nao ha divergencia.
        if val_af.get(a, set()) & vals_tr:
            continue
        vistos.add(a)
        out.append({
            "na_afirmacao": lit_af.get(a, a),
            "no_trecho": lit_tr.get(_vizinho(a, lit_tr), "") if lit_tr else "",
        })
    return out


def _vizinho(assinatura: str, literais: dict[str, str]) -> str:
    """A assinatura do trecho mais parecida — mesmo comprimento, maior overlap.

    Serve so para o humano: mostrar `723.810.827,57` ao lado de
    `723.910.827,57` diz o que aconteceu; mostrar um numero de folha nao diz
    nada. Exige mesmo comprimento porque valores de escalas diferentes nao sao
    "o mesmo numero mal lido".
    """
    melhor, melhor_score = "", 0
    for cand in literais:
        if len(cand) != len(assinatura):
            continue
        score = sum(1 for x, y in zip(assinatura, cand) if x == y)
        if score > melhor_score:
            melhor, melhor_score = cand, score
    # Menos de metade dos digitos em comum nao e "o mesmo numero mal lido".
    return melhor if melhor_score * 2 >= len(assinatura) else ""


# ── validacao do vocabulario ────────────────────────────────────────────────

def _validar_vocabulario(parsed: dict) -> tuple[Optional[dict], Optional[str]]:
    """Rotulo e motivo dentro dos enums, ou erro tipado. Sem coercao.

    Nao mapeamos "aprovado"/"ok"/"yes" para `supported`: coercao esconde um
    modelo que nao entendeu o contrato e transforma um erro visivel numa
    aprovacao silenciosa — a mesma classe de falha que o `_MOTIVO_OMISSO` do
    auditor antigo existe para matar.
    """
    veredito = parsed.get("veredito")
    if veredito not in VEREDITOS:
        return None, (
            f"`veredito` fora do vocabulario fechado: {veredito!r} — "
            f"aceitos {list(VEREDITOS)}"
        )
    motivo_tipado = parsed.get("motivo_tipado")
    if motivo_tipado not in MOTIVOS_TIPADOS and motivo_tipado != MOTIVO_OK:
        return None, (
            f"`motivo_tipado` fora do enum fechado: {motivo_tipado!r} — "
            f"aceitos {list(MOTIVOS_TIPADOS) + [MOTIVO_OK]}"
        )
    if veredito != "supported" and motivo_tipado == MOTIVO_OK:
        return None, (
            f"veredito `{veredito}` com motivo `{MOTIVO_OK}`: se nao ha "
            "divergencia, o veredito e `supported`"
        )
    return {
        "veredito": veredito,
        "motivo_tipado": motivo_tipado,
        "motivo": str(parsed.get("motivo") or "").strip(),
    }, None


async def _uma_chamada(
    llm_provider: Any, prompt: str, model: str, max_tokens: int = 2048
) -> tuple[dict | None, str, str, float]:
    """(parsed | None, raw, model_usado, custo). Nunca levanta por parse."""
    response: LLMResponse = await llm_provider.agenerate(
        prompt=prompt,
        model=model,
        temperature=0.0,
        response_mime_type="application/json",
        max_tokens=max_tokens,
    )
    raw = response.text or ""
    used_model = response.model or model
    cost = (response.metadata.get("cost_usd", 0.0) if response.metadata else 0.0)
    try:
        return parse_llm_json(raw), raw, used_model, cost
    except Exception:  # noqa: BLE001 — parse quebrado nao aprova nada
        return None, raw, used_model, cost


async def _votos_dinco(
    llm_provider: Any,
    trecho: str,
    conf_alegacao: float,
    afirmacao: str,
    distractors: list[Any],
    model: str,
) -> tuple[float, list[dict], float]:
    """N-1 chamadas INDEPENDENTES, uma por distractor. Devolve (conf, votos, custo).

    `asyncio.gather` e paralelismo de I/O, nao compartilhamento de contexto: as
    chamadas nao se veem, que e o requisito do metodo. Voto que falha o parse e
    DESCARTADO em vez de virar 0.0 — um zero inventado inflaria a confianca
    normalizada da alegacao (denominador menor), que e a direcao errada de
    errar.
    """
    if not distractors:
        return conf_alegacao, normalizar_dinco(conf_alegacao, [])[1], 0.0

    prompts = [build_confianca_variante_prompt(d, trecho) for d in distractors]
    resultados = await asyncio.gather(
        *(_uma_chamada(llm_provider, p, model, max_tokens=512) for p in prompts),
        return_exceptions=True,
    )

    custo = 0.0
    pares: list[tuple[Any, float]] = []
    for distractor, res in zip(distractors, resultados):
        if isinstance(res, BaseException):
            logger.warning("VERIFICADOR_DINCO_VOTO_FALHOU: %r", res)
            continue
        parsed, _raw, _m, c = res
        custo += c
        if not isinstance(parsed, dict):
            continue
        try:
            env = validar_envelope(parsed)
        except EnvelopeInvalidoError as e:
            logger.info("VERIFICADOR_DINCO_VOTO_SEM_ENVELOPE: %s", e)
            continue
        pares.append((distractor, env["confianca"]))

    conf_norm, votos = normalizar_dinco(conf_alegacao, pares)
    return conf_norm, votos, custo


async def verificar_par(
    request: VerificarParRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> VerificarParResponse:
    """Verifica UM par (afirmacao, trecho) as cegas.

    Nunca levanta: falha vira `success=false` + `error`/`error_tipo`, que o
    harness registra como rejeicao — falha do verificador nao e aprovacao.
    """
    if isinstance(request, dict):
        request = VerificarParRequest(**request)

    provider = provider or request.provider or DEFAULT_PROVIDER
    model = model or request.model or DEFAULT_MODEL

    afirmacao = (request.afirmacao or "").strip()
    trecho = (request.trecho or "").strip()
    if not afirmacao or not trecho:
        return VerificarParResponse(
            success=False, model=model, cost_usd=0.0,
            error="par incompleto: `afirmacao` e `trecho` sao obrigatorios",
            error_tipo="request", ancora=request.ancora,
        )

    # (1) O achado do CODIGO, antes de qualquer LLM. Ele vai para o prompt como
    #     fato dado e sobrevive ao que o modelo responder.
    divergentes = _numeros_divergentes(afirmacao, trecho)

    llm_provider = create_provider(provider)
    prompt = build_verificar_par_prompt(afirmacao, trecho, divergentes)

    parsed, raw, used_model, custo = await _uma_chamada(llm_provider, prompt, model)
    if parsed is None:
        logger.warning("VERIFICADOR_PARSE_FAIL head=%r", raw[:200])
        return VerificarParResponse(
            success=False, model=used_model, cost_usd=custo,
            error="parse do JSON do LLM falhou", error_tipo="parse",
            numeros_divergentes=divergentes, ancora=request.ancora,
        )

    vocab, err = _validar_vocabulario(parsed)
    if err is not None:
        logger.info("VERIFICADOR_VOCABULARIO_FAIL: %s", err)
        return VerificarParResponse(
            success=False, model=used_model, cost_usd=custo,
            error=err, error_tipo="vocabulario",
            numeros_divergentes=divergentes, ancora=request.ancora,
        )

    # (2) Envelope em CAMPO. UM retry que NOMEIA a falha — o modelo costuma
    #     acertar quando lhe dizem qual campo faltou; depois disso, erro tipado.
    #     Nunca um default: confianca inventada pelo codigo e o pior resultado.
    try:
        envelope = validar_envelope(parsed)
    except EnvelopeInvalidoError as e:
        logger.info("VERIFICADOR_ENVELOPE_FAIL (1a): %s", e)
        prompt_retry = (
            f"{prompt}\n\n"
            "=== CORRECAO OBRIGATORIA (sua resposta anterior foi REJEITADA) ===\n"
            f"Motivo da rejeicao: {e}\n"
            "Reenvie o MESMO julgamento, agora com `confianca` como NUMERO "
            "entre 0.0 e 1.0 (nao texto, nao percentual entre aspas) e "
            "`objeto_da_confianca` como frase nao-vazia dizendo do que "
            "exatamente voce esta confiante."
        )
        parsed2, raw2, used_model, custo2 = await _uma_chamada(
            llm_provider, prompt_retry, model
        )
        custo += custo2
        if parsed2 is None:
            return VerificarParResponse(
                success=False, model=used_model, cost_usd=custo,
                error=f"envelope invalido ({e}); retry nao parseou",
                error_tipo="envelope",
                numeros_divergentes=divergentes, ancora=request.ancora,
            )
        vocab2, err2 = _validar_vocabulario(parsed2)
        if err2 is not None:
            return VerificarParResponse(
                success=False, model=used_model, cost_usd=custo,
                error=f"envelope invalido ({e}); retry saiu do vocabulario: {err2}",
                error_tipo="vocabulario",
                numeros_divergentes=divergentes, ancora=request.ancora,
            )
        vocab = vocab2
        try:
            envelope = validar_envelope(parsed2)
        except EnvelopeInvalidoError as e2:
            logger.warning("VERIFICADOR_ENVELOPE_FAIL (retry): %s | head=%r", e2, raw2[:200])
            return VerificarParResponse(
                success=False, model=used_model, cost_usd=custo,
                error=f"envelope sem confianca em campo apos retry: {e2}",
                error_tipo="envelope",
                numeros_divergentes=divergentes, ancora=request.ancora,
            )

    veredito = vocab["veredito"]
    motivo_tipado = vocab["motivo_tipado"]
    motivo = vocab["motivo"]

    # (3) A trava que prompt nao faz: divergencia numerica achada pelo CODIGO
    #     nunca vira aprovacao. O modelo pode ter "entendido" que os valores sao
    #     equivalentes; a assinatura ja tolerou o que havia para tolerar.
    if divergentes and veredito == "supported":
        logger.warning(
            "VERIFICADOR_REBAIXOU_POR_NUMERO: modelo=supported, "
            "divergencias=%s", divergentes,
        )
        veredito = "contradicted"
        motivo_tipado = "numero_diferente"
        pares = "; ".join(
            f"{d['na_afirmacao']} != {d['no_trecho'] or '(ausente no trecho)'}"
            for d in divergentes
        )
        motivo = (
            "rebaixado por CODIGO: o modelo respondeu `supported`, mas a "
            f"assinatura numerica diverge ({pares}). "
            + (f"Julgamento do modelo: {motivo}" if motivo else "")
        ).strip()

    # (4) DINCO — N chamadas independentes, ou N=1 declarado com a flag off.
    n_pedido = _n_efetivo(request.n_dinco)
    dinco = _dinco_ligado()
    conf = envelope["confianca"]
    votos: list[dict] = normalizar_dinco(conf, [])[1]
    n = 1

    if dinco and n_pedido > 1:
        distractors = request.distractors
        if distractors is None:
            distractors = gerar_distractors(
                {"valor": _valor_da_afirmacao(afirmacao)},
                texto_documento=trecho,
                n=n_pedido,
            )
        distractors = list(distractors)
        conf, votos, custo_dinco = await _votos_dinco(
            llm_provider, trecho, conf, afirmacao, distractors, model,
        )
        custo += custo_dinco
        # O N que vai para a memoria e o EFETIVO, nao o pedido. `n_pedido` e
        # um TETO: `gerar_distractors` devolve menos quando o trecho nao tem
        # numeros plausiveis suficientes (um trecho com um unico valor so rende
        # as duas perturbacoes de milhar). Gravar o teto faria a recalibracao
        # comparar uma celula DINCO@4 com uma DINCO@3 como se fossem iguais —
        # e o N gravado existe justamente para tornar as runs comparaveis.
        n = 1 + len(distractors)

    logger.info(
        "VERIFICADOR_OK veredito=%s motivo=%s divergencias=%d n=%d dinco=%s model=%s",
        veredito, motivo_tipado, len(divergentes), n, dinco, used_model,
    )
    return VerificarParResponse(
        success=True,
        veredito=veredito,
        motivo_tipado=motivo_tipado,
        motivo=motivo,
        numeros_divergentes=divergentes,
        confianca=conf,
        objeto_da_confianca=envelope["objeto_da_confianca"],
        votos=votos,
        self_consistency_n=n,
        dinco_enabled=dinco,
        ancora=request.ancora,
        model=used_model,
        cost_usd=custo,
        error=None,
    )


def _valor_da_afirmacao(afirmacao: str) -> Any:
    """O valor sobre o qual a afirmacao fala — para o `gerar_distractors`.

    Heuristica DELIBERADAMENTE simples: o maior numero da afirmacao (o valor
    monetario domina os numeros de contexto — artigo, folha, percentual), ou a
    competencia `YYYY-MM` se houver. Quando nao ha numero, devolve a afirmacao
    e o shared cai no ramo de fundamentacao (sentencas vizinhas).

    Quem tem o `DocumentoIndexado` na mao gera distractors melhores — por isso
    o request aceita `distractors` prontos e este caminho e so o default.
    """
    comp = re.search(r"\b(\d{4})-(\d{2})\b", afirmacao)
    if comp:
        return comp.group(0)
    melhor: Optional[float] = None
    for tok in _NUM_LITERAL_RE.findall(afirmacao):
        limpo = tok.strip(".,")
        if len(re.sub(r"[^0-9]", "", limpo)) < 2:
            continue
        try:
            num = float(limpo.replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if melhor is None or num > melhor:
            melhor = num
    return melhor if melhor is not None else afirmacao


__all__ = ["DEFAULT_MODEL", "verificar_par"]
