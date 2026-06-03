## Punto de entrada FastAPI: microservicio TTS El Comercio.

from dotenv import load_dotenv

load_dotenv(override=True)

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth_router import router as auth_router
from api.tts_router import router as tts_router
from core.config import settings
from core.request_validation_handler import register_structured_validation_handler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    force=True,
)

azure_http_logger = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
azure_http_logger.setLevel(logging.WARNING)

TEMP_DIR = Path("./src")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title=settings.app_name,
    description="Conversión de noticias a audio (TTS) con Azure OpenAI y Blob Storage",
    version="1.0.0",
)

register_structured_validation_handler(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health():
    """
    Comprobación de vida para balanceadores y Container Apps.

    Returns:
        Estado simple ok.
    """
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(tts_router, prefix="/api/tts", tags=["tts"])
