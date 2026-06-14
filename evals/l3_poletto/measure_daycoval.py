"""Mede o classificador Daycoval deterministico vs Poletto (validacao de sucesso)
+ vs o engine atual (gap). Roda sobre as fixtures (sem LLM, instantaneo).

  python measure_daycoval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parent))
from metrics import Pair, compute, format_report  # noqa: E402
from daycoval_classifier import classify_merito    # noqa: E402

FIX = _THIS.parent / "fixtures"


def main() -> int:
    fixtures = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(FIX.glob("*.json"))]
    if not fixtures:
        print("Sem fixtures.", file=sys.stderr); return 1

    dvp, evp, evd = [], [], []   # daycoval-vs-poletto, engine-vs-poletto, engine-vs-daycoval
    for fx in fixtures:
        mid = fx["merito_id"]
        pol = fx["poletto"]["risco"]
        prod = fx["production"]["risco"]
        if prod == "indeterminado":
            prod = None
        dc = classify_merito(fx)
        dvp.append(Pair(merito_id=mid, engine=dc, poletto=pol))
        evp.append(Pair(merito_id=mid, engine=prod, poletto=pol))
        evd.append(Pair(merito_id=mid, engine=prod, poletto=dc))  # "poletto" slot = daycoval ref

    print(format_report(compute(dvp), "DAYCOVAL-classificador vs POLETTO (validacao de sucesso)"))
    print()
    print(format_report(compute(evp), "ENGINE atual vs POLETTO (baseline)"))
    print()
    print(format_report(compute(evd), "ENGINE atual vs DAYCOVAL-classificador (o gap a fechar)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
