"""O checklist do auditor cego (S6), por bloco, com um ID por item.

Fonte: `docs/livro-da-ficha/compilado/checklist-auditor-ficha.md` do repo
carf-pipeline (`origin/main`, lido em 22/10/2026), mais as licoes do
`FEEDBACK-INSPETOR.md` (lote carf_esgotados_2026-09-23, R1-R27 e S1-S4) e do
`BRIEF-REVISOR.md` (lote resp_agravo_2s_2026-10-01).

Decisao de 22/10/2026 (DECIDI-SOZINHO, classe A): o compilado nao tem ID por
item. Este modulo da um ID a cada item, com o prefixo do bloco:

    KC-* kill-checks   H-* header      V-* valor      T-* timeline
    D-*  datas         S-* slot        TX-* texto     DA-* divida ativa
    F-*  fechamento

O ID do Livro que originou o item fica em `origem`. O prompt, o
`REGRAS_CONHECIDAS` e o README saem desta lista. Mude aqui, e os 3 mudam
juntos.

O QUE SAIU DO COMPILADO, e por que:
- Tudo que a S5 ja cobre com regra fixa: limite de caracteres, enum, formato
  de data, DV de CNPJ, CDA abreviada, lista negra E14/E19, taxa/premio, numero
  de bullets, "Garantis", fornecedor, "nao consultada", "remanescente", cifra
  em `valor.descricao`. O auditor confere so a FORMA NOVA que a regex nao pega.
- O que e do codigo de outra etapa: Selic por formula, mes desconhecido =
  junho, duplo calculo (S3). Recontagem depois da edicao (S5). Ficha
  regenerada (S7).
- Bloco 9 (render) e bloco 10 (lote): o auditor le o JSON de UMA ficha. Ele
  nao ve o PDF nem o lote.
"""

from dataclasses import dataclass
from typing import Literal

#: Em que balde o item cai quando falha.
#: "1"   = erro objetivo. O redator corrige.
#: "2"   = juizo de substancia. Pendencia. Nunca vai ao redator.
#: "1|2" = depende do caso. A regra geral dos baldes decide.
Balde = Literal["1", "2", "1|2"]


@dataclass(frozen=True)
class Item:
    id: str
    texto: str
    origem: str
    balde: Balde = "1|2"


@dataclass(frozen=True)
class Bloco:
    numero: int
    titulo: str
    itens: tuple[Item, ...]


