"""Prompts do LEITOR — ele lê UM documento e cita por ID, ou declara a lacuna.

ONDA 4 do desenho (DESENHO-INVESTIGADOR-2026-08-13, §2, §2.2, §5.3). O Leitor é
o papel de janela ISOLADA: recebe o `DocumentoIndexado` inteiro daquele
documento e **nada do grafo**, nada dos outros documentos, nada da rodada. Essa
cegueira é o produto, não uma limitação: é o que impede o *telephone game* que a
pesquisa §4.1 nomeia como anti-padrão (3–10x tokens), e é o que faz a resposta
dele ser sobre o que o documento DIZ, não sobre o que o cálculo PRECISA.

## O texto com IDs injetados — formato XML do sui-1

    <fl5-s12>Fica mantida a exigencia de IRPJ no valor de R$ 723.810.827,57.</fl5-s12>

O formato é o do sui-1 (arXiv:2601.08472), cuja taxa de tags válidas medida é
95,2% — e é por causa desses 4,8% que o parser aqui **não confia na tag de
volta**: o modelo devolve os IDs num campo JSON separado (`citacoes`), e o
código confere cada um contra o `_por_sid` do documento. Um `sid` que não existe
é citação inventada e a resposta é rejeitada, não "quase aceita".

Usamos `texto_bruto` e não o normalizado: o normalizado é minúsculo e sem
tipográficos — bom para comparar, ruim para ler. O modelo tem que ver o
documento como o humano vê, senão "R$ 723.810.827,57" chega como outra coisa e
a leitura do número fica pior justamente onde ela mais importa.

## Anti prompt-injection

Mesmo padrão do calculador e do `ficha_writer` (QA-B1 achado B-3): fence com
boundary ALEATÓRIO por request e `neutralizar()` em todo texto de terceiro. Aqui
o vetor é o mais largo do sistema inteiro — o corpo de um PDF de terceiro entra
**inteiro** no prompt, que é literalmente a definição do papel. Um acórdão que
contenha `<fl9-s1>` no corpo não pode conseguir forjar uma citação, e é por isso
que a neutralização vem ANTES da injeção das tags nossas: as nossas são escritas
depois, sobre texto já neutro.

## O que o prompt EXIGE, e o que o código faz quando ele não obedece

Prompt não é enforcement — é a doutrina da casa e vale aqui inteira. O prompt
pede `confianca` e `objeto_da_confianca`; quem **rejeita** o envelope sem eles é
o `agent.py`, com retry e depois erro tipado. O prompt pede `[sid]` em toda
afirmação; quem valida com regex e confere contra o documento é o código.
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from garantis_shared.calculo_fichas.documento import DocumentoIndexado

from .._utils.prompt_fence import gerar_fence_token
from .._utils.prompt_fence import neutralizar as _neutralizar

__all__ = [
    "PROMPT_VERSION",
    "SID_RE",
    "prompt_version_hash",
    "montar_texto_indexado",
    "build_perguntar_prompt",
    "build_resumir_prompt",
    "sids_citados_no_texto",
]

#: Versão do prompt. Entra na chave de cache (§7.1) — **e é por isso que ela é
#: um fato, não um TTL**: deploy de prompt orfana as entradas antigas por
#: construção. Bumpar isto é o gesto deliberado de invalidar o cache do Leitor.
PROMPT_VERSION = "doc-reader/v1"

#: O formato de ID do §1.3: `fl{pagina}-s{ordinal}` para sentença, `-p` para
#: parágrafo. Ancorado nas duas pontas para não casar `fl5-s12x` nem sufixo de
#: outra coisa. O Leitor cita sentenças (é a política `span` do §4.1, e é onde
#: mora o número); parágrafo é do Verificador e da fundamentação.
SID_RE = re.compile(r"^fl\d+-s\d+$")

#: A mesma coisa, para VARRER prosa atrás de `[fl5-s12]`. Separado do de cima
#: de propósito: um valida um id isolado, o outro acha ids dentro de texto, e
#: colar os dois num regex só faria a validação aceitar lixo ao redor.
_SID_EM_TEXTO_RE = re.compile(r"\[(fl\d+-s\d+)\]")


def prompt_version_hash() -> str:
    """`sha256[:12]` do PROMPT_VERSION + dos templates. A chave de cache do §7.1.

    Não é o `PROMPT_VERSION` cru porque a string é editável à mão e o gesto de
    esquecer de bumpá-la é exatamente o que produz cache stale — o risco nº 1 do
    desenho inteiro. Hashear o CORPO dos templates faz a invalidação acontecer
    mesmo quando o humano esquece: mudou uma palavra do prompt, mudou a chave.

    ⚑ SHA-256, nunca `hash()` builtin: o builtin é salgado por processo
    (`PYTHONHASHSEED`) e daria chave diferente em cada container do Cloud Run.
    """
    corpo = "\x1f".join([PROMPT_VERSION, _REGRAS_LEITOR, _REGRAS_RESUMO, _PERSONA])
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:12]


# ── o documento, com os IDs injetados ───────────────────────────────────────

def montar_texto_indexado(
    doc: DocumentoIndexado, *, sids: Iterable[str] | None = None
) -> str:
    """O documento inteiro como `<fl5-s12>texto</fl5-s12>`, folha a folha.

    `sids=None` (o caso normal) manda o documento **inteiro** — é a definição do
    papel: janela isolada, um documento, tudo dele. O parâmetro existe para o
    caller que já sabe o recorte (uma releitura de páginas específicas), não
    para o Leitor economizar contexto por conta própria.

    As folhas aparecem com `<folha n="5">` ao redor porque "fl. 5" é o
    vocabulário do domínio e o `sid` sozinho pede do modelo uma aritmética de
    string (`fl5-s12` → página 5) que ele erra. Dar a folha explícita custa
    poucos tokens e remove uma classe inteira de erro de localização.
    """
    filtro = set(sids) if sids is not None else None
    partes: list[str] = []
    pagina_atual: int | None = None

    for s in doc.sentencas:
        if filtro is not None and s.sid not in filtro:
            continue
        if s.pagina != pagina_atual:
            if pagina_atual is not None:
                partes.append("</folha>")
            partes.append(f'<folha n="{s.pagina}">')
            pagina_atual = s.pagina
        # Neutraliza ANTES de escrever a nossa tag: o texto do PDF é de
        # terceiro e um `<fl9-s1>` dentro dele forjaria uma citação. As tags
        # nossas são escritas depois, sobre texto já neutro.
        partes.append(f"<{s.sid}>{_neutralizar(s.texto_bruto)}</{s.sid}>")

    if pagina_atual is not None:
        partes.append("</folha>")
    return "\n".join(partes)


# ── persona e regras ────────────────────────────────────────────────────────

_PERSONA = (
    "Voce e um LEITOR de um unico documento tributario. Voce ve ESTE documento "
    "e mais nada: nao sabe qual e o calculo, nao sabe o que as outras pecas "
    "dizem, nao sabe o que a resposta 'deveria' ser.\n\n"
    "Isso e deliberado e e o seu valor. Quem sabe do calculo e outro agente, e "
    "se voce tentasse adivinhar o que ele quer ouvir, voce entregaria o que ele "
    "espera em vez do que o documento diz — que e exatamente o erro que voce "
    "existe para evitar.\n\n"
    "Voce so reporta o que esta ESCRITO nas folhas abaixo, sempre com o ID da "
    "sentenca. Voce nao calcula, nao soma, nao converte, nao infere valor que "
    "nao esteja escrito."
)

_REGRAS_LEITOR = """<regras>
REGRAS DURAS. Violar qualquer uma reprova a resposta inteira.

