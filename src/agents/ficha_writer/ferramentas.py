"""Navegação dos autos: o núcleo, o índice, as ferramentas, o budget e o breaker.

Decisão do Alfredo de 23/10/2026: "núcleo obrigatório + índice navegável". O
redator v5 (`agent_v5.py`) e o auditor v3 (`auditor_ficha/agent_v3.py`) usam
este módulo. Ele segue o molde do qualificador do conexo (S2c) e do Investigador
do C4:

- O menu é FECHADO e é o mesmo da S2c: `resumir_com_missao`,
  `perguntar_ao_documento` e `pedir_pagina` (`qualificador_conexo.ferramentas`).
- O circuit breaker é o do C4: 3 falhas seguidas de (ferramenta, documento) tiram
  a ferramenta do menu daquele documento.
- O budget é próprio: 25 chamadas por ficha no redator, 20 no auditor, 5 por
  documento e 3 páginas cruas por documento.

A fase A (decisão) roda SEM schema: o LLM escolhe UMA ferramenta por turno, e o
código executa a ferramenta. Budget esgotado encerra a leitura. O agente escreve
com o que leu, e as regras duras do código continuam a valer.

Quem confere a trilha e a prova é o CÓDIGO (`Autos.conferir_citacao`):

1. O `doc_id` existe no núcleo ou no índice.
2. Um documento do índice foi lido de fato na fase A. Um documento do núcleo
   conta como lido: ele está inteiro no prompt.
3. Com o texto disponível, o trecho está no documento (nas páginas citadas, se
   há páginas). A comparação ignora acento, caixa e espaço repetido.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..calculo_ficha.ferramentas import CircuitBreaker
from ..qualificador_conexo.ferramentas import FERRAMENTAS, menu, parse_chamada
from .schemas import ItemIndice, Nucleo

logger = logging.getLogger(__name__)

#: Turnos seguidos sem chamada legível antes de encerrar a fase A.
MAX_FALHAS_DE_PROTOCOLO = 3

#: Trechos literais por resposta do Leitor. O resto fica no Leitor.
_MAX_TRECHOS_POR_LEITURA = 8

#: Caracteres de uma página crua devolvida ao agente.
_MAX_CHARS_PAGINA = 6000


@dataclass
class BudgetNavegacao:
    """Os tetos da fase A. Baixos de propósito (ver o Investigador do C4)."""

    max_por_ficha: int = 25
    max_por_doc: int = 5
    max_paginas_por_doc: int = 3

    chamadas: int = 0
    por_doc: dict[str, int] = field(default_factory=dict)
    paginas_por_doc: dict[str, int] = field(default_factory=dict)

    def esgotado(self) -> bool:
        return self.chamadas >= self.max_por_ficha

    def doc_esgotado(self, doc_id: str) -> bool:
        return self.por_doc.get(doc_id, 0) >= self.max_por_doc

    def restante(self) -> int:
        return max(0, self.max_por_ficha - self.chamadas)


# ── Os autos: núcleo + índice ───────────────────────────────────────────────


def normalizar(texto: str) -> str:
    """Sem acento, sem caixa e sem espaço repetido."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto or "") if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento.casefold()).strip()


def _texto_da_pagina(doc: Any, pagina: int) -> str:
    return " ".join(
        (s.texto_bruto or s.texto) for s in doc.sentencas_da_pagina(pagina)
    ).strip()


