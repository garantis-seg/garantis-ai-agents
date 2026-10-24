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

As regras 11 e 12 (23/10/2026) ficam neste módulo, mas só o v5 e o auditor v3 chamam as
regras. O v4 não tem os autos. Ver a seção "Fato sem fonte" no fim do módulo:

11. Toda data e todo número de acórdão, processo, CDA e valor em R$ de um slot existe,
    normalizado, numa fonte (`FontesDeFato`).
12. Palavra de esgotamento ("esgotad", "encerrando a via", "não foi admitido", "não
    conhecido", "trânsito") só com a etapa concluída no esqueleto ou com a decisão nas
    fontes de documento.

As mensagens de `max` começam por `"<slot> > <max> chars"`, o mesmo prefixo de
`contratos.validar_ficha`. Assim o `_ERRO_PARA_CAMPO` do shared continua a casar.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
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


# ── Fato sem fonte (regras 11 e 12, 23/10/2026) ───────────────────────────────
#
# Defeito de 23/10/2026 (rodada real, IRB 1481420, rev 00413): o redator v5 escreveu
# "O recurso especial à Câmara Superior não foi admitido em 01/09/2026, encerrando a via
# administrativa" em 4 slots. A data 01/09/2026 não existe em fonte nenhuma: nem no
# núcleo, nem no índice, nem no esqueleto (CSRF `em_andamento`), nem nas premissas. O
# modelo inventou a data, e a ficha saiu aprovada.
#
# Princípio: determinismo máximo. O código pega o que consegue pegar. Uma data ou um
# número do texto tem de existir, normalizado, numa fonte. O LLM só decide o resto.

#: O prefixo do erro de fato sem fonte (regra 11).
ERRO_FATO_SEM_FONTE = "fato sem fonte"
#: O prefixo do erro de esgotamento sem fonte (regra 12).
ERRO_ESGOTAMENTO_SEM_FONTE = "afirmação de esgotamento sem fonte"

_MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_RE_MES_NOME = "|".join(_MESES)

#: Datas no texto do slot (texto já sem acento e em caixa baixa).
_RE_DATA_BR = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")
_RE_DATA_EXT = re.compile(rf"(?<!\d)(\d{{1,2}})o?\s+de\s+({_RE_MES_NOME})\s+de\s+(\d{{4}})(?!\d)")
_RE_DATA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_RE_MES_ANO = re.compile(r"(?<![\d/.])(\d{1,2})/(\d{4})(?![\d/])")
#: Só nas fontes: data com ponto, mês ISO e "mês de AAAA".
_RE_DATA_PONTO = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\.?\d)")
_RE_MES_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})(?![\d-])")
_RE_MES_EXT = re.compile(rf"\b({_RE_MES_NOME})\s+de\s+(\d{{4}})(?!\d)")

#: Números de identificação no texto do slot. Acórdão ("3102-004.203"), CDA ("80 6 10
#: 010169-09") e os processos de `RE_PROCESSO`.
_RE_ACORDAO = re.compile(r"(?<![\d.])\d{4}-\d{3}\.?\d{3}(?![\d])")
_RE_CDA = re.compile(r"(?<![\d.])\d{2}[\s.]?\d[\s.]?\d{2}[\s.]?\d{6}-?\d{2}(?![\d])")
#: Nas fontes: toda sequência de dígitos com separador, com 6 dígitos ou mais.
_RE_SEQ_DIGITOS = re.compile(r"\d[\d.\-/]*\d")
_MIN_DIGITOS_ID = 6

#: Valores nas fontes: número com separador de milhar, cifra "R$ 182.8M" e cifra comum.
_RE_NUM_MILHAR = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d])")
_RE_CIFRA_SUFIXO = re.compile(r"R\$\s*(\d[\d.,]*)\s*(MM|M|K|B|BI|MI|MIL)\b", re.I)
_RE_NUM_PURO = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*$")
_MULT = {
    "mil": 1e3, "k": 1e3, "m": 1e6, "mm": 1e6, "mi": 1e6, "milhao": 1e6, "milhoes": 1e6,
    "b": 1e9, "bi": 1e9, "bilhao": 1e9, "bilhoes": 1e9,
}

