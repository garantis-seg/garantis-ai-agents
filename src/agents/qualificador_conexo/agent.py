"""QUALIFICADOR DO CONEXO (S2c) — é fiscal? e qual o estado de cada garantia?

Plano de 21/10/2026, Parte 3, S2c. Card 869ffv22t.

O agente é um investigador em 2 fases, no molde do Investigador do C4
(`calculo_ficha.investigador`):

- Fase A (decisão): sem schema. O LLM escolhe UMA ferramenta por turno. O
  código executa a ferramenta, conta o budget e abre o circuit breaker.
- Fase B (emissão): JSON. O LLM emite a resposta fechada. O código valida a
  resposta com as regras duras. Erro volta ao LLM como `{campo, erro,
  valor_anterior}`, por até 2 rodadas de correção. Depois disso, a rota
  devolve HTTP 422 com os mesmos erros.

Regras duras (no código, não no prompt):

1. `e_fiscal=false` exige `prova` com `doc_id` do índice.
2. `estado` substituida ou liberada exige `prova` com `doc_id` do índice.
3. `sem_evidencia` exige `documentos_lidos` não vazio, e cada doc_id da lista
   foi lido de fato na fase A. O agente tem de ler antes de desistir.
4. Todo alerta de entrada tem UMA resposta. Alerta `refutado` exige prova.
5. Toda prova tem `doc_id` do índice e `pagina` do documento. Com o documento
   legível, o `trecho` tem de estar na página citada (comparação sem acento,
   sem caixa e sem espaço repetido).

Exceção das regras 1, 2 e 4 (modo capa): o item não tem documento para citar.
Ver `_modo_capa_do_processo`.

`sem_evidencia` não exige `prova`: a falta de prova é o próprio estado.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Optional

from garantis_shared.llm_models import model_for
from pydantic import ValidationError

from ...providers import create_provider
from ...utils.llm_json import parse_llm_json
from .._utils.llm_seed import seed_for
from .._utils.prompt_identity import versao_com_identidade
from . import auditor as auditor_mod
from .ferramentas import BudgetConexo, CircuitBreaker, menu, parse_chamada
from .prompts import (
    PROMPT_VERSION,
    build_decisao_prompt,
    build_emissao_prompt,
    dados_do_conexo,
)
from .schemas import (
    AlertaRespondido,
    Divergencia,
    ErroCampo,
    GarantiaQualificada,
    ProcessoQualificado,
    QualificacaoInvalidaBody,
    QualificacaoLLM,
    QualificarConexoRequest,
    QualificarConexoResponse,
)

logger = logging.getLogger(__name__)

#: 22/10/2026: papéis provisórios; pedido ao Elton de `ficha_qualificador` e
#: `ficha_auditor_qualificacao` no registro (card 869ffv22t). O auditor usa
#: `ficha_auditoria_evidencias`, de família diferente (regra anti-conluio).
DEFAULT_MODEL = model_for("ficha_calculo")

#: Rodadas de correção da fase B, depois da 1ª emissão (pedido de 22/10/2026).
RODADAS_DE_CORRECAO = 2

#: Turnos seguidos sem chamada legível antes de encerrar a fase A.
_MAX_FALHAS_DE_PROTOCOLO = 3

#: Trechos literais por resposta de Leitor. O resto fica no Leitor.
_MAX_TRECHOS_POR_LEITURA = 8

#: Caracteres de uma página crua devolvida ao agente.
_MAX_CHARS_PAGINA = 6000

_AQUI = Path(__file__).resolve().parent


def prompt_version() -> str:
    """`qualificador_conexo_v1+<hash>`. O hash muda quando o prompt ou o schema muda."""
    return versao_com_identidade(
        PROMPT_VERSION, str(_AQUI / "prompts.py"), str(_AQUI / "schemas.py"),
    )


class QualificacaoInvalidaError(Exception):
    """A emissão falhou nas regras duras depois das rodadas de correção."""

    def __init__(self, body: QualificacaoInvalidaBody):
        super().__init__(f"{len(body.erros)} erro(s) na qualificação")
        self.body = body


# ── Ponto de entrada ────────────────────────────────────────────────────────


async def qualificar_conexo(
    request: QualificarConexoRequest | dict,
    leitor_perguntar: Optional[Callable] = None,
    leitor_resumir: Optional[Callable] = None,
) -> QualificarConexoResponse:
    """Roda as fases A e B e, com `auditar`, o auditor.

    Levanta `QualificacaoInvalidaError` quando a emissão não passa nas regras
    duras. `leitor_*` são injetáveis para o teste. O default é o `doc_reader`.
    """
    if isinstance(request, dict):
        request = QualificarConexoRequest(**request)

    llm = create_provider("gemini")
    pv = prompt_version()
    ctx = _Contexto.montar(request)
    custo = 0.0
    chamadas_llm = 0

    # ── Fase A — decisão ────────────────────────────────────────────────────
    budget = BudgetConexo()
    breaker = CircuitBreaker()
    achados: list[dict[str, Any]] = []
    budget_esgotado = False
    if not ctx.modo_capa:
        perguntar = leitor_perguntar or _perguntar_via_doc_reader
        resumir = leitor_resumir or _resumir_via_doc_reader
        falhas_protocolo = 0
        turno = 0
        while True:
            if budget.esgotado():
                budget_esgotado = True
                logger.warning("QUALIFICADOR_BUDGET conexo=%s", request.conexo_id)
                break
            turno += 1
            resp = await llm.agenerate(
                prompt=build_decisao_prompt(
                    dados=ctx.dados, achados=achados, menu=menu(breaker),
                    budget_restante=budget.restante(),
                    budget_por_item=budget.max_por_item,
                ),
                model=DEFAULT_MODEL,
                temperature=0.0,
                max_tokens=2048,
                seed=seed_for("qualificador_conexo", request.conexo_id, "A", turno),
            )
            chamadas_llm += 1
            custo += _custo(resp)

            chamada = parse_chamada(resp.text or "")
            if chamada is None:
                falhas_protocolo += 1
                achados.append({"erro": "resposta sem chamada JSON válida. Responda um JSON só."})
                if falhas_protocolo >= _MAX_FALHAS_DE_PROTOCOLO:
                    break
                continue
            falhas_protocolo = 0
            if chamada.get("fim"):
                break

            budget.chamadas += 1
            tool, args = chamada["tool"], chamada["args"]
            doc_id = str(args.get("doc_id") or "")
            item = str(args.get("item") or "")
            if item not in ctx.itens:
                achados.append({"tool": tool, "args": args, "erro": (
                    "args.item tem de ser o número de um processo ou o id de uma garantia"
                )})
                continue
            if budget.item_esgotado(item):
                achados.append({"tool": tool, "args": args, "erro": (
                    f"teto de {budget.max_por_item} chamadas do item {item} atingido"
                )})
                continue
            budget.por_item[item] = budget.por_item.get(item, 0) + 1
            if not breaker.disponivel(tool, doc_id):
                achados.append({"tool": tool, "args": args, "erro": (
                    "circuito aberto para esta ferramenta neste documento (3 falhas)"
                )})
                continue

            resultado, ok = await _executar(tool, args, ctx, budget, perguntar, resumir)
            custo += float(resultado.pop("_cost_usd", 0.0) or 0.0)
            achados.append({"tool": tool, "args": args, **resultado})
            if ok:
                breaker.registrar_sucesso(tool, doc_id)
                ctx.lidos.add(doc_id)
            elif breaker.registrar_falha(tool, doc_id):
                achados.append({"tool": tool, "doc_id": doc_id, "nota": (
                    "ferramenta fora do menu deste documento (circuit breaker)"
                )})

    # ── Fase B — emissão com validação ──────────────────────────────────────
    erros: list[dict[str, Any]] = []
    qualificacao: Optional[QualificacaoLLM] = None
    rodadas = 0
    for rodada in range(RODADAS_DE_CORRECAO + 1):
        rodadas = rodada
        resp = await llm.agenerate(
            prompt=build_emissao_prompt(
                dados=ctx.dados, achados=achados, modo_capa=ctx.modo_capa,
                erros_anteriores=erros or None,
            ),
            model=DEFAULT_MODEL,
            temperature=0.0,
            max_tokens=16384,
            response_mime_type="application/json",
            seed=seed_for("qualificador_conexo", request.conexo_id, "B", rodada),
        )
        chamadas_llm += 1
        custo += _custo(resp)
        try:
            parsed = parse_llm_json(resp.text or "")
        except Exception as e:  # noqa: BLE001 — JSON ilegível é erro de campo
            erros = [_erro("$", f"JSON ilegível: {e}", (resp.text or "")[:200])]
            continue
        qualificacao, erros = validar_qualificacao(parsed, ctx)
        if not erros:
            break
        logger.info("QUALIFICADOR_EMISSAO_REJEITADA conexo=%s rodada=%d erros=%d",
                    request.conexo_id, rodada, len(erros))

    if erros or qualificacao is None:
        raise QualificacaoInvalidaError(QualificacaoInvalidaBody(
            erros=[ErroCampo(**e) for e in erros],
            rodadas=rodadas,
            custo_usd=round(custo, 6),
            modelo=DEFAULT_MODEL,
            prompt_version=pv,
        ))

    out = _montar_saida(qualificacao, ctx)

    # ── Auditor ─────────────────────────────────────────────────────────────
    modelo_auditor: Optional[str] = None
    auditado = False
    if request.auditar:
        afirmacoes = _afirmacoes_auditaveis(out)
        if afirmacoes:
            vereditos, c, modelo_auditor, n, erro = await auditor_mod.auditar(
                afirmacoes, llm, request.conexo_id,
            )
            custo += c
            chamadas_llm += n
            auditado = True
            _aplicar_vereditos(out, afirmacoes, vereditos, erro)

    return QualificarConexoResponse(
        conexo_id=request.conexo_id,
        processos=out["processos"],
        garantias=out["garantias"],
        alertas_respondidos=out["alertas"],
        divergencias=out["divergencias"],
        requer_revisao=(
            any(p.requer_revisao for p in out["processos"])
            or any(g.requer_revisao for g in out["garantias"])
            or any(a.requer_revisao for a in out["alertas"])
        ),
        modo="capa" if ctx.modo_capa else "documentos",
        auditado=auditado,
        budget_esgotado=budget_esgotado,
        rodadas_de_correcao=rodadas,
        custo_usd=round(custo, 6),
        chamadas=budget.chamadas,
        chamadas_llm=chamadas_llm,
        modelo=DEFAULT_MODEL,
        modelo_auditor=modelo_auditor,
        prompt_version=pv,
    )


# ── Contexto: o índice, os documentos legíveis e o que foi lido ─────────────


class _Contexto:
    def __init__(self) -> None:
        self.request: QualificarConexoRequest
        self.indice: dict[str, Any] = {}
        self.legiveis: dict[str, Any] = {}
        self.lidos: set[str] = set()
        self.itens: set[str] = set()
        self.modo_capa = True
        self.dados: dict[str, Any] = {}
        self.paginas_por_doc: dict[str, int] = {}

    @classmethod
    def montar(cls, request: QualificarConexoRequest) -> "_Contexto":
        from garantis_shared.calculo_fichas.documento import DocumentoIndexado

        ctx = cls()
        ctx.request = request
        for d in request.documentos_indexados:
            ctx.indice[d.doc_id] = d
            if d.documento_indexado:
                try:
                    doc = DocumentoIndexado.from_dict(d.documento_indexado)
                except Exception as e:  # noqa: BLE001 — doc quebrado não derruba os outros
                    logger.warning("QUALIFICADOR_DOC_INVALIDO doc=%s: %r", d.doc_id, e)
                    continue
                if doc.sentencas:
                    ctx.legiveis[d.doc_id] = doc
        # Modo capa = nenhum documento legível. 22/10/2026 (DECIDI-SOZINHO, classe A):
        # índice com itens sem conteúdo conta como "sem documentos indexados",
        # porque o agente não tem o que ler.
        ctx.modo_capa = not ctx.legiveis
        ctx.itens = {p.numero for p in request.processos} | {g.id for g in request.garantias}
        indice_llm = []
        for doc_id, d in ctx.indice.items():
            doc = ctx.legiveis.get(doc_id)
            indice_llm.append({
                k: v for k, v in {
                    "doc_id": doc_id,
                    "nome": d.nome,
                    "tipo": d.tipo,
                    "paginas": len(doc.paginas()) if doc is not None else d.paginas,
                    "processo_numero": d.processo_numero,
                    "data": d.data,
                    "movimento_ref": d.movimento_ref,
                    "legivel": doc is not None,
                }.items() if v is not None
            })
        ctx.dados = dados_do_conexo(request, indice_llm)
        return ctx

    def processo_tem_documentos(self, numero: str) -> bool:
        """O processo tem documento legível para citar?

        Sem nenhum `processo_numero` no índice, o vínculo é desconhecido, e todo
        documento legível serve a todo processo.
        """
        if not self.legiveis:
            return False
        com_dono = [self.indice[d].processo_numero for d in self.legiveis
                    if self.indice[d].processo_numero]
        if not com_dono:
            return True
        return numero in com_dono


# ── Ferramentas ─────────────────────────────────────────────────────────────


async def _executar(
    tool: str,
    args: dict[str, Any],
    ctx: _Contexto,
    budget: BudgetConexo,
    perguntar: Callable,
    resumir: Callable,
) -> tuple[dict[str, Any], bool]:
    """Executa UMA ferramenta. Devolve `(resultado, sucesso)`."""
    doc_id = str(args.get("doc_id") or "")
    if doc_id not in ctx.indice:
        return {"erro": f"doc_id fora do índice: {doc_id!r}"}, False
    doc = ctx.legiveis.get(doc_id)
    if doc is None:
        return {"erro": "documento sem conteúdo indexado: não dá para ler"}, False

    if tool == "pedir_pagina":
        usadas = ctx.paginas_por_doc.get(doc_id, 0)
        if usadas >= budget.max_paginas_por_doc:
            return {"erro": (
                f"teto de {budget.max_paginas_por_doc} páginas cruas por documento atingido"
            )}, False
        try:
            pagina = int(args.get("pagina"))
        except (TypeError, ValueError):
            return {"erro": "args.pagina tem de ser inteiro"}, False
        texto = _texto_da_pagina(doc, pagina)
        if not texto:
            return {"erro": f"a página {pagina} não tem texto neste documento"}, False
        ctx.paginas_por_doc[doc_id] = usadas + 1
        return {"resultado": {"pagina": pagina, "texto": texto[:_MAX_CHARS_PAGINA]}}, True

    fn = perguntar if tool == "perguntar_ao_documento" else resumir
    texto_arg = str(args.get("pergunta") or args.get("missao") or "").strip()
    if not texto_arg:
        campo = "pergunta" if tool == "perguntar_ao_documento" else "missao"
        return {"erro": f"args.{campo} vazio"}, False
    try:
        envelope = dict(await fn(doc_id=doc_id, documento=doc, texto=texto_arg) or {})
    except Exception as e:  # noqa: BLE001 — falha do Leitor é falha da ferramenta
        return {"erro": f"Leitor falhou: {e}"}, False
    custo = float(envelope.get("cost_usd", 0.0) or 0.0)
    if envelope.get("success") is False:
        return {"erro": f"Leitor falhou: {envelope.get('error')}", "_cost_usd": custo}, False
    c = envelope.get("confianca")
    if (isinstance(c, bool) or not isinstance(c, (int, float))
            or not str(envelope.get("objeto_da_confianca") or "").strip()):
        return {"erro": "envelope do Leitor sem confianca/objeto_da_confianca",
                "_cost_usd": custo}, False
    sids = list(envelope.get("citacoes") or []) + [
        str(e.get("sid")) for e in envelope.get("evidencias") or [] if isinstance(e, dict)
    ]
    resultado = {
        k: envelope.get(k) for k in
        ("resposta", "resumo", "encontrou", "lacuna", "lacunas", "confianca",
         "objeto_da_confianca")
        if envelope.get(k) not in (None, "", [])
    }
    # O CÓDIGO resolve o sid em página e texto literal. O agente copia o trecho
    # daqui para a prova, e a regra 5 confere o trecho na página.
    resultado["trechos"] = _trechos(doc, sids)
    return {"resultado": resultado, "_cost_usd": custo}, True


async def _perguntar_via_doc_reader(doc_id: str, documento: Any, texto: str) -> dict:
    from ..doc_reader.agent import perguntar

    r = await perguntar({
        "doc_id": documento.doc_id, "doc_hash": documento.doc_hash,
        "pergunta": texto, "documento_indexado": documento.to_dict(),
    })
    return r.model_dump()


async def _resumir_via_doc_reader(doc_id: str, documento: Any, texto: str) -> dict:
    from ..doc_reader.agent import resumir

    r = await resumir({
        "doc_id": documento.doc_id, "doc_hash": documento.doc_hash,
        "missao": texto, "documento_indexado": documento.to_dict(),
    })
    return r.model_dump()


def _texto_da_pagina(doc: Any, pagina: int) -> str:
    return " ".join(
        (s.texto_bruto or s.texto) for s in doc.sentencas_da_pagina(pagina)
    ).strip()


def _trechos(doc: Any, sids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    vistos: set[str] = set()
    for sid in sids:
        if sid in vistos or len(out) >= _MAX_TRECHOS_POR_LEITURA:
            continue
        vistos.add(sid)
        s = doc.sentenca(sid)
        if s is not None:
            out.append({"sid": sid, "pagina": s.pagina, "texto": s.texto_bruto or s.texto})
    return out


# ── Validação: as regras duras ──────────────────────────────────────────────


def _erro(campo: str, erro: str, valor: Any = None) -> dict[str, Any]:
    return {"campo": campo, "erro": erro, "valor_anterior": valor}


def _normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento.casefold()).strip()


def _validar_prova(prova: Any, campo: str, ctx: _Contexto) -> list[dict[str, Any]]:
    if prova is None:
        return []
    erros: list[dict[str, Any]] = []
    if prova.doc_id not in ctx.indice:
        return [_erro(f"{campo}.doc_id", "doc_id fora do índice", prova.doc_id)]
    doc = ctx.legiveis.get(prova.doc_id)
    n_paginas = ctx.indice[prova.doc_id].paginas
    if doc is not None:
        if prova.pagina not in doc.paginas():
            erros.append(_erro(f"{campo}.pagina", "a página não existe no documento",
                               prova.pagina))
            return erros
        pagina = _normalizar(_texto_da_pagina(doc, prova.pagina))
        pedacos = [p for p in re.split(r"\.\.\.|…", prova.trecho) if p.strip()]
        if not pedacos or any(_normalizar(p) not in pagina for p in pedacos):
            erros.append(_erro(f"{campo}.trecho",
                               "o trecho não está, literal, na página citada", prova.trecho))
    elif n_paginas and prova.pagina > n_paginas:
        erros.append(_erro(f"{campo}.pagina", "a página passa do total do documento",
                           prova.pagina))
    return erros


def validar_qualificacao(
    parsed: Any, ctx: _Contexto,
) -> tuple[Optional[QualificacaoLLM], list[dict[str, Any]]]:
    """Valida a emissão do LLM. Devolve `(qualificacao, erros)`."""
    if isinstance(parsed, dict) and ctx.modo_capa:
        # Modo capa: o código manda nas provas, na confiança e nas garantias.
        parsed = dict(parsed)
        parsed["garantias"] = []
        for chave in ("processos", "alertas_respondidos"):
            itens = parsed.get(chave)
            if isinstance(itens, list):
                parsed[chave] = [
                    {**i, "prova": None, **({"confianca": "baixa"} if chave == "processos" else {})}
                    if isinstance(i, dict) else i
                    for i in itens
                ]
    try:
        q = QualificacaoLLM.model_validate(parsed)
    except ValidationError as e:
        return None, [
            _erro(".".join(str(p) for p in err["loc"]) or "$", err["msg"], err.get("input"))
            for err in e.errors(include_url=False)
        ]

    erros: list[dict[str, Any]] = []
    req = ctx.request

    # Processos: um por processo de entrada.
    esperados = [p.numero for p in req.processos]
    vistos = [p.numero for p in q.processos]
    for n in esperados:
        if vistos.count(n) != 1:
            erros.append(_erro("processos", f"o processo {n} tem de aparecer 1 vez",
                               vistos.count(n)))
    for i, p in enumerate(q.processos):
        campo = f"processos[{i}]"
        if p.numero not in esperados:
            erros.append(_erro(f"{campo}.numero", "processo fora da entrada", p.numero))
            continue
        if (not p.e_fiscal and p.prova is None
                and ctx.processo_tem_documentos(p.numero)):
            erros.append(_erro(f"{campo}.prova", "e_fiscal=false exige prova", None))
        erros += _validar_prova(p.prova, f"{campo}.prova", ctx)

    # Garantias: uma por garantia de entrada (fora do modo capa).
    if not ctx.modo_capa:
        ids = [g.id for g in req.garantias]
        vistos_g = [g.id for g in q.garantias]
        for gid in ids:
            if vistos_g.count(gid) != 1:
                erros.append(_erro("garantias", f"a garantia {gid} tem de aparecer 1 vez",
                                   vistos_g.count(gid)))
        for i, g in enumerate(q.garantias):
            campo = f"garantias[{i}]"
            if g.id not in ids:
                erros.append(_erro(f"{campo}.id", "garantia fora da entrada", g.id))
                continue
            if g.estado in ("substituida", "liberada") and g.prova is None:
                erros.append(_erro(f"{campo}.prova", f"estado {g.estado} exige prova", None))
            if g.estado == "sem_evidencia" and not g.documentos_lidos:
                erros.append(_erro(f"{campo}.documentos_lidos",
                                   "sem_evidencia exige a lista dos documentos lidos", []))
            nao_lidos = [d for d in g.documentos_lidos if d not in ctx.lidos]
            if nao_lidos:
                erros.append(_erro(f"{campo}.documentos_lidos",
                                   "documento que a fase A não leu", nao_lidos))
            if g.substituida_por is not None:
                if g.estado != "substituida":
                    erros.append(_erro(f"{campo}.substituida_por",
                                       "só vale com estado substituida", g.substituida_por))
                elif g.substituida_por not in ids or g.substituida_por == g.id:
                    erros.append(_erro(f"{campo}.substituida_por",
                                       "tem de ser o id de outra garantia da entrada",
                                       g.substituida_por))
            if g.debito_coberto is not None and g.debito_coberto.processo_numero not in esperados:
                erros.append(_erro(f"{campo}.debito_coberto.processo_numero",
                                   "processo fora da entrada", g.debito_coberto.processo_numero))
            erros += _validar_prova(g.prova, f"{campo}.prova", ctx)

    # Alertas: UM por alerta de entrada.
    chaves = [(a.codigo, a.alvo) for a in req.alertas]
    respondidas = [(a.codigo, a.alvo) for a in q.alertas_respondidos]
    for ch in chaves:
        if respondidas.count(ch) != 1:
            erros.append(_erro("alertas_respondidos",
                               f"o alerta {ch[0]} sobre {ch[1]} tem de ter 1 resposta",
                               respondidas.count(ch)))
    for i, a in enumerate(q.alertas_respondidos):
        campo = f"alertas_respondidos[{i}]"
        if (a.codigo, a.alvo) not in chaves:
            erros.append(_erro(campo, "alerta fora da entrada", [a.codigo, a.alvo]))
            continue
        if a.resposta == "refutado" and a.prova is None and not ctx.modo_capa:
            erros.append(_erro(f"{campo}.prova", "alerta refutado exige prova", None))
        erros += _validar_prova(a.prova, f"{campo}.prova", ctx)

    return (q if not erros else None), erros


# ── Saída ───────────────────────────────────────────────────────────────────


def _montar_saida(q: QualificacaoLLM, ctx: _Contexto) -> dict[str, Any]:
    processos = []
    for p in q.processos:
        capa = not ctx.processo_tem_documentos(p.numero)
        dados = p.model_dump()
        if capa:
            dados["confianca"] = "baixa"
        processos.append(ProcessoQualificado(
            **dados,
            fonte="capa" if capa else "documentos",
            # Um "não fiscal" sem prova bloqueia a ficha sem nada para conferir.
            requer_revisao=capa and not p.e_fiscal,
        ))

    if ctx.modo_capa:
        # 22/10/2026 (DECIDI-SOZINHO, classe A; o efeito na S2 é classe B no PR):
        # sem documento, a S2c não tem fato sobre a garantia. O estado honesto é
        # `sem_evidencia`, com `documentos_lidos` vazio e `fonte="capa"`. A regra
        # "ler antes de desistir" não se aplica: não há o que ler.
        garantias = [
            GarantiaQualificada(
                id=g.id, estado="sem_evidencia", documentos_lidos=[],
                confianca="baixa", motivo="conexo sem documento legível",
                fonte="capa", requer_revisao=True,
            )
            for g in ctx.request.garantias
        ]
    else:
        garantias = [GarantiaQualificada(**g.model_dump(), fonte="documentos")
                     for g in q.garantias]

    alertas = [AlertaRespondido(**a.model_dump()) for a in q.alertas_respondidos]
    return {"processos": processos, "garantias": garantias, "alertas": alertas,
            "divergencias": []}


def _afirmacoes_auditaveis(out: dict[str, Any]) -> list[dict[str, Any]]:
    afirmacoes = []
    for p in out["processos"]:
        if not p.e_fiscal and p.prova is not None:
            afirmacoes.append({
                "afirmacao_id": f"processo:{p.numero}", "alvo_tipo": "processo",
                "alvo": p.numero, "codigo": None,
                "afirmacao": f"O processo {p.numero} NÃO é fiscal. {p.motivo}",
                "prova": p.prova.model_dump(),
            })
    for g in out["garantias"]:
        if g.estado in ("substituida", "liberada") and g.prova is not None:
            por = f" pela garantia {g.substituida_por}" if g.substituida_por else ""
            afirmacoes.append({
                "afirmacao_id": f"garantia:{g.id}", "alvo_tipo": "garantia",
                "alvo": g.id, "codigo": None,
                "afirmacao": f"A garantia {g.id} foi {g.estado}{por}. {g.motivo}".strip(),
                "prova": g.prova.model_dump(),
            })
    for a in out["alertas"]:
        if a.resposta == "refutado" and a.prova is not None:
            afirmacoes.append({
                "afirmacao_id": f"alerta:{a.codigo}:{a.alvo}", "alvo_tipo": "alerta",
                "alvo": a.alvo, "codigo": a.codigo,
                "afirmacao": f"O alerta {a.codigo} sobre {a.alvo} é FALSO. {a.motivo}",
                "prova": a.prova.model_dump(),
            })
    return afirmacoes


def _aplicar_vereditos(
    out: dict[str, Any],
    afirmacoes: list[dict[str, Any]],
    vereditos: dict[str, tuple[bool, str]],
    erro: Optional[str],
) -> None:
    """Divergência rebaixa a `confianca` para `baixa` e marca `requer_revisao`."""
    for af in afirmacoes:
        sustenta, motivo = vereditos.get(af["afirmacao_id"], (False, ""))
        if sustenta:
            continue
        motivo = motivo or erro or "o auditor não deu veredito"
        out["divergencias"].append(Divergencia(
            alvo_tipo=af["alvo_tipo"], alvo=af["alvo"], codigo=af["codigo"],
            afirmacao=af["afirmacao"], motivo=motivo[:200],
        ))
        if af["alvo_tipo"] == "processo":
            for p in out["processos"]:
                if p.numero == af["alvo"]:
                    p.confianca, p.requer_revisao = "baixa", True
        elif af["alvo_tipo"] == "garantia":
            for g in out["garantias"]:
                if g.id == af["alvo"]:
                    g.confianca, g.requer_revisao = "baixa", True
        else:
            for a in out["alertas"]:
                if (a.codigo, a.alvo) == (af["codigo"], af["alvo"]):
                    a.requer_revisao = True


def _custo(resp: Any) -> float:
    return float((getattr(resp, "metadata", None) or {}).get("cost_usd", 0.0) or 0.0)


__all__ = [
    "DEFAULT_MODEL",
    "RODADAS_DE_CORRECAO",
    "QualificacaoInvalidaError",
    "prompt_version",
    "qualificar_conexo",
    "validar_qualificacao",
]
