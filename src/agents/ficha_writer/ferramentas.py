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
   há páginas). A função dona é `trecho_confere` (23/10/2026). Ela normaliza os
   2 lados (acento, caixa, aspas, travessão, hífen de fim de linha, quebra,
   espaço, pontuação dupla) e tira o cabeçalho de página. Depois ela tenta 3
   métodos: `literal`, `prefixo` (80 caracteres) e `similar` (difflib por token,
   no mínimo 0,90). Só reprova quando os 3 falham.

Determinismo máximo (plano 1.2, rodada real de 23/10/2026): o que o código
consegue consertar ou verificar, ele conserta ou verifica. Só reprova o que não
consegue (`Autos.verificar`):

- Trecho longo: o código corta o trecho no fim de palavra (`cortar_trecho`).
- Documento do núcleo: `paginas` é opcional. O código confere o texto inteiro.
- Documento do índice com página errada ou sem página: o código acha a página.
- Documento do índice que a fase A não leu: o código abre o documento (até 5
  documentos por ficha) e confere o trecho. Sem sucesso, o erro dá a lista dos
  documentos que o agente pode citar.
"""
from __future__ import annotations

import difflib
import functools
import json
import logging
import re
import unicodedata
from collections import Counter
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

#: Documentos não lidos na fase A que o código abre para conferir uma citação,
#: por ficha (23/10/2026). Budget separado do budget da fase A.
MAX_VERIFICACOES = 5


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


def cortar_trecho(texto: Any, limite: int) -> Any:
    """Corta o trecho em `limite` caracteres, no fim de palavra (23/10/2026).

    Um valor que não é texto volta igual: o schema dá o erro dele. O código nunca
    reprova um trecho por tamanho. Um prefixo do trecho literal continua literal.
    """
    if not isinstance(texto, str):
        return texto
    t = texto.strip()
    if len(t) <= limite:
        return t
    corte = t[:limite]
    if not t[limite].isspace():
        m = re.search(r"\s\S*$", corte)
        if m and m.start() > 0:
            corte = corte[:m.start()]
    # Um "..." cortado no meio deixa um pedaço que não está no documento.
    return corte.rstrip(" \t\n.…") or t[:limite]


# ── A conferência do trecho (23/10/2026) ────────────────────────────────────
#
# Rodada real IRB 1481420 (rev 00412): o redator reprovou `bullets[2]` 3 vezes.
# O trecho estava no acórdão, mas o cabeçalho da página seguinte ("Fl. 1094 / DF
# CARF MF / ...") cortava a frase no meio. O texto de PDF também traz hífen de fim
# de linha, espaço repetido e aspas e travessões de outro tipo. A função dona é
# `trecho_confere`. O v5 e o v3 usam só ela, pela `Autos.verificar`.

#: Prefixo normalizado do trecho que basta para a citação casar (23/10/2026).
PREFIXO_TRECHO = 80

#: Similaridade mínima (difflib, por token) entre o trecho e a janela do texto.
LIMIAR_SIMILAR = 0.90

#: Tokens mínimos do trecho para o método `similar`. Abaixo disso, o acaso casa.
MIN_TOKENS_SIMILAR = 8

#: Tokens raros do trecho que ancoram a busca da janela, e ocorrências por token.
_ANCORAS = 3
_MAX_OCORRENCIAS = 20

#: Palavras de negação. No método `similar`, uma negação a mais ou a menos reprova.
_NEGACOES = frozenset({"nao", "nem", "nunca", "jamais", "sem"})

#: Tokens de folga em cada borda da janela na conferência de grafia.
_FOLGA = 3

_ASPAS = str.maketrans({c: '"' for c in "\u201c\u201d\u201e\u201f\u00ab\u00bb\u2033"
                        "\u2018\u2019\u201a\u201b\u2032\u00b4`'"})
_TRACOS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"})


def _sem_hifen_de_quebra(texto: str) -> str:
    """Junta a palavra que o PDF partiu no fim da linha ("contribui-\\nções")."""
    texto = texto.replace("\u00ad", "")
    # Entre letras, o hífen de quebra sai. Entre dígitos ("3401-\n004"), ele fica.
    texto = re.sub(r"(\d)[-\u2010\u2011][ \t]*\r?\n\s*(?=\d)", r"\1-", texto)
    return re.sub(r"([^\W\d_])[-\u2010\u2011][ \t]*\r?\n\s*(?=[^\W\d_])", r"\1", texto)


def _normalizar(texto: str) -> str:
    """O texto na forma de comparar (23/10/2026).

    Sem acento, sem caixa, aspas e travessões unificados, hífen de fim de linha
    removido com a quebra, hífen entre letras removido ("negar-lhe" = "negarlhe"),
    toda sequência de espaço e quebra vira 1 espaço, sem espaço antes da pontuação e
    sem pontuação dupla.
    """
    t = _sem_hifen_de_quebra(texto or "")
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if not unicodedata.combining(c))
    t = t.casefold().translate(_ASPAS).translate(_TRACOS)
    t = re.sub(r"(?<=[^\W\d_])-(?=[^\W\d_])", "", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r" (?=[.,;:!?)\]])", "", t)
    t = re.sub(r"(?<=[(\[]) ", "", t)
    t = re.sub(r"([.,;:!?\"-])\1+", r"\1", t)
    return t.strip()


@functools.lru_cache(maxsize=256)
def normalizar(texto: str) -> str:
    """`_normalizar` com cache: o mesmo documento é conferido várias vezes por ficha."""
    return _normalizar(texto)


def _chave_de_linha(linha: str) -> str:
    return re.sub(r"\d+", "#", _normalizar(linha))


@functools.lru_cache(maxsize=64)
def _sem_cabecalho(texto: str) -> str:
    """O texto sem as linhas de cabeçalho e de rodapé de página.

    Uma linha é cabeçalho quando a forma dela (com os dígitos mascarados) se repete
    pelo menos 5 vezes e pelo menos metade das vezes da linha que mais se repete.
    Sem linha assim, o texto volta igual.
    """
    linhas = (texto or "").split("\n")
    contagem = Counter(k for k in map(_chave_de_linha, linhas) if k)
    if not contagem:
        return texto
    piso = max(5, contagem.most_common(1)[0][1] // 2)
    repetidas = {k for k, n in contagem.items() if n >= piso}
    if not repetidas:
        return texto
    return "\n".join(ln for ln in linhas if _chave_de_linha(ln) not in repetidas)


def _tokens(normalizado: str) -> list[str]:
    return re.findall(r"\w+", normalizado)


@dataclass(frozen=True)
class Casamento:
    """O resultado de `trecho_confere`. Vale como bool.

    `metodo`: `literal` (o trecho inteiro, ou cada pedaço entre "...", está no
    texto), `prefixo` (os primeiros 80 caracteres estão no texto) ou `similar`
    (similaridade por token de pelo menos 0,90 com uma janela do texto). None
    quando os 3 falham.
    """

    ok: bool
    metodo: Optional[str] = None
    similaridade: Optional[float] = None

    def __bool__(self) -> bool:
        return self.ok


def _literal(trecho: str, base: str) -> bool:
    pedacos = [normalizar(p) for p in re.split(r"\.\.\.|…", trecho or "")]
    pedacos = [p for p in pedacos if p.strip(" .")]
    return bool(pedacos) and all(p in base for p in pedacos)


def _prefixo(trecho_n: str, base: str) -> bool:
    if len(trecho_n) <= PREFIXO_TRECHO:
        return False
    corte = trecho_n[:PREFIXO_TRECHO].strip()
    return bool(corte) and corte in base


def _so_diferenca_de_grafia(alvo: list[str], janela: list[str]) -> bool:
    """As diferenças entre o trecho e a janela são só de grafia (OCR, plural, typo).

    Uma palavra trocada ("dar" por "negar") muda o sentido. Uma palavra a mais ou a
    menos só passa se ela é curta (até 3 letras, como "a" ou "de") e não é negação.
    A `janela` tem folga nas bordas: o texto a mais no início e no fim não conta.
    """
    ops = difflib.SequenceMatcher(None, alvo, janela, autojunk=False).get_opcodes()
    for k, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == "equal" or (op == "insert" and k in (0, len(ops) - 1)):
            continue
        a, b = alvo[i1:i2], janela[j1:j2]
        if op == "replace":
            if difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() < 0.8:
                return False
            continue
        if any(len(t) > 3 or t in _NEGACOES for t in a + b):
            return False
    return True


def _similar(trecho_n: str, base: str) -> float:
    """A melhor similaridade entre o trecho e uma janela do texto do mesmo tamanho.

    A busca anda 1 token por vez na vizinhança dos tokens raros do trecho. A janela
    só conta se tem todos os números do trecho ("721182" nunca casa com "721183") e
    se o resto da diferença é só de grafia (`_so_diferenca_de_grafia`): "foi
    admitido" nunca casa com "não foi admitido", e "dar provimento" nunca casa com
    "negar provimento".
    """
    alvo = _tokens(trecho_n)
    n = len(alvo)
    if n < MIN_TOKENS_SIMILAR:
        return 0.0
    texto = _tokens(base)
    if len(texto) < n:
        return 0.0
    freq = Counter(texto)
    raros = sorted({t for t in alvo if len(t) >= 4 and t in freq}, key=lambda t: (freq[t], t))
    numeros = {t for t in alvo if any(c.isdigit() for c in t)}
    posicoes = {}
    for i, t in enumerate(texto):
        if t in raros[:_ANCORAS]:
            posicoes.setdefault(t, []).append(i)
    inicios: set[int] = set()
    for t in raros[:_ANCORAS]:
        for p in posicoes.get(t, [])[:_MAX_OCORRENCIAS]:
            inicios.update(range(max(0, p - n + 1), min(p, len(texto) - n) + 1))
    sm = difflib.SequenceMatcher(None, autojunk=False)
    sm.set_seq2(alvo)
    melhor = 0.0
    for i in sorted(inicios):
        janela = texto[i:i + n]
        sm.set_seq1(janela)
        if sm.real_quick_ratio() < LIMIAR_SIMILAR or sm.quick_ratio() < LIMIAR_SIMILAR:
            continue
        r = sm.ratio()
        if r <= melhor:
            continue
        if not numeros <= set(janela):
            continue
        if not _so_diferenca_de_grafia(alvo, texto[max(0, i - _FOLGA):i + n + _FOLGA]):
            continue
        melhor = r
    return melhor


def trecho_confere(trecho: str, texto: str) -> Casamento:
    """O trecho citado está no texto do documento? (23/10/2026)

    Normaliza os dois lados (`normalizar`) e tenta, em ordem: `literal`,
    `prefixo` e `similar`. Tenta também o texto sem cabeçalho de página
    (`_sem_cabecalho`). Erro só quando os 3 métodos falham.
    """
    if not (trecho or "").strip() or not (texto or "").strip():
        return Casamento(False)
    trecho_n = normalizar(trecho)
    bases = [normalizar(texto)]
    limpo = _sem_cabecalho(texto)
    if limpo != texto:
        bases.append(normalizar(limpo))
    for metodo, teste in (("literal", lambda b: _literal(trecho, b)),
                          ("prefixo", lambda b: _prefixo(trecho_n, b))):
        if any(teste(b) for b in bases):
            return Casamento(True, metodo)
    melhor = max(_similar(trecho_n, b) for b in bases)
    if melhor >= LIMIAR_SIMILAR:
        return Casamento(True, "similar", round(melhor, 3))
    return Casamento(False, similaridade=round(melhor, 3) if melhor else None)


#: O erro quando os 3 métodos de `trecho_confere` falham.
_ERRO_SEM_TRECHO = ("o trecho não está no documento citado (o código comparou o texto "
                    "normalizado, o prefixo de 80 caracteres e a similaridade)")


@dataclass
class Conferencia:
    """O resultado de `Autos.verificar`. `erro=None` quer dizer citação aceita.

    `paginas` são as páginas certas do trecho (o código corrige a página errada).
    `verificado_pelo_codigo=True`: a fase A não leu o documento, e o código abriu o
    documento e achou o trecho.
    """

    erro: Optional[str] = None
    paginas: list[int] = field(default_factory=list)
    verificado_pelo_codigo: bool = False
    paginas_corrigidas: bool = False
    #: Como o trecho casou (`trecho_confere`): literal, prefixo ou similar.
    metodo: Optional[str] = None


def _texto_da_pagina(doc: Any, pagina: int) -> str:
    return " ".join(
        (s.texto_bruto or s.texto) for s in doc.sentencas_da_pagina(pagina)
    ).strip()


# ── O núcleo legível no prompt (23/10/2026) ─────────────────────────────────
#
# O shared 1.826 manda as CDAs e os metadados como dicts aninhados. Em JSON cru, o
# LLM lê mal um dict de 4 níveis. Aqui cada CDA vira uma linha, e cada metadado vira
# uma linha `caminho: valor`. Os documentos entram com o texto inteiro.

#: Profundidade máxima do caminho de um metadado. Abaixo dela, o valor vai em JSON.
_MAX_PROF_METADADO = 4


def _vazio(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _linha_de_item(item: Any) -> str:
    """Um dict vira `chave: valor; chave: valor`. Os valores vazios ficam fora."""
    if not isinstance(item, dict):
        return str(item)
    partes = []
    for k, v in item.items():
        if _vazio(v):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False, default=str)
        partes.append(f"{k}: {v}")
    return "; ".join(partes) or "(sem dado)"


def cdas_legiveis(cdas: Any) -> list[str]:
    """As CDAs do núcleo, uma linha por item. Aceita a forma do shared e a lista antiga."""
    if cdas is None:
        return []
    if isinstance(cdas, list):
        return [f"CDA {i}: {_linha_de_item(c)}" for i, c in enumerate(cdas, 1)]
    dados = cdas.model_dump(mode="json") if hasattr(cdas, "model_dump") else dict(cdas)
    linhas: list[str] = []
    da = dados.get("divida_ativa")
    if isinstance(da, dict):
        resumo = {k: v for k, v in da.items() if not isinstance(v, list)}
        linhas.append(f"Dívida ativa (esqueleto): {_linha_de_item(resumo)}")
        for k, v in da.items():
            if isinstance(v, list):
                linhas += [f"Dívida ativa, {k} {i}: {_linha_de_item(x)}"
                           for i, x in enumerate(v, 1)]
    elif da is not None:
        linhas.append(f"Dívida ativa (esqueleto): {da}")
    for i, m in enumerate(dados.get("inscricoes_membros") or [], 1):
        linhas.append(f"Inscrição membro do conexo {i}: {_linha_de_item(m)}")
    if dados.get("valor_cdas") is not None:
        linhas.append(f"Valor das CDAs (R$): {dados['valor_cdas']}")
    linhas.append(f"Dívida ativa verificada em: {dados.get('da_verificada_em') or 'sem data'}")
    extras = {k: v for k, v in dados.items() if k not in (
        "divida_ativa", "inscricoes_membros", "valor_cdas", "da_verificada_em")}
    if extras:
        linhas.append(f"Outros dados das CDAs: {_linha_de_item(extras)}")
    return linhas


def metadados_legiveis(meta: Any, prefixo: str = "", prof: int = 0) -> list[str]:
    """Os metadados, uma linha `caminho: valor` por folha. Os vazios ficam fora."""
    if _vazio(meta):
        return []
    if prof >= _MAX_PROF_METADADO or not isinstance(meta, (dict, list)):
        valor = (json.dumps(meta, ensure_ascii=False, default=str)
                 if isinstance(meta, (dict, list)) else meta)
        return [f"{prefixo}: {valor}"]
    itens = meta.items() if isinstance(meta, dict) else enumerate(meta)
    linhas: list[str] = []
    for k, v in itens:
        caminho = (f"{prefixo}[{k}]" if isinstance(meta, list)
                   else (f"{prefixo}.{k}" if prefixo else str(k)))
        linhas += metadados_legiveis(v, caminho, prof + 1)
    return linhas


def nucleo_legivel(nucleo: Nucleo) -> dict[str, Any]:
    """O núcleo do prompt: uma seção por item.

    - `documentos`: cada documento com o texto inteiro.
    - `cdas`: uma linha por CDA (`cdas_legiveis`).
    - `metadados`: uma linha por dado (`metadados_legiveis`). Uma chave que já tem
      seção própria no núcleo (`premissas_v3`) sai dos metadados.
    - `premissas_v3` e `qualificacao`: o JSON do shared, como veio.
    """
    out: dict[str, Any] = {}
    docs = [d.model_dump(include={"doc_id", "nome", "tipo", "papel", "processo", "data",
                                  "marca", "texto"}, exclude_none=True)
            for d in nucleo.documentos()]
    if docs:
        out["documentos"] = docs
    cdas = cdas_legiveis(nucleo.cdas)
    if cdas:
        out["cdas"] = cdas
    if nucleo.metadados:
        meta = {k: v for k, v in nucleo.metadados.items()
                if not (k == "premissas_v3" and nucleo.premissas_v3 is not None)}
        out["metadados"] = metadados_legiveis(meta)
    if nucleo.premissas_v3 is not None:
        out["premissas_v3"] = nucleo.premissas_v3
    if nucleo.qualificacao is not None:
        out["qualificacao"] = nucleo.qualificacao
    return out


class Autos:
    """O que o agente pode ler e citar, e o que ele leu de fato."""

    def __init__(
        self, nucleo: Nucleo, indice: list[ItemIndice],
        max_verificacoes: int = MAX_VERIFICACOES,
    ) -> None:
        from garantis_shared.calculo_fichas.documento import DocumentoIndexado

        self.nucleo = nucleo
        self.textos_nucleo: dict[str, str] = {d.doc_id: d.texto for d in nucleo.documentos()}
        self.indice: dict[str, ItemIndice] = {d.doc_id: d for d in indice}
        self.legiveis: dict[str, Any] = {}
        self.lidos: set[str] = set()
        #: Documentos que o código abriu para conferir uma citação (23/10/2026).
        self.abertos_pelo_codigo: set[str] = set()
        #: Os abertos em que o código achou o trecho citado.
        self.verificados: set[str] = set()
        self.max_verificacoes = max_verificacoes
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
        """O núcleo inteiro: a leitura obrigatória. Ver `nucleo_legivel`."""
        return nucleo_legivel(self.nucleo)

    def indice_para_llm(self) -> list[dict[str, Any]]:
        """O índice SEM o conteúdo: só os metadados e se dá para abrir."""
        out = []
        for doc_id, d in self.indice.items():
            doc = self.legiveis.get(doc_id)
            meta = d.model_dump(exclude={"documento_indexado", "gcs_path"}, exclude_none=True)
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

    def citaveis(self) -> list[str]:
        """Os doc_id que o agente pode citar: o núcleo, os lidos e os verificados."""
        out = list(self.textos_nucleo)
        out += sorted((self.lidos | self.verificados) - set(out))
        return out

    def _erro_com_lista(self, motivo: str) -> str:
        return (f"{motivo}. Cite só documentos desta lista: "
                f"{json.dumps(self.citaveis(), ensure_ascii=False)}")

    def _localizar(self, doc: Any, trecho: str) -> list[int]:
        """As páginas do documento em que o trecho está. Vazia: não achou."""
        return [p for p in sorted(set(doc.paginas()))
                if trecho_confere(trecho, _texto_da_pagina(doc, p))]

    def _abrir_para_verificar(self, doc_id: str) -> Optional[str]:
        """Abre um documento do índice que a fase A não leu. Devolve o erro, ou None."""
        if doc_id in self.abertos_pelo_codigo:
            return None
        if doc_id not in self.legiveis:
            return self._erro_com_lista(
                f"o documento {doc_id!r} não foi lido na fase A, e o código não consegue "
                "abrir o documento (sem conteúdo indexado)")
        if len(self.abertos_pelo_codigo) >= self.max_verificacoes:
            return self._erro_com_lista(
                f"o documento {doc_id!r} não foi lido na fase A, e o código já abriu "
                f"{self.max_verificacoes} documentos para conferir citações nesta ficha")
        self.abertos_pelo_codigo.add(doc_id)
        logger.info("FICHA_AUTOS_VERIFICACAO doc=%s n=%d", doc_id, len(self.abertos_pelo_codigo))
        return None

    def verificar(self, doc_id: str, paginas: list[int], trecho: str) -> Conferencia:
        """Confere a citação e conserta o que dá para consertar (23/10/2026).

        Ordem: o doc_id existe; o documento foi lido (ou o código abre o documento);
        o trecho está no documento. Ver o docstring do módulo.
        """
        paginas = list(paginas or [])
        if not self.existe(doc_id):
            return Conferencia(erro=self._erro_com_lista(
                f"doc_id fora do núcleo e do índice: {doc_id!r}"))
        pelo_codigo = not self.foi_lido(doc_id)
        if pelo_codigo:
            erro = self._abrir_para_verificar(doc_id)
            if erro:
                return Conferencia(erro=erro)

        # Documento do núcleo: o texto inteiro. `paginas` é opcional e não conta.
        texto_nucleo = self.textos_nucleo.get(doc_id, "")
        doc = self.legiveis.get(doc_id)
        if texto_nucleo.strip() or doc is None:
            casou = trecho_confere(trecho, texto_nucleo)
            if casou:
                return Conferencia(paginas=paginas, metodo=casou.metodo)
            return Conferencia(erro=_ERRO_SEM_TRECHO)

        # Documento do índice: as páginas citadas e, se não casar, o código acha a página.
        existentes = set(doc.paginas())
        citadas = [p for p in paginas if p in existentes]
        casou = (trecho_confere(trecho, "\n".join(_texto_da_pagina(doc, p) for p in citadas))
                 if citadas and len(citadas) == len(paginas) else Casamento(False))
        if casou:
            conf = Conferencia(paginas=citadas, metodo=casou.metodo)
        else:
            achadas = self._localizar(doc, trecho)
            metodo = "literal"
            if achadas:
                metodo = trecho_confere(
                    trecho, "\n".join(_texto_da_pagina(doc, p) for p in achadas)).metodo
            else:
                todas = "\n".join(_texto_da_pagina(doc, p) for p in sorted(existentes))
                casou = trecho_confere(trecho, todas)
                if casou:
                    # O trecho cruza a quebra de página.
                    achadas, metodo = citadas or sorted(existentes), casou.metodo
            if not achadas:
                motivo = ("o código abriu o documento, e o trecho não está nele"
                          if pelo_codigo else _ERRO_SEM_TRECHO)
                if paginas:
                    motivo += f" (páginas citadas {paginas}"
                    fora = [p for p in paginas if p not in existentes]
                    motivo += (f"; página que não existe no documento {doc_id!r}: {fora})"
                               if fora else ")")
                return Conferencia(erro=(self._erro_com_lista(motivo) if pelo_codigo
                                         else motivo))
            conf = Conferencia(paginas=achadas, paginas_corrigidas=achadas != paginas,
                               metodo=metodo)
            if conf.paginas_corrigidas:
                logger.info("FICHA_AUTOS_PAGINA_CORRIGIDA doc=%s de=%s para=%s",
                            doc_id, paginas, achadas)
        if pelo_codigo:
            self.verificados.add(doc_id)
            conf.verificado_pelo_codigo = True
        return conf

    def conferir_citacao(
        self, doc_id: str, paginas: list[int], trecho: str,
    ) -> Optional[str]:
        """Devolve o erro da citação, ou None. Ver `verificar`."""
        return self.verificar(doc_id, paginas, trecho).erro


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
    "MAX_VERIFICACOES",
    "LIMIAR_SIMILAR",
    "PREFIXO_TRECHO",
    "Autos",
    "Casamento",
    "BudgetNavegacao",
    "CircuitBreaker",
    "Conferencia",
    "ResultadoNavegacao",
    "cortar_trecho",
    "custo_da_resposta",
    "navegar",
    "normalizar",
    "perguntar_via_doc_reader",
    "resumir_via_doc_reader",
    "trecho_confere",
]
