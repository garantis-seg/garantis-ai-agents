# Eval L3 (risco de acionamento) vs ground truth Poletto

Harness de calibração da Camada 3 (risco do mérito) contra os rótulos manuais do Poletto (`monitoramento.apolices_monitoradas.risco_poletto`). Mede a acurácia e permite A/B de mudança de prompt **sem recascatear**: re-roda só o L3 sobre cards L1/L2 congelados. Existe porque mudar o prompt L3 sem medir já produziu regressão.

## O que ele mede

A banda final não é só o veredito do LLM: uma camada determinística pode substituí-lo. O harness mede os dois, o veredito do LLM e a banda final, e reporta o quanto a camada determinística decidiu (`promoted_rate`). Por isso consertar só o prompt L3 pode mover pouco a banda final: rode o baseline antes de concluir. Os números de hoje saem de `python run_l3_eval.py`.

## Uso

```bash
# 1) Congelar fixtures do DB (read-only via claude-db-tools; regenerável)
export DB_TOKEN=$(gcloud auth print-identity-token)
python dump_fixtures.py                 # -> fixtures/<merito_id>.json

# 2) Baseline SEM LLM: o risco que a produção gravou nos fixtures
python run_l3_eval.py                    # modo from-snapshot, o default

# 3) Re-rodar o L3 de verdade — Vertex/ADC por default, sem key
#    (aistudio = GEMINI_BACKEND=aistudio + GEMINI_API_KEY manual, NUNCA a de prod)
python run_l3_eval.py --live --runs 3                 # 3-run majority sobre os cards congelados
python run_l3_eval.py --live --limit 3               # smoke

# 4) A/B de prompt (3-run majority contra baseline salvo)
python run_l3_eval.py --live --runs 3 --save base.json          # prompt ATUAL (nesta branch)
git checkout <branch-com-prompt-proposto>
python run_l3_eval.py --live --runs 3 --compare-to base.json    # imprime DELTA + gate
```

O gate é **HARD em false_baixo**: o A/B falha (exit 2) se o `false_baixo` subir (perder acionamento real = risco financeiro direto pra seguradora). false_alto/exact são de tuning.

## Como o `--live` decide, e onde a produção decide

- Fixtures = saída de `_build_payload_and_context` (mesmas queries dos loaders L3: `load_processo_syntheses` / `load_tomador_card` / `load_cdas` / role list), com `processo_numero` forçado a dígitos como em produção.
- `--live` chama o agente L3 **local** (`src.agents.merito_synthesis`), pega `card['risco']` (o veredito do LLM) e decide a banda final em `run_l3_eval.py::_classify_one`: a leitura determinística `resolve_banda_matriz` (garantis-shared) substitui o LLM quando não é ambígua; ambígua, fica o LLM. `--no-override` deixa o LLM decidir sozinho. **Não persiste** (read-only).
- ⚠️ A produção decide em `garantis_shared/engine_v6/layer3_merito_synthesis/materializer.py::_apply_risk_decomposition`, com as flags do `config/services.yaml` do execucao-fiscal. Confira lá antes de tratar o `--live` como espelho dela.

## Arquivos
- `dump_fixtures.py` — congela fixtures do DB (read-only).
- `run_l3_eval.py` — runner (from-snapshot / live / A/B gate).
- `metrics.py` — matriz de confusão + 4 métricas (exact / within1 / false_alto / false_baixo) + recall + promoted_rate.
- `daycoval_classifier.py` — classificador determinístico da matriz Daycoval, a referência oficial do risco (o Poletto valida).
- `measure_daycoval.py` — mede o classificador Daycoval contra o Poletto e contra o engine, sobre as fixtures (sem LLM).
- `baseline_from_snapshot.json` — um report antigo do from-snapshot, guardado no repo; não é a produção de hoje.
- `fixtures/` — gitignored (regenerável via dump; contém dados de produção).
