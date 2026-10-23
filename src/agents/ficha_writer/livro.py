"""A guidance do Livro da Ficha por slot × tipo, vendorizada em `livro_guidance.json`.

O JSON sai de `scripts/gerar_livro_guidance.py`. Não edite o JSON à mão: edite o
script e rode de novo. O teste `test_guidance_vendorizada_bate_com_o_script` reprova
um JSON velho.

Regra de mistura (decisão de 22/10/2026): o `CampoSpec` do request vence campo a
campo. O shared vai mandar `guidance` no `CampoSpec`. Quando ele vem vazio, o agente
usa a guidance vendorizada. O mesmo vale para `exemplos`, `proibicoes` e
`obrigatorio`. O `max` é sempre o do request: ele é o contrato que a S5 confere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .schemas import CampoSpec, FichaWriteFieldsRequest

ARQUIVO = Path(__file__).with_name("livro_guidance.json")


@lru_cache(maxsize=1)
def carregar() -> dict:
    return json.loads(ARQUIVO.read_text(encoding="utf-8"))


def chave_livro(req: FichaWriteFieldsRequest) -> Optional[str]:
    """A chave do Livro para o request. `tipo_livro` explícito vence."""
    if req.tipo_livro:
        return req.tipo_livro
    if req.tipo_ficha == "nova_apolice":
        return f"nova_apolice@{req.trilho}" if req.trilho else None
    if req.tipo_ficha in carregar()["tipos"]:
        return req.tipo_ficha
    return None


@dataclass
class SlotResolvido:
    """Um slot pronto para o prompt e para a validação."""

    nome: str
    max: int
    obrigatorio: bool
    guidance: str
    exemplos: list[str]
    proibicoes: list[str]
    exemplos_herdados: bool = False
    fonte: str = ""
    path: str = ""
    livro_ids: list[str] = field(default_factory=list)


def resolver_slots(
    req: FichaWriteFieldsRequest, campos: list[CampoSpec]
) -> tuple[list[SlotResolvido], list[str]]:
    """(slots aplicáveis, nomes NÃO aplicáveis ao tipo).

    Um slot pedido que o Livro fecha para o tipo (ex.: bullets[3] na renovação) não vai
    ao LLM. Ele sai em `campos_nao_aplicaveis` na resposta: o caller sabe, e nada some
    em silêncio. Slot que o Livro não conhece vai ao LLM só com o `CampoSpec`.
    """
    livro = carregar()
    chave = chave_livro(req)
    tipo = livro["tipos"].get(chave or "", {})
    variante = None
    if req.esqueleto is not None and "acompanhamento" in (req.esqueleto.tags or []):
        variante = livro["variantes"]["acompanhamento"]["slots"]

    aplicaveis: list[SlotResolvido] = []
    nao_aplicaveis: list[str] = []
    for spec in campos:
        v = (tipo.get("slots") or {}).get(spec.nome)
        if v is not None and not v["aplicavel"]:
            nao_aplicaveis.append(spec.nome)
            continue
        v = v or {}
        guidance = spec.guidance or v.get("guidance", "")
        exemplos = list(spec.exemplos or v.get("exemplos", []))
        if variante and variante.get(spec.nome, {}).get("guidance"):
            ov = variante[spec.nome]
            guidance = f"{guidance} {ov['guidance']}".strip()
            exemplos = list(dict.fromkeys(list(ov["exemplos"]) + exemplos))
        if spec.obrigatorio is not None:
            obrigatorio = spec.obrigatorio
        else:
            obrigatorio = bool(v.get("obrigatorio", spec.nome != "observacao"))
        aplicaveis.append(SlotResolvido(
            nome=spec.nome,
            max=spec.max,
            obrigatorio=obrigatorio,
            guidance=guidance,
            exemplos=exemplos,
            proibicoes=list(spec.proibicoes or v.get("proibicoes", [])),
            exemplos_herdados=bool(not spec.exemplos and v.get("exemplos_herdados")),
            fonte=v.get("fonte", "request"),
            path=spec.path,
            livro_ids=list(v.get("livro_ids", [])),
        ))
    return aplicaveis, nao_aplicaveis


def descricao_tipo(chave: Optional[str]) -> str:
    return carregar()["tipos"].get(chave or "", {}).get("descricao", "")


def proibicoes_globais() -> list[dict]:
    return carregar()["proibicoes_globais"]


__all__ = [
    "ARQUIVO",
    "SlotResolvido",
    "carregar",
    "chave_livro",
    "descricao_tipo",
    "proibicoes_globais",
    "resolver_slots",
]
