"""PromptFoo provider — caminho v4 (FATOS NEUTROS) do L1 mov_factsheet. FASE 2 / warning-only.

Idêntico ao provider v3.1 (`mov_factsheet_provider.py`), mas força `L1_NEUTRAL_ENABLED=true`
→ `classify_mov_factsheet` toma o caminho v4: a LLM emite o card v4 (fatos neutros) e o
agent aplica os derivados sujeito-INDEPENDENTES (categoria/status_garantia/relevante/
peca_pivo) via `garantis_shared...derivacoes`.

`sentido`/`delta_risco` NÃO entram no card v4 (são parte_seguravel-dependentes, computados
on-read na Fase 3) → o `promptfooconfig.v4.yaml` NÃO asserta esses campos. A acurácia de
`sentido` (derivar on-read vs rótulo do golden) é o gate F1 (Fase 3), fora deste eval.

Roda num config próprio (`promptfooconfig.v4.yaml`), então o env-set fica isolado ao run v4.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ativa o caminho v4 no agent. Isolado: só o config v4 carrega este provider.
os.environ["L1_NEUTRAL_ENABLED"] = "true"

# Reusa o pipeline do provider v3.1 (mesmo diretório) — DRY, sem duplicar prompt/parse/call.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mov_factsheet_provider import call_api  # noqa: E402,F401  (re-exportado pro PromptFoo)