BLOCOS: tuple[Bloco, ...] = (
    Bloco(0, "Kill-checks: o caso deveria existir?", (
        Item("KC-01",
             "Natureza do processo. PER/DCOMP de restituicao ou ressarcimento NAO gera "
             "ficha: e credito DO contribuinte. Sinal forte: serie 9xxxxx, 903xxx, "
             "940xxx ou 900xxx no numero.",
             "§0.2 · TIP-11, S6, B05-24, B05-25", "2"),
        Item("KC-02",
             "Quem ganhou. O classificador da base pode estar invertido (voto do relator "
             "vencido). Com Recurso de Oficio no bloco, leia o dispositivo. 'RO nao "
             "conhecido' NAO e vitoria do contribuinte.",
             "§3.4 · B22, S9", "2"),
        Item("KC-03",
             "Debito pago, parcelado, transacionado ou com apolice ja existente no dossie.",
             "§10.5 · B05-24", "2"),
        Item("KC-04",
             "Porte e capital muito abaixo de R$ 50 milhoes: ressalva de subscricao. "
             "Grau baixa, sempre. Apetite e decisao humana, nunca motivo para reter.",
             "§10.5 · B05-24 + §10.4 · S38, A27", "2"),
        Item("KC-05",
             "O mesmo debito aparece no dossie por outra frente (CARF, CDA, CNJ). "
             "Dedupe por DEBITO, nao por chave de origem.",
             "§10.5 · S37, TIP-07", "2"),
        Item("KC-06",
             "Substituicao: so carta VIGENTE vira ficha. Data-fim no passado = descarte. "
             "SG protocolado ha pouco = janela fechada. 'Carta fianca' e candidato, nao "
             "fato. Nunca ficha contra carta da propria Daycoval.",
             "§10.5 · A17-A20 + §0.2 · A22", "2"),
        Item("KC-07",
             "Uma ficha por oportunidade. Consolidar so com os 3 eixos iguais: mesmo "
             "contribuinte, mesmo merito ou fato gerador, mesmo estado processual.",
             "§0.1 · TIP-01, S36 + R27", "2"),
    )),
    Bloco(1, "Header e identidade", (
        Item("H-01",
             "Quem e o devedor HOJE? Incorporacao, venda de ativo, nova razao social. "
             "Ficha para a parte errada e inutil.",
             "§1 · A23"),
        Item("H-02",
             "CNPJ do estabelecimento certo (o DV e da S5). O auto pode ser contra uma "
             "filial: o numero da ficha tem de ser o do dossie.",
             "§1 · CON-14, S24, B05-35", "1"),
        Item("H-03",
             "Processo judicial E administrativo quando os dois existem no dossie, "
             "judicial primeiro.",
             "§1 · B05-07", "1"),
        Item("H-04",
             "EF: os 3 numeros aparecem e sao explicados (EF, CARF/TIT, divida ativa).",
             "§1.3 · CON-01", "1"),
        Item("H-05",
             "Cada tag tem lastro no dossie. 'voto_qualidade' so com voto de qualidade "
             "real. Multa qualificada so com 150%. Tag errada e afirmacao errada.",
             "§1.1 · S43 + R22", "1"),
        Item("H-06",
             "Tag ou slot 'triagem' so com incerteza REAL de garantia. Valor fechado em "
             "CDA confirmada nao e triagem.",
             "§1.1 · S43"),
        Item("H-07",
             "Substituicao: o banco emissor no topo e o banco que o dossie mostra.",
             "§1.2 · A13", "1"),
    )),
    Bloco(2, "Valor (o que mais custa errar)", (
        Item("V-01",
             "O valor do ESQUELETO e a verdade fixa. A prosa que diz outro valor, outra "
             "origem ou outra natureza do numero vai ao balde 1. Se o proprio valor do "
             "esqueleto parece errado diante do dossie, e balde 2.",
             "plano S3/S3b, 21/10/2026"),
        Item("V-02",
             "Reprodutibilidade: todo numero da prosa (valor, quorum, percentual, numero "
             "de acordao, votos) esta no dossie ou no esqueleto. Numero que nao esta la "
             "e invencao, mesmo plausivel.",
             "§2.1 · VAL-15", "1"),
        Item("V-03",
             "Base de calculo NAO e credito tributario. Total de saidas ou 'o maior valor "
             "do documento' apresentado como credito e o erro numero 1 da IA.",
             "§2.2 · S2, B05-06"),
        Item("V-04",
             "Provimento parcial: o valor e o saldo MANTIDO, nunca o lancamento cheio.",
             "§2.2 · S5"),
        Item("V-05",
             "Natureza bate com a composicao: AI = principal + multa + juros. DCOMP de "
             "debito nao homologado = tributo + juros, SEM multa de oficio.",
             "§2.3 · VAL-12, S6"),
        Item("V-06",
             "Multa citada na ficha com a ancora juridica do dossie. No TIT, a alinea do "
             "art. 85 da Lei 6.374/89 certa (o art. 85-B e distrator).",
             "§2.3 · B05-02 + §2.6 · S27", "1"),
        Item("V-07",
             "Estimativa rotulada como estimativa. Valor exato so com fonte primaria. "
             "Valor desconhecido com teto explicado PASSA. Numero inventado com cara de "
             "exato, nao.",
             "§2.2 · VAL-08 + §2.4 · S3, VAL-14, S25 + R15"),
        Item("V-08",
             "A 1a frase de valor.descricao diz O QUE o numero e: auto integral, saldo "
             "mantido, CDA consolidada, piso. Nunca um apresentado como o outro.",
             "§2.5 · S4/E22 + R13", "1"),
        Item("V-09",
             "Substituicao: valor exato, enquadrado como o valor da garantia, sem hedge e "
             "sem afirmar que o valor atual esta errado.",
             "§2.8 · VAL-11, A14", "1"),
    )),
    Bloco(3, "Timeline: a etapa corrente e a real?", (
        Item("T-01",
             "A etapa em_andamento do esqueleto e a real? Recurso pendente: a etapa dele "
             "e a corrente. Etapa futura marcada como atual e o erro de substancia mais "
             "caro do acervo. A prosa segue o esqueleto (balde 1). A discordancia com o "
             "proprio esqueleto e balde 2.",
             "§3.3 · S11"),
        Item("T-02",
             "Esgotou o CARF: a corrente e a Cobranca. Caso a caso, so com esgotamento "
             "inequivoco. Esgotamento duvidoso e balde 2.",
             "§3.3 · TML-01, TML-02 + R11", "2"),
        Item("T-03",
             "Escala pos-CARF: 'Em Encerramento'/CENCOP/COJUL e formalizacao, 'Expedido "
             "para PGFN' e inscricao a caminho, CDA inscrita e divida ativa. Nao promover "
             "um estagio ao seguinte.",
             "§3.3 · S12", "1"),
        Item("T-04",
             "DRJ: processo no CARF quer dizer DRJ desfavoravel (default forte). So "
             "desviar com o dispositivo da DRJ no dossie.",
             "§3.3 · S31"),
        Item("T-05",
             "O estado vem do ultimo ato DECISORIO, nunca do ultimo movimento de fila "
             "(triagem, expedicao, distribuicao, pauta, ata retificada). Resolucao = "
             "diligencia (processo vivo). Acordao = merito.",
             "§3.4 · TER-06, S47"),
        Item("T-06",
             "A peca lida INTEIRA: 'Indefiro o processamento do recurso' + 'enviado para "
             "a Cobranca' = esgotado. 'Defiro o processamento do Recurso Especial' = vivo. "
             "Nunca decidir por trecho, rotulo ou status.percentual.",
             "§3.4 · S46", "2"),
        Item("T-07",
             "Instancia pelo NUMERO e cabecalho do acordao, nunca pelo rotulo. Acordao "
             "9xxx ou 'Turma da CSRF' = CSRF. 'Xa TO-Xa Camara' = CARF. 'DRJ-XXX' = DRJ.",
             "§3.4 · S10", "1"),
        Item("T-08",
             "Sujeito processual de cada movimento: contribuinte, solidario, Fazenda, de "
             "oficio. Inadmissao de recurso DA FAZENDA nao e derrota do contribuinte. "
             "Agravo herda a autoria do RE anterior.",
             "§3.4 · S30 + BRIEF-REVISOR", "1"),
        Item("T-09",
             "Embargos pelo VERBO do dispositivo: acolhidos COM efeitos infringentes "
             "reabrem. Rejeitados, nao conhecidos ou acolhidos SEM infringentes sao "
             "transparentes.",
             "§3.4 · S29"),
        Item("T-10",
             "Embargos, diligencia e CENCOP vao no SUBTITULO, nunca como etapa propria.",
             "§3.1 · B03, S32", "1"),
        Item("T-11",
             "'Nao conhecido' NAO e 'negado no merito'. A prosa que troca um pelo outro "
             "erra o fato.",
             "§5.1 · TER-04", "1"),
    )),
    Bloco(4, "Datas", (
        Item("D-01",
             "ultima_decisao.data e a data da SESSAO, nunca a da publicacao ou da "
             "intimacao. E o erro de data mais recorrente do acervo.",
             "§4 · S7", "1"),
        Item("D-02",
             "Coerencia campo x texto: um campo estruturado diz uma data e a prosa diz "
             "outra. Reprove o campo de TEXTO que diverge do dossie.",
             "§4 · S40", "1"),
        Item("D-03",
             "Hierarquia da fonte de data: capa do acordao ou despacho > andamento cru > "
             "timeline derivada. A prosa usa a fonte de maior hierarquia do dossie.",
             "§3.4 · S8", "1"),
        Item("D-04",
             "ultima_decisao e DECISAO de merito (acordao), nao despacho de "
             "admissibilidade. ultima_ocorrencia e o andamento POSTERIOR a decisao, com "
             "outra data.",
             "FEEDBACK-INSPETOR S3 + R16", "1"),
    )),
    Bloco(5, "Slot central (termometro, triagem, fianca)", (
        Item("S-01",
             "O termometro e o do ESQUELETO (regua fixa da S3b). A prosa que narra outra "
             "temperatura vai ao balde 1. A discordancia com a regua e balde 2.",
             "§5.1 · S35, S9 + plano S3b"),
        Item("S-02",
             "A regua: muito_quente = esgotado de fato (CDA, agravo barrado ou RE negado "
             "no merito pela CSRF). quente = perdeu, mas cabe um passo formal. morno = "
             "perda sem bola com o contribuinte. frio = processo vivo.",
             "§5.1 · TER-03, B05-36", "2"),
        Item("S-03",
             "Na duvida sobre ESGOTAMENTO, rebaixa. Esgotamento certo e duvida so de "
             "apetite: sobe uma casa.",
             "§5.1 · TER-05, B08", "2"),
        Item("S-04",
             "estado_da_bola: AGUARDA_FISCO sai do lote de cacada, mesmo com rotulo "
             "quente. Quem nao tentou a ultima instancia nao envia.",
             "§5.1 · TER-08, TER-01, TER-02, TER-07", "2"),
        Item("S-05",
             "Substituicao: bloco da carta de fianca coerente com o dossie (banco, "
             "vigencia). Numero e valor de face ausentes sao gap de FONTE, aceitavel com "
             "a nota interna.",
             "§5.3 · A43, A43b"),
        Item("S-06",
             "Substituicao: nenhuma afirmacao de gap ou insuficiencia da carta e nenhuma "
             "conviccao absoluta sobre o deferimento. A S5 pega a forma literal. Voce "
             "pega a forma nova.",
             "§5.3 · A45, A46", "1"),
    )),
    Bloco(6, "Bullets e texto do cliente", (
        Item("TX-01",
             "Cada bullet e autocontido e diz o que aconteceu e o que isso significa "
             "para a garantia.",
             "§6 · S49", "1"),
        Item("TX-02",
             "Nova apolice: o 4o bullet e o aviso de timing. O evento futuro conhecido "
             "do dossie esta la?",
             "§6 · B05-37, A20", "1"),
        Item("TX-03",
             "Substituicao: cada bullet responde a uma das 6 perguntas (apresentacao, "
             "movimentacoes, ainda ativa, SG apresentado, ainda necessaria, faz sentido "
             "dado o tempo).",
             "§6.1 · A20f, A21", "1"),
        Item("TX-04",
             "Nenhum bullet obvio ('e usuaria de seguro garantia', 'empresa de grande "
             "porte').",
             "§6 · B07 + R5", "1"),
        Item("TX-05",
             "Achado que nao muda valor, temperatura, tipo ou timing nao vira bullet.",
             "§6 · B05-43, CON-11", "1"),
        Item("TX-06",
             "Ressalva interna de subscricao nao aparece no texto do cliente, nem "
             "parafraseada. A S5 pega a copia literal da nota interna.",
             "§6 · CON-04 + §10.4 · S38, A24", "1"),
        Item("TX-07",
             "Persona de subscritor: comentario so factual. Sem vocabulario de vendedor "
             "('janela tipica de contratacao', 'oportunidade impar', 'momento "
             "estrategico', 'captura', superlativo).",
             "§7 · S15, B05-09, B05-10 + R18", "1"),
        Item("TX-08",
             "DISPOSITIVO x ALEGACAO DA PARTE x INFERENCIA NOSSA. Numero que no dossie "
             "esta na sintese das alegacoes da defesa nao e 'o que a decisao registra'. "
             "Alegacao se escreve como alegacao. Inferencia se marca como inferencia.",
             "§7 · S15 + R20", "1"),
        Item("TX-09",
             "Nada do nosso bastidor: vocabulario de esteira, quem pediu, prioridade, "
             "dificuldade NOSSA de obter documento, mecanica de calculo. A S5 pega a "
             "forma literal. Voce pega a forma nova.",
             "§7 · S14, B05-12 + R1-R4", "1"),
        Item("TX-10",
             "Linguagem deterministica sobre o futuro ('acontecera em breve', 'o proximo "
             "passo sera'). A S5 pega a lista negra. Voce pega a forma nova.",
             "E14/S13 + R20", "1"),
        Item("TX-11",
             "Cada fato tem UM dono. O mesmo fato dito em 3 ou 4 campos (esgotamento no "
             "bullet, no merito, na ocorrencia e no pipeline) e defeito. Bullet que "
             "repete o campo ao lado nao informa nada.",
             "R16 + FEEDBACK-INSPETOR S1", "1"),
        Item("TX-12",
             "Escopo do processo: nada de apolices da empresa, outras dividas ativas da "
             "raiz, perfil comercial ou relacionamento.",
             "R5, R6, R10", "1"),
    )),
    Bloco(7, "Divida ativa e ausencias", (
        Item("DA-01",
             "A CDA citada casa pelo NUMERO DO PROCESSO ADMINISTRATIVO desta ficha, nao "
             "por qualquer CDA do CNPJ.",
             "§8 · TIP-13 + R9", "1"),
        Item("DA-02",
             "Tres estados da consulta: (a) consultado e sem inscricao = 'Nao ha', com "
             "data. (b) consultado e defasado = o que a consulta de DD/MM mostrou. (c) "
             "NUNCA consultado = 'sem registro na base consultada', jamais 'nao tem'.",
             "§8.1 · S16 + R8", "1"),
        Item("DA-03",
             "Frescor: ausencia (de CDA, EF ou garantia) com consulta anterior ao evento "
             "terminal ou com mais de 30 dias. Pendencia, nao correcao.",
             "§8.2 · S39 + §8 · TIP-14", "2"),
        Item("DA-04",
             "Ausencia de garantia afirmada sem verificar anulatoria ou MS do "
             "contribuinte no dossie.",
             "§8.3 · B05-18, TIP-15, TIP-16"),
        Item("DA-05",
             "Achado judicial so contradiz a ficha se o polo passivo e a empresa E o "
             "processo se vincula AQUELE credito. Garantia de outro debito nao e deste.",
             "§8.3 · S19, S18", "1"),
        Item("DA-06",
             "Metadado de classe processual e sinal, nunca conclusao. Ausencia na API "
             "nao prova inexistencia.",
             "§8.3 · TIP-17, PRO-15", "1"),
        Item("DA-07",
             "Ficha TIT: 'sem execucao fiscal' e INFERENCIA e exige hedge no texto.",
             "§8.4 · S17", "1"),
        Item("DA-08",
             "Absoluto sobre ausencia sem data e fonte ('nao tem apolice', 'nao ha acao "
             "judicial'). A S5 avisa a forma literal (A31). Voce pega a forma nova.",
             "A31/S17", "1"),
    )),
    Bloco(8, "Coerencia cruzada e fechamento", (
        Item("F-01",
             "Passada final: pipeline, texto, valor, termometro e datas contam a MESMA "
             "historia. Execucao ajuizada nao e 'iminente'. Um fato com 2 versoes em 2 "
             "campos: reprove o campo que diverge do dossie.",
             "§10.3 · S40", "1"),
        Item("F-02",
             "Conexos: a ficha decidiu onde eles entram (corpo, nota interna ou lacuna "
             "declarada)?",
             "§7 · S41, B21", "2"),
        Item("F-03",
             "Nota interna, lida SO NO FIM: tem a secao 'nao confirmado / limitacoes'? "
             "Ela contradiz o corpo?",
             "§10.4 · S42 + §10.2 · S20"),
        Item("F-04",
             "Gabarito: a ficha diverge da ficha local aprovada do mesmo processo em "
             "FATO (data, valor, etapa, fase, quem recorreu)? Redacao diferente nao e "
             "divergencia.",
             "§10.6 · B25 + plano 1.3"),
    )),
)


