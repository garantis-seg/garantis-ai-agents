"""⚰️ `autor_polo` + PASSO 0 — REVERTIDOS em 2026-08-23 (decisao do Elton).

Lapide do PR #180. ⛔ Isto NAO diz "o problema nao existe" — diz que a SOLUCAO era o
proxy errado. O substituto (`acao_julgada`) e bem-vindo; o que nao volta e o proxy.

## O PROBLEMA, que continua vivo
Sentenca de EMBARGOS A EXECUCAO **trasladada** pros autos da EXECUCAO julga OUTRA acao:
la o autor e o EMBARGANTE, que e o EXECUTADO da execucao. O `<regra_polos>` bucketiza
pela CLASSE DO PROCESSO, entao inverte 100% desses casos. Medido: **29 cards / 22 PNs /
18 meritos (15 com apolice)** com o `sentido` invertido em prod.

## O QUE SE TENTOU, e por que foi revertido
`autor_polo` = *"qual polo DESTE processo e o autor da acao julgada"* + um PASSO 0 no
prompt do L2 mandando resolver a acao antes do bucket. Tres coisas mataram:

1. ⭐⭐ **E um PROXY OBLIQUO do sujeito.** Ele codifica "qual acao" como "qual polo",
   obrigando quem le a inverter de volta — e essa obliquidade GERA os casos especiais:
   - **interlocutoria**: nao ha como dizer "isto e incidente do proprio processo". Medido
     em prod: 2 dos 16 valores gravados estavam em `natureza='interlocutoria'` (embargos
     de DECLARACAO), violando a propria instrucao do L1.
   - **embargos de terceiro**: o embargante e TERCEIRO, nao esta em polo nenhum. O
     `Literal["ativo","passivo"]` **forca o L1 a mentir**.
   - **inversao espelho**: nos autos DOS PROPRIOS embargos a resposta vira, e a clausula
     saliente da instrucao nao vira junto. 169 PNs de classe 1118 expostos.
2. 🚨 **A mudanca ABAIXA banda e subiu sem flag.** A coorte se parte em duas metades de
   direcao OPOSTA — 19 `improcedente` (risco SOBE, certo) e **16 `procedente` (risco
   CAI)** — e a metade que cai nunca foi contada. Populacao exposta: 96 cards / 44
   meritos, **33 com apolice**, 21 deles em banda acima de `Baixo`. A regra da casa e
   *"ABAIXA banda ⇒ flag propria, default OFF, OK do Elton"*, e o PASSO 0 nao tinha
   flag nenhuma (`grep` em services.yaml + cloudbuild = 0).
3. 🚨 **A prova era CIRCULAR.** O flip do merito 13294 veio de um card cujo `resumo_ato`
   nao tem dispositivo. **8 dos 16** cards `procedente` da coorte estao nessa situacao,
   contra **0 de 19** na metade que sobe.

## A RAIZ, e o que a substitui
**O L1 emite o VEREDITO (`natureza`) sem emitir o SUJEITO do veredito.** `procedente` e
resposta a *"procedente do que?"*, pergunta que nunca e gravada — entao TODO consumidor
re-infere o sujeito e cada um erra do seu jeito (o L2 pela classe, o
`_papel_na_acao_julgada` do shared pelo `lado`+default, o PASSO 0 lendo prosa).

⇒ O substituto e **nomear a acao julgada DIRETO**, nao por proxy de polo. Com isso o
PASSO 0 inteiro DESAPARECE (o L2 bucketiza pela acao julgada em vez da classe), e somem
junto o gate por natureza, a exclusao de ED e a mentira dos embargos de terceiro —
conserto que REMOVE caso especial em vez de acrescentar.

⭐ O encanamento do #180 estava certo e fica de pe pro substituto: coluna em
`leitura_conexos.mov_factsheet` (mig `20260822_1600`), persistencia no garantis-shared
(#405/#407) e o render chave-a-chave do `_summarize_factsheet`. O cano e o certo; o que
passou por ele e que era a coisa errada.

Card: [869efuvwk](https://app.clickup.com/t/869efuvwk).
Run: pytest tests/test_autor_polo_revertido.py -q
"""
from __future__ import annotations

