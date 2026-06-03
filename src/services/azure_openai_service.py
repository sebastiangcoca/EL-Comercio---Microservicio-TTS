"""
Servicio centralizado de Azure OpenAI: síntesis de voz (TTS).
"""

from typing import Optional

import httpx

from core.config import settings


class AzureOpenAIService:
    """
    Acceso a Azure OpenAI para síntesis de voz (TTS) vía audio/speech.
    """

    def __init__(self):
        """
        Inicializa el cliente TTS de Azure OpenAI.

        Raises:
            ValueError: Si faltan endpoint, key o versión de API para TTS.
        """
        tts_key = settings.ai_services.tts_api_key
        tts_version = settings.ai_services.tts_openai_api_version
        tts_endpoint = (settings.ai_services.tts_endpoint or "").rstrip("/")

        if not tts_key:
            raise ValueError("Azure OpenAI TTS API Key no configurada")
        if not tts_version:
            raise ValueError("Azure OpenAI TTS API Version no configurada")
        if not tts_endpoint:
            raise ValueError("Azure OpenAI TTS Endpoint no configurado")

        self._tts_api_key = tts_key
        self._tts_api_version = tts_version
        self._tts_endpoint = tts_endpoint
        self._tts_deployment = settings.ai_services.model_tts_deployment
        self._tts_model_body = settings.ai_services.model_tts_api_name



    async def synthesize_speech(
        self,
        text: str,
        voice: str,
        instructions: Optional[str] = None,
        response_format: Optional[str] = None,
    ) -> bytes:
        """
        Llama al endpoint audio/speech del deployment TTS en Azure OpenAI.

        Args:
            text: Guion final a vocalizar.
            voice: Identificador de voz (p. ej. sage); viene del cuerpo HTTP o default en código.
            instructions: Instrucciones de estilo de habla; None o cadena vacía omite el campo en la API.
            response_format: Opcional. Si se envía, reemplaza el formato configurado (p. ej. wav para concatenar).

        Returns:
            Bytes del archivo de audio (mp3, wav, etc. según TTS_FORMAT).

        Raises:
            httpx.HTTPStatusError: Si la API responde error.
            ValueError: Si el texto está vacío.
        """
        if not text or not text.strip():
            raise ValueError("El texto para TTS no puede estar vacío")

        instructions_stripped = (instructions or "").strip()

        url = f"{self._tts_endpoint}/openai/deployments/{self._tts_deployment}/audio/speech"
        effective_format = (response_format or "mp3").lstrip(".")

        payload: dict = {
            "model": self._tts_model_body,
            "input": text.strip(),
            "voice": voice,
            "response_format": effective_format,
        }
        if instructions_stripped:
            payload["instructions"] = instructions_stripped

        headers = {
            "api-key": self._tts_api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=30.0)) as client:
            response = await client.post(
                url,
                params={"api-version": self._tts_api_version},
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            return response.content
