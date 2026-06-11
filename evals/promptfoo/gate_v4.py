# -*- coding: utf-8 -*-
"""Gate local pra mudança de prompt/schema do L1 v4 — N runs + maioria por caso.

Por que existe (prompt-review 2026-06-11): o golden em exact-match SINGLE-RUN tem
dois modos de ruído que mascaram/forjam regressão:
  1. TEMPORAL — flash-lite a temp=0 NÃO é determinístico entre janelas de tempo,
     mesmo com prompt byte-idêntico (caso "designo audiência": FAIL num run, 10/10
     PASS em re-teste nos dois estados).
  2. KNIFE-EDGE — casos cujo output flipa com QUALQUER perturbação de byte no
     prompt/schema (até 1 parêntese numa description). Esses estão marcados com
     `_boundary: true` no golden (asserts categóricos viram informacionais).
A resposta: rodar N vezes (default 3), decidir por MAIORIA por caso, e comparar
contra um sumário de baseline — só reprova em regressão NOVA (caso que era
majority-PASS no baseline e virou majority-FAIL), ignorando os _boundary.

Uso (precisa de GEMINI_API_KEY — usar a GEMINI_API_KEY_EVAL, NUNCA a de prod):
  export GEMINI_API_KEY=$(gcloud secrets versions access latest \
      --secret=GEMINI_API_KEY_EVAL --project=neqsti)
  # 1) na base de comparação (ex: master):
  python gate_v4.py --runs 3 --save baseline_master.json
  # 2) no branch com a mudança:
  python gate_v4.py --runs 3 --compare-to baseline_master.json
Exit 0 = sem regressão nova; exit 1 = regressão nova (lista no stdout).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = "promptfooconfig.v4.yaml"


def run_eval(out_path: Path, log_path: Path) -> None:
    cmd = (
        f'npx promptfoo eval -c {CONFIG} --no-cache --max-concurrency 5 '
        f'--no-progress-bar --output "{out_path}"'
    )
    # --no-cache é OBRIGATÓRIO: o prompt é construído DENTRO do provider python,
    # então a cache-key do promptfoo não muda quando o prompt muda — com cache
    # ligado o run devolve resultados velhos e o gate é falso.
    #
    # stdout/stderr vão pra ARQUIVO (não pipe): no Windows, os providers python
    # que o promptfoo spawna herdam o handle do pipe e capture_output deadlocka
    # esperando EOF mesmo depois do promptfoo sair. stdin=DEVNULL pelo mesmo
    # motivo. Sucesso = o arquivo de output existir (promptfoo sai !=0 quando
    # há fails de assert — isso NÃO é erro pro gate).
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            subprocess.run(
                cmd, shell=True, cwd=HERE, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, timeout=900,
            )
        except subprocess.TimeoutExpired:
            raise SystemExit(f"promptfoo eval estourou 900s; log em {log_path}")
    if not out_path.exists():
        raise SystemExit(f"promptfoo não gerou {out_path}; log em {log_path}")


def parse_results(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for r in data["results"]["results"]:
        vars_ = r.get("testCase", {}).get("vars", {}) or {}
        mov = (vars_.get("mov") or {}).get("mov_id", "?")
        cnj = (vars_.get("processo") or {}).get("cnj", "?")
        exp = vars_.get("expected") or {}
        out[f"{cnj}::{mov}"] = {
            "pass": bool(r.get("success")),
            "boundary": bool(exp.get("_boundary")),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--save", help="salva sumário de maioria por caso (JSON)")
    ap.add_argument("--compare-to", help="sumário de baseline pra detectar regressão nova")
    args = ap.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        raise SystemExit("GEMINI_API_KEY não setada (use a GEMINI_API_KEY_EVAL)")

    runs: list[dict[str, dict]] = []
    with tempfile.TemporaryDirectory() as td:
        for i in range(args.runs):
            out = Path(td) / f"run{i}.json"
            log = Path(td) / f"run{i}.log"
            print(f"[gate] run {i + 1}/{args.runs}...", flush=True)
            run_eval(out, log)
            runs.append(parse_results(out))

    keys = sorted(runs[0].keys())
    summary: dict[str, dict] = {}
    unstable: list[str] = []
    for k in keys:
        passes = sum(1 for r in runs if r.get(k, {}).get("pass"))
        boundary = any(r.get(k, {}).get("boundary") for r in runs)
        majority = passes * 2 > args.runs
        summary[k] = {"majority": majority, "passes": f"{passes}/{args.runs}", "boundary": boundary}
        if 0 < passes < args.runs:
            unstable.append(f"{k} ({passes}/{args.runs})")

    n_pass = sum(1 for v in summary.values() if v["majority"])
    print(f"\n[gate] maioria: {n_pass}/{len(summary)} casos PASS "
          f"({args.runs} runs; {len(unstable)} instáveis entre runs)")
    for u in unstable:
        print(f"  instável: {u}")

    if args.save:
        Path(args.save).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[gate] sumário salvo em {args.save}")

    if args.compare_to:
        base = json.loads(Path(args.compare_to).read_text(encoding="utf-8"))
        regressions = [
            k for k, v in summary.items()
            if not v["majority"] and not v["boundary"]
            and base.get(k, {}).get("majority")
        ]
        improvements = [
            k for k, v in summary.items()
            if v["majority"] and k in base and not base[k].get("majority")
        ]
        for k in improvements:
            print(f"[gate] melhora: {k}")
        if regressions:
            print(f"\n[gate] REGRESSÃO NOVA em {len(regressions)} caso(s):")
            for k in regressions:
                print(f"  REGRESSÃO: {k} (baseline majority-PASS -> agora {summary[k]['passes']})")
            return 1
        print("[gate] OK — nenhuma regressão nova vs baseline (boundary ignorados).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