1. TODA AFIRMACAO CARREGA [sid]. Cada frase da sua `resposta` termina com o ID
   da sentenca que a sustenta, entre colchetes: [fl5-s12]. Uma frase que
   sustenta-se em duas sentencas leva as duas: [fl5-s12][fl5-s13]. Frase sem ID
   e frase sem fonte, e sera rejeitada.

2. CITE SO IDs QUE EXISTEM. Os IDs validos sao exatamente os que aparecem como
   tag no documento abaixo. Nao invente, nao extrapole a numeracao, nao cite
   uma folha que voce nao viu. Um ID inventado invalida a resposta inteira.

3. NAO ACHOU E RESPOSTA CERTA. Se o documento nao responde a pergunta, devolva
   `encontrou: false` e escreva em `lacuna` O QUE especificamente faltou ("o
   documento traz o IRPJ mas nao discrimina a multa isolada"). Isso e barato,
   util e esperado. Inventar, extrapolar ou responder vago e o unico erro
   grave — e "provavelmente e X" e resposta vaga.

4. COPIE, NAO REESCREVA. Numero se transcreve digito por digito, como esta
   escrito, com a pontuacao original. Nao arredonde, nao converta, nao
   normalize "R$ 1.234.567,89" para outra forma. Se o documento escreve por
   extenso, reporte as duas formas.

5. DISTINGA O QUE O DOMINIO CONFUNDE. Ao reportar um valor, diga SEMPRE de qual
   grandeza ele e. Os pares que se confundem, e que voce tem que separar:
   - principal x consolidado (com multa e juros)
   - base de calculo x credito tributario
   - valor lancado x valor mantido apos a decisao
   - o tributo deste processo x outro tributo citado de passagem
   - a decisao deste processo x o acordao paradigma citado nela
   Se o documento nao deixa claro qual e, isso e uma LACUNA, nao um palpite.

6. CONFIANCA EM CAMPO, COM OBJETO LITERAL. Os dois campos sao OBRIGATORIOS:
   - `confianca`: numero entre 0 e 1.
   - `objeto_da_confianca`: a frase LITERAL do que voce esta confiante. Nao o
     tema, nao "da resposta": a proposicao especifica.
   Exemplos do que e aceito:
     "de que o valor 723810827.57 e o que esta escrito no trecho citado"
     "de que este valor e o IRPJ PRINCIPAL mantido, e nao o credito consolidado"
     "de que o acordao citado e o que decide este processo, e nao o paradigma"
   Exemplos do que e REJEITADO:
     "alta" / "da resposta" / "do IRPJ" / "boa confianca na leitura"
   A diferenca importa: "85% confiante de que li o numero certo" nao e a mesma
   coisa que "85% confiante de que este e o numero que se pediu". Diga QUAL das
   duas voce quer dizer.
</regras>"""

_REGRAS_RESUMO = """<regras>
REGRAS DURAS. Violar qualquer uma reprova a resposta inteira.

1. TODA AFIRMACAO CARREGA [sid]. Vale igual ao da pergunta: cada frase do
   `resumo` termina com o ID da sentenca que a sustenta.

2. CITE SO IDs QUE EXISTEM. ID inventado invalida o resumo inteiro.

3. MISSAO E FILTRO, NAO ROTEIRO. Reporte o que o documento traz SOBRE a missao.
   O que o documento nao traz vira item de `lacunas` — nomeado e especifico, nao
   "faltam detalhes".

4. COPIE OS NUMEROS. Digito por digito, com a pontuacao original, dizendo de
   qual grandeza cada um e (principal x consolidado, base x credito, lancado x
   mantido). Numero sem grandeza declarada e numero inutil.

5. COBERTURA E MEDIDA, NAO IMPRESSAO. `cobertura` e a fracao das folhas que
   efetivamente tinham conteudo relevante para a missao e que voce leu, entre 0
   e 1. Se o documento e 200 folhas e so 12 falam da missao, e voce leu as 12, a
   cobertura e alta — a fracao e sobre o RELEVANTE, nao sobre o volume.

6. CONFIANCA EM CAMPO, COM OBJETO LITERAL. `confianca` (0 a 1) e
   `objeto_da_confianca` (a proposicao LITERAL) sao OBRIGATORIOS. "alta" ou "do
   resumo" sao rejeitados; "de que estas sao TODAS as exigencias mantidas no
   quadro da fl. 12, e nao um subconjunto" e aceito.
</regras>"""


# ── os dois prompts ─────────────────────────────────────────────────────────

def build_perguntar_prompt(doc: DocumentoIndexado, pergunta: str) -> str:
    """O prompt de pergunta pontual (`perguntar_ao_documento`, §2.2).

    A ORDEM é deliberada: persona → documento → pergunta → regras → schema. O
    documento vem cedo (o modelo precisa vê-lo antes de saber o que procurar,
    mesmo motivo pelo qual o `vision.py` põe os PDFs antes do prompt) e as
    regras vêm por último, como *recency anchor* — é o mesmo desenho do
    calculador, e a ordem lá nasceu de erro medido.
    """
    token = gerar_fence_token()
    return f"""{_PERSONA}

<documento-{token}>
{montar_texto_indexado(doc)}
</documento-{token}>

<pergunta-{token}>
{_neutralizar(pergunta)}
</pergunta-{token}>

{_metodo_do_documento(doc)}

{_REGRAS_LEITOR}

<formato_de_saida>
Devolva APENAS um objeto JSON, sem cerca de codigo, exatamente com estas chaves:

{{
  "resposta": "texto de no maximo 400 tokens, cada afirmacao terminando em [sid]",
  "citacoes": ["fl5-s12", "fl5-s13"],
  "encontrou": true,
  "lacuna": null,
  "confianca": 0.0,
  "objeto_da_confianca": "a proposicao LITERAL de que voce esta confiante"
}}

`citacoes` traz TODOS os IDs usados na resposta, sem repeticao, na ordem em que
aparecem. Quando `encontrou` for false, `resposta` fica curta, `citacoes` pode
vir vazia e `lacuna` e obrigatoria.
</formato_de_saida>"""


def build_resumir_prompt(doc: DocumentoIndexado, missao: str) -> str:
    """O prompt de missão ampla (`resumir_com_missao`, §2.2).

    É a ferramenta de PRIMEIRA passada num documento colossal — o Investigador
    chama esta antes de perguntar, para saber o que perguntar. Por isso o teto é
    2000 tokens e não 400: o produto aqui é um mapa do documento, e um mapa
    apertado demais faz o Investigador perguntar no lugar errado.
    """
    token = gerar_fence_token()
    return f"""{_PERSONA}

<documento-{token}>
{montar_texto_indexado(doc)}
</documento-{token}>

<missao-{token}>
{_neutralizar(missao)}
</missao-{token}>

{_metodo_do_documento(doc)}

{_REGRAS_RESUMO}

<formato_de_saida>
Devolva APENAS um objeto JSON, sem cerca de codigo, exatamente com estas chaves:

{{
  "resumo": "texto de no maximo 2000 tokens, cada afirmacao terminando em [sid]",
  "evidencias": ["fl5-s12", "fl12-s3"],
  "cobertura": 0.0,
  "lacunas": ["o que a missao pediu e o documento nao traz, nomeado"],
  "confianca": 0.0,
  "objeto_da_confianca": "a proposicao LITERAL de que voce esta confiante"
}}

`evidencias` e a lista de IDs, so os IDs — a folha de cada um o codigo resolve.
</formato_de_saida>"""


def _metodo_do_documento(doc: DocumentoIndexado) -> str:
    """Avisa o Leitor quando o texto veio de OCR — e por quê ele precisa saber.

    Num documento OCR a citação é contra o texto transcrito, nunca contra o PDF
    original (§7-risco-6), e o erro de leitura muda de natureza: deixa de ser
    "entendi errado" e passa a ser "o caractere pode estar errado". Um `0`/`O`
    trocado num valor é o modo de falha caro, e o Leitor é quem tem o texto na
    frente para desconfiar dele.
    """
    from garantis_shared.calculo_fichas.documento import METODO_NATIVE

    if doc.metodo == METODO_NATIVE:
        return ""
    return (
        f"<aviso_de_extracao>\n"
        f"Parte ou todo o texto acima veio de OCR (metodo: {doc.metodo}), nao do "
        f"PDF nativo. Digitos podem ter sido transcritos errado (0/O, 1/l, 5/S, "
        f"8/B). Ao reportar um numero de um trecho assim, diga no "
        f"`objeto_da_confianca` que a leitura e contra texto de OCR, e baixe a "
        f"confianca se o digito for ambiguo.\n"
        f"</aviso_de_extracao>"
    )


def sids_citados_no_texto(texto: str) -> list[str]:
    """Os `[fl5-s12]` que aparecem na prosa, na ordem, sem repetição.

    Serve ao gate de "afirmação sem citação": o `agent.py` compara as frases da
    resposta com o que esta função acha. Ordem preservada e sem repetição porque
    o consumidor é uma comparação de conjunto, mas a ordem ajuda o humano que lê
    o log da rejeição.
    """
    vistos: set[str] = set()
    out: list[str] = []
    for m in _SID_EM_TEXTO_RE.finditer(texto or ""):
        sid = m.group(1)
        if sid not in vistos:
            vistos.add(sid)
            out.append(sid)
    return out
