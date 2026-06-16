"""Metricas de calibracao L3 (risco de acionamento) vs ground truth Poletto.

Dominio dos labels: Baixo < Medio < Alto < Altissimo (ordinal 1..4).
`Indeterminado` / None = engine nao opinou (nao entra no calculo de erro;
conta so na cobertura).

4 metricas (decisao Elton/diagnostico 2026-06-13):
- exact     : engine == poletto (4x4). Metrica de tuning.
- within1   : |engine - poletto| <= 1. Saude geral.
- false_alto: engine > poletto. Caro = infla priorizacao/alarme falso.
- false_baixo: engine < poletto. CARO = perde acionamento real (HARD constraint).
Otimizar: minimizar false_baixo (<=15%), depois false_alto, mantendo within1>=85%.

Reportar SEMPRE separando subset-resolvido de universo-total (indeterminado
distorce o denominador — foi como nasceu o falso "ceiling 26.7%").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

_ORD = {"Baixo": 1, "Medio": 2, "Alto": 3, "Altissimo": 4}
_LEVELS = ["Baixo", "Medio", "Alto", "Altissimo"]
_RESOLVED = set(_LEVELS)


def _ord(label: Optional[str]) -> Optional[int]:
    return _ORD.get(label or "")


@dataclass
class Pair:
    merito_id: int
    engine: Optional[str]    # risco final do engine (apos promote mode=new)
    poletto: Optional[str]   # ground truth
    # contexto opcional pro relatorio/decomposicao de erro
    llm_verdict: Optional[str] = None       # card['risco'] do LLM ANTES do promote
    factual_agg: Optional[str] = None
    juris_agg: Optional[str] = None
    derived: Optional[str] = None           # matriz 5x5 (o que promove)
    apolice_aceita: Optional[str] = None
    prob_exito: Optional[str] = None
    promoted: Optional[bool] = None         # matriz substituiu o LLM?


@dataclass
class Report:
    n_total: int = 0
    n_resolved: int = 0                       # engine opinou (nao-indeterminado)
    coverage: float = 0.0
    exact: float = 0.0
    within1: float = 0.0
    mean_signed: float = 0.0
    over: int = 0
    under: int = 0
    exact_n: int = 0
    false_alto_rate: float = 0.0
    false_baixo_rate: float = 0.0
    recall_alto_plus: float = 0.0             # Poletto in {Alto,Altissimo} -> engine >= Alto
    n_poletto_alto_plus: int = 0
    confusion: dict = field(default_factory=dict)   # confusion[engine][poletto]=n
    promoted_rate: float = 0.0                # % dos resolvidos onde a matriz substituiu o LLM
    final_eq_factual_rate: float = 0.0        # % onde final == factual_agg (matriz dominou)


def compute(pairs: Iterable[Pair]) -> Report:
    pairs = [p for p in pairs if p.poletto in _RESOLVED]  # so com label Poletto
    r = Report()
    r.n_total = len(pairs)
    if not r.n_total:
        return r

    resolved = [p for p in pairs if p.engine in _RESOLVED]
    r.n_resolved = len(resolved)
    r.coverage = r.n_resolved / r.n_total

    # Confusion 4x4 (+ linha 'Indeterminado' do engine sobre todos os pairs).
    conf: dict = {e: {pl: 0 for pl in _LEVELS} for e in _LEVELS + ["Indeterminado"]}
    for p in pairs:
        e = p.engine if p.engine in _RESOLVED else "Indeterminado"
        conf[e][p.poletto] += 1
    r.confusion = conf

    if r.n_resolved:
        diffs = [(_ord(p.engine) - _ord(p.poletto)) for p in resolved]
        r.exact_n = sum(1 for d in diffs if d == 0)
        r.exact = r.exact_n / r.n_resolved
        r.within1 = sum(1 for d in diffs if abs(d) <= 1) / r.n_resolved
        r.mean_signed = sum(diffs) / r.n_resolved
        r.over = sum(1 for d in diffs if d > 0)
        r.under = sum(1 for d in diffs if d < 0)
        r.false_alto_rate = r.over / r.n_resolved
        r.false_baixo_rate = r.under / r.n_resolved
        r.promoted_rate = sum(1 for p in resolved if p.promoted) / r.n_resolved
        comparable = [p for p in resolved if p.factual_agg in _RESOLVED]
        if comparable:
            r.final_eq_factual_rate = sum(
                1 for p in comparable if p.engine == p.factual_agg
            ) / len(comparable)

    # Recall nos genuinamente arriscados (Poletto Alto/Altissimo).
    alto_plus = [p for p in pairs if _ord(p.poletto) >= 3]
    r.n_poletto_alto_plus = len(alto_plus)
    if alto_plus:
        r.recall_alto_plus = sum(
            1 for p in alto_plus if (_ord(p.engine) or 0) >= 3
        ) / len(alto_plus)
    return r


def format_report(r: Report, title: str = "") -> str:
    lines = []
    if title:
        lines.append(f"=== {title} ===")
    lines.append(
        f"N={r.n_total} | resolvido={r.n_resolved} ({r.coverage:.0%} cobertura) "
        f"| indeterminado={r.n_total - r.n_resolved}"
    )
    lines.append(
        f"exact={r.exact:.1%} ({r.exact_n}/{r.n_resolved}) | within1={r.within1:.1%} "
        f"| mean_signed={r.mean_signed:+.2f} ({r.over} over / {r.under} under)"
    )
    lines.append(
        f"false_alto={r.false_alto_rate:.1%} | false_baixo={r.false_baixo_rate:.1%} "
        f"(HARD<=15%) | recall_Poletto>=Alto={r.recall_alto_plus:.0%} "
        f"(n={r.n_poletto_alto_plus})"
    )
    lines.append(
        f"matriz_promoveu_LLM={r.promoted_rate:.0%} | final==factual_agg={r.final_eq_factual_rate:.0%} "
        f"(quanto a produçao = risco_factual do L2, nao o L3)"
    )
    # Confusion matrix
    lines.append("Confusao (linha=engine, col=Poletto):")
    header = "  engine\\poletto |" + "".join(f"{pl:>10}" for pl in _LEVELS)
    lines.append(header)
    for e in _LEVELS + ["Indeterminado"]:
        row = "".join(f"{r.confusion.get(e, {}).get(pl, 0):>10}" for pl in _LEVELS)
        lines.append(f"  {e:>14} |{row}")
    return "\n".join(lines)


def diff_reports(baseline: Report, proposed: Report) -> str:
    """Delta proposed - baseline (so as metricas-chave). Para gate A/B."""
    def d(a, b, pct=True):
        delta = b - a
        s = f"{delta:+.1%}" if pct else f"{delta:+.2f}"
        return s
    return "\n".join([
        "=== DELTA (proposed - baseline) ===",
        f"exact      : {baseline.exact:.1%} -> {proposed.exact:.1%}  ({d(baseline.exact, proposed.exact)})",
        f"within1    : {baseline.within1:.1%} -> {proposed.within1:.1%}  ({d(baseline.within1, proposed.within1)})",
        f"false_alto : {baseline.false_alto_rate:.1%} -> {proposed.false_alto_rate:.1%}  ({d(baseline.false_alto_rate, proposed.false_alto_rate)})",
        f"false_baixo: {baseline.false_baixo_rate:.1%} -> {proposed.false_baixo_rate:.1%}  ({d(baseline.false_baixo_rate, proposed.false_baixo_rate)})  [HARD: nao pode subir]",
        f"recall>=Alto: {baseline.recall_alto_plus:.0%} -> {proposed.recall_alto_plus:.0%}  ({d(baseline.recall_alto_plus, proposed.recall_alto_plus)})",
        f"mean_signed: {baseline.mean_signed:+.2f} -> {proposed.mean_signed:+.2f}  ({d(baseline.mean_signed, proposed.mean_signed, pct=False)})",
    ])
