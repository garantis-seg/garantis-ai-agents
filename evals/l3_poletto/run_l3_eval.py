"""Runner do eval L3 (risco de acionamento) vs ground truth Poletto.

DOIS modos:

  --from-snapshot   (default, sem LLM): usa o risco de PRODUCAO ja gravado nos
                    fixtures como output do engine. Valida o harness reproduzindo
                    o diagnostico (exact ~45% nos 46 resolvidos) + audita quanto
                    a matriz 5x5 (mode=new) substituiu o LLM. NAO chama Gemini.

  --live            re-roda o L3 LOCAL (src.agents.merito_synthesis) sobre os
                    cards congelados dos fixtures, 3-run majority, aplica o
                    risk_decomposition mode=new (FIEL a producao: a matriz
                    substitui o LLM quando derived != Indeterminado), e compara
                    com Poletto. Precisa de GEMINI_API_KEY (use a _EVAL, NUNCA prod):
                      export GEMINI_API_KEY=$(gcloud secrets versions access latest \
                        --secret=GEMINI_API_KEY_EVAL --project=neqsti)

A/B (gate estilo gate_v4): rodar --live com o prompt ATUAL e `--save base.json`;
trocar o prompt (outra branch) e rodar `--compare-to base.json` -> imprime o DELTA
(false_baixo nao pode subir = HARD constraint).

  python run_l3_eval.py                          # baseline from-snapshot
  python run_l3_eval.py --live --runs 3 --save base.json
  python run_l3_eval.py --live --runs 3 --compare-to base.json
  python run_l3_eval.py --live --limit 3         # smoke
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parent.parent.parent          # evals/l3_poletto/X.py -> repo root
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_THIS.parent))

from metrics import Pair, compute, format_report, diff_reports, Report  # noqa: E402

FIX_DIR = _THIS.parent / "fixtures"
_LEVELS = {"Baixo", "Medio", "Alto", "Altissimo"}


def _load_fixtures(limit: int = 0) -> list[dict]:
    fs = sorted(FIX_DIR.glob("*.json"))
    if limit:
        fs = fs[:limit]
    return [json.loads(f.read_text(encoding="utf-8")) for f in fs]


# ── modo from-snapshot (sem LLM) ───────────────────────────────────────────
def _pairs_from_snapshot(fixtures: list[dict]) -> list[Pair]:
    pairs = []
    for fx in fixtures:
        prod = fx["production"]
        prod_risco = prod.get("risco")
        if prod_risco == "indeterminado":
            prod_risco = None
        derived = prod.get("derived")
        pairs.append(Pair(
            merito_id=fx["merito_id"],
            engine=prod_risco,
            poletto=fx["poletto"]["risco"],
            llm_verdict=prod.get("llm_legacy"),
            factual_agg=prod.get("factual_agg"),
            juris_agg=prod.get("juris_agg"),
            derived=derived,
            apolice_aceita=fx["poletto"].get("apolice_aceita"),
            promoted=(derived in _LEVELS),
        ))
    return pairs


# ── modo live (re-roda L3 local) ───────────────────────────────────────────
async def _classify_one(payload: dict, runs: int, no_override: bool = False) -> dict:
    """Roda o L3 local `runs` vezes; aplica risk_decomposition mode=new fiel
    a producao; majority do risco FINAL. Retorna campos pro Pair.

    no_override=True: final = veredito do LLM puro (sem override da matriz/prob_base).
    Testa o desenho "LLM decide com as regras injetadas" (a Matriz de Risco no prompt).
    """
    from src.agents.merito_synthesis import classify_merito_synthesis  # local agent
    from garantis_shared.engine_v6.matrices import resolve_banda_matriz

    ps_cards = payload["processo_syntheses"]
    # R1/C (2026-07-05): build_risk_decomposition/derive_aggregated_risk (matriz-5x5) foram
    # DELETADOS na grande poda; o decisor agora e resolve_banda_matriz (leitura de 3 eixos).
    # FIEL a producao: ambiguous (needs_review/acumulacao) => o LLM decide => Indeterminado
    # (nao promovido). O split factual/jurisprudencial da matriz-5x5 nao existe mais -> None.
    agg = resolve_banda_matriz(ps_cards, tipo_principal=payload.get("tipo_principal"))
    derived = "Indeterminado" if agg.get("ambiguous") else agg["banda"]
    finals, llms = [], []
    for _ in range(runs):
        res = await classify_merito_synthesis(payload)
        card = (res or {}).get("card") or {}
        llm = card.get("risco")
        llms.append(llm)
        # mode=new: matriz substitui o LLM quando derived != Indeterminado.
        # no_override: o LLM decide sozinho (desenho LLM-decide com Matriz de Risco no prompt).
        final = llm if no_override else (derived if derived in _LEVELS else llm)
        finals.append(final)
    final_majority = Counter([f for f in finals if f]).most_common(1)
    llm_majority = Counter([l for l in llms if l]).most_common(1)
    return {
        "final": final_majority[0][0] if final_majority else None,
        "llm": llm_majority[0][0] if llm_majority else None,
        "derived": derived,
        "factual_agg": None,   # split factual/juris da matriz-5x5 deletado no R1/C (poda)
        "juris_agg": None,
        "promoted": derived in _LEVELS,
        "runs_final": finals,
    }


async def _pairs_live(
    fixtures: list[dict], runs: int, no_override: bool = False, concurrency: int = 6,
) -> list[Pair]:
    """Roda os fixtures CONCORRENTES (semaforo) — cada merito e independente, entao
    o paralelismo nao muda o resultado, so o wall-clock (~6x). Cap conservador
    pra nao estourar TPM da key de eval."""
    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit(
            "GEMINI_API_KEY nao setada. Use a _EVAL:\n"
            "  export GEMINI_API_KEY=$(gcloud secrets versions access latest "
            "--secret=GEMINI_API_KEY_EVAL --project=neqsti)"
        )
    sem = asyncio.Semaphore(concurrency)
    done = 0
    total = len(fixtures)

    async def _one(fx: dict) -> Pair:
        nonlocal done
        async with sem:
            out = await _classify_one(fx["payload"], runs, no_override=no_override)
        done += 1
        print(
            f"  [{done}/{total}] m={fx['merito_id']} "
            f"final={out['final']} (llm={out['llm']} derived={out['derived']} "
            f"promoted={out['promoted']}) poletto={fx['poletto']['risco']}",
            file=sys.stderr,
        )
        return Pair(
            merito_id=fx["merito_id"],
            engine=out["final"],
            poletto=fx["poletto"]["risco"],
            llm_verdict=out["llm"],
            factual_agg=out["factual_agg"],
            juris_agg=out["juris_agg"],
            derived=out["derived"],
            apolice_aceita=fx["poletto"].get("apolice_aceita"),
            promoted=out["promoted"],
        )

    return list(await asyncio.gather(*[_one(fx) for fx in fixtures]))


def _report_to_dict(r: Report) -> dict:
    return {k: getattr(r, k) for k in (
        "n_total", "n_resolved", "coverage", "exact", "within1", "mean_signed",
        "over", "under", "exact_n", "false_alto_rate", "false_baixo_rate",
        "recall_alto_plus", "n_poletto_alto_plus", "promoted_rate",
        "final_eq_factual_rate",
    )}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="re-roda o L3 local (precisa GEMINI_API_KEY_EVAL)")
    ap.add_argument("--runs", type=int, default=3, help="N runs por merito (majority); so --live")
    ap.add_argument("--limit", type=int, default=0, help="amostra N fixtures")
    ap.add_argument("--save", type=str, default="", help="salva o report (baseline) em FILE")
    ap.add_argument("--compare-to", type=str, default="", help="compara com baseline salvo (DELTA)")
    ap.add_argument("--no-override", action="store_true",
                    help="final = veredito do LLM puro (sem override matriz/prob_base); so --live")
    ap.add_argument("--concurrency", type=int, default=6,
                    help="fixtures concorrentes (semaforo); so --live. ~6x mais rapido.")
    ap.add_argument("--fixtures-dir", type=str, default="",
                    help="dir de fixtures alternativo (default: ./fixtures). Use p/ subset fresco.")
    args = ap.parse_args()

    if args.fixtures_dir:
        global FIX_DIR
        FIX_DIR = Path(args.fixtures_dir)

    fixtures = _load_fixtures(args.limit)
    if not fixtures:
        print("Sem fixtures. Rode dump_fixtures.py primeiro.", file=sys.stderr)
        return 1

    mode = "live (re-roda L3)" if args.live else "from-snapshot (producao gravada)"
    print(f"Modo: {mode} | fixtures: {len(fixtures)}", file=sys.stderr)
    if args.live:
        pairs = asyncio.run(_pairs_live(fixtures, args.runs, no_override=args.no_override, concurrency=args.concurrency))
    else:
        pairs = _pairs_from_snapshot(fixtures)

    report = compute(pairs)
    print()
    print(format_report(report, title=f"L3 vs Poletto — {mode}"))

    if args.save:
        Path(args.save).write_text(
            json.dumps(_report_to_dict(report), indent=2), encoding="utf-8"
        )
        print(f"\n[baseline salvo em {args.save}]", file=sys.stderr)

    if args.compare_to:
        base = json.loads(Path(args.compare_to).read_text(encoding="utf-8"))
        base_r = Report(**base)
        print()
        print(diff_reports(base_r, report))
        # Gate HARD: false_baixo nao pode subir.
        if report.false_baixo_rate > base_r.false_baixo_rate + 1e-9:
            print("\nGATE: FALHOU (false_baixo subiu — perde acionamento real).", file=sys.stderr)
            return 2
        print("\nGATE: OK (false_baixo nao subiu).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
