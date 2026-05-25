# Engine v6 — PromptFoo regression suite

Gate de regressão pros prompts dos agentes (L1 `mov_factsheet` primeiro, L2/L3
depois). Roda chamadas reais ao Gemini 2.5 Flash Lite contra um golden snapshot
de cards atuais. Falha se accuracy regredir além de threshold configurado.

## Decisões arquiteturais

- **Provider Python custom** (não prompt-only): chama
  `src.agents.mov_factsheet.classify_mov_factsheet` direto. Cobre o pipeline
  inteiro (rendering + Gemini + parse + Pydantic). Mudança em
  `prompts.py` OU `schemas.py` OU `agent.py` dispara o eval.
- **Golden = snapshot dos cards atuais** (não gabarito humano curado). Função
  é **no-regression**, não accuracy absoluta. Mudar prompt e gerar card
  diferente do snapshot = potencial regressão (precisa justificar).
- **Asserts por campo categórico** (exact match em `decisao.sentido`,
  `categoria`, `relevancia_merito`, `peca_pivo.e_pivo`, etc.) +
  **similarity em campos texto-livre** (`resumo_ato`, `motivo`).
- **Cloud Build step pré-deploy** roda em modo WARNING inicialmente. User
  vira em "block" depois de validar 1-2 deploys passando sem ruído.

## Como rodar local

Requisitos:

- Node 20+ e Python 3.11+
- `GEMINI_API_KEY` no env (ou via `gcloud secrets versions access`)
- Conexão ao Cloud SQL pra gerar snapshot (`cloud-sql-proxy` apontando pra
  instância `neqsti:southamerica-east1:garantis-db`)

```powershell
# Setup uma vez
cd garantis-ai-agents/evals/promptfoo
npm ci

# Gerar snapshot inicial (precisa DB connection)
$env:DATABASE_URL = "postgresql://USER:PASS@localhost:5432/garantis"
$env:GEMINI_API_KEY = (gcloud secrets versions access latest --secret=GEMINI_API_KEY --project=neqsti)
python scripts/build_golden_snapshot.py --out golden/snapshot_v1.yaml --sample 30

# Rodar eval
npm run eval

# Ver resultado em browser
npm run view
```

Custo por eval run: ~30 movs × 1 prompt × $0.0004 = **~$0.012** (trivial).

## Como comparar prompt variants

1. Edite `prompts.py` no agente — esse JÁ É o prompt que será testado (provider
   chama o agente, que importa `build_mov_factsheet_prompt`).
2. Pra comparar prompt-v6 (atual) vs prompt-v7 (candidato), commit prompt-v7 e
   bump `PROMPT_VERSION` em `agent.py`. PromptFoo pegará a versão atual do código.
3. Pra comparar em paralelo: edite `promptfooconfig.yaml` adicionando entry
   `providers:` com prompt-v7 (alternativa: usa branch git).

## Como atualizar snapshot quando mudar legitimamente

Se uma mudança de prompt é INTENCIONAL (ex: corrige bug L1 documentado),
regenere snapshot DEPOIS do merge:

```bash
python scripts/build_golden_snapshot.py --out golden/snapshot_v2.yaml --sample 30
# Inspeciona diff entre v1 e v2 — diferenças devem ser EXATAMENTE as esperadas
diff golden/snapshot_v1.yaml golden/snapshot_v2.yaml
# Se OK, substitui:
mv golden/snapshot_v2.yaml golden/snapshot_v1.yaml
git commit -m "evals: refresh L1 golden snapshot pos-fix Bug X"
```

## Asserts customizados

`promptfooconfig.yaml` declara asserts por campo (exact-match em categóricos,
threshold em float, similarity em texto-livre). Pra adicionar campo novo
ao gate, edite a seção `defaultTest.assert`.

## Cloud Build integration

`cloudbuild-deploy.yaml` do `garantis-ai-agents` adiciona step PromptFoo entre
o Kaniko build e o Cloud Run deploy. Modo inicial: **warning-only** (`||true`
no final). User vira pra **block** removendo `||true` depois de validar
estabilidade.

Variáveis disponíveis no step:
- `GEMINI_API_KEY` via Secret Manager (`projects/$PROJECT_ID/secrets/GEMINI_API_KEY/versions/latest`)
- Snapshot lido de `golden/snapshot_v1.yaml` (commitado no repo)
- Cloud Build SA precisa de `roles/secretmanager.secretAccessor`

## Limitações conhecidas

- Snapshot fixo de 30 movs **não cobre todos edge cases.** Polo-regression suite
  (10 cards curados manualmente com casos críticos GOL/União, EF/executado,
  Tutela cautelar antecedente, extincao_sem_merito em Cautelar) é roadmap
  posterior — quando P1/P2 estiverem em prod.
- Provider chama Gemini real → eval custa $$$ e tem latência (~30 × 2-3s ≈ 90s).
  Aceitável pra 1 build/dia. Se virar gargalo: paralelizar com
  `concurrency` no promptfooconfig.
- Texto-livre (`resumo_ato`) tem variance residual (memory
  [engine-v6-gemini-determinism-residual](../../../../.claude/projects/c--Users-Eltonxp-dev-Garantis/memory/engine-v6-gemini-determinism-residual.md))
  — usa similarity threshold 0.80 não exact-match.
