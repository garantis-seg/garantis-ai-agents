"""O PROMPT do CONFIRMADOR COMPARATIVO da peticao inicial (C5).

⛔⛔ **O TEXTO ABAIXO E VERBATIM E NAO SE REESCREVE.** `SISTEMA`, `USUARIO` e
`BLOCO` sao um PORTE byte-a-byte do arnes que MEDIU esta camada (o `d2_prompt.py`
da sessao de 08-09/09/2026). O placar que sustenta o C5 -- 21/22 afirmando certo
no gold adjudicado, 1/22 no CONTROLE NEGATIVO (o doc do gold REMOVIDO do
conjunto), Fisher exato 1-cauda p = 2,19e-11 -- foi medido com ESTE texto.
Reescrever, "melhorar", traduzir, acentuar ou enxugar um paragrafo **invalida a
medicao** e devolve esta camada ao C4 com outro nome.
⛔ E o C4 nao e hipotese: com o frame INDUTOR (1 doc isolado, "isto e a inicial?
s/n") ele respondeu `peticao_inicial` em 49,2% de 4.228 chamadas de producao
quando a verdade e ~3%, e fabricou os 411 cards errados que este pacote existe
pra desfazer.

## Os 4 INVARIANTES (o `garantis_shared` os lista e o PR e auditado contra eles)

O que separa o C5 do C4 e o FRAME, e o frame tem duas metades: a de la (uma
chamada, N candidatos numerados, `head` truncado, contrato 0..N) e a de ca, que
sao estes 4. ⛔ Ligar o endpoint sem qualquer um deles e reabrir o C4.

  1. COMPARATIVO          -- os N candidatos julgados JUNTOS numa chamada, nunca
                             um por vez. Mora em `USUARIO` ("CANDIDATOS ({n}
                             documentos...)" + "Escolha entre os candidatos [1] a
                             [{n}], ou 0 para NENHUM") e no bloco "QUANDO MAIS DE
                             UM CANDIDATO CARREGA A MESMA PECA" do `SISTEMA`.
  2. ABSTENCAO NOMEADA    -- secao "REGRA DE ABSTENCAO -- LEIA COM ATENCAO" do
                             `SISTEMA`: `escolhido = 0` e resposta CERTA e
                             esperada, "nao existe premio por escolher", "apontar
                             o documento errado e pior do que nao apontar nenhum".
  3. DECIDA PELO TEXTO    -- "Os titulos dos candidatos vem do sistema do
                             tribunal: sao frequentemente genericos, automaticos
                             ou enganosos. Decida pelo TEXTO, nao pelo titulo."
  4. RECUSE PECA DE OUTRO -- 1o item de "O QUE NAO E A PECA INAUGURAL": "Os autos
     PROCESSO                digitalizados costumam trazer copias integrais de
                             processos conexos, anteriores ou de outra instancia
                             -- essas copias comecam com a inicial DAQUELE
                             processo."

⭐ O guard e `tests/test_peticao_confirmador_rota.py::test_os_4_invariantes_...`,
que le ESTE arquivo e exige uma frase-ancora por invariante. Ele existe pra que
"enxugar o prompt" seja um teste vermelho, nao uma descoberta em producao.

## O que NAO esta aqui, e e deliberado

⛔ **Nenhum numero medido entra no prompt.** Nem taxa, nem barra, nem "quantos
costumam ser certos" -- so invariantes do que E / NAO E peca inaugural mais as
regras de decisao. Numero medido no prompt ensina o modelo a bater a meta, nao a
ler o documento.
⛔ **Nenhuma dica de qual candidato e a resposta**, e a DATA e o caso nomeado:
*"a inicial e o documento mais antigo"* e a heuristica que o degrau X1 ja aplica
sozinho e de graca, e oferece-la ao modelo lhe da como responder SEM ler -- que e
exatamente a diferenca entre o frame comparativo e o indutor. O bloco por
candidato do arnes que produziu o 21/22 e `titulo` + inicio do texto, e mais nada.
⛔ **A JANELA (`head_chars`) NAO mora aqui.** Ela e a defesa ESTRUTURAL contra
copia-integral e vive no `garantis_shared` (`_CONFIRMADOR_HEAD_CHARS = 3000`),
onde o guard dele a alcanca. Este modulo TRUNCA no valor que o request DECLARA --
nao num literal local, que seria uma segunda fonte de verdade a divergir em
silencio. O mecanismo esta medido: o unico falso-positivo do gold e do acervo e um
volume titulado "Copia integral do Mandado de Seguranca n. <OUTRO processo>", cuja
cabeca ate ~3.000 chars e capa + lista de andamentos (que o modelo recusa, certo)
e cujo enderecamento da inicial DAQUELE outro processo comeca no char **3.914**.
⇒ o paragrafo do invariante 4 **nao basta sozinho**; a janela e que fecha a porta.
"""

from __future__ import annotations

from typing import Any

