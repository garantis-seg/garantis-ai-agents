"""Validação da saída do v4 (S4). Determinística, pura, sem LLM.

Esta validação é o critério de parada do loop interno de 3 rodadas. Ela NÃO é a S5:
a S5 roda no shared sobre a ficha inteira (Apêndice A). Aqui ficam só as regras que o
agente sabe conferir com o que recebeu:

1. Só os slots pedidos. Chave a mais é descartada e logada. Chave que falta reprova.
2. Cada valor é string.
3. `max` de cada slot. Antes de 22/10/2026 só o caller conferia.
4. Slot obrigatório não fica vazio.
5. Zero cifra `R$` em `valor.descricao` (regra de 09/10/2026, A56 da S5).
6. Nenhum número de processo fora dos citáveis (regra de 28/09/2026: processo de outra
   empresa fica fora dos lugares que citam número).
7. Todo alerta tem UMA resposta `acatado|refutado`, com motivo.
8. Status da dívida ativa (SERPRO) fora de todo slot (regra 26, 23/10/2026).
9. `valor.descricao` com origem fixa (cda, apolice_ou_fianca) sem "estimad" nem "pode
   variar" (regra 25, 23/10/2026).
10. Renovação sem corretor no esqueleto: o `bullets[1]` diz "corretagem não identificada"
    (23/10/2026). O agente nunca inventa corretor.

As mensagens de `max` começam por `"<slot> > <max> chars"`, o mesmo prefixo de
`contratos.validar_ficha`. Assim o `_ERRO_PARA_CAMPO` do shared continua a casar.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional

from .livro import SlotResolvido
from .schemas import Alerta, AlertaRespondido, ErroDeCampo, FichaWriteFieldsRequest

logger = logging.getLogger(__name__)

#: Campo do erro que não é slot: o JSON inteiro ou a lista de alertas.
CAMPO_SAIDA = "_saida"
CAMPO_ALERTAS = "alertas_respondidos"

#: Igual a `_RE_A56` da S5 (garantis_shared/fichas/validadores/apendice_a.py).
RE_CIFRA = re.compile(r"R\$\s*\d[\d.,]*(?:\s*(?:mil|milh[ãõ]o|milh[õo]es|bilh[ãõ]o|bilh[õo]es)\b)?")

#: Números de processo que o texto pode trazer. Decisão de 22/10/2026 (classe A): só
#: os 2 formatos de processo, CNJ (20 dígitos) e processo administrativo federal (15 ou
#: 17 dígitos). Número de acórdão ("3102-004.203"), CDA ("80 6 10 010169-09") e AIIM
#: não são processo e não entram: o falso positivo custaria uma rodada.
RE_PROCESSO = re.compile(
    r"(?<![\d.])(?:"
    r"\d{7}-?\d{2}\.?\d{4}\.?\d\.?\d{2}\.?\d{4}"      # CNJ
    r"|\d{5}\.?\d{6}/?\d{4}-?\d{2}"                   # PA federal, 17 dígitos
    r"|\d{5}\.\d{6}/\d{2}-\d{2}"                      # PA federal antigo, 15 dígitos
    r")(?![\d])"
)

#: Regra 26 (Alfredo, 23/10/2026): o status da dívida ativa é fato do código e não vai ao
#: texto. Vale em TODO slot, como a regra da cifra vale em valor.descricao.
RE_STATUS_DIVIDA = re.compile(
    r"\b(ativa\s+ajuizada|ativa\s+n[aã]o\s+ajuizada|garantida\s+por\s+seguro|serpro|regularize)\b",
    re.I)

#: Regra 25 (Alfredo, 23/10/2026): com o valor de origem fixa, a descrição do valor não
#: fala em estimativa.
ORIGENS_VALOR_FIXO = frozenset({"cda", "apolice_ou_fianca"})
RE_VALOR_VARIAVEL = re.compile(r"estimad|pode\s+variar", re.I)

#: A frase do bullet 2 da renovação sem corretor no esqueleto (23/10/2026).
FRASE_SEM_CORRETOR = "Corretagem não identificada na base."
_RE_SEM_CORRETOR = re.compile(r"corretagem\s+n[ãa]o\s+identificada", re.I)
SLOT_CORRETAGEM = "bullets[1]"
AVISO_RENOVACAO_SEM_BLOCO = "renovacao_sem_bloco"

_MAX_MOTIVO = 400


def so_digitos(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def processos_citaveis(req: FichaWriteFieldsRequest) -> set[str]:
    """Os números (só dígitos) que o texto pode citar: o request + o esqueleto."""
    return {d for d in (so_digitos(n) for n in processos_citaveis_brutos(req)) if d}


def processos_citaveis_brutos(req: FichaWriteFieldsRequest) -> list[str]:
    """Os mesmos números, com a máscara original, para o prompt. Ordem estável."""
    nums: list[Any] = list(req.processos_citaveis or [])
    e = req.esqueleto
    if e is not None:
        nums.append(e.processo_id)
        for bloco in (e.processo_judicial, getattr(e, "processo_administrativo", None)):
            if isinstance(bloco, dict):
                nums.append(bloco.get("numero"))
        for pj in getattr(e, "processos_judiciais", None) or []:
            if isinstance(pj, dict):
                nums.append(pj.get("numero"))
    return list(dict.fromkeys(str(n).strip() for n in nums if so_digitos(n)))


def origem_valor(req: FichaWriteFieldsRequest) -> Optional[str]:
    e = req.esqueleto
    return (e.valor.origem or None) if e is not None else None


def bloco_renovacao(req: FichaWriteFieldsRequest) -> Optional[dict]:
    """O bloco `renovacao` do esqueleto (fe-api, 23/10/2026), ou None."""
    e = req.esqueleto
    bloco = getattr(e, "renovacao", None) if e is not None else None
    return bloco if isinstance(bloco, dict) else None


def renovacao_sem_corretor(req: FichaWriteFieldsRequest, chave: Optional[str]) -> bool:
    """Renovação sem bloco `renovacao`, ou com a lista de corretores vazia."""
    if not (chave or "").startswith("renovacao"):
        return False
    bloco = bloco_renovacao(req)
    return not (bloco and bloco.get("corretores"))


def avisos(req: FichaWriteFieldsRequest, chave: Optional[str],
           slots: Iterable[SlotResolvido]) -> list[str]:
    """Os avisos do código para o caller. Aviso não reprova: ele diz o que faltou."""
    out: list[str] = []
    nomes = {s.nome for s in slots}
    if ((chave or "").startswith("renovacao") and SLOT_CORRETAGEM in nomes
            and bloco_renovacao(req) is None):
        logger.warning("FICHA_WRITER_V4 %s: o esqueleto não traz o bloco renovacao",
                       AVISO_RENOVACAO_SEM_BLOCO)
        out.append(AVISO_RENOVACAO_SEM_BLOCO)
    return out


def processos_no_texto(texto: str) -> list[str]:
    return [m.group(0) for m in RE_PROCESSO.finditer(texto or "")]


def validar_campos(
    parsed: Any, slots: Iterable[SlotResolvido], citaveis: Optional[set[str]],
    *, origem_valor: Optional[str] = None, sem_corretor: bool = False,
) -> tuple[dict[str, str], list[ErroDeCampo]]:
    """(slots aprovados, erros). `citaveis=None` desliga a regra 6.

    `origem_valor` liga a regra 9. `sem_corretor=True` liga a regra 10.
    """
    if not isinstance(parsed, dict):
        return {}, [ErroDeCampo(campo=CAMPO_SAIDA, erro="a saída não é um objeto JSON")]
    campos = parsed.get("campos")
    if not isinstance(campos, dict):
        return {}, [ErroDeCampo(campo=CAMPO_SAIDA,
                                erro="a saída não tem o objeto 'campos' {slot: texto}")]
    slots = list(slots)
    extras = sorted(set(campos) - {s.nome for s in slots})
    if extras:
        # DECIDI-SOZINHO 22/10/2026 (classe A): chave a mais é descartada, não reprovada.
        # Ela nunca chega ao caller, e uma rodada a mais por isso só gastaria dinheiro.
        logger.warning("FICHA_WRITER_V4_EXTRAS descartados: %s", extras)

    ok: dict[str, str] = {}
    erros: list[ErroDeCampo] = []
    for s in slots:
        if s.nome not in campos:
            erros.append(ErroDeCampo(campo=s.nome, erro=f"{s.nome}: slot ausente na resposta"))
            continue
        v = campos[s.nome]
        if not isinstance(v, str):
            erros.append(ErroDeCampo(campo=s.nome, erro=(
                f"{s.nome}: deveria ser string, veio {type(v).__name__}"), valor_anterior=v))
            continue
        v = v.strip()
        erro = _erro_do_texto(s, v, citaveis, origem_valor, sem_corretor)
        if erro:
            erros.append(ErroDeCampo(campo=s.nome, erro=erro, valor_anterior=v))
        else:
            ok[s.nome] = v
    return ok, erros


def _erro_do_texto(s: SlotResolvido, v: str, citaveis: Optional[set[str]],
                   origem_valor: Optional[str] = None,
                   sem_corretor: bool = False) -> Optional[str]:
    if not v:
        return f"{s.nome}: slot obrigatório vazio" if s.obrigatorio else None
    if len(v) > s.max:
        return f"{s.nome} > {s.max} chars (tem {len(v)}). Corte sem perder o fato principal"
    if s.nome == "valor.descricao":
        m = RE_CIFRA.search(v)
        if m:
            return (f'valor.descricao: cifra no texto do box: "{m.group(0)}". O número fica só '
                    "no box: diga em palavras o que ele é (regra de 09/10/2026)")
        if origem_valor in ORIGENS_VALOR_FIXO:
            m = RE_VALOR_VARIAVEL.search(v)
            if m:
                return (f'valor.descricao: o valor de origem {origem_valor} é exato: "{m.group(0)}" '
                        "não vai ao texto. Copie valor.descricao_fixa dos FATOS FIXOS, sem "
                        '"estimado" nem "pode variar" (regra 25, 23/10/2026)')
    m = RE_STATUS_DIVIDA.search(v)
    if m:
        return (f'{s.nome}: status da dívida não vai ao texto: regra 26 ("{m.group(0)}"). O '
                "status é fato do código. Tire o trecho e mantenha o resto")
    if sem_corretor and s.nome == SLOT_CORRETAGEM and not _RE_SEM_CORRETOR.search(v):
        return (f"{s.nome}: o esqueleto não traz corretor. Escreva "
                f'"{FRASE_SEM_CORRETOR}" e nunca invente corretor (23/10/2026)')
    if citaveis is not None:
        fora = [p for p in processos_no_texto(v) if so_digitos(p) not in citaveis]
        if fora:
            return (f"{s.nome}: cita processo fora dos permitidos ({', '.join(fora)}). Processo "
                    "de outra empresa ou sem vínculo não aparece no texto (regra de 28/09/2026)")
    return None


def validar_alertas(
    parsed: Any, pendentes: list[Alerta]
) -> tuple[list[AlertaRespondido], list[ErroDeCampo]]:
    """(respostas válidas dos `pendentes`, erros). Resposta a código desconhecido é
    descartada (log). A 1ª resposta válida de cada código vence."""
    if not pendentes:
        return [], []
    brutas = parsed.get("alertas_respondidos") if isinstance(parsed, dict) else None
    if not isinstance(brutas, list):
        brutas = []
    por_codigo = {a.codigo: a for a in pendentes}
    ok: dict[str, AlertaRespondido] = {}
    invalidas: dict[str, str] = {}
    for b in brutas:
        if not isinstance(b, dict):
            continue
        cod = str(b.get("codigo") or "")
        if cod not in por_codigo:
            logger.warning("FICHA_WRITER_V4 alerta desconhecido descartado: %r", cod)
            continue
        if cod in ok:
            continue
        resp, motivo = b.get("resposta"), str(b.get("motivo") or "").strip()
        if resp not in ("acatado", "refutado"):
            invalidas[cod] = f"resposta {resp!r} fora de acatado|refutado"
        elif not motivo:
            invalidas[cod] = "motivo vazio"
        else:
            ok[cod] = AlertaRespondido(codigo=cod, resposta=resp, motivo=motivo[:_MAX_MOTIVO])
    erros = [
        ErroDeCampo(campo=CAMPO_ALERTAS, erro=(
            f"alerta '{a.codigo}' sem resposta válida"
            + (f" ({invalidas[a.codigo]})" if a.codigo in invalidas else "")
            + ": responda acatado ou refutado, com motivo"), valor_anterior=a.texto)
        for a in pendentes if a.codigo not in ok
    ]
    return [ok[a.codigo] for a in pendentes if a.codigo in ok], erros


__all__ = [
    "AVISO_RENOVACAO_SEM_BLOCO",
    "CAMPO_ALERTAS",
    "CAMPO_SAIDA",
    "FRASE_SEM_CORRETOR",
    "ORIGENS_VALOR_FIXO",
    "RE_CIFRA",
    "RE_PROCESSO",
    "RE_STATUS_DIVIDA",
    "RE_VALOR_VARIAVEL",
    "avisos",
    "bloco_renovacao",
    "origem_valor",
    "renovacao_sem_corretor",
    "processos_citaveis",
    "processos_citaveis_brutos",
    "processos_no_texto",
    "so_digitos",
    "validar_alertas",
    "validar_campos",
]
