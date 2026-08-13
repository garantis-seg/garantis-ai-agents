"""
FastAPI application para garantis-ai-agents.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from garantis_shared.logging_setup import setup_logging

from .middleware import GeminiCallTimeoutMiddleware
# (court_state_classifier REMOVIDO 2026-08-10 por decisao do Elton: a flag
#  USE_LLM_COURT_STATE_CLASSIFIER do frontend-api nasceu "false" e nao ha registro
#  de "true" em ambiente nenhum. Medido 2026-08-10: 0 requests a /court-state-
#  classifier/ nos logs DESTE servico, em prod e em staging, na janela inteira
#  disponivel (entrada mais antiga 2026-07-12; controle positivo: /mov-factsheet/
#  classify aparece no mesmo filtro). ⚠️ A retencao de log de app no neqsti e 30
#  dias — "0 em 30d" e o TETO do que o log prova, nao "nunca". O classificador de estado de
#  court_presentation e o REGEX em
#  execucao-fiscal/frontend-api/services/court_presentation_inference_service.py.
#  Posicao mais ampla do Elton na mesma decisao: caminho de LLM para derivar FATO
#  ESTRUTURAL do processo (tribunal, estado) e para ser EVITADO — o fato deve vir do
#  provider ou de derivacao deterministica.)
from .routes import apolice_lifecycle, calculo_ficha, celula_base_classifier, ficha_writer, health, merito_reducao_v2, merito_synthesis, mov_factsheet, mov_summarizer, pdf, processo_synthesis, prompts, providers, text

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logging estruturado (usa garantis-shared)
setup_logging("garantis-ai-agents")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management da aplicação."""
    logger.info("Iniciando garantis-ai-agents...")
    logger.info(f"Provider padrão: {os.getenv('DEFAULT_PROVIDER', 'gemini')}")
    logger.info(f"Modelo padrão: {os.getenv('DEFAULT_MODEL', 'gemini-2.5-flash-lite')}")
    logger.info(f"Prompt padrão: {os.getenv('DEFAULT_PROMPT_VERSION', 'v3')}")

    yield

    logger.info("Encerrando garantis-ai-agents...")


# Criar aplicação
app = FastAPI(
    title="Garantis AI Agents",
    description="API centralizada de AI Agents com suporte a múltiplos LLM providers",
    version="0.5.0",
    lifespan=lifespan,
)

# Per-call Gemini timeout do engine (header X-Gemini-Timeout-Ms -> ContextVar)
app.add_middleware(GeminiCallTimeoutMiddleware)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especificar origens permitidas
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registrar routers
app.include_router(health.router)
app.include_router(prompts.router)
app.include_router(providers.router)
app.include_router(text.router)
app.include_router(pdf.router)
app.include_router(apolice_lifecycle.router)
app.include_router(mov_summarizer.router)
app.include_router(mov_factsheet.router)
app.include_router(processo_synthesis.router)
app.include_router(merito_synthesis.router)
app.include_router(merito_reducao_v2.router)
app.include_router(celula_base_classifier.router)
app.include_router(ficha_writer.router)
app.include_router(calculo_ficha.router)


@app.get("/")
async def root():
    """Endpoint raiz."""
    return {
        "service": "garantis-ai-agents",
        "version": "0.5.0",
        "docs": "/docs",
        "endpoints": {
            "text": "/text",
            "pdf": "/pdf",
            "prompts": "/prompts",
            "providers": "/providers",
            "health": "/health",
        },
    }


# Para rodar localmente: uvicorn src.api.main:app --reload
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 8080)),
        reload=True,
    )
