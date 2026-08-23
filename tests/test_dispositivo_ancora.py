"""`dispositivo` — a ANCORA do veredito. Card RAIZ A ([869enpem7]).

## Por que este campo existe, e por que ele NAO e "mais uma regra"

A regra que ele serve **JA EXISTE** no `_REGRAS_CRUS`, palavra por palavra:

    natureza/tem_decisao: classifique pelo ATO DESTE documento, NAO pela decisao que ele
    menciona/transcreve.

O L1 a violou em prod: o card que dirige a banda do merito 13294 tem
`natureza='procedente'` e o `resumo_ato` INTEIRO e *"Comunicacao eletronica de sentenca
proferida nos autos dos Embargos a Execucao Fiscal n 50094492720244047009/PR."* — um AVISO,
que nao diz quem ganhou. A sentenca de verdade, no processo apontado (que esta no MESMO
merito, com 242 cards), diz **`extinto_sem_merito` por coisa julgada**. O oposto.

⇒ **Nao falta regra, falta VERIFICACAO.** Este campo nao julga nada novo: ele exige a PROVA
da regra que ja esta escrita.

## 🚨 E a justificativa e RESULTADO MEDIDO, nao preferencia

Tentei 4 detectores que NAO exigiam schema novo. Os 4 falharam
([[quatro-proxies-falharam-e-e-isso-que-justifica-a-ancora-2026-08-23]]):

| instrumento | resultado |
|---|---|
| lista de verbos dispositivos | 342 PNs, **~100% falso positivo** (faltava `julgando`, `deu provimento`, `reformou`...) |
| vocabulario de AVISO na abertura | 8 PNs, **~60% FP** — certidao que TRANSCREVE tem o desfecho |
| irmaos do mesmo merito na mesma DATA | 32 pares, **paradoxo do aniversario** (conexo de 483 membros = 17 deles) + abstencao lida como contradicao |
| contradicao ESTRITA | 6 pares, preciso — **mas nao pega o caso-alvo** |

⭐⭐ O resultado NEGATIVO e o achado: o defeito e *"o card afirma o que o documento nao
sustenta"*, e **nao existe sinal no dado que os separe, porque o card nao carrega o que o
sustenta**. Sem ancora nao HA detector — 4 tentativas provaram.

⭐ Com ela, o detector deixa de ser adivinhacao semantica e vira **um `IS NULL`**:
`tem_decisao=true` + natureza de merito + `dispositivo IS NULL` = o card ADMITE que nao tem
suporte.

## Escopo deste PR: BYTE-NEUTRO de proposito

Nada le o campo. A banda **nao se move**, entao nao ha flag a pedir nem OK a esperar — e essa
e a licao do #180, revertido por subir uma mudanca que ABAIXAVA banda sem flag. Primeiro o
instrumento, depois a medicao, so entao a decisao.

Run: pytest tests/test_dispositivo_ancora.py -q
"""
from __future__ import annotations

import inspect

import src.agents.mov_factsheet.prompts_v4 as p1
from src.agents.mov_factsheet.schemas_v4 import DecisaoBlockV4


def test_o_campo_existe_e_e_TEXTO_livre():
    """⛔ Nao e enum. O dispositivo e um trecho COPIADO — vocabulario fechado seria a 5a
    tentativa de aproximar semantica por lista, que e o que falhou 4 vezes."""
    assert "dispositivo" in DecisaoBlockV4.model_fields
    d = DecisaoBlockV4(dispositivo="julgo improcedentes os embargos a execucao fiscal")
    assert d.dispositivo.startswith("julgo improcedentes")


def test_ausente_e_None_e_isso_e_uma_RESPOSTA():
    """`null` significa "nao consegui apontar a frase" — que e o sinal util, nao uma falha.
    O default nao pode ser string vazia: '' e falsy igual a None e some no `IS NULL`."""
    assert DecisaoBlockV4().dispositivo is None


def test_o_acervo_inteiro_continua_VALIDO_sem_o_campo():
    """CONTRA-EXEMPLO de nao-regressao: 410k cards existentes nao tem `dispositivo`. Se ele
    nascesse obrigatorio, TODA releitura de card antigo falharia a validacao."""
    antigo = {"tem_decisao": True, "natureza": "procedente", "instancia": "1g"}
    assert DecisaoBlockV4(**antigo).dispositivo is None


def test_a_familia_de_campos_que_ja_existia_continua_de_pe():
    """CONTRA-EXEMPLO: acrescentar campo nao pode ter deslocado os vizinhos."""
    for nome in ("tem_decisao", "natureza", "transito_certificado",
                 "recorrente_polo", "requerente_polo"):
        assert nome in DecisaoBlockV4.model_fields, f"{nome} sumiu do schema"


def test_o_prompt_amarra_o_dispositivo_a_regra_que_JA_EXISTE():
    """⭐ O ponto do PR: o bullet nao introduz julgamento novo, ele exige a PROVA da regra de
    `tem_decisao`. Se as duas se separarem, o campo vira decoracao e o card volta a poder
    afirmar sem sustentar."""
    fonte = inspect.getsource(p1)
    i_regra = fonte.index("classifique pelo ATO DESTE documento")
    i_disp = fonte.index("- dispositivo:")
    assert i_regra < i_disp, "o dispositivo tem de vir DEPOIS da regra que ele prova"
    trecho = fonte[i_disp:i_disp + 700]
    assert "tem_decisao=false" in trecho, (
        "o bullet nao amarra dispositivo=null a tem_decisao=false — sem isso o card pode "
        "seguir afirmando veredito sem conseguir apontar onde"
    )
    assert "LITERAL" in trecho, "o bullet nao exige trecho COPIADO (parafrase nao e ancora)"


def test_a_regra_ORIGINAL_do_prompt_continua_intacta():
    """⛔ Este PR NAO reescreve a regra — ela ja estava certa e foi VIOLADA, nao mal escrita.
    Mexer nela seria a regra-atras-de-regra que o defeito nao pede."""
    fonte = inspect.getsource(p1)
    assert "classifique pelo ATO DESTE documento, NÃO pela decisão que ele" in fonte
    assert "MESMO que transcreva sentenças/acórdãos" in fonte
    assert "true SÓ com decisão material" in fonte