# ⛔ VERBATIM do arnes de medicao. NAO EDITE. Ver o docstring do modulo.
SISTEMA = """Voce e um LOCALIZADOR de pecas processuais brasileiras.

Sua tarefa NAO e resumir nem julgar o merito de um documento. E escolher, entre
candidatos NUMERADOS, qual deles e a PECA INAUGURAL (a "peticao inicial") do
processo descrito -- ou responder que NENHUM deles e.

O QUE CARACTERIZA A PECA INAUGURAL DE UM PROCESSO
- Ela INSTAURA o processo: e a primeira peca dos autos, escrita pela parte que
  PROPOE a acao, antes de qualquer decisao do juizo neste processo.
- Ela e ENDERECADA ao juizo/orgao onde ESTE processo corre ("Excelentissimo
  Senhor Doutor Juiz...", "Ao Juizo da ... Vara...", "Egregio Tribunal...").
- Ela QUALIFICA quem propoe (nome, CNPJ/CPF, sede/endereco, procuradores) e
  nomeia contra quem se propoe.
- Ela NARRA os fatos, invoca o fundamento juridico e FORMULA PEDIDO ao juizo
  ("requer", "pede deferimento"), em geral com valor da causa.
- O nome da peca acompanha a classe do processo: execucao fiscal -> peticao
  inicial de execucao do exequente; embargos -> a peca que "apresenta os
  presentes embargos"; mandado de seguranca -> a impetracao; acao declaratoria /
  procedimento comum -> a peticao que "propoe a presente acao"; cautelar -> a
  peca que pede a tutela.
- E NORMAL que a peca inaugural se REFIRA a outro processo como objeto ou
  referencia (embargos referem a execucao embargada; mandado de seguranca refere
  o ato atacado; apelacao tem a acao de origem). Referir outro processo NAO a
  desqualifica.

O QUE NAO E A PECA INAUGURAL, AINDA QUE SE PARECA
- Peca inaugural de OUTRO processo: enderecada a outro juizo/comarca/tribunal, ou
  que PROPOE uma acao diferente da classe deste processo. Os autos digitalizados
  costumam trazer copias integrais de processos conexos, anteriores ou de outra
  instancia -- essas copias comecam com a inicial DAQUELE processo.
- Peticao intermediaria, manifestacao, impugnacao, contestacao, habilitacao,
  embargos/agravo/apelacao quando a classe deste processo e outra.
- Ato do JUIZO ou da serventia: decisao, sentenca, despacho, acordao, intimacao,
  citacao, certidao, mandado, alvara, oficio, termo de audiencia.
- Documento de INSTRUCAO anexado a uma peca: procuracao, substabelecimento,
  contrato social, certidao de junta comercial, CDA, guia de recolhimento,
  extrato, declaracao fiscal (DCTF/DARF/ECF), planilha de calculo, laudo,
  comprovante, apolice de seguro.
- Indice, capa, sumario, lista de pecas ou folha de rosto de um volume
  digitalizado.

QUANDO MAIS DE UM CANDIDATO CARREGA A MESMA PECA
Acontece de a mesma peca inaugural aparecer em mais de um candidato: o mesmo
arquivo juntado duas vezes, ou um VOLUME digitalizado que engloba a peca junto
com muitos outros documentos. Nesse caso escolha o candidato em que a peca e o
documento INTEIRO e comeca no inicio dele -- nao o volume que a contem no meio,
nem o arquivo cujo texto e majoritariamente outra coisa. Esse criterio olha para
o CONTEUDO do candidato; a posicao dele na lista nao entra na decisao.

QUANDO A PECA VEM PARTIDA
Acontece de a peca inaugural ser protocolada em partes numeradas ("parte 1",
"parte 2"), cada uma um candidato: a primeira abre enderecando o juizo e o texto
INTERROMPE no meio; a seguinte RETOMA de onde a anterior parou, sem novo
enderecamento e sem nova qualificacao. Nesse caso aponte como escolhido o
candidato em que a peca COMECA e liste os demais em `continuacao`, na ordem de
leitura.
⛔ `continuacao` e SO isto: o RESTO da mesma peca. Outra COPIA da peca, um
volume que a engloba, um anexo, um documento de instrucao ou qualquer peca
distinta NAO entram em `continuacao`. Na duvida, deixe `continuacao` vazia --
uma peca inteira num documento so e o caso comum.

REGRA DE ABSTENCAO -- LEIA COM ATENCAO
Responder "nenhum" (escolhido = 0) e uma resposta CERTA e esperada, nao uma
falha. Em muitos processos a peca inaugural simplesmente NAO esta entre os
documentos disponiveis, porque nunca foi digitalizada ou nunca foi comprada.
Aponte um candidato SOMENTE se o trecho que voce leu MOSTRAR as caracteristicas
acima. Se o candidato apenas PODERIA ser, se o trecho nao permite decidir, ou se
voce estaria supondo a partir do titulo, responda 0. Nao existe premio por
escolher, nem penalidade por se abster. Apontar o documento errado e pior do que
nao apontar nenhum.

Os titulos dos candidatos vem do sistema do tribunal: sao frequentemente
genericos, automaticos ou enganosos. Decida pelo TEXTO, nao pelo titulo.

FORMATO DA RESPOSTA
Responda no schema pedido, e nada alem dele.
  escolhido    = o NUMERO do candidato que e a peca inaugural DESTE processo,
                 ou 0 se NENHUM dos candidatos e. Use apenas numeros que
                 aparecem na lista de candidatos.
  continuacao  = lista de NUMEROS dos candidatos que sao a continuacao da MESMA
                 peca, na ordem de leitura. Vazia quando a peca cabe num
                 documento so, e sempre vazia quando `escolhido` e 0.
  motivo       = uma frase curta citando o que no TRECHO sustenta a resposta."""

