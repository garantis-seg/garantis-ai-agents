"""Extração NATIVA por página (PyMuPDF) + casamento de bbox por offset.

ONDA 2 do desenho do Agente Investigador (DESENHO-INVESTIGADOR-2026-08-13, §1.4
passos 2, 5 e 7). A onda 1 entregou o contrato puro no shared
(`calculo_fichas/documento.py` + `segmentacao.py`); aqui mora a metade que
**toca o PDF** — e é por isso que este módulo vive no ai-agents, junto de
`ocr_gate.py` e `vision.py` (*"reuse, não reescreva"*, RECON-ocr).

## A divisão de trabalho, e por que ela é assim

    doc_indexer/extracao.py   → PDF  → {pagina: texto}  + spans com bbox
    garantis_shared/segmentacao → texto → Sentenca/Paragrafo com sid/pid/offset
    doc_indexer/extracao.py   → offset → bbox            (casa de volta)

A segmentação **não** pode receber bbox: ela é pura e testada por AST no shared,
e coordenada é conhecimento de extrator. Mas a `Ancora` precisa de bbox — é a
única forma de reconferência humana em documento escaneado (`documento.py`,
docstring da `Ancora`). A costura é o `atribuir_bboxes`: a segmentação devolve
`offset` no texto canonizado da página, e aqui casamos esse offset de volta com
o span que o produziu.

⚑ O offset da segmentação é medido no texto **canonizado** (`canonicalizar`), e
o offset dos spans do PyMuPDF é medido no texto **cru**. Os dois não são o mesmo
número, e assumir que são produziria bbox apontando para a linha errada — que é
pior que bbox ausente, porque manda o humano olhar para o lugar errado e ele
conclui que a citação é falsa. Por isso o casamento não é por aritmética de
offset: é por reconstrução do mesmo mapa de posições que a `canonicalizar` faz.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "EXTRATOR_NATIVO",
    "SpanPagina",
    "doc_hash_de",
    "extractor_version_de",
    "abrir_pdf",
    "texto_nativo_por_pagina",
    "spans_por_pagina",
    "atribuir_bboxes",
]

#: Nome do extrator nativo. A VERSÃO vem do PyMuPDF instalado, em runtime — ver
#: `extractor_version_de`.
EXTRATOR_NATIVO = "pymupdf"

#: Sufixo de versão da NORMALIZAÇÃO/segmentação do shared. Bumpar quando
#: `segmentacao.py` mudar de forma que altere os IDs ou o texto emitido.
#:
#: ⚑ Este número é metade da chave de cache do `DocumentoIndexado`
#: (`(doc_hash, extractor_version)`, §7.2) e é o que invalida âncora quando a
#: segmentação muda. Esquecer de bumpar aqui é o risco nº 1 da pesquisa —
#: cache stale devolvendo IDs que apontam para outra frase — então ele NÃO é
#: derivado da versão da wheel (que muda por qualquer motivo, inflacionando
#: MISS) nem inferido: é declarado, e mudá-lo é decisão consciente.
NORM_VERSION = "norm-2"


def doc_hash_de(pdf_bytes: bytes) -> str:
    """`sha256` hex do PDF **cru** — a identidade do blob, não do texto.

    Cru, e não do texto extraído, porque é o `doc_hash` que responde "o PDF no
    GCS mudou entre o `/start` e o S2b?" (§1.6). Hash do texto responderia outra
    pergunta e deixaria passar troca de PDF que produz o mesmo texto.

    ⚑ `bytes()` explícito: `memoryview` vindo de coluna BYTEA do Postgres quebra
    `hashlib.update` em algumas versões e é exatamente o bug que o checklist do
    RECON-ocr lista primeiro (o mesmo que quebrava `types.Blob`).
    """
    return hashlib.sha256(bytes(pdf_bytes)).hexdigest()


def extractor_version_de(metodo_pagina: str, *, modelo_ocr: Optional[str] = None) -> str:
    """A string que vai na `Ancora.extractor_version`, e ela CODIFICA o método.

    Formatos (§1.2 do desenho):

        "pymupdf-1.28.2+norm-2"                  — página lida nativamente
        "ocr-gemini-3.1-flash-lite+norm-2"       — página lida por OCR

    O desenho é explícito ao mandar o método entrar na `extractor_version`, e a
    razão é a invalidação: reler por OCR uma página antes lida nativamente
    **muda o texto**, então as âncoras daquele documento têm que morrer. Se o
    método não estivesse aqui, a versão continuaria igual, a âncora continuaria
    "válida" e apontaria para um texto que não existe mais — o modo de falha
    silencioso que a `Ancora` inteira existe para acabar.

    ⚠️ Para documento MISTO a versão do documento é a do método dominante mas
    cada âncora carrega a da SUA página (ver `DocumentoIndexado` montado em
    `agent.py`): duas páginas do mesmo PDF podem ter sido lidas por caminhos
    diferentes, e mentir sobre isso é mentir sobre a força da citação.
    """
    if metodo_pagina == "ocr":
        alvo = modelo_ocr or "desconhecido"
        return f"ocr-{alvo}+{NORM_VERSION}"
    return f"{EXTRATOR_NATIVO}-{_versao_pymupdf()}+{NORM_VERSION}"


def _versao_pymupdf() -> str:
    try:
        import pymupdf

        return str(pymupdf.version[0])
    except Exception:  # pragma: no cover — sem pymupdf não há caminho nativo
        return "indisponivel"


class SpanPagina:
    """Um span de texto do PyMuPDF: o texto, onde ele começa, e a caixa dele.

    `inicio`/`fim` são offsets no texto CRU da página (o mesmo que
    `page.get_text("text")` produz, na mesma ordem de blocos), porque é esse o
    texto que a `canonicalizar` do shared recebe.
    """

    __slots__ = ("texto", "inicio", "fim", "bbox")

    def __init__(self, texto: str, inicio: int, bbox: tuple[float, float, float, float]):
        self.texto = texto
        self.inicio = inicio
        self.fim = inicio + len(texto)
        self.bbox = bbox

    def __repr__(self) -> str:  # pragma: no cover — debug
        return f"SpanPagina({self.texto[:20]!r}, {self.inicio}, {self.bbox})"


def abrir_pdf(pdf_bytes: bytes) -> Optional[Any]:
    """`pymupdf.Document` ou `None` — nunca levanta.

    O `None` não é teórico: 6 de 20 "PDFs" de uma amostra real do cohort do gate
    são HTML ou RTF servidos sob nome `.pdf` (`ocr_gate.analisar_pdf_bytes`
    documenta a medição). Quem chama trata o `None` como "documento ilegível" e
    devolve `success=false` — nunca um documento indexado vazio, que pareceria
    um PDF em branco legítimo.
    """
    try:
        import pymupdf
    except Exception as exc:  # pragma: no cover — dep declarada em requirements
        logger.warning("[doc_indexer] pymupdf indisponível: %r", exc)
        return None
    try:
        return pymupdf.open(stream=bytes(pdf_bytes), filetype="pdf")
    except Exception as exc:
        logger.warning("[doc_indexer] pymupdf.open falhou: %r", exc)
        return None


def texto_nativo_por_pagina(doc: Any) -> dict[int, str]:
    """`{pagina_1based: texto_cru}` para todas as páginas do documento.

    1-based porque é a numeração da FOLHA — a mesma de `Evidencia.pagina`, de
    `Sentenca.pagina` e do "confira fl. 5" que o analista recebe. Um 0-based
    aqui e 1-based lá produz citação off-by-one que só aparece quando o humano
    abre o PDF, e aí a confiança no sistema inteiro cai (`documento.py`,
    `_pagina_valida`).

    Página que não produz texto entra como `""` — a chave existe, o valor é
    vazio. Omitir a chave faria a página sumir da contagem e o gate não teria o
    que julgar.
    """
    out: dict[int, str] = {}
    for i, page in enumerate(doc, start=1):
        try:
            out[i] = page.get_text("text") or ""
        except Exception as exc:  # pragma: no cover — página corrompida isolada
            logger.warning("[doc_indexer] get_text falhou na pg %d: %r", i, exc)
            out[i] = ""
    return out


def spans_por_pagina(doc: Any) -> dict[int, list[SpanPagina]]:
    """`{pagina: [SpanPagina]}` — o texto com coordenada, na ORDEM do `get_text`.

    Reconstrói o offset acumulando exatamente as mesmas junções que o
    `get_text("text")` do PyMuPDF usa (`"\\n"` entre linhas, `"\\n"` entre
    blocos), porque é contra ESSE texto que o offset tem de valer. Reconstruir
    aproximadamente daria bbox deslocado — e bbox deslocado é pior que ausente.

    Falha em qualquer página ⇒ aquela página fica sem spans (bbox `None`), nunca
    derruba a indexação: perder a coordenada degrada a reconferência, perder o
    documento perde o número.
    """
    out: dict[int, list[SpanPagina]] = {}
    for i, page in enumerate(doc, start=1):
        spans: list[SpanPagina] = []
        cursor = 0
        try:
            blocos = page.get_text("dict").get("blocks") or []
        except Exception as exc:  # pragma: no cover
            logger.warning("[doc_indexer] get_text(dict) falhou na pg %d: %r", i, exc)
            out[i] = []
            continue
        for b in blocos:
            if b.get("type") != 0:  # 1 = imagem; não produz texto no get_text
                continue
            for linha in b.get("lines") or []:
                for span in linha.get("spans") or []:
                    txt = span.get("text") or ""
                    if not txt:
                        continue
                    bbox = span.get("bbox")
                    if bbox and len(bbox) == 4:
                        spans.append(SpanPagina(txt, cursor, tuple(float(v) for v in bbox)))
                    cursor += len(txt)
                cursor += 1  # o "\n" que o get_text põe no fim de cada linha
            cursor += 1  # o "\n" extra entre blocos
        out[i] = spans
    return out


def atribuir_bboxes(
    sentencas: tuple, spans: dict[int, list[SpanPagina]]
) -> tuple:
    """Devolve as sentenças com `bbox` preenchido onde deu para casar.

    ## Por que o casamento é por TEXTO e não por aritmética de offset

    A segmentação mede `offset` no texto **canonizado** da página
    (`canonicalizar`: NFKC, confusáveis, colapso de espaço horizontal). O span
    do PyMuPDF conhece o texto **cru**. As duas escalas divergem por cada
    ligadura desfeita, cada NBSP colapsado e cada soft-hyphen removido — e a
    divergência é acumulativa, então o erro cresce ao longo da página. Somar ou
    subtrair um delta constante não conserta: o delta não é constante.

    O que funciona é procurar a primeira palavra "gorda" da sentença no texto
    cru dos spans, a partir do span onde a sentença anterior parou. Palavra
    gorda (≥4 chars alfanuméricos) porque `de`/`e`/`do` casam em qualquer lugar
    e produziriam bbox aleatório.

    Não casou ⇒ `bbox=None`, que é um valor **legítimo e documentado** no
    contrato (`documento.py::_bbox_valida`: *"um bbox inventado seria pior que
    ausente"*). OCR sem coordenada cai aqui por construção, e é o caso comum.

    A bbox devolvida é a UNIÃO das caixas dos spans que a sentença cobre, na
    página — é a caixa que o humano quer ver destacada, não a da primeira
    palavra.
    """
    from garantis_shared.calculo_fichas.documento import Sentenca

    # cursor por página: o casamento é progressivo, como na segmentação. Sem
    # ele, a segunda ocorrência de uma frase repetida (cabeçalho, carimbo) casa
    # sempre na primeira e todas as sentenças da página apontam para o topo.
    cursor: dict[int, int] = {}
    # Quantas vezes a MESMA palavra-âncora já foi consumida no span sob o
    # cursor, por palavra. Um span é uma LINHA e uma linha carrega várias
    # sentenças — mas sentenças DIFERENTES têm âncoras diferentes, então a
    # contagem tem que ser por palavra, não por sentença: contar sentenças faria
    # a segunda frase de uma linha comum ser empurrada para a linha de baixo.
    consumos: dict[int, dict[str, int]] = {}
    out: list[Sentenca] = []
    for s in sentencas:
        pagina_spans = spans.get(s.pagina) or []
        if not pagina_spans:
            out.append(s)
            continue
        desde = cursor.get(s.pagina, 0)
        achado = _casar_span(
            s.texto_bruto, pagina_spans, desde, consumos.get(s.pagina) or {}
        )
        if achado is None:
            out.append(s)
            continue
        i_ini, i_ultimo, bbox = achado
        # ⚑ O cursor para NO último span da sentença, não depois dele. Um span do
        # PyMuPDF é uma LINHA, e uma linha de acórdão carrega tipicamente 2-3
        # sentenças ("…R$ 723.810.827,57. Nos termos do art. 142…"). Avançar para
        # `i_ultimo + 1` faria a sentença seguinte — que começa na MESMA linha —
        # procurar a partir da linha de baixo e não achar nada: ela sairia com
        # `bbox=None` mesmo estando perfeitamente localizável. Medido na
        # construção: 3 de 6 sentenças de uma folha de prosa normal perdiam a
        # coordenada por isso.
        #
        # Ficar no último span é seguro contra o retrocesso que o
        # `test_MUTACAO_bbox_nunca_anda_para_TRAS_na_pagina` prende, porque a
        # busca nunca olha para trás do cursor — no pior caso duas sentenças
        # compartilham a caixa da linha que de fato as contém, que é a verdade.
        novo = max(i_ini, i_ultimo)
        ancora = _primeira_ancora(s.texto_bruto)
        if novo != desde:
            consumos[s.pagina] = {}
        contagem = consumos.setdefault(s.pagina, {})
        if ancora:
            contagem[ancora] = contagem.get(ancora, 0) + 1
        cursor[s.pagina] = novo
        out.append(
            Sentenca(
                sid=s.sid,
                texto=s.texto,
                texto_bruto=s.texto_bruto,
                pagina=s.pagina,
                par_id=s.par_id,
                offset=s.offset,
                bbox=bbox,
            )
        )
    return tuple(out)


#: Piso de tamanho da palavra-âncora do casamento. `de`/`e`/`do` casam em
#: qualquer lugar da página; 4 chars é onde a colisão deixa de ser a regra.
_MIN_PALAVRA_ANCORA = 4


def _palavras_ancora(texto: str) -> list[str]:
    """As palavras "gordas" do texto, em ordem, minúsculas.

    Minúsculas porque o span pode trazer versalete/maiúscula de estilo que a
    canonicalização do shared não iguala — e o que se procura é a POSIÇÃO, não
    a igualdade literal (essa é responsabilidade do `sha_texto`).
    """
    import re

    return [
        p.lower()
        for p in re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+", texto)
        if len(p) >= _MIN_PALAVRA_ANCORA
    ]


def _primeira_ancora(texto: str) -> Optional[str]:
    """A palavra "gorda" pela qual esta sentença é procurada, ou `None`."""
    ancoras = _palavras_ancora(texto)
    return ancoras[0] if ancoras else None


def _casar_span(
    texto: str,
    spans: list[SpanPagina],
    desde: int,
    consumos: Optional[dict[str, int]] = None,
) -> Optional[tuple[int, int, tuple[float, float, float, float]]]:
    """`(indice_primeiro_span, indice_ULTIMO_span, bbox_uniao)` ou `None`.

    O último índice é **inclusivo** — é o span que ainda contém texto desta
    sentença, e é onde o cursor do `atribuir_bboxes` para (ver o comentário lá:
    uma linha carrega várias sentenças).

    `consumos` é `{palavra_ancora: vezes_já_casadas}` no span `desde`. Serve a um
    caso só, e é o da folha com frase repetida: se a linha tem 4 cópias de
    "Consideracoes do relator." e as 4 já foram consumidas, a 5ª sentença
    pertence à linha SEGUINTE. Sem isso todas as cópias da página empilhariam na
    mesma caixa — não seria uma caixa *errada* (a frase está lá), mas seria uma
    caixa inútil, apontando para a primeira linha de um bloco de sete.

    ⚑ A contagem é **por palavra**, não por sentença, e a diferença é o que
    separa este código de uma regressão: numa linha comum de acórdão as duas ou
    três sentenças têm âncoras DIFERENTES ("Fica…", "Nos…", "Recurso…"), e
    contar sentenças empurraria a segunda para a linha de baixo — que foi
    exatamente o bug medido (3 de 6 sentenças perdendo a coordenada).
    """
    ancoras = _palavras_ancora(texto)
    if not ancoras:
        return None
    primeira, ultima = ancoras[0], ancoras[-1]

    ja_usadas = (consumos or {}).get(primeira, 0)
    if ja_usadas and desde < len(spans):
        # A linha sob o cursor ainda tem uma cópia NÃO consumida desta âncora?
        # Só desce quando elas se esgotam.
        if spans[desde].texto.lower().count(primeira) <= ja_usadas:
            desde = desde + 1

    i_ini = _indice_do_span_com(spans, primeira, desde)
    if i_ini is None:
        # ⛔ NÃO reinicia a busca do topo da página. A tentação é grande — "melhor
        # um bbox fora de ordem que nenhum" — e ela está errada em texto que se
        # REPETE, que é o caso comum: cabeçalho, rodapé, carimbo e a frase de
        # fórmula do relator aparecem N vezes na mesma folha. Reiniciando, a
        # 9ª ocorrência casa na 1ª e a bbox aponta para o TOPO da página enquanto
        # a sentença está no rodapé.
        #
        # Isso é pior que `None` pela assimetria que `documento.py::_bbox_valida`
        # nomeia: bbox ausente degrada a reconferência (o humano ainda tem
        # `sid` + `pagina` + `texto_bruto` para achar a linha); bbox ERRADA manda
        # a pessoa olhar para o lugar errado, ela não encontra o trecho e conclui
        # que a citação é falsa — reprovando a evidência CERTA.
        return None
    i_fim = _indice_do_span_com(spans, ultima, i_ini)
    if i_fim is None:
        i_fim = i_ini

    x0 = min(spans[i].bbox[0] for i in range(i_ini, i_fim + 1))
    y0 = min(spans[i].bbox[1] for i in range(i_ini, i_fim + 1))
    x1 = max(spans[i].bbox[2] for i in range(i_ini, i_fim + 1))
    y1 = max(spans[i].bbox[3] for i in range(i_ini, i_fim + 1))
    return i_ini, i_fim, (x0, y0, x1, y1)


def _indice_do_span_com(spans: list[SpanPagina], palavra: str, desde: int) -> Optional[int]:
    for i in range(max(0, desde), len(spans)):
        if palavra in spans[i].texto.lower():
            return i
    return None