#: Regra 12. Termos de esgotamento no texto (sem acento, caixa baixa).
_RE_ESGOTAMENTO_ADM = re.compile(
    r"esgotad|encerr\w*\s+(?:a\s+)?(?:via|esfera|instancia)\s+administrativa|"
    r"encerrando\s+a\s+via|nao\s+(?:foi\s+)?admitid|inadmitid|nao\s+(?:foi\s+)?conhecid")
_RE_TRANSITO = re.compile(r"\btransit(?:o|ou|ad[oa])\b")
#: Regra 12. A decisão nas fontes de documento (literal, sem acento).
_RE_DECISAO_ADM = re.compile(
    r"nao\s+(?:foi\s+)?admitid|inadmit|negad[oa]\s+seguimento|neg(?:o|ou)\s+seguimento|"
    r"nao\s+(?:se\s+)?conhec(?:o|eu|ido|ida|er)\b|esgotad")
_RE_DECISAO_TRANSITO = re.compile(r"transit\w*\s+em\s+julgado")
#: Etapas do pipeline que não são do contencioso administrativo.
_ETAPAS_NAO_ADM = ("cobranca", "judicial", "execucao", "divida", "inscricao", "embargo",
                   "apelacao", "sentenca", "tribunal", "acao", "stj", "stf", "trf")
_ETAPAS_JUDICIAIS = ("judicial", "execucao", "embargo", "apelacao", "sentenca", "tribunal",
                     "acao", "stj", "stf", "trf")

#: Teto da lista de permitidos no erro do retry.
_MAX_PERMITIDOS = 60


def sem_acento(texto: Any) -> str:
    """Caixa baixa, sem acento. "1º" vira "1o"."""
    n = unicodedata.normalize("NFKD", str(texto or "")).lower()
    return "".join(c for c in n if not unicodedata.combining(c))


def _data_ok(d: int, m: int, a: int) -> bool:
    return 1 <= d <= 31 and 1 <= m <= 12 and 1900 <= a <= 2100


def _mes_ok(m: int, a: int) -> bool:
    return 1 <= m <= 12 and 1900 <= a <= 2100


def _br(iso: str) -> str:
    """'2026-09-01' vira '01/09/2026'. '2026-09' vira '09/2026'."""
    p = iso.split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else f"{p[1]}/{p[0]}"


def datas_no_texto(texto: str) -> list[tuple[str, str]]:
    """As datas de um slot: `[(trecho original, chave ISO)]`. Chave de mês: 'AAAA-MM'."""
    t = sem_acento(texto)
    out: list[tuple[str, str]] = []
    for m in _RE_DATA_BR.finditer(t):
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _data_ok(d, mes, a):
            out.append((m.group(0), f"{a:04d}-{mes:02d}-{d:02d}"))
    for m in _RE_DATA_EXT.finditer(t):
        d, mes, a = int(m.group(1)), _MESES[m.group(2)], int(m.group(3))
        if _data_ok(d, mes, a):
            out.append((m.group(0), f"{a:04d}-{mes:02d}-{d:02d}"))
    for m in _RE_DATA_ISO.finditer(t):
        a, mes, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _data_ok(d, mes, a):
            out.append((m.group(0), f"{a:04d}-{mes:02d}-{d:02d}"))
    for m in _RE_MES_ANO.finditer(t):
        mes, a = int(m.group(1)), int(m.group(2))
        if _mes_ok(mes, a):
            out.append((m.group(0), f"{a:04d}-{mes:02d}"))
    return out


def _valor_br(numero: str, sufixo: str = "") -> Optional[tuple[float, float]]:
    """'182,8' + 'milhões' vira (182.8e6, 0.1e6): o valor e a unidade da última casa."""
    s = numero.strip().rstrip(".,")
    if not s:
        return None
    if "," in s:
        inteiro, dec = s.rsplit(",", 1)
        inteiro = inteiro.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        inteiro, dec = s.replace(".", ""), ""
    elif "." in s:
        inteiro, dec = s.rsplit(".", 1)
        inteiro = inteiro.replace(".", "")
    else:
        inteiro, dec = s, ""
    if not inteiro.isdigit() or (dec and not dec.isdigit()):
        return None
    mult = _MULT.get(sem_acento(sufixo).strip(), 1.0)
    valor = float(f"{inteiro}.{dec}" if dec else inteiro) * mult
    return valor, (10 ** -len(dec)) * mult