class Autos:
    """O que o agente pode ler e citar, e o que ele leu de fato."""

    def __init__(self, nucleo: Nucleo, indice: list[ItemIndice]) -> None:
        from garantis_shared.calculo_fichas.documento import DocumentoIndexado

        self.nucleo = nucleo
        self.textos_nucleo: dict[str, str] = {d.doc_id: d.texto for d in nucleo.documentos()}
        self.indice: dict[str, ItemIndice] = {d.doc_id: d for d in indice}
        self.legiveis: dict[str, Any] = {}
        self.lidos: set[str] = set()
        for d in indice:
            if not d.documento_indexado:
                continue
            try:
                doc = DocumentoIndexado.from_dict(d.documento_indexado)
            except Exception as e:  # noqa: BLE001 — doc quebrado não derruba os outros
                logger.warning("FICHA_AUTOS_DOC_INVALIDO doc=%s: %r", d.doc_id, e)
                continue
            if doc.sentencas:
                self.legiveis[d.doc_id] = doc

    # ── o que o LLM vê ─────────────────────────────────────────────────────

    def nucleo_para_llm(self) -> dict[str, Any]:
        """O núcleo inteiro: a leitura obrigatória."""
        return self.nucleo.model_dump(mode="json", exclude_none=True)

    def indice_para_llm(self) -> list[dict[str, Any]]:
        """O índice SEM o conteúdo: só os metadados e se dá para abrir."""
        out = []
        for doc_id, d in self.indice.items():
            doc = self.legiveis.get(doc_id)
            meta = d.model_dump(exclude={"documento_indexado"}, exclude_none=True)
            if doc is not None and d.paginas is None:
                meta["paginas"] = len(doc.paginas())
            meta["legivel"] = doc is not None
            meta["no_nucleo"] = doc_id in self.textos_nucleo
            out.append(meta)
        return out

    # ── as regras do código ────────────────────────────────────────────────

    def existe(self, doc_id: str) -> bool:
        return doc_id in self.textos_nucleo or doc_id in self.indice

    def foi_lido(self, doc_id: str) -> bool:
        return doc_id in self.textos_nucleo or doc_id in self.lidos

    def conferir_citacao(
        self, doc_id: str, paginas: list[int], trecho: str,
    ) -> Optional[str]:
        """Devolve o erro da citação, ou None. Ver as 3 regras no docstring do módulo."""
        if not self.existe(doc_id):
            return f"doc_id fora do núcleo e do índice: {doc_id!r}"
        if not self.foi_lido(doc_id):
            return (f"o documento {doc_id!r} não foi lido na fase A. Cite só o núcleo ou "
                    "um documento que você abriu com uma ferramenta")
        doc = self.legiveis.get(doc_id)
        if doc is not None:
            existentes = set(doc.paginas())
            fora = [p for p in paginas if p not in existentes]
            if fora:
                return f"página que não existe no documento {doc_id!r}: {fora}"
            if paginas:
                base = " ".join(_texto_da_pagina(doc, p) for p in paginas)
            else:
                base = " ".join(_texto_da_pagina(doc, p) for p in sorted(existentes))
        else:
            base = self.textos_nucleo.get(doc_id, "")
        alvo = normalizar(base)
        pedacos = [p for p in re.split(r"\.\.\.|…", trecho or "") if p.strip()]
        if not pedacos or any(normalizar(p) not in alvo for p in pedacos):
            return ("o trecho não está, literal, no documento citado"
                    + (f" (páginas {paginas})" if paginas and doc is not None else ""))
        return None


# ── As ferramentas ──────────────────────────────────────────────────────────


Leitor = Callable[..., Awaitable[dict]]


async def _executar(
    tool: str,
    args: dict[str, Any],
    autos: Autos,
    budget: BudgetNavegacao,
    perguntar: Leitor,
    resumir: Leitor,
) -> tuple[dict[str, Any], bool]:
    """Executa UMA ferramenta. Devolve `(resultado, sucesso)`."""
    doc_id = str(args.get("doc_id") or "")
    if doc_id not in autos.indice:
        if doc_id in autos.textos_nucleo:
            return {"erro": "o documento está no núcleo: o texto inteiro já está no "
                            "prompt. Não gaste chamada nele"}, False
        return {"erro": f"doc_id fora do índice: {doc_id!r}"}, False
    doc = autos.legiveis.get(doc_id)
    if doc is None:
        return {"erro": "documento sem conteúdo indexado: não dá para abrir"}, False

    if tool == "pedir_pagina":
        usadas = budget.paginas_por_doc.get(doc_id, 0)
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
        budget.paginas_por_doc[doc_id] = usadas + 1
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
    # daqui para a trilha ou para a prova, e o código confere o trecho.
    resultado["trechos"] = _trechos(doc, sids)
    return {"resultado": resultado, "_cost_usd": custo}, True


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


async def perguntar_via_doc_reader(doc_id: str, documento: Any, texto: str) -> dict:
    from ..doc_reader.agent import perguntar

    r = await perguntar({
        "doc_id": documento.doc_id, "doc_hash": documento.doc_hash,
        "pergunta": texto, "documento_indexado": documento.to_dict(),
    })
    return r.model_dump()


