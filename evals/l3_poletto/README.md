# Eval L3 (risco de acionamento) vs ground truth Poletto

Harness de calibração da Camada 3 (risco do mérito) contra os rótulos manuais do
Poletto (`monitoramento.apolices_monitoradas.risco_poletto`). Mede acurácia + permite
A/B de mudança de prompt **sem recascatear** (re-roda só o L3 sobre cards L1/L2
congelados). Instrumento de DS — construído porque mudar o prompt L3 sem medir foi
como nasceu a regressão v2.5 (memory `modelo-risco-critica-profunda-2026-06-13`).

## Por que ele existe / o que ele revelou

A produção roda `JURISPRUDENCE_PATH_ENABLED=new` → no `_apply_risk_decomposition` a
**matriz determinística 5×5 (factual × juris) SUBSTITUI o veredito do LLM L3** sempre que
`derived != Indeterminado`. Baseline medido (2026-06-13, N=46 resolvidos):

| métrica | valor |
|---|---|
| exact | 43,5% |
| false_alto | 39,1% (engine super-estima) |
| false_baixo | 17,4% (**HARD constraint ≤15%** — perder acionamento real) |
| **matriz_promoveu_LLM** | **74%** |
| **final == risco_factual (L2)** | **91%** |

→ **A produção hoje ≈ o `risco_factual` do L2, não o prompt L3.** Consertar o prompt L3
sem mexer no `risco_factual` (L2) + na matriz 5×5 mal move a produção. O harness mede os
dois (veredito LLM × final pós-promote) e o `promoted_rate` / `final_eq_factual_rate`.

## Uso

```bash
# 1) Congelar fixtures do DB (read-only via claude-db-tools; regenerável)
export DB_TOKEN=$(gcloud auth print-identity-token)
python dump_fixtures.py                 # -> fixtures/<merito_id>.json (55 méritos com input L2)

# 2) Baseline SEM LLM (valida o harness reproduzindo o diagnóstico)
python run_l3_eval.py                    # --from-snapshot (usa o risco de produção gravado)

# 3) Re-rodar o L3 de verdade (precisa da key de EVAL, NUNCA a de prod)
export GEMINI_API_KEY=$(gcloud secrets versions access latest --secret=GEMINI_API_KEY_EVAL --project=neqsti)
python run_l3_eval.py --live --runs 3                 # 3-run majority sobre os cards congelados
python run_l3_eval.py --live --limit 3               # smoke

# 4) A/B de prompt (gate estilo gate_v4)
python run_l3_eval.py --live --runs 3 --save base.json          # prompt ATUAL (nesta branch)
git checkout <branch-com-prompt-proposto>
python run_l3_eval.py --live --runs 3 --compare-to base.json    # imprime DELTA + gate
```

O gate é **HARD em false_baixo**: o A/B falha (exit 2) se o `false_baixo` subir (perder
acionamento real = risco financeiro direto pra seguradora). false_alto/exact são de tuning.

## Fidelidade ao caminho de produção

- Fixtures = saída de `_build_payload_and_context` (mesmas queries dos loaders L3:
  `load_processo_syntheses` / `load_tomador_card` / `load_cdas_aiims` / role list), com
  `processo_numero` forçado a dígitos como em produção.
- `--live` chama o agente L3 **local** (`src.agents.merito_synthesis`) → pega `card['risco']`
  (LLM) → aplica `build_risk_decomposition(mode="new")` (garantis-shared) → se
  `derived ∈ {Baixo..Altissimo}` o final = derived (matriz promove), senão = LLM. Idêntico
  ao `materializer._apply_risk_decomposition`. **Não persiste** (read-only).
- O único override que muda `card['risco']` em produção é o `risk_decomposition` — os demais
  (aggregator/valor/pipeline) não tocam o risco, então o harness os omite.

## Arquivos
- `dump_fixtures.py` — congela fixtures do DB (read-only).
- `run_l3_eval.py` — runner (from-snapshot / live / A/B gate).
- `metrics.py` — matriz de confusão + 4 métricas (exact / within1 / false_alto / false_baixo) + recall + promoted_rate.
- `baseline_from_snapshot.json` — referência da produção atual (commitado).
- `fixtures/` — gitignored (regenerável via dump; contém dados de produção).
