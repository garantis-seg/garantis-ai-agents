# Garantis AI Agents

Repositório centralizado de AI Agents usando Google ADK (Agent Development Kit).

## Agentes Disponíveis

### Timing Analysis

Analisa processos judiciais para identificar oportunidades de timing para oferta de seguro garantia judicial.

**Features:**
- Decision tree de 5 nodes para análise estruturada
- Scoring determinístico no backend
- Suporte a múltiplos modelos Gemini
- Versionamento de prompts

## Setup

### Requisitos

- Python 3.11+
- Google API Key (Gemini)

### Instalação

```bash
# Clonar repositório
git clone https://github.com/garantis-seg/garantis-ai-agents.git
cd garantis-ai-agents

# Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou
.venv\Scripts\activate  # Windows

# Instalar dependências
pip install -e ".[dev]"

# Configurar ambiente
cp .env.example .env
# Editar .env com sua GOOGLE_API_KEY
```

### Rodar Localmente

```bash
# API FastAPI
uvicorn src.api.main:app --reload

# Acessar docs em http://localhost:8000/docs
```

## API Endpoints

### Timing Analysis

#### `POST /timing/analyze`

Analisa um processo para timing de seguro garantia.

```json
{
  "case_data": {
    "processo_numero": "1234567-89.2024.8.26.0000",
    "foro": "TJSP",
    "classe": "Execução Fiscal",
    "assunto": "ICMS",
    "case_value": 100000.00,
    "polo_ativo": "Fazenda Pública",
    "polo_passivo": "Empresa XYZ"
  },
  "movements": [
    {"data_movimento": "01/01/2024", "descricao": "Distribuição"},
    {"data_movimento": "15/01/2024", "descricao": "Citação do executado"}
  ],
  "model": "gemini-2.0-flash",
  "prompt_version": "v3"
}
```

**Response:**
```json
{
  "processo_numero": "1234567-89.2024.8.26.0000",
  "timing_base": "AGORA_CONSTITUICAO",
  "score_final": 9,
  "score_breakdown": {
    "timing_base": "AGORA_CONSTITUICAO",
    "base": 9,
    "penalties": 0,
    "penalty_details": [],
    "bonus": 1,
    "bonus_details": ["marco_recente_15_dias"],
    "grave_multiplier": 1.0,
    "final": 9
  },
  "tokens_used": 5000,
  "cost_usd": 0.0007,
  "model": "gemini-2.0-flash",
  "prompt_version": "v3",
  "diagnostico_timing": "AGORA",
  "score_oportunidade": 9.0,
  "justificativa_curta": "...",
  "recomendacao_final": "Oferecer seguro garantia para constituição de garantia"
}
```

#### `POST /timing/analyze-batch`

Analisa múltiplos processos em lote.

#### `GET /timing/prompts`

Lista versões de prompts disponíveis.

### Health

#### `GET /health`

Health check do serviço.

## Estrutura do Projeto

```
garantis-ai-agents/
├── src/
│   ├── agents/
│   │   └── timing_analysis/    # Agente de timing
│   │       ├── agent.py        # Lógica do agente
│   │       └── schemas.py      # Pydantic models
│   ├── prompts/
│   │   ├── index.json          # Versionamento
│   │   ├── loader.py           # Carregador
│   │   └── timing_analysis/    # Prompts do agente
│   ├── scoring/
│   │   ├── calculator.py       # Cálculo de score
│   │   ├── temporal.py         # Cálculos temporais
│   │   └── types.py            # Tipos
│   ├── models/
│   │   └── config.py           # Config de modelos
│   └── api/
│       ├── main.py             # FastAPI app
│       └── routes/             # Endpoints
├── tests/
├── Dockerfile
├── cloudbuild.yaml
└── pyproject.toml
```

## Workflow de Desenvolvimento (Prompts)

1. **Criar nova versão:**
   ```bash
   cp src/prompts/timing_analysis/v3_decision_tree.md src/prompts/timing_analysis/v4_improved.md
   ```

2. **Editar o prompt**

3. **Atualizar index.json:**
   ```json
   {
     "id": "v4",
     "name": "V4 - Improved",
     "file": "v4_improved.md",
     "created_at": "2025-12-22T00:00:00Z"
   }
   ```

4. **Testar localmente:**
   ```bash
   uvicorn src.api.main:app --reload
   # Chamar POST /timing/analyze com prompt_version="v4"
   ```

5. **Comparar resultados no poc-prompt-benchmark** (UI separada)

## Deploy

### Cloud Run (via Cloud Build)

```bash
gcloud builds submit --config cloudbuild.yaml
```

### Manual

```bash
# Build
docker build -t garantis-ai-agents .

# Run
docker run -p 8080:8080 -e GOOGLE_API_KEY=xxx garantis-ai-agents
```

## Modelos Suportados

| Modelo | Input/1M | Output/1M | Recomendado |
|--------|----------|-----------|-------------|
| gemini-2.5-pro | $1.25 | $10.00 | Alta qualidade |
| gemini-2.5-flash | $0.15 | $0.60 | Balanceado |
| gemini-2.0-flash | $0.10 | $0.40 | **Default** |
| gemini-2.0-flash-lite | $0.075 | $0.30 | Custo mínimo |

## Compatibilidade

A API retorna campos compatíveis com o serviço `gemini-timing` legado:

- `diagnostico_timing`: "AGORA" | "PASSOU" | "ACOMPANHAR"
- `score_oportunidade`: Score como float (0-10)
- `justificativa_curta`: Resumo da análise
- `recomendacao_final`: Recomendação de ação

Novos campos V3:
- `timing_base`: Classificação detalhada
- `score_breakdown`: Detalhamento do cálculo
- `llm_response`: Resposta completa dos 5 nodes

## Licença

MIT
