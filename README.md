# Garantis AI Agents

Repositório centralizado dos AI Agents da Garantis, servidos por uma API FastAPI.

## Agentes Disponíveis

Os agentes vivos (engine v6 L1/L2/L3 — mov_factsheet, processo_synthesis, merito_synthesis, apolice_lifecycle — e os do Agente Investigador) são montados via `src/api/main.py`: a lista viva é o `include_router` de lá.

⛔ Caminho de LLM para derivar fato estrutural do processo (tribunal, estado) é para ser evitado: o fato vem do provider ou de derivação determinística (posição do Elton).

## Provider

Só **Gemini** (Google) — é o único registrado em `src/providers/factory.py`. Preço por modelo vem de `garantis_shared.llm_models` (catálogo com preço de fatura); o custo de cada chamada, inclusive a parte servida do cache implícito, é `BaseLLMProvider.calculate_cost`.

O backend do Gemini é o Vertex AI, com auth por ADC e sem key: com `GEMINI_BACKEND` ausente ou inválida, vale o Vertex (`garantis_shared.gemini_backend`). O AI Studio é o modo legado, só com `GEMINI_BACKEND=aistudio` explícito e uma key.

## Instalação

```bash
# As deps de runtime moram só no requirements.txt (é o que o Dockerfile e o gate instalam).
# O garantis-shared vem do Artifact Registry: o índice e o keyring estão no Dockerfile.
pip install -r requirements.txt

# Ferramentas de teste/lint
pip install ".[dev]"
```

## Uso Local

```bash
# Gemini pelo Vertex (o default): ADC da sua conta
gcloud auth application-default login

# Rodar servidor
uvicorn src.api.main:app --reload
```

## API

`GET /health` é o health check. As demais rotas estão no OpenAPI do serviço (`/docs`), montado pelos `include_router` de `src/api/main.py`.

## Variáveis de Ambiente

| Variável | Descrição |
|----------|-----------|
| `GEMINI_BACKEND` | `vertex` (o default, auth por ADC) ou `aistudio` (modo legado, exige key) |
| `GEMINI_API_KEY` (ou `GOOGLE_API_KEY`) | Chave do AI Studio; só vale com `GEMINI_BACKEND=aistudio` |
| `DEFAULT_PROVIDER` | Provider padrão; só `gemini` está registrado |
| `<AGENTE>_MODEL` | Modelo de cada agente (por exemplo, `MERITO_SYNTHESIS_MODEL`): a env e o default moram no código do agente, em geral o `agent.py` |
| `DEFAULT_MODEL` | Fallback de modelo só nos agentes cujo código o lê; os do engine v6 não o leem |

## License

MIT