# ⛔ VERBATIM do arnes de medicao. NAO EDITE.
USUARIO = """PROCESSO
  numero CNJ: {cnj}
  tribunal/orgao: {tribunal}
  classe: {classe}
  assunto: {assunto}
  polo ativo: {ativo}
  polo passivo: {passivo}

CANDIDATOS ({n} documentos; para cada um, o INICIO do texto)
{blocos}
Escolha entre os candidatos [1] a [{n}], ou 0 para NENHUM."""

# ⛔ VERBATIM do arnes de medicao. NAO EDITE.
BLOCO = """----- CANDIDATO [{i}]
titulo informado pelo tribunal: {titulo}
inicio do texto:
<<<
{head}
>>>
"""

# ⭐ Os CAPS do bloco PROCESSO sao do arnes, nao estetica: o payload medido levava
# `assunto` cortado em 200 chars e cada polo em 300. Polo de execucao fiscal com 40
# co-executados encheria a janela com nomes e empurraria os candidatos pra fora da
# atencao util. ⛔ Nao suba sem re-rodar os dois controles negativos.
_CAP_ASSUNTO = 200
_CAP_POLO = 300

# ⛔⛔ **SO ESTES 6 CAMPOS DO `processo` ENTRAM NO PROMPT.** E exatamente o que o
# arnes mediu. O payload do `garantis_shared` traz ainda `classe_cnj_code`,
# `materia`, `nm_tomador` e `cnpj_tomador` (vem do mesmo loader do L1-mov) e eles
# NAO entram: numero medido so descreve o payload medido. ⛔ E o `doc_key` do
# candidato tambem nao entra -- e identidade opaca, serve pro log do agent.
# ⭐ O guard e `test_o_payload_nao_vaza_metadado_pro_prompt`.
CAMPOS_DO_PROCESSO_NO_PROMPT = ("cnj", "tribunal", "classe", "assunto",
                                "polo_ativo", "polo_passivo")


def _ou(valor: Any, cap: int | None = None) -> str:
    """Valor do processo como o arnes o formatava: `"?"` quando vazio, cortado no cap.

    ⚠️ O arnes caia no proprio `pn` quando `cnj` vinha vazio; aqui nao ha `pn`
    separado no payload (o `cnj` E a chave), entao o fallback e o mesmo `"?"` dos
    outros campos. Na medicao o `cnj` nunca veio vazio, entao o ramo nao foi
    exercitado nem la nem ca.
    """
    texto = str(valor).strip() if valor not in (None, "") else ""
    if not texto:
        return "?"
    return texto[:cap] if cap else texto


def build_confirmador_prompt(
    processo: dict,
    candidatos: list[dict],
    head_chars: int,
) -> tuple[str, str]:
    """Monta `(sistema, usuario)` -- UMA chamada com os N candidatos JUNTOS.

    ⛔ Nao troque por N chamadas de 1 documento: esse e o frame INDUTOR, e ele esta
    medido em 4.228 chamadas de producao afirmando `peticao_inicial` em 49,2% dos
    C4 quando a verdade e ~3%.

    A NUMERACAO e a POSICAO na lista (1..N), que e como o `garantis_shared` decodifica
    o veredito (`candidatos[escolhido - 1]`). O campo `n` que chega em cada candidato
    e informativo -- quem manda e a posicao, para que um `n` fora de ordem nunca possa
    apontar o documento errado.

    O `head` e cortado em `head_chars` DECLARADO NO REQUEST. O caller ja o manda
    truncado; cortar de novo no MESMO valor e idempotente e nao cria segunda fonte de
    verdade -- o numero continua sendo dele.
    """
    blocos = "".join(
        BLOCO.format(
            i=i,
            titulo=(c.get("titulo") or "(sem titulo)"),
            head=(c.get("head") or "")[:head_chars],
        )
        for i, c in enumerate(candidatos, 1)
    )
    usuario = USUARIO.format(
        cnj=_ou(processo.get("cnj")),
        tribunal=_ou(processo.get("tribunal")),
        classe=_ou(processo.get("classe")),
        assunto=_ou(processo.get("assunto"), _CAP_ASSUNTO),
        ativo=_ou(processo.get("polo_ativo"), _CAP_POLO),
        passivo=_ou(processo.get("polo_passivo"), _CAP_POLO),
        n=len(candidatos),
        blocos=blocos,
    )
    return SISTEMA, usuario
