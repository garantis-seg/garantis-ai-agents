"""O LEITOR — um documento inteiro, uma missão estreita, citação por ID.

ONDA 4 do desenho do Agente Investigador (DESENHO-INVESTIGADOR-2026-08-13, §2,
§2.2, §5.3, §8.3). O papel de janela ISOLADA: recebe o `DocumentoIndexado`
inteiro daquele documento e **nada mais** — nada do grafo, nada dos outros
documentos, nada da rodada anterior. Devolve um envelope ≤2K tokens em que toda
afirmação carrega `[sid]`.

## As três coisas que este módulo garante

**1. Nunca lê outro documento em silêncio.** O `doc_hash` do request é conferido
contra o do documento carregado, e divergência é `documento_mudou` — erro
tipado, não um aviso. Esse é o modo de falha caro do §1.6: uma resposta
perfeitamente plausível sobre o acórdão errado é indistinguível de uma resposta
certa até alguém conferir a folha.

**2. Nunca deixa passar envelope sem confiança em CAMPO.** O §5.3 é o coração da
lição: `confianca` e `objeto_da_confianca` são obrigatórios, e o segundo tem que
ser uma proposição LITERAL — *"de que este é o IRPJ principal mantido, e não o
consolidado"*, nunca *"alta"*. Envelope sem os dois vai a retry uma vez e depois
vira erro tipado. **Nunca passa adiante**, porque confiança em prosa é
*confidence laundering* (§2.7 da pesquisa): ruído com aparência de rigor.

**3. Nunca deixa passar citação inventada.** Todo `sid` devolvido é conferido
contra o `_por_sid` do documento — lookup O(1), o que a onda 1 comprou. Um ID
que não existe é citação forjada, e o gate rejeita antes de a resposta virar
âncora de célula.

## Por que a validação é aqui, e não no prompt

Prompt não é enforcement. É a doutrina que já pôs a regra do junho e o banimento
do fato gerador em código (`harness.py:22-31`), e vale igual aqui: o prompt
**pede** os campos e os IDs; quem os **exige** é este módulo, com retry e erro
tipado. A taxa de tags válidas medida do formato XML do sui-1 é 95,2% — os 4,8%
restantes são exatamente o que a validação existe para pegar.

## O retry é UM, e ele muda o prompt

Retry cego repetindo o mesmo prompt é o modo de falha nº 1 dos agentes (§4.11:
*"o agente repetindo a mesma chamada que falha"*). A segunda tentativa vai com
um bloco de correção que nomeia o que faltou, e é só uma: se o modelo não
obedeceu com a falha apontada na cara, insistir é queimar token contra a mesma
parede.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, Optional

from garantis_shared.calculo_fichas.documento import (
    DocumentoIndexado,
    DocumentoInvalidoError,
)

from ...providers import create_provider
from ...providers.base import LLMResponse
from ...utils.llm_json import parse_llm_json
from . import prompts as P
from .cache import (
    NAMESPACE_PERGUNTAR,
    NAMESPACE_RESUMIR,
    cache_get,
    cache_put,
    chave_leitor,
)
from .schemas import (
    EvidenciaResumo,
    PerguntarRequest,
    PerguntarResponse,
    ResumirRequest,
    ResumirResponse,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ERRO_CITACAO_INEXISTENTE",
    "ERRO_DOC_INVALIDO",
    "ERRO_DOC_MUDOU",
    "ERRO_ENVELOPE_SEM_CONFIANCA",
    "ERRO_PARSE",
    "ERRO_SEM_CITACAO",
    "PAPEL_LEITOR",
    "modelo_leitor",
    "perguntar",
    "resumir",
]

#: Papel do ROLES (§8.4). O desenho propõe `ficha_leitor → gemini-3.1-flash-lite`
#: — volume alto, resposta curta, e `cached`=0,025 faz o context caching pagar
#: muito bem em doc-QA repetido. Mas **trocar modelo de papel é decisão do
#: Elton** (memory `engine-owns-model-control`) e `ficha_leitor` ainda não existe
#: no catálogo; a proposta formal de ROLES é a onda 12. Enquanto isso,
#: `leitor_autos_monolith` é o papel já registrado que faz **esta mesma coisa** —
#: ler documento processual longo e devolver extração citada — e resolve para o
#: mesmo `gemini-3.1-flash-lite` que o desenho propõe. Apontar para ele é o
#: mesmo modelo com uma decisão a menos tomada por conta própria, exatamente
#: como o `doc_indexer` fez com `vision_fallback`.
PAPEL_LEITOR = "leitor_autos_monolith"

#: Env override, no padrão da casa (env específica → papel do ROLES). O desenho
#: (§8.4) nomeia `DOC_READER_MODEL`.
_ENV_MODELO = "DOC_READER_MODEL"

#: Tetos de saída do §2.2, em tokens, convertidos para o `max_tokens` do
#: provider com folga: o teto do contrato é sobre o que o Leitor **deve**
#: escrever, e cortar a geração no meio produziria JSON truncado — que o parser
#: tolerante remendaria em silêncio, perdendo a última citação. Melhor deixar
#: espaço e cobrar o tamanho no prompt.
MAX_TOKENS_PERGUNTAR = 4096
MAX_TOKENS_RESUMIR = 8192

#: Motivos de falha — enum FECHADO, mesma doutrina de `Rejeicao.codigo` e de
#: `Ancora.valida_contra`: o QA agrega por eles, e prosa não vira métrica.
ERRO_DOC_MUDOU = "documento_mudou"
ERRO_DOC_INVALIDO = "documento_indexado_invalido"
ERRO_PARSE = "parse_do_json_do_leitor_falhou"
ERRO_ENVELOPE_SEM_CONFIANCA = "envelope_sem_objeto_da_confianca"
ERRO_CITACAO_INEXISTENTE = "citacao_de_sid_inexistente"
ERRO_SEM_CITACAO = "afirmacao_sem_citacao"

#: O N de self-consistency que esta onda de fato roda. Ver `_n_dinco`: o campo
#: viaja no envelope desde já, a chamada N-vezes é a onda 7.
N_DINCO_EFETIVO = 1

#: Quantas vezes se tenta de novo depois de um envelope reprovado. UM: o retry
#: leva a falha nomeada no prompt, e se o modelo não obedecer com o erro na cara
#: dele, repetir é queimar token contra a mesma parede (§4.11).
MAX_RETRY = 1

#: Comprimento mínimo de um `objeto_da_confianca` que não seja rótulo. "alta",
#: "boa", "do IRPJ" têm menos que isso; a proposição literal que o §5.3 exige —
#: *"de que este é o valor do IRPJ principal mantido, e não do consolidado"* —
#: tem muito mais. É um piso grosseiro de propósito: o gate fino é a lista de
#: rótulos abaixo, e um piso alto demais rejeitaria objeto legítimo e curto.
MIN_OBJETO_CONFIANCA = 20

#: Rótulos que o modelo devolve quando ignorou a instrução e escreveu o TEMA em
#: vez da PROPOSIÇÃO. São exatamente os exemplos que o prompt lista como
#: rejeitados, e existem aqui porque prompt não é enforcement.
_OBJETOS_REJEITADOS = frozenset({
    "alta", "media", "média", "baixa", "boa", "alto", "baixo",
    "da resposta", "do resumo", "da leitura", "resposta", "resumo",
    "confianca", "confiança", "confianca alta", "confiança alta",
    "n/a", "na", "none", "null", "-",
})

#: O que separa duas afirmações, para efeito do gate de citação: `.`/`;`/`!`/`?`
#: seguido de espaço ou de fim de texto.
#:
#: ⚑ O `(?<!\d)` NÃO é adorno — é a regra 3 do §1.5 aplicada aqui. Sem ele,
#: `R$ 723.810.827,57` vira três "afirmações", as duas primeiras sem `[sid]`, e
#: o gate reprovaria justamente a resposta bem citada que traz um valor — o
#: caso que este agente existe para produzir. O ponto entre dígitos nunca
#: separa afirmação.
#:
#: Continua mais grosseiro que o segmentador do shared, de propósito: aqui não
#: se indexa documento jurídico, confere-se se a prosa CURTA de um envelope tem
#: ID. A lista de abreviações PT-BR (`art.`, `fls.`, `inc.`) pertence ao
#: segmentador; o efeito dela aqui seria no máximo partir uma frase em duas, e
#: as duas metades carregariam o mesmo `[sid]` do fim — que é o que o gate quer.
_SEPARADOR_DE_FRASE_RE = re.compile(r"(?<!\d)[.;!?]+(?:\s+|$)")


def modelo_leitor() -> str:
    """O modelo do Leitor: env específica → ROLES. **Nunca** hard-code.

    `model_for` levanta `KeyError` para papel inexistente, de propósito — papel
    desconhecido é bug de chamada, não um default silencioso. Diferente do OCR
    (onde o documento ainda sai nativo se o modelo faltar), aqui não há caminho
    degradado: sem modelo não há leitura, e a exceção sobe para virar
    `success=false` no envelope.
    """
    env = os.getenv(_ENV_MODELO)
    if env:
        return env
    from garantis_shared.llm_models import model_for

    return model_for(PAPEL_LEITOR)


# ── as duas ferramentas ─────────────────────────────────────────────────────

async def perguntar(
    request: PerguntarRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> PerguntarResponse:
    """`perguntar_ao_documento` (§2.2) — pergunta pontual, resposta ≤400 tokens.

    Nunca levanta: falha vira `success=false` + `error` tipado, com o custo já
    gasto propagado. É o contrato do resto do repo — erro barato não atravessa a
    rede de novo como exceção, e o Investigador transforma isso em rejeição de
    rodada.

    `encontrou=False` com `lacuna` é **sucesso**: é a resposta legítima e barata
    que o §2.2 exige, e tratá-la como falha faria o Investigador insistir num
    documento que comprovadamente não tem o dado.
    """
    if isinstance(request, dict):
        request = PerguntarRequest(**request)

    doc, erro = _carregar_documento(request.documento_indexado, request.doc_hash, request.doc_id)
    if erro is not None:
        return PerguntarResponse(success=False, error=erro)
    assert doc is not None

    n_dinco = _n_dinco(request.n_dinco)
    modelo = model or request.model or modelo_leitor()
    chave = chave_leitor(
        namespace=NAMESPACE_PERGUNTAR,
        doc_hash=doc.doc_hash,
        extractor_version=doc.extractor_version,
        pergunta=request.pergunta,
        prompt_version=P.prompt_version_hash(),
        model=modelo,
        n_dinco=n_dinco,
    )
    em_cache = cache_get(chave)
    if em_cache is not None:
        return PerguntarResponse(**{**em_cache, "cache_hit": True})

    resposta = await _rodar(
        prompt_base=P.build_perguntar_prompt(doc, request.pergunta),
        validar=lambda parsed: _validar_perguntar(parsed, doc),
        provider=provider or request.provider,
        model=modelo,
        max_tokens=MAX_TOKENS_PERGUNTAR,
    )
    envelope, erro, custo, modelo_usado = resposta

    if erro is not None:
        return PerguntarResponse(
            success=False, error=erro, cost_usd=custo, model=modelo_usado,
            self_consistency_n=n_dinco,
        )
    assert envelope is not None

    out = PerguntarResponse(
        success=True,
        resposta=envelope["resposta"],
        citacoes=envelope["citacoes"],
        confianca=envelope["confianca"],
        objeto_da_confianca=envelope["objeto_da_confianca"],
        encontrou=envelope["encontrou"],
        lacuna=envelope["lacuna"],
        cache_hit=False,
        self_consistency_n=n_dinco,
        model=modelo_usado,
        cost_usd=custo,
    )
    # Só SUCESSO vai ao cache, e com os voláteis do §7.4 zerados: `cache_hit` e
    # `cost_usd` descrevem ESTA leitura, não a entrada. Guardar o custo da
    # geração faria cada hit refaturá-lo no ledger, inflando o gasto da ficha
    # com dinheiro que ninguém gastou — o espelho do bug de custo zerado, e tão
    # ruim quanto: um ledger que mente para cima também deixa de ser medida.
    cache_put(chave, {**out.model_dump(), "cache_hit": False, "cost_usd": 0.0})
    return out


async def resumir(
    request: ResumirRequest | dict,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> ResumirResponse:
    """`resumir_com_missao` (§2.2) — missão ampla, resumo ≤2000 tokens.

    É a ferramenta de PRIMEIRA passada num documento colossal: o Investigador
    chama esta **antes** de perguntar, para saber o que perguntar. Por isso o
    teto é 5x o da pergunta — o produto é um mapa do documento, e um mapa
    apertado demais faz a próxima pergunta cair no lugar errado.
    """
    if isinstance(request, dict):
        request = ResumirRequest(**request)

    doc, erro = _carregar_documento(request.documento_indexado, request.doc_hash, request.doc_id)
    if erro is not None:
        return ResumirResponse(success=False, error=erro)
    assert doc is not None

    n_dinco = _n_dinco(request.n_dinco)
    modelo = model or request.model or modelo_leitor()
    chave = chave_leitor(
        namespace=NAMESPACE_RESUMIR,
        doc_hash=doc.doc_hash,
        extractor_version=doc.extractor_version,
        pergunta=request.missao,
        prompt_version=P.prompt_version_hash(),
        model=modelo,
        n_dinco=n_dinco,
    )
    em_cache = cache_get(chave)
    if em_cache is not None:
        return ResumirResponse(**{**em_cache, "cache_hit": True})

    envelope, erro, custo, modelo_usado = await _rodar(
        prompt_base=P.build_resumir_prompt(doc, request.missao),
        validar=lambda parsed: _validar_resumir(parsed, doc),
        provider=provider or request.provider,
        model=modelo,
        max_tokens=MAX_TOKENS_RESUMIR,
    )

    if erro is not None:
        return ResumirResponse(
            success=False, error=erro, cost_usd=custo, model=modelo_usado,
            self_consistency_n=n_dinco,
        )
    assert envelope is not None

    out = ResumirResponse(
        success=True,
        resumo=envelope["resumo"],
        evidencias=envelope["evidencias"],
        confianca=envelope["confianca"],
        objeto_da_confianca=envelope["objeto_da_confianca"],
        cobertura=envelope["cobertura"],
        lacunas=envelope["lacunas"],
        cache_hit=False,
        self_consistency_n=n_dinco,
        model=modelo_usado,
        cost_usd=custo,
    )
    cache_put(chave, {**out.model_dump(), "cache_hit": False, "cost_usd": 0.0})
    return out


# ── o laço de chamada, com o retry que NOMEIA a falha ───────────────────────

async def _rodar(
    *,
    prompt_base: str,
    validar,
    provider: Optional[str],
    model: str,
    max_tokens: int,
) -> tuple[Optional[dict[str, Any]], Optional[str], float, Optional[str]]:
    """Chama o modelo, valida, e tenta UMA vez de novo nomeando o que faltou.

    Devolve `(envelope, erro, custo_acumulado, modelo_usado)`. O custo é
    **acumulado** entre as tentativas de propósito: as duas chamadas
    aconteceram e as duas foram faturadas, e um ledger que só registra a última
    é o mesmo mecanismo que já escondeu US$ 97,61 em 39.309 calls.
    """
    llm = create_provider(provider or os.getenv("DEFAULT_PROVIDER", "gemini"))

    custo_total = 0.0
    modelo_usado: Optional[str] = None
    ultimo_erro = ERRO_PARSE
    prompt = prompt_base

    for tentativa in range(MAX_RETRY + 1):
        try:
            resp: LLMResponse = await llm.agenerate(
                prompt=prompt,
                model=model,
                temperature=0.0,
                response_mime_type="application/json",
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 — falha de rede vira envelope
            logger.warning("DOC_READER_LLM_FAIL (tentativa %d): %r", tentativa + 1, exc)
            return None, f"chamada ao modelo falhou: {exc}", custo_total, modelo_usado

        modelo_usado = resp.model or model
        custo_total += float(
            (resp.metadata or {}).get("cost_usd", 0.0) if resp.metadata else 0.0
        )

        try:
            parsed = parse_llm_json(resp.text or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DOC_READER_PARSE_FAIL (tentativa %d): %r | head=%r",
                tentativa + 1, exc, (resp.text or "")[:200],
            )
            ultimo_erro = ERRO_PARSE
            prompt = _prompt_com_correcao(prompt_base, ultimo_erro, str(exc))
            continue

        envelope, erro, detalhe = validar(parsed)
        if erro is None:
            return envelope, None, custo_total, modelo_usado

        logger.info(
            "DOC_READER_ENVELOPE_REPROVADO (tentativa %d): %s | %s",
            tentativa + 1, erro, detalhe,
        )
        ultimo_erro = erro
        prompt = _prompt_com_correcao(prompt_base, erro, detalhe)

    return None, ultimo_erro, custo_total, modelo_usado


def _prompt_com_correcao(prompt_base: str, erro: str, detalhe: str) -> str:
    """O prompt do retry: o original + o que exatamente foi reprovado.

    Reenviar o prompt idêntico é o anti-padrão do §4.11 — o modelo não tem por
    que acertar na segunda o que errou na primeira sem nenhum sinal novo. O
    bloco vai no FIM, como *recency anchor*, pelo mesmo motivo que as regras
    duras vão por último no prompt do calculador.
    """
    return (
        f"{prompt_base}\n\n"
        f"<correcao_obrigatoria>\n"
        f"Sua resposta anterior foi REPROVADA por: {erro}\n"
        f"Detalhe: {detalhe}\n\n"
        f"Corrija exatamente isso e devolva o JSON completo de novo. Nao explique "
        f"a correcao, nao peca desculpa: devolva so o objeto JSON corrigido.\n"
        f"</correcao_obrigatoria>"
    )


# ── validação de envelope ───────────────────────────────────────────────────

def _validar_confianca(parsed: dict) -> tuple[Optional[tuple[float, str]], Optional[str], str]:
    """`confianca` + `objeto_da_confianca`, os dois OBRIGATÓRIOS (§5.3).

    Este é o gate que o §9.1 nomeia (`test_envelope_confianca.py`: *"envelope sem
    `objeto_da_confianca` → rejeitado. Confiança em prosa → rejeitada"*), e é o
    que impede o *confidence laundering*: um número sem o objeto dele é ruído
    com aparência de rigor, porque *"85% confiante de que li o número certo"* e
    *"85% confiante de que este é o número que se pediu"* são afirmações
    diferentes e multiplicá-las não significa nada (arXiv:2604.23505).
    """
    if "confianca" not in parsed:
        return None, ERRO_ENVELOPE_SEM_CONFIANCA, "campo `confianca` ausente"

    bruta = parsed.get("confianca")
    if isinstance(bruta, bool) or not isinstance(bruta, (int, float)):
        return None, ERRO_ENVELOPE_SEM_CONFIANCA, (
            f"`confianca` tem que ser numero entre 0 e 1, veio {type(bruta).__name__}"
        )
    conf = float(bruta)
    if not math.isfinite(conf) or not (0.0 <= conf <= 1.0):
        return None, ERRO_ENVELOPE_SEM_CONFIANCA, (
            f"`confianca` fora de [0,1]: {bruta!r}"
        )

    objeto = parsed.get("objeto_da_confianca")
    if not isinstance(objeto, str) or not objeto.strip():
        return None, ERRO_ENVELOPE_SEM_CONFIANCA, (
            "`objeto_da_confianca` ausente ou vazio — a confianca viaja em CAMPO, "
            "com a proposicao LITERAL de que voce esta confiante"
        )
    objeto = objeto.strip()
    if objeto.lower().rstrip(".") in _OBJETOS_REJEITADOS or len(objeto) < MIN_OBJETO_CONFIANCA:
        return None, ERRO_ENVELOPE_SEM_CONFIANCA, (
            f"`objeto_da_confianca` = {objeto!r} e um ROTULO, nao uma proposicao. "
            "Escreva a afirmacao literal: 'de que este e o valor do IRPJ principal "
            "mantido, e nao do consolidado'"
        )
    return (conf, objeto), None, ""


def _validar_citacoes(
    brutas: Any, doc: DocumentoIndexado, campo: str
) -> tuple[Optional[list[str]], Optional[str], str]:
    """Cada `sid` tem que existir NESTE documento. Lookup O(1) — o que a onda 1 comprou.

    Aceita objeto `{"sid": …}` além da string porque o modelo às vezes devolve a
    forma rica mesmo quando o schema pede só o ID; extrair o `sid` de um dict é
    tolerância barata, e o que importa — que o ID exista de verdade — é
    conferido igual nos dois casos.
    """
    if brutas is None:
        brutas = []
    if not isinstance(brutas, list):
        return None, ERRO_CITACAO_INEXISTENTE, (
            f"`{campo}` deveria ser lista de IDs, veio {type(brutas).__name__}"
        )

    out: list[str] = []
    vistos: set[str] = set()
    for i, bruto in enumerate(brutas):
        sid = bruto.get("sid") if isinstance(bruto, dict) else bruto
        if not isinstance(sid, str) or not P.SID_RE.match(sid.strip()):
            return None, ERRO_CITACAO_INEXISTENTE, (
                f"`{campo}`[{i}] = {bruto!r} nao tem a forma de um id de sentenca "
                "(esperado 'fl<folha>-s<n>')"
            )
        sid = sid.strip()
        if doc.sentenca(sid) is None:
            return None, ERRO_CITACAO_INEXISTENTE, (
                f"`{campo}`[{i}] = {sid!r} nao existe neste documento. Cite so os "
                "IDs que aparecem como tag no texto que voce recebeu"
            )
        if sid not in vistos:
            vistos.add(sid)
            out.append(sid)
    return out, None, ""


def _afirmacoes_sem_sid(texto: str) -> list[str]:
    """As frases da prosa que não terminam apoiadas num `[sid]` (§2.2, regra 1).

    Uma frase "carrega" o ID se ele aparece nela. Frases curtas demais (um
    fragmento de 15 chars sobrando de uma quebra) não contam: o gate quer pegar
    afirmação sem fonte, não punir pontuação. E a última frase pode legitimamente
    não ter ID quando é uma ressalva sobre a própria leitura — mas isso não a
    isenta, porque uma ressalva sem fonte também é uma afirmação sobre o
    documento.
    """
    faltando: list[str] = []
    for bruta in _SEPARADOR_DE_FRASE_RE.split(texto or ""):
        frase = bruta.strip()
        if len(frase) < 25:
            continue
        if not P.sids_citados_no_texto(frase):
            faltando.append(frase)
    return faltando


def _validar_perguntar(
    parsed: dict, doc: DocumentoIndexado
) -> tuple[Optional[dict[str, Any]], Optional[str], str]:
    """O envelope de `perguntar_ao_documento`. `(envelope, erro, detalhe)`."""
    conf_par, erro, detalhe = _validar_confianca(parsed)
    if erro is not None:
        return None, erro, detalhe
    assert conf_par is not None
    confianca, objeto = conf_par

    resposta = str(parsed.get("resposta") or "").strip()
    encontrou = bool(parsed.get("encontrou"))
    lacuna_bruta = parsed.get("lacuna")
    lacuna = str(lacuna_bruta).strip() if isinstance(lacuna_bruta, str) and lacuna_bruta.strip() else None

    citacoes, erro, detalhe = _validar_citacoes(parsed.get("citacoes"), doc, "citacoes")
    if erro is not None:
        return None, erro, detalhe
    assert citacoes is not None

    if not encontrou:
        # `encontrou=false` é resposta LEGÍTIMA (§2.2) — mas só com a lacuna
        # nomeada. Sem ela o Investigador recebe "não achei" sem saber se deve
        # perguntar de outro jeito, procurar em outro documento, ou desistir; e
        # essa é justamente a prosa vaga que o contrato proíbe.
        if not lacuna:
            return None, ERRO_SEM_CITACAO, (
                "`encontrou` e false mas `lacuna` esta vazia — diga O QUE "
                "especificamente faltou no documento"
            )
        return {
            "resposta": resposta, "citacoes": citacoes, "confianca": confianca,
            "objeto_da_confianca": objeto, "encontrou": False, "lacuna": lacuna,
        }, None, ""

    if not resposta:
        return None, ERRO_SEM_CITACAO, "`encontrou` e true mas `resposta` esta vazia"
    if not citacoes:
        return None, ERRO_SEM_CITACAO, (
            "`encontrou` e true mas `citacoes` esta vazia — toda afirmacao carrega [sid]"
        )

    orfas = _afirmacoes_sem_sid(resposta)
    if orfas:
        return None, ERRO_SEM_CITACAO, (
            f"{len(orfas)} afirmacao(oes) da resposta sem [sid]: {orfas[0]!r}"
        )

    # Os IDs escritos na prosa também são citação, e também podem ser
    # inventados — validá-los só na lista `citacoes` deixaria a porta aberta
    # pela prosa, que é justamente o texto que o humano lê na ficha.
    na_prosa, erro, detalhe = _validar_citacoes(
        P.sids_citados_no_texto(resposta), doc, "resposta"
    )
    if erro is not None:
        return None, erro, detalhe
    assert na_prosa is not None

    # A lista consolidada é a união: o modelo às vezes cita na prosa e esquece
    # de listar (ou o contrário). Perder a citação por causa disso jogaria fora
    # uma âncora legítima que o gate G1 usaria.
    consolidadas = citacoes + [s for s in na_prosa if s not in set(citacoes)]

    return {
        "resposta": resposta, "citacoes": consolidadas, "confianca": confianca,
        "objeto_da_confianca": objeto, "encontrou": True, "lacuna": lacuna,
    }, None, ""


def _validar_resumir(
    parsed: dict, doc: DocumentoIndexado
) -> tuple[Optional[dict[str, Any]], Optional[str], str]:
    """O envelope de `resumir_com_missao`. `(envelope, erro, detalhe)`."""
    conf_par, erro, detalhe = _validar_confianca(parsed)
    if erro is not None:
        return None, erro, detalhe
    assert conf_par is not None
    confianca, objeto = conf_par

    resumo = str(parsed.get("resumo") or "").strip()
    if not resumo:
        return None, ERRO_SEM_CITACAO, "`resumo` vazio"

    sids, erro, detalhe = _validar_citacoes(parsed.get("evidencias"), doc, "evidencias")
    if erro is not None:
        return None, erro, detalhe
    assert sids is not None

    orfas = _afirmacoes_sem_sid(resumo)
    if orfas:
        return None, ERRO_SEM_CITACAO, (
            f"{len(orfas)} afirmacao(oes) do resumo sem [sid]: {orfas[0]!r}"
        )

    na_prosa, erro, detalhe = _validar_citacoes(
        P.sids_citados_no_texto(resumo), doc, "resumo"
    )
    if erro is not None:
        return None, erro, detalhe
    assert na_prosa is not None

    consolidados = sids + [s for s in na_prosa if s not in set(sids)]
    if not consolidados:
        return None, ERRO_SEM_CITACAO, (
            "resumo sem nenhuma evidencia — toda afirmacao carrega [sid]"
        )

    # A `pagina` sai do CÓDIGO, não do modelo (§6.2): ele devolve o ID e o resto
    # é lookup determinístico. Mata a classe "citou a folha errada para o trecho
    # certo", que é indetectável na leitura porque as duas coisas são plausíveis.
    evidencias = [
        EvidenciaResumo(sid=sid, pagina=doc.sentenca(sid).pagina)  # type: ignore[union-attr]
        for sid in consolidados
    ]

    lacunas = [
        str(x).strip() for x in (parsed.get("lacunas") or [])
        if isinstance(x, (str, int, float)) and str(x).strip()
    ]

    return {
        "resumo": resumo, "evidencias": evidencias, "confianca": confianca,
        "objeto_da_confianca": objeto, "cobertura": _cobertura(parsed.get("cobertura")),
        "lacunas": lacunas,
    }, None, ""


def _cobertura(bruta: Any) -> float:
    """`cobertura` em [0,1]. Fora disso vira 0.0 — declarar 0 é honesto.

    Diferente da `confianca`, cobertura malformada **não** reprova o envelope:
    ela é telemetria de quanto do documento foi considerado, não uma afirmação
    sobre o conteúdo, e perder um resumo inteiro e bem citado porque o modelo
    escreveu `"alta"` num campo de métrica seria trocar o valioso pelo acessório.
    """
    if isinstance(bruta, bool) or not isinstance(bruta, (int, float)):
        return 0.0
    v = float(bruta)
    if not math.isfinite(v):
        return 0.0
    return min(1.0, max(0.0, v))


# ── entrada: o documento e o hash ───────────────────────────────────────────

def _carregar_documento(
    payload: dict[str, Any], doc_hash: str, doc_id: str
) -> tuple[Optional[DocumentoIndexado], Optional[str]]:
    """Desserializa e **confere o hash**. `(doc, None)` ou `(None, erro_tipado)`.

    A conferência é o §1.6 aplicado ao Leitor: ler outro documento em silêncio é
    o modo de falha caro, porque uma resposta plausível sobre o acórdão errado é
    indistinguível de uma resposta certa até alguém abrir a folha. Confere-se
    também o `doc_id`: hash igual com id diferente significaria que o mesmo PDF
    entrou no dossiê por dois caminhos, e responder por um quando se perguntou
    do outro embaralharia a proveniência da célula.
    """
    if not isinstance(payload, dict) or not payload:
        return None, ERRO_DOC_INVALIDO

    try:
        doc = DocumentoIndexado.from_dict(payload)
    except (DocumentoInvalidoError, KeyError, TypeError, ValueError) as exc:
        logger.warning("[doc_reader] %s: documento invalido: %r", doc_id, exc)
        return None, ERRO_DOC_INVALIDO

    if doc.doc_hash != doc_hash:
        logger.warning(
            "[doc_reader] %s: hash divergente (pedido=%s, documento=%s)",
            doc_id, str(doc_hash)[:12], doc.doc_hash[:12],
        )
        return None, ERRO_DOC_MUDOU
    if doc.doc_id != doc_id:
        logger.warning(
            "[doc_reader] doc_id divergente (pedido=%s, documento=%s)", doc_id, doc.doc_id
        )
        return None, ERRO_DOC_MUDOU
    if not doc.sentencas:
        return None, ERRO_DOC_INVALIDO
    return doc, None


def _n_dinco(bruto: Optional[int]) -> int:
    """O N efetivo desta onda. Aceita o campo, devolve o que de fato rodou.

    O campo **viaja** desde já (o envelope o declara como `self_consistency_n`)
    porque mudar o shape do envelope depois é o que quebra o consumidor — mesma
    razão pela qual o `doc_indexer` já devolve `cache_hit` sem ter cache. Mas a
    chamada N-vezes em si é a onda 7: o normalizador DINCO vive no shared
    (`confianca.py`) e é ele que sabe gerar os distractors e normalizar os
    votos. Fazer aqui uma média de N chamadas seria inventar um segundo
    normalizador — e o §5.2 é explícito em que quorum-N puro é caro, pior, e em
    problema difícil pode PIORAR (arXiv:2608.11403).

    Por isso o N efetivo é 1 **sempre**, inclusive quando o request pede 10, e é
    reportado como 1: declarar 3 quando rodou 1 seria mentir exatamente no campo
    que o §5.2 manda gravar para permitir a recalibração depois. Quando a onda 7
    entrar, é esta função que passa a devolver o N de verdade — o envelope e os
    callers não mudam.
    """
    return N_DINCO_EFETIVO
