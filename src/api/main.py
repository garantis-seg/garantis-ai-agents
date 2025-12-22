"""
FastAPI application para garantis-ai-agents.
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import categorization, health, prompts, providers, text, timing, validation

# Carregar variáveis de ambiente
load_dotenv()

# Configurar logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle management da aplicação."""
    logger.info("Iniciando garantis-ai-agents...")
    logger.info(f"Provider padrão: {os.getenv('DEFAULT_PROVIDER', 'gemini')}")
    logger.info(f"Modelo padrão: {os.getenv('DEFAULT_MODEL', 'gemini-2.0-flash')}")
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
app.include_router(categorization.router)
app.include_router(validation.router)
app.include_router(text.router)


@app.get("/")
async def root():
    """Endpoint raiz."""
    return {
        "service": "garantis-ai-agents",
        "version": "0.5.0",
        "docs": "/docs",
        "endpoints": {
            "timing": "/timing",
            "categorization": "/categorization",
            "validation": "/validation",
            "text": "/text",
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
