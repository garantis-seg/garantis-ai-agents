# Garantis AI Agents

Repositório centralizado de AI Agents com suporte a múltiplos LLM providers.

## Agentes Disponíveis

| Agente | Descrição | Endpoint |
|--------|-----------|----------|
| **Timing Analysis** | Análise de timing para processos judiciais | `/timing/analyze` |
| **Edital Categorizer** | Categorização L1/L2/L3 de editais | `/categorization/full` |
| **Domain Validator** | Validação de domínios de escritórios | `/validation/domain` |
| **Text Processor** | Correção OCR, formatação, extração | `/text/*` |

## Providers Suportados

- **Gemini** (Google) - Default
- **OpenAI** (GPT-4o, GPT-4o-mini)
- **Groq** (Llama 3.3 70B)
- **OpenRouter** (múltiplos modelos)

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
export GOOGLE_API_KEY=your-api-key

# Rodar servidor
uvicorn src.api.main:app --reload
```

## API Endpoints

- `GET /health` - Health check
- `POST /timing/analyze` - Timing analysis
- `POST /categorization/full` - Full categorization
- `POST /validation/domain` - Domain validation
- `POST /text/correct-ocr` - OCR correction
- `GET /providers` - List providers

## Variáveis de Ambiente

| Variável | Descrição | Default |
|----------|-----------|---------|
| `GOOGLE_API_KEY` | Chave API do Gemini | - |
| `DEFAULT_PROVIDER` | Provider padrão | `gemini` |
| `DEFAULT_MODEL` | Modelo padrão | `gemini-2.0-flash` |

## License

MIT