import inspect

import src.agents.mov_factsheet.prompts_v4 as p1
import src.agents.processo_synthesis.prompts as p2
from src.agents.mov_factsheet.schemas_v4 import DecisaoBlockV4
from src.agents.processo_synthesis.prompts import _summarize_factsheet
from src.agents.processo_synthesis.schemas import MovFactSheetMin


def _fs(**decisao):
    return MovFactSheetMin(mov_id="11111111-2222-3333-4444-555555555555",
                           data="2026-02-19", resumo_ato="Sentenca nos embargos",
                           decisao={"tem_decisao": True, **decisao})


def test_o_proxy_saiu_do_schema_do_L1():
    """⛔ `autor_polo` nao volta. `acao_julgada` (o sujeito DIRETO) e outra coisa."""
    assert "autor_polo" not in DecisaoBlockV4.model_fields


def test_os_polos_POR_ATO_que_sempre_existiram_continuam_de_pe():
    """CONTRA-EXEMPLO: sem isto, um revert exagerado que levasse a familia inteira
    passaria verde. `recorrente_polo`/`requerente_polo` sao de RECURSO e de INCIDENTE —
    perguntas que o ato responde sozinho, sem depender de qual acao foi julgada."""
    for nome in ("recorrente_polo", "requerente_polo", "natureza", "tem_decisao"):
        assert nome in DecisaoBlockV4.model_fields, f"{nome} caiu junto no revert"


def test_o_render_do_L2_nao_emite_mais_o_proxy():
    """O render escolhe CHAVE A CHAVE; o campo tem de ter sumido de la tambem, senao
    ficaria um emissor sem produtor (e um card antigo com o campo voltaria a falar)."""
    linha = _summarize_factsheet(_fs(natureza="procedente", autor_polo="passivo"))
    assert "autor_polo" not in linha, f"o render ainda passa o proxy pro LLM: {linha!r}"


def test_o_render_nao_perdeu_o_que_ja_emitia_antes_do_180():
    """Nao-regressao: o revert nao pode ter levado junto os campos originais da linha."""
    linha = _summarize_factsheet(_fs(natureza="improcedente", instancia="2g",
                                     sentido="desfavoravel", transito_certificado=True))
    for esperado in ("DECISAO improcedente", "2g", "desfavoravel", "(TRANSITO)"):
        assert esperado in linha, f"'{esperado}' sumiu do render. Linha: {linha!r}"


def test_o_PASSO_0_saiu_do_prompt_do_L2():
    """A ancora e o CABECALHO literal da regra, nao as palavras 'PASSO 0' — elas
    aparecem nesta lapide e num comentario, e ancora mais larga que a coisa guardada nao
    separa CITAR de EXISTIR (mutante que ja sobreviveu uma vez neste mesmo card)."""
    assert "PASSO 0 — DE QUAL ACAO E ESTA DECISAO?" not in inspect.getsource(p2)


def test_o_bucket_pela_CLASSE_continua_sendo_o_que_roda():
    """CONTRA-EXEMPLO do teste acima: o revert restaura o estado anterior, que E o bucket
    por classe. Se ele tambem tivesse sumido, o L2 ficaria sem regra de polo nenhuma —
    pior que o defeito que se tentou consertar."""
    fonte = inspect.getsource(p2)
    assert "PASSO 1 — Bucket pela classe:" in fonte
    assert "Embargos a Execucao, Excecao de Pre-Executividade:" in fonte


def test_o_bullet_do_proxy_saiu_do_prompt_do_L1():
    assert "autor_polo" not in inspect.getsource(p1)