#: IDs do Livro que o v1 aceitava. Ficam validos: um modelo ou um teste que
#: cite o ID do Livro direto nao perde a ancora.
REGRAS_DO_LIVRO_V1: frozenset[str] = frozenset({
    "S2", "S7", "S10", "S12", "S13", "S14", "S15", "S16", "S17", "S19",
    "S40", "S40-cross", "S44", "E14", "E19", "E14/S13", "E19/S14",
    "A31", "A31/S17", "S44/CON-05", "CON-05", "CON-11", "VAL-15", "TER-04",
    "B07", "B05-09", "B05-10", "B05-43", "B05-09/B05-10", "B05-43/CON-11",
})

ITENS: dict[str, Item] = {it.id: it for b in BLOCOS for it in b.itens}

#: IDs aceitos no campo `regra`. Fora desta lista, o item fica e leva a marca
#: "(ancora nao reconhecida)".
REGRAS_CONHECIDAS: frozenset[str] = frozenset(ITENS) | REGRAS_DO_LIVRO_V1

#: Itens que so cabem no balde 2. O redator nao conserta "o caso nao deveria
#: existir" nem "o esgotamento e duvidoso".
SO_BALDE_2: frozenset[str] = frozenset(i for i, it in ITENS.items() if it.balde == "2")


def checklist_texto() -> str:
    """O checklist inteiro, por bloco, no formato do prompt."""
    linhas: list[str] = []
    for b in BLOCOS:
        linhas.append(f"--- BLOCO {b.numero}. {b.titulo.upper()} ---")
        for it in b.itens:
            balde = {"1": "balde 1", "2": "SO balde 2", "1|2": "balde 1 ou 2"}[it.balde]
            linhas.append(f"[{it.id}] ({balde}) {it.texto}")
        linhas.append("")
    return "\n".join(linhas).rstrip()


__all__ = [
    "BLOCOS",
    "Bloco",
    "ITENS",
    "Item",
    "REGRAS_CONHECIDAS",
    "REGRAS_DO_LIVRO_V1",
    "SO_BALDE_2",
    "checklist_texto",
]