def valores_no_texto(texto: str) -> list[tuple[str, float, float]]:
    """As cifras de um slot: `[(trecho, valor, unidade)]`. Usa a `RE_CIFRA` da S5."""
    out: list[tuple[str, float, float]] = []
    for m in RE_CIFRA.finditer(texto or ""):
        corpo = m.group(0)[2:].strip()
        partes = corpo.split(None, 1)
        v = _valor_br(partes[0], partes[1] if len(partes) > 1 else "")
        if v is not None:
            out.append((m.group(0), v[0], v[1]))
    return out


def ids_no_texto(texto: str) -> list[str]:
    """Os números de acórdão, de processo e de CDA de um slot, com a máscara."""
    t = texto or ""
    vistos: list[str] = []
    for rx in (RE_PROCESSO, _RE_ACORDAO, _RE_CDA):
        for m in rx.finditer(t):
            if not any(m.group(0) in v for v in vistos):
                vistos.append(m.group(0))
    return vistos


@dataclass
class FontesDeFato:
    """O que o texto pode afirmar: as datas, os números e os valores das fontes.

    `texto_docs` é o texto dos documentos (núcleo e lidos), sem acento, para a regra 12.
    `pipeline` é o pipeline do esqueleto: `[(etapa, status)]`, sem acento.
    """

    datas: set[str] = field(default_factory=set)
    meses: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)
    valores: list[float] = field(default_factory=list)
    texto_docs: str = ""
    pipeline: list[tuple[str, str]] = field(default_factory=list)
    #: Para o erro do retry: a máscara de cada data, número e valor citável.
    ids_com_mascara: dict[str, str] = field(default_factory=dict)
    cifras: list[str] = field(default_factory=list)

    @classmethod
    def montar(cls, *, textos_docs: Iterable[str] = (), estruturados: Iterable[Any] = (),
               pipeline: Iterable[Any] = ()) -> "FontesDeFato":
        f = cls()
        docs = [str(t) for t in textos_docs if t]
        for t in docs:
            f._ler_texto(t)
        f.texto_docs = sem_acento("\n".join(docs))
        for obj in estruturados:
            f._ler_estruturado(obj)
        for e in pipeline or []:
            etapa = e.get("etapa") if isinstance(e, dict) else getattr(e, "etapa", "")
            status = e.get("status") if isinstance(e, dict) else getattr(e, "status", "")
            f.pipeline.append((sem_acento(etapa), sem_acento(status)))
        return f

    # ── leitura das fontes ────────────────────────────────────────────────

    def _ler_estruturado(self, obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            self.valores.append(float(obj))
            d = so_digitos(int(obj)) if float(obj).is_integer() else ""
            if len(d) >= _MIN_DIGITOS_ID:
                self.ids.add(d)
            return
        if isinstance(obj, dict):
            for v in obj.values():
                self._ler_estruturado(v)
            return
        if isinstance(obj, (list, tuple, set)):
            for v in obj:
                self._ler_estruturado(v)
            return
        if hasattr(obj, "model_dump"):
            self._ler_estruturado(obj.model_dump(mode="json"))
            return
        s = str(obj)
        if _RE_NUM_PURO.match(s):
            self.valores.append(float(s))
        self._ler_texto(s)

    def _ler_texto(self, texto: str) -> None:
        t = sem_acento(texto)
        for rx in (_RE_DATA_BR, _RE_DATA_PONTO):
            for m in rx.finditer(t):
                self._data(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        for m in _RE_DATA_EXT.finditer(t):
            self._data(int(m.group(1)), _MESES[m.group(2)], int(m.group(3)))
        for m in _RE_DATA_ISO.finditer(t):
            self._data(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        for m in _RE_MES_ANO.finditer(t):
            if _mes_ok(int(m.group(1)), int(m.group(2))):
                self.meses.add(f"{int(m.group(2)):04d}-{int(m.group(1)):02d}")
        for m in _RE_MES_ISO.finditer(t):
            if _mes_ok(int(m.group(2)), int(m.group(1))):
                self.meses.add(f"{int(m.group(1)):04d}-{int(m.group(2)):02d}")
        for m in _RE_MES_EXT.finditer(t):
            self.meses.add(f"{int(m.group(2)):04d}-{_MESES[m.group(1)]:02d}")
        for m in _RE_SEQ_DIGITOS.finditer(texto):
            d = so_digitos(m.group(0))
            if len(d) >= _MIN_DIGITOS_ID:
                self.ids.add(d)
        for mask in ids_no_texto(texto):
            d = so_digitos(mask)
            self.ids.add(d)
            self.ids_com_mascara.setdefault(d, mask)
        for trecho, v, _u in valores_no_texto(texto):
            self.valores.append(v)
            if trecho not in self.cifras:
                self.cifras.append(trecho)
        for m in _RE_CIFRA_SUFIXO.finditer(texto):
            v = _valor_br(m.group(1), m.group(2))
            if v is not None:
                self.valores.append(v[0])
        for m in _RE_NUM_MILHAR.finditer(texto):
            v = _valor_br(m.group(0))
            if v is not None:
                self.valores.append(v[0])

    def _data(self, d: int, m: int, a: int) -> None:
        if _data_ok(d, m, a):
            self.datas.add(f"{a:04d}-{m:02d}-{d:02d}")
            self.meses.add(f"{a:04d}-{m:02d}")

    # ── as regras ─────────────────────────────────────────────────────────

    def tem_data(self, chave: str) -> bool:
        return chave in (self.datas if len(chave) == 10 else self.meses)

    def tem_valor(self, valor: float, unidade: float) -> bool:
        tol = max(unidade, 0.01) * (1 + 1e-9)
        return any(abs(v - valor) < tol for v in self.valores)

    def sem_fonte(self, texto: str, citaveis: Optional[set[str]] = None) -> list[str]:
        """Os fatos do texto sem fonte (regra 11), na ordem do texto, sem repetição."""
        fora: list[str] = []
        for trecho, chave in datas_no_texto(texto):
            if not self.tem_data(chave):
                fora.append(trecho)
        for mask in ids_no_texto(texto):
            d = so_digitos(mask)
            if d not in self.ids and d not in (citaveis or set()):
                fora.append(mask)
        for trecho, v, u in valores_no_texto(texto):
            if not self.tem_valor(v, u):
                fora.append(trecho)
        return list(dict.fromkeys(fora))

    def _etapas_adm(self) -> list[tuple[str, str]]:
        return [(e, s) for e, s in self.pipeline
                if e and not any(k in e for k in _ETAPAS_NAO_ADM)]

    def _etapas_judiciais(self) -> list[tuple[str, str]]:
        return [(e, s) for e, s in self.pipeline if any(k in e for k in _ETAPAS_JUDICIAIS)]

    def esgotamento_sem_fonte(self, texto: str) -> list[str]:
        """Os termos de esgotamento sem lastro (regra 12), na ordem do texto.

        Esgotamento administrativo ("esgotad", "não foi admitido", ...): vale com todas
        as etapas administrativas do pipeline concluídas, ou com a decisão literal nos
        documentos. Trânsito: vale com uma etapa judicial concluída, ou com "transitado
        em julgado" literal nos documentos.
        """
        t = sem_acento(texto)
        fora: list[str] = []
        adm = [m.group(0) for m in _RE_ESGOTAMENTO_ADM.finditer(t)]
        if adm:
            etapas = self._etapas_adm()
            concluido = bool(etapas) and all(s.startswith("concluid") for _e, s in etapas)
            if not concluido and not _RE_DECISAO_ADM.search(self.texto_docs):
                fora += adm
        trans = [m.group(0) for m in _RE_TRANSITO.finditer(t)]
        if trans:
            concluido = any(s.startswith("concluid") for _e, s in self._etapas_judiciais())
            if not concluido and not _RE_DECISAO_TRANSITO.search(self.texto_docs):
                fora += trans
        return list(dict.fromkeys(fora))

    def permitidos(self) -> str:
        """A lista das datas e dos números que o texto pode citar, para o retry."""
        # A mais recente primeiro: a lista tem teto, e a data do caso é a recente.
        datas = [_br(d) for d in sorted(self.datas, reverse=True)]
        meses = sorted(self.meses - {d[:7] for d in self.datas}, reverse=True)
        ids = list(self.ids_com_mascara.values())
        partes = [f"datas permitidas: {', '.join(datas[:_MAX_PERMITIDOS]) or '(nenhuma)'}"]
        if meses:
            partes.append(f"meses permitidos: {', '.join(_br(m) for m in meses[:_MAX_PERMITIDOS])}")
        partes.append(f"números permitidos: {', '.join(ids[:_MAX_PERMITIDOS]) or '(nenhum)'}")
        if self.cifras:
            partes.append(f"valores permitidos: {', '.join(self.cifras[:_MAX_PERMITIDOS])}")
        return "; ".join(partes)

    def erros_do_slot(self, campo: str, texto: str,
                      citaveis: Optional[set[str]] = None) -> list[ErroDeCampo]:
        """Os erros estruturados das regras 11 e 12 para UM slot. Vazio: o slot passa."""
        erros: list[ErroDeCampo] = []
        fora = self.sem_fonte(texto, citaveis)
        if fora:
            erros.append(ErroDeCampo(campo=campo, erro=(
                f"{ERRO_FATO_SEM_FONTE}: {', '.join(fora)}. {campo}: a data ou o número não "
                "está no núcleo, nos documentos lidos, no esqueleto, nos alertas nem nas "
                "premissas. Tire o fato ou use um fato da lista. "
                f"{self.permitidos()} (regra 11, 23/10/2026)"), valor_anterior=texto))
        esg = self.esgotamento_sem_fonte(texto)
        if esg:
            erros.append(ErroDeCampo(campo=campo, erro=(
                f"{ERRO_ESGOTAMENTO_SEM_FONTE}: {', '.join(esg)}. {campo}: o esqueleto não "
                "marca a etapa concluída, e os documentos não trazem a decisão. Siga o "
                "pipeline do esqueleto: a etapa em andamento continua em andamento "
                "(regra 12, 23/10/2026)"), valor_anterior=texto))
        return erros


#: Os caminhos dos slots de texto na ficha (os mesmos de `prompts_v4._PATHS_SLOTS`).
_PATHS_SLOTS_TEXTO: tuple[tuple[str, ...], ...] = (
    ("descricao_infracao",),
    ("valor", "descricao"),
    ("processo_administrativo", "resumo"),
    ("ultima_decisao", "texto"),
    ("ultima_ocorrencia", "texto"),
    ("bullets",),
    ("merito",),
    ("observacao",),
    ("divida_ativa", "detalhe"),
)
_CHAVES_FORA_DA_FONTE = ("metadata", "nota_interna", "alerta")


def slots_de_texto(ficha: Any) -> dict[str, str]:
    """Os slots de texto de uma ficha, achatados: `{"bullets[0]": "...", "merito.p1": ...}`."""
    out: dict[str, str] = {}
    if not isinstance(ficha, dict):
        return out
    for path in _PATHS_SLOTS_TEXTO:
        node: Any = ficha
        for p in path:
            node = node.get(p) if isinstance(node, dict) else None
        nome = ".".join(path)
        if isinstance(node, str):
            out[nome] = node
        elif isinstance(node, list):
            out.update({f"{nome}[{i}]": v for i, v in enumerate(node) if isinstance(v, str)})
        elif isinstance(node, dict):
            out.update({f"{nome}.{k}": v for k, v in node.items() if isinstance(v, str)})
    return out


def sem_slots_de_texto(ficha: Any) -> Any:
    """A ficha sem os slots de texto e sem a metadata: o que é fato do código."""
    if not isinstance(ficha, dict):
        return ficha
    fatos = json.loads(json.dumps(ficha, default=str))
    for k in _CHAVES_FORA_DA_FONTE:
        fatos.pop(k, None)
    for path in _PATHS_SLOTS_TEXTO:
        node: Any = fatos
        for p in path[:-1]:
            node = node.get(p) if isinstance(node, dict) else None
        if isinstance(node, dict):
            node.pop(path[-1], None)
    return fatos


__all__ = [
    "AVISO_RENOVACAO_SEM_BLOCO",
    "CAMPO_ALERTAS",
    "CAMPO_SAIDA",
    "ERRO_ESGOTAMENTO_SEM_FONTE",
    "ERRO_FATO_SEM_FONTE",
    "FontesDeFato",
    "FRASE_SEM_CORRETOR",
    "ORIGENS_VALOR_FIXO",
    "RE_CIFRA",
    "RE_PROCESSO",
    "RE_STATUS_DIVIDA",
    "RE_VALOR_VARIAVEL",
    "avisos",
    "bloco_renovacao",
    "datas_no_texto",
    "ids_no_texto",
    "origem_valor",
    "renovacao_sem_corretor",
    "processos_citaveis",
    "processos_citaveis_brutos",
    "processos_no_texto",
    "sem_acento",
    "sem_slots_de_texto",
    "slots_de_texto",
    "so_digitos",
    "validar_alertas",
    "validar_campos",
    "valores_no_texto",
]
