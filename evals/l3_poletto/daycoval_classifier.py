"""Classificador DETERMINISTICO do risco de acionamento — matriz Daycoval canonica.

Ground-truth OFICIAL (decisao Elton 2026-06-14): a regra e 100% Daycoval; Poletto
e so validacao de sucesso. Este classificador (a) e a REFERENCIA que mede o engine
atual, e (b) e o candidato a risco#2 do engine (LLM so extrai features; a matriz
decide o nivel).

Per-PROCESSO via os campos estruturados do card L2 (processo_synthesis), depois
agregado per-MERITO via MAX + Regra de Ouro #4 (RJ +1).

Fonte da matriz: garantis-app/src/lib/daycoval-matrix.ts (4 niveis x 3 materias +
5 Regras de Ouro). Espelhado aqui como logica executavel.

PROTOTIPO no eval pra iterar contra Poletto; promove pra garantis-shared quando
validado (vira o risco#2 do engine).
"""
from __future__ import annotations

_NIVEIS = ["Baixo", "Medio", "Alto", "Altissimo"]
_ORD = {n: i for i, n in enumerate(_NIVEIS)}


# ── Feature extraction (do card L2) ────────────────────────────────────────
def garantia_status(ps: dict) -> str:
    """viva | morta | pendente | desconhecida — colapso do ULTIMO evento do
    lifecycle_garantia por data. Sem eventos = desconhecida (merito e monitorado,
    apolice existe, mas os movs nao capturaram o estado — gap em ~51%)."""
    lc = ps.get("lifecycle_garantia") or []
    if not lc:
        return "desconhecida"
    last = sorted(lc, key=lambda e: (e.get("data") or ""))[-1]
    st = (last.get("status_pos") or "").lower()
    ev = (last.get("evento") or "").lower()
    if st == "aceito" or ev == "aceitacao":
        return "viva"
    if st in ("recusado", "levantado", "substituido") or ev in ("recusa", "levantamento", "substituicao"):
        return "morta"
    if st == "apresentado" or ev == "apresentacao":
        return "pendente"
    return "desconhecida"


def gatilho_consumado(ps: dict) -> bool:
    """Acionamento JA disparado — sinais FORTES de efetivacao na prosa.
    Conservador: penhora SO conta com efetivacao explicita (anti-falso-alto:
    termo de penhora != penhora efetivada)."""
    est = (ps.get("estado_processual") or "").lower()
    fortes = [
        "intimacao da seguradora", "intimada a seguradora", "pagamento pela seguradora",
        "seguradora para pagamento", "seguradora a pagar",
    ]
    if any(k in est for k in fortes):
        return True
    # penhora/bloqueio SO se efetivada (valor bloqueado/sequestrado)
    if ("penhora" in est or "bloqueio" in est or "sequestr" in est) and any(
        k in est for k in ["efetivad", "bloqueado", "sequestrad", "transferenc", "sisbajud positivo", "bacenjud positivo"]
    ):
        return True
    return False


def transacao_ativa(ps: dict) -> bool:
    """Regra de Ouro #3: acordo/REFIS/transacao = Baixo. So quando NAO ha
    descumprimento (descumprimento -> volta a subir, fora do escopo Baixo)."""
    est = (ps.get("estado_processual") or "").lower()
    tem = any(k in est for k in ["transac", "parcelamen", "refis", "desenrola", " acordo"])
    descumpriu = any(k in est for k in ["descumprimento", "descumpr", "inadimpl", "nao pagou", "rescis"])
    return tem and not descumpriu


# ── Matriz: (materia, decisao_vigente) -> nivel ────────────────────────────
def nivel_por_decisao(ps: dict) -> str:
    """Mapeia decisao_vigente -> nivel da matriz canonica (pressupoe apolice viva).

    Eixo direcao = sentido DO TOMADOR (favoravel=tomador ganhou); eixo fase =
    instancia + transito + recurso pendente. Regras de Ouro #1 (transito exige
    cert; sem recurso = Alto nao Altissimo) ja embutidas.
    """
    dv = ps.get("decisao_vigente") or {}
    sentido = dv.get("sentido")
    natureza = dv.get("natureza")
    instancia = dv.get("instancia")
    transito = bool(dv.get("transito_certificado"))
    recorrida = bool(dv.get("recorrida"))

    # Extincao sem merito = PROCESSUAL, nao consolida divida (anti-falso-alto) -> NEUTRO/Baixo.
    if natureza == "extinto_sem_merito":
        return "Baixo"

    # Sem decisao de merito (so interlocutoria/homologatoria/null) = fase pre-decisao.
    if sentido is None or natureza in ("interlocutoria", "homologatoria", None):
        # matriz Baixo: "apolice aceita p/ embargos SEM sentenca" / "aguarda aceitacao".
        return "Baixo"

    # Favoravel ao Tomador (procedente p/ ele) -> Baixo (matriz Baixo, qualquer instancia).
    if sentido == "favoravel":
        return "Baixo"

    # Desfavoravel (ou parcial) ao Tomador:
    desfav = sentido in ("desfavoravel", "parcial")
    if desfav:
        if transito:
            return "Altissimo"                      # Regra #1: transito desfav certificado
        if instancia in ("2g", "stj", "stf"):
            return "Alto"                            # mantido 2a/superior sem transito
        # 1a instancia:
        if recorrida:
            return "Medio"                           # 1g desfav + recurso pendente (efeito susp.)
        return "Alto"                                # 1g desfav SEM recurso (Regra #1: Alto)
    return "Baixo"


# ── Per-processo (short-circuit) ───────────────────────────────────────────
def classify_processo(ps: dict) -> str:
    # (0) gatilho consumado -> Altissimo (independe de tudo)
    if gatilho_consumado(ps):
        return "Altissimo"
    g = garantia_status(ps)
    # (1) garantia MORTA -> Baixo (sem apolice viva = sem acionamento; a matriz
    # nao modela morta). desconhecida NAO entra aqui (default = trata como presente).
    if g == "morta":
        return "Baixo"
    # (2) Regra de Ouro #3: transacao -> Baixo (override, mesmo com transito desfav)
    if transacao_ativa(ps):
        return "Baixo"
    # (3) matriz por decisao (pressupoe apolice viva/pendente/desconhecida=presente)
    return nivel_por_decisao(ps)


# ── Per-merito (agregacao) ─────────────────────────────────────────────────
def classify_merito(fixture: dict) -> str:
    """MAX dos processos (pior caso) + Regra de Ouro #4 (RJ +1, exceto Baixo)."""
    ps_list = fixture["payload"]["processo_syntheses"]
    if not ps_list:
        return "Baixo"
    niveis = [classify_processo(ps) for ps in ps_list]
    pior = max(niveis, key=lambda n: _ORD[n])
    # Regra #4: RJ vigente agrava +1 (exceto quando ja Baixo por suspensao da RJ).
    tom = fixture["payload"].get("tomador") or {}
    rj = bool(((tom.get("historico") or {}).get("rj_atual")) or "recupera" in (fixture["payload"].get("titulo") or "").lower())
    if rj and pior != "Baixo":
        i = min(_ORD[pior] + 1, 3)
        pior = _NIVEIS[i]
    return pior
