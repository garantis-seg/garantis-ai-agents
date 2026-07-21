# Garantis AI Agents

Repositório centralizado de AI Agents com suporte a múltiplos LLM providers.

## Agentes Disponíveis

| Agente | Descrição | Endpoint |
|--------|-----------|----------|
| **Text Processor** | Extração de info-chave | `/text/extract` |

> Nota: os agentes vivos do engine v6 (L1/L2/L3: mov_factsheet, processo_synthesis, merito_synthesis, apolice_lifecycle, court_state_classifier, mov_summarizer, pdf/ocr) são montados via `src/api/main.py` — esta tabela cobre só utilitários. Timing Analysis foi REMOVIDO (pré-engine-v6, 2026-07-08).

## Providers Suportados

- **Gemini** (Google) - Default: `gemini-2.5-flash-lite` ✨
- **OpenAI** (GPT-4o, GPT-4o-mini)
- **Groq** (Llama 3.3 70B)
- **OpenRouter** (múltiplos modelos)

### Custo Estimado (Gemini Flash Lite)
- **Input**: $0.075 per 1M tokens
- **Output**: $0.30 per 1M tokens
- **Análise típica**: ~$0.0012 (vs $0.005 com Flash regular)

## Instalação

```bash
# Instalar dependências básicas
pip install .

# Com providers adicionais
pip install ".[all]"

# Com cliente HTTP
pip install ".[client]"
```

## Uso Local

```bash
# Configurar variáveis de ambiente
# (prod roda GEMINI_BACKEND=vertex via ADC — a key é o fallback aistudio)
export GOOGLE_API_KEY=your-api-key

# Rodar servidor
uvicorn src.api.main:app --reload
```

## API Endpoints

- `GET /health` - Health check
- `POST /text/extract` - Extração de info-chave
- `GET /prompts/engine-v6/raw-templates` - Templates de prompt do engine v6
- `GET /providers` - List providers

## Variáveis de Ambiente

| Variável | Descrição | Default |
|----------|-----------|---------|
| `GOOGLE_API_KEY` | Chave API do Gemini (fallback aistudio; em prod use `GEMINI_BACKEND=vertex` com ADC, sem key) | - |
| `GEMINI_BACKEND` | Backend Gemini: `vertex` (prod, auth ADC) ou `aistudio` (key) | `aistudio` |
| `DEFAULT_PROVIDER` | Provider padrão | `gemini` |
| `DEFAULT_MODEL` | Modelo padrão | `gemini-2.5-flash-lite` |

## License

MIT