async def resumir_via_doc_reader(doc_id: str, documento: Any, texto: str) -> dict:
    from ..doc_reader.agent import resumir

    r = await resumir({
        "doc_id": documento.doc_id, "doc_hash": documento.doc_hash,
        "missao": texto, "documento_indexado": documento.to_dict(),
    })
    return r.model_dump()


# ── Fase A: o loop de decisão ───────────────────────────────────────────────


@dataclass
class ResultadoNavegacao:
    achados: list[dict[str, Any]] = field(default_factory=list)
    chamadas_llm: int = 0
    custo_usd: float = 0.0
    budget_esgotado: bool = False


#: `(achados, menu, budget_restante, budget_por_doc) -> prompt`.
PromptDeDecisao = Callable[[list[dict[str, Any]], list[str], int, int], str]


async def navegar(
    *,
    llm: Any,
    model: str,
    autos: Autos,
    budget: BudgetNavegacao,
    prompt_de_decisao: PromptDeDecisao,
    seed: Callable[[int], int],
    leitor_perguntar: Optional[Leitor] = None,
    leitor_resumir: Optional[Leitor] = None,
    rotulo: str = "FICHA",
) -> ResultadoNavegacao:
    """A fase A. Sem documento legível no índice, ela não chama o LLM.

    `seed(turno)` dá o seed de cada turno (`_utils.llm_seed.seed_for`).
    """
    out = ResultadoNavegacao()
    if not autos.legiveis:
        return out
    perguntar = leitor_perguntar or perguntar_via_doc_reader
    resumir = leitor_resumir or resumir_via_doc_reader
    breaker = CircuitBreaker()
    falhas_protocolo = 0
    turno = 0
    while True:
        if budget.esgotado():
            out.budget_esgotado = True
            logger.warning("%s_BUDGET chamadas=%d", rotulo, budget.chamadas)
            break
        turno += 1
        # A fase A NUNCA leva response_mime_type (ver tests/test_duas_fases.py).
        resp = await llm.agenerate(
            prompt=prompt_de_decisao(
                out.achados, menu(breaker), budget.restante(), budget.max_por_doc,
            ),
            model=model,
            temperature=0.0,
            max_tokens=2048,
            seed=seed(turno),
        )
        out.chamadas_llm += 1
        out.custo_usd += custo_da_resposta(resp)

        chamada = parse_chamada(resp.text or "")
        if chamada is None:
            falhas_protocolo += 1
            out.achados.append({"erro": "resposta sem chamada JSON válida. Responda um JSON só."})
            if falhas_protocolo >= MAX_FALHAS_DE_PROTOCOLO:
                break
            continue
        falhas_protocolo = 0
        if chamada.get("fim"):
            break

        budget.chamadas += 1
        tool, args = chamada["tool"], chamada["args"]
        doc_id = str(args.get("doc_id") or "")
        if budget.doc_esgotado(doc_id):
            out.achados.append({"tool": tool, "args": args, "erro": (
                f"teto de {budget.max_por_doc} chamadas no documento {doc_id} atingido"
            )})
            continue
        budget.por_doc[doc_id] = budget.por_doc.get(doc_id, 0) + 1
        if not breaker.disponivel(tool, doc_id):
            out.achados.append({"tool": tool, "args": args, "erro": (
                "circuito aberto para esta ferramenta neste documento (3 falhas)"
            )})
            continue

        resultado, ok = await _executar(tool, args, autos, budget, perguntar, resumir)
        out.custo_usd += float(resultado.pop("_cost_usd", 0.0) or 0.0)
        out.achados.append({"tool": tool, "args": args, **resultado})
        if ok:
            breaker.registrar_sucesso(tool, doc_id)
            autos.lidos.add(doc_id)
        elif breaker.registrar_falha(tool, doc_id):
            out.achados.append({"tool": tool, "doc_id": doc_id, "nota": (
                "ferramenta fora do menu deste documento (circuit breaker)"
            )})
    return out


def custo_da_resposta(resp: Any) -> float:
    return float((getattr(resp, "metadata", None) or {}).get("cost_usd", 0.0) or 0.0)


__all__ = [
    "FERRAMENTAS",
    "MAX_FALHAS_DE_PROTOCOLO",
    "Autos",
    "BudgetNavegacao",
    "CircuitBreaker",
    "ResultadoNavegacao",
    "custo_da_resposta",
    "navegar",
    "normalizar",
    "perguntar_via_doc_reader",
    "resumir_via_doc_reader",
]
