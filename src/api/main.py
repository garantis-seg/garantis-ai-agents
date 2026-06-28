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
from .routes import apolice_lifecycle, court_state_classifier, health, merito_synthesis, mov_factsheet, mov_summarizer, pdf, processo_synthesis, prompts, providers, summarization, text, timing

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
app.include_router(timing.router)
app.include_router(summarization.router)
app.include_router(text.router)
app.include_router(pdf.router)
app.include_router(apolice_lifecycle.router)
app.include_router(court_state_classifier.router)
app.include_router(mov_summarizer.router)
app.include_router(mov_factsheet.router)
app.include_router(processo_synthesis.router)
app.include_router(merito_synthesis.router)


@app.get("/")
async def root():
    """Endpoint raiz."""
    return {
        "service": "garantis-ai-agents",
        "version": "0.5.0",
        "docs": "/docs",
        "endpoints": {
            "timing": "/timing",
            "summarization": "/summarization",
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
