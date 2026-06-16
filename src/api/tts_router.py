## Endpoints TTS noticias: audio-tts (chunked WAV marin/marin1/marin2/cedar), preview, o full-only con SAS.

import asyncio
import io
import logging
import time
import uuid
from typing import Optional, Tuple
import wave

import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from core.audio_duration import get_audio_duration_seconds
from core.config import settings
from core.schema_http import (
    TtsApiErrorDetail,
    TtsErrorCode,
    TtsStructuredHttpError,
    TTSArticleFullOnlyAudioRequest,
    TTSArticleFullOnlyAudioResponse,
    TTSArticleChunkedMp3AudioRequest,
    TTSArticleChunkedMp3AudioResponse,
    TTSSingleVoicePreviewRequest,
)
from core.tts_sentence_split import split_sentences
from core.text_preprocessing import preprocess_article_body
from core.tts_voice_instructions import (
    get_default_speech_instructions_for_voice,
    resolve_effective_speech_instructions_for_preview,
    resolve_openai_speech_voice,
)
from auth.dependencies import get_current_active_user
from auth.models import User
from services.azure_openai_service import AzureOpenAIService
from services.azure_storage_service import (
    AzureStorageService,
    AzureTableTtsIdempotencyService,
    ChunkedMp3TtsIdempotencyRow,
    IdempotencyPendingTimeoutError,
    IdempotencyTableOperationError,
)

logger = logging.getLogger(__name__)

# MIME para audio-tts: el flujo chunked entrega WAV.
_TTS_AUDIO_CONTENT_TYPE = "audio/wav"

# Flujo /audio-tts: voces permitidas para el producto (marin1/marin2 = misma voz proveedor, distintas instrucciones).
_SIX_TTS_VOICE_MARIN = "marin"
_SIX_TTS_VOICE_MARIN1 = "marin1"
_SIX_TTS_VOICE_MARIN2 = "marin2"
_SIX_TTS_VOICE_CEDAR = "cedar"

_ALLOWED_AUDIO_TTS_VOICES = frozenset(
    {
        _SIX_TTS_VOICE_MARIN,
        _SIX_TTS_VOICE_MARIN1,
        _SIX_TTS_VOICE_MARIN2,
        _SIX_TTS_VOICE_CEDAR,
    }
)
_SENTENCE_SILENCE_SECONDS = 0.05
_TTS_MAX_CONCURRENT_REQUESTS = 10

router = APIRouter()

_openai_singleton: Optional[AzureOpenAIService] = None
_storage_singleton: Optional[AzureStorageService] = None
_idempotency_singleton: Optional[AzureTableTtsIdempotencyService] = None

_TTS_POST_ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {
        "model": TtsStructuredHttpError,
        "description": (
            "Reglas de negocio: texto vacío tras preprocesar, o voz TTS no permitida en preview. "
            "Cuerpo: objeto `detail` con `code`, `message` y opcionalmente `request_id` "
            "(p. ej. `TTS_UNKNOWN_VOICE`)."
        ),
    },
    status.HTTP_401_UNAUTHORIZED: {
        "description": (
            "Requiere cabecera Authorization Bearer con JWT emitido por POST /api/auth/token cuando "
            "`REQUIRE-AUTH` está activo. El middleware puede devolver `detail` como string."
        ),
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": TtsStructuredHttpError,
        "description": (
            "JSON inválido (p. ej. caracteres de control sin escapar) o campos que no cumplen el esquema. "
            "Mismo formato que otros errores: `detail.code` (`API_INVALID_JSON_BODY` o "
            "`API_REQUEST_VALIDATION_FAILED`) y `detail.issues` con el detalle técnico."
        ),
    },
    status.HTTP_502_BAD_GATEWAY: {
        "model": TtsStructuredHttpError,
        "description": (
            "Fallo del proveedor de síntesis (HTTP de upstream) o error al subir audio a Blob Storage. "
            "Revisar `code` y `upstream_http_status` si aplica."
        ),
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": TtsStructuredHttpError,
        "description": (
            "Variables de entorno o configuración de Azure OpenAI / Storage incompleta, "
            "fallo de Azure Table o URL de Storage incompatible con idempotencia TTS, "
            "o tiempo de espera agotado ante otra petición en curso "
            "(`TTS_IDEMPOTENCY_TABLE_ERROR`, `TTS_IDEMPOTENCY_PENDING_TIMEOUT`)."
        ),
    },
}


def _raise_tts_api_error(
    status_code: int,
    *,
    error_code: TtsErrorCode,
    message: str,
    request_id: Optional[str] = None,
    upstream_http_status: Optional[int] = None,
) -> None:
    """
    Aborta la petición con un cuerpo JSON estable para integración (detail estructurado).

    El detalle cumple el esquema TtsApiErrorDetail bajo la clave estándar ``detail`` de FastAPI.

    Args:
        status_code: Código HTTP (400, 502 o 503 en flujos TTS propios).
        error_code: Código de negocio estable (TtsErrorCode).
        message: Mensaje en español para humanos (no usar para lógica en el cliente).
        request_id: Identificador de trazabilidad si ya existe en la petición.
        upstream_http_status: Status HTTP del proveedor TTS cuando error_code es SYNTHESIS_UPSTREAM_ERROR.
    """
    payload = TtsApiErrorDetail(
        code=error_code,
        message=message,
        request_id=request_id,
        upstream_http_status=upstream_http_status,
    ).model_dump(mode="json", exclude_none=True)
    raise HTTPException(status_code=status_code, detail=payload)


def _get_openai_service() -> AzureOpenAIService:
    """
    Devuelve la instancia singleton de Azure OpenAI (lazy).

    Returns:
        AzureOpenAIService configurado.

    Raises:
        ValueError: Si falta configuración obligatoria.
    """
    global _openai_singleton
    if _openai_singleton is None:
        _openai_singleton = AzureOpenAIService()
    return _openai_singleton


def _get_storage_service() -> AzureStorageService:
    """
    Devuelve la instancia singleton de Azure Storage (lazy).

    Returns:
        AzureStorageService configurado.

    Raises:
        ValueError: Si falta configuración obligatoria.
    """
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = AzureStorageService()
    return _storage_singleton


def _get_idempotency_service() -> AzureTableTtsIdempotencyService:
    """
    Devuelve el singleton de idempotencia TTS (Table Storage).

    Returns:
        Servicio de tabla configurado.

    Raises:
        IdempotencyTableOperationError: Si no se puede crear o usar la tabla.
    """
    global _idempotency_singleton
    if _idempotency_singleton is None:
        _idempotency_singleton = AzureTableTtsIdempotencyService(settings.tts_idempotency)
    return _idempotency_singleton


def _build_chunked_mp3_tts_cache_response(
    *,
    cached: ChunkedMp3TtsIdempotencyRow,
    storage: AzureStorageService,
) -> TTSArticleChunkedMp3AudioResponse:
    """
    Construye la respuesta desde una fila completed (SAS nuevo, sin TTS).

    Args:
        cached: Metadatos almacenados en Table.
        storage: Cliente Blob para firmar lectura.

    Returns:
        Respuesta API con URL SAS regenerada.
    """
    url_audio, _ = storage.generate_read_sas_url(cached.path_audio)
    return TTSArticleChunkedMp3AudioResponse(
        url_audio=url_audio,
        duration_seconds=cached.duration_seconds,
        success=True,
    )


def _extract_wav_frames(wav_bytes: bytes) -> Tuple[bytes, dict]:
    """
    Extrae frames PCM y parámetros relevantes desde un WAV en memoria.

    Args:
        wav_bytes: WAV completo devuelto por TTS.

    Returns:
        Tupla (frames_pcm, params) donde params incluye nchannels, sampwidth y framerate.
    """
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        params = {
            "nchannels": wf.getnchannels(),
            "sampwidth": wf.getsampwidth(),
            "framerate": wf.getframerate(),
        }
        frames = wf.readframes(wf.getnframes())
    return frames, params


async def _synthesize_sentence_with_limit(
    semaphore: asyncio.Semaphore,
    openai_svc: AzureOpenAIService,
    sentence: str,
    *,
    voice: str,
    instructions: str,
) -> bytes:
    """
    Sintetiza una oración respetando el límite de concurrencia hacia Azure TTS.

    Usa un semáforo para garantizar que no más de _TTS_MAX_CONCURRENT_REQUESTS
    llamadas a Azure estén activas al mismo tiempo dentro de una misma petición.

    Args:
        semaphore: Controla cuántas llamadas simultáneas se permiten.
        openai_svc: Cliente de Azure OpenAI TTS.
        sentence: Texto de la oración a vocalizar.
        voice: Voz del proveedor (p. ej. sage).
        instructions: Instrucciones de estilo de habla.

    Returns:
        Bytes del audio WAV correspondiente a la oración.
    """
    async with semaphore:
        return await openai_svc.synthesize_speech(
            sentence,
            voice=voice,
            instructions=instructions,
            response_format="wav",
        )


@router.post(
    "/audio-tts",
    response_model=TTSArticleChunkedMp3AudioResponse,
    response_model_by_alias=True,
    responses=_TTS_POST_ERROR_RESPONSES,
)
async def create_article_audios(
    payload: TTSArticleChunkedMp3AudioRequest,
    _: User = Depends(get_current_active_user),
) -> TTSArticleChunkedMp3AudioResponse:
    """
    Preprocesa un texto, lo divide por oraciones y sintetiza WAV (una voz: marin, marin1, marin2 o cedar) que sube a Blob con SAS.

    Cada voz usa las instrucciones de habla definidas en ``core.tts_voice_instructions``.

    Args:
        payload: Identificador de historia, texto (text) y voz (`audio`).

    Returns:
        URL firmada, duración, y ``success`` en true cuando la conversión y el guardado en blob finalizaron bien.

    Raises:
        HTTPException: Errores de configuración, texto vacío, TTS o almacenamiento (detail estructurado).
    """
    request_id = str(uuid.uuid4())
    story_id = payload.story_id.strip()
    voice = (payload.audio or "").strip().lower()
    if voice not in _ALLOWED_AUDIO_TTS_VOICES:
        _raise_tts_api_error(
            status.HTTP_400_BAD_REQUEST,
            error_code=TtsErrorCode.UNKNOWN_VOICE,
            message="La voz solicitada no está permitida. Use 'marin', 'marin1', 'marin2' o 'cedar'.",
            request_id=request_id,
        )
    t_start = time.perf_counter()

    try:
        openai = _get_openai_service()
    except ValueError as e:
        logger.error("OpenAI no disponible: %s", e)
        _raise_tts_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=TtsErrorCode.OPENAI_UNAVAILABLE,
            message="El servicio de síntesis no está disponible: configuración de Azure OpenAI incompleta.",
            request_id=request_id,
        )

    try:
        storage = _get_storage_service()
    except ValueError as e:
        logger.error("Storage no disponible: %s", e)
        _raise_tts_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=TtsErrorCode.STORAGE_UNAVAILABLE,
            message="El almacenamiento de audio no está disponible: configuración de Azure Storage incompleta.",
            request_id=request_id,
        )

    partition_key = AzureStorageService.sanitize_article_id(story_id)
    idem_slot: Optional[Tuple[AzureTableTtsIdempotencyService, str, str]] = None

    if not settings.tts_idempotency.enabled:
        logger.error(
            "Idempotencia TTS obligatoria: configure AZURE_STORAGE_ACCOUNT_URL (https://<cuenta>.blob.core.windows.net) "
            "y AZURE_STORAGE_ACCOUNT_KEY."
        )
        _raise_tts_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=TtsErrorCode.IDEMPOTENCY_TABLE_ERROR,
            message=(
                "La idempotencia TTS requiere Azure Storage con URL de cuenta Blob estandar y clave. "
                "Revise AZURE_STORAGE_ACCOUNT_URL y AZURE_STORAGE_ACCOUNT_KEY."
            ),
            request_id=request_id,
        )

    try:
        idempo = _get_idempotency_service()
    except IdempotencyTableOperationError as e:
        logger.error("Tabla de idempotencia TTS no disponible: %s", e)
        _raise_tts_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=TtsErrorCode.IDEMPOTENCY_TABLE_ERROR,
            message="No se pudo usar la tabla de idempotencia para TTS. Revisar permisos y nombre de tabla.",
            request_id=request_id,
        )
    row_key = AzureTableTtsIdempotencyService.compute_chunked_mp3_voice_text_hash(payload.text_end, voice)
    try:
        cached = await idempo.resolve_generate_or_cache_hit_chunked_mp3(
            partition_key=partition_key,
            row_key=row_key,
            request_id=request_id,
            storage=storage,
        )
    except IdempotencyPendingTimeoutError as e:
        logger.error("Idempotencia TTS timeout: %s", e)
        _raise_tts_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=TtsErrorCode.IDEMPOTENCY_PENDING_TIMEOUT,
            message="Otra petición con la misma historia y el mismo texto está generando audio. Reintente más tarde.",
            request_id=request_id,
        )
    except IdempotencyTableOperationError as e:
        logger.error("Error de tabla en idempotencia TTS: %s", e)
        _raise_tts_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code=TtsErrorCode.IDEMPOTENCY_TABLE_ERROR,
            message="Error al consultar la tabla de idempotencia TTS.",
            request_id=request_id,
        )

    if cached is not None:
        logger.info(
            "tts_request request_id=%s story_id=%s phase=idempotency_cache_hit",
            cached.request_id,
            story_id,
        )
        return _build_chunked_mp3_tts_cache_response(
            cached=cached,
            storage=storage,
        )

    idem_slot = (idempo, partition_key, row_key)

    try:
        t0 = time.perf_counter()
        preprocessed = preprocess_article_body(payload.text_end).strip()
        logger.info(
            "tts_request request_id=%s story_id=%s phase=preprocess ms=%.0f",
            request_id,
            story_id,
            (time.perf_counter() - t0) * 1000,
        )

        if not preprocessed:
            _raise_tts_api_error(
                status.HTTP_400_BAD_REQUEST,
                error_code=TtsErrorCode.EMPTY_PREPROCESSED_TEXT,
                message="El texto quedó vacío tras preprocesar.",
                request_id=request_id,
            )

        fmt = "wav"
        content_type = _TTS_AUDIO_CONTENT_TYPE

        t1 = time.perf_counter()
        try:
            sentences = split_sentences(preprocessed)
            if not sentences:
                _raise_tts_api_error(
                    status.HTTP_400_BAD_REQUEST,
                    error_code=TtsErrorCode.EMPTY_PREPROCESSED_TEXT,
                    message="El texto no contiene oraciones válidas tras segmentar.",
                    request_id=request_id,
                )

            instructions = get_default_speech_instructions_for_voice(voice)
            provider_voice = resolve_openai_speech_voice(voice)
            if not provider_voice:
                _raise_tts_api_error(
                    status.HTTP_400_BAD_REQUEST,
                    error_code=TtsErrorCode.UNKNOWN_VOICE,
                    message="La voz solicitada no está permitida. Use 'marin', 'marin1', 'marin2' o 'cedar'.",
                    request_id=request_id,
                )
            semaphore = asyncio.Semaphore(_TTS_MAX_CONCURRENT_REQUESTS)
            logger.info(
                "tts_request request_id=%s story_id=%s phase=tts_start sentences=%s max_concurrent=%s",
                request_id,
                story_id,
                len(sentences),
                _TTS_MAX_CONCURRENT_REQUESTS,
            )
            wav_results = await asyncio.gather(
                *[
                    _synthesize_sentence_with_limit(
                        semaphore,
                        openai,
                        sentence,
                        voice=provider_voice,
                        instructions=instructions,
                    )
                    for sentence in sentences
                ]
            )
        except httpx.HTTPStatusError as e:
            logger.error("TTS HTTP error: %s", e)
            _raise_tts_api_error(
                status.HTTP_502_BAD_GATEWAY,
                error_code=TtsErrorCode.SYNTHESIS_UPSTREAM_ERROR,
                message="La API de síntesis de voz devolvió un error.",
                request_id=request_id,
                upstream_http_status=e.response.status_code,
            )
        except Exception as e:
            logger.exception("Fallo en TTS: %s", e)
            _raise_tts_api_error(
                status.HTTP_502_BAD_GATEWAY,
                error_code=TtsErrorCode.SYNTHESIS_FAILED,
                message="No se pudo completar la síntesis de voz.",
                request_id=request_id,
            )

        logger.info(
            "tts_request request_id=%s story_id=%s phase=tts ms=%.0f",
            request_id,
            story_id,
            (time.perf_counter() - t1) * 1000,
        )

        try:
            out_buf = io.BytesIO()
            silence_frames: bytes = b""
            wav_params: Optional[dict] = None
            with wave.open(out_buf, "wb") as out_wf:
                for wav_bytes in wav_results:
                    frames, params = _extract_wav_frames(wav_bytes)
                    if wav_params is None:
                        wav_params = params
                        out_wf.setnchannels(params["nchannels"])
                        out_wf.setsampwidth(params["sampwidth"])
                        out_wf.setframerate(params["framerate"])
                        silence_frames = b"\x00" * int(
                            params["framerate"] * params["nchannels"] * params["sampwidth"] * _SENTENCE_SILENCE_SECONDS
                        )
                    else:
                        if params != wav_params:
                            raise ValueError("Parámetros WAV inconsistentes entre oraciones.")
                    out_wf.writeframes(frames)
                    if silence_frames:
                        out_wf.writeframes(silence_frames)
            wav_joined = out_buf.getvalue()
            audio_wav = wav_joined
        except Exception as e:
            logger.exception("Fallo ensamblando audio WAV: %s", e)
            _raise_tts_api_error(
                status.HTTP_502_BAD_GATEWAY,
                error_code=TtsErrorCode.SYNTHESIS_FAILED,
                message="No se pudo ensamblar el audio final en WAV.",
                request_id=request_id,
            )

        path_audio = storage.build_blob_path(story_id, request_id, voice, fmt)

        t2 = time.perf_counter()
        try:
            await asyncio.to_thread(storage.upload_audio_bytes, audio_wav, path_audio, content_type)
        except Exception as e:
            logger.exception("Fallo subiendo blobs: %s", e)
            _raise_tts_api_error(
                status.HTTP_502_BAD_GATEWAY,
                error_code=TtsErrorCode.BLOB_UPLOAD_FAILED,
                message="No se pudo almacenar el audio en Azure Blob Storage.",
                request_id=request_id,
            )

        logger.info(
            "tts_request request_id=%s story_id=%s phase=blob_upload ms=%.0f",
            request_id,
            story_id,
            (time.perf_counter() - t2) * 1000,
        )

        url_audio, sas_expires_at = storage.generate_read_sas_url(path_audio)

        duration_seconds = round(get_audio_duration_seconds(audio_wav), 2)
        size_bytes = len(audio_wav)

        if idem_slot is not None:
            idempo_svc, pk, rk = idem_slot
            try:
                await asyncio.to_thread(
                    idempo_svc.mark_completed_chunked_mp3_row,
                    pk,
                    rk,
                    request_id=request_id,
                    voice=voice,
                    path_audio=path_audio,
                    url_audio=url_audio,
                    sas_expires_at=sas_expires_at,
                    output_format=fmt,
                    duration_seconds=duration_seconds,
                    size_bytes=size_bytes,
                )
            except IdempotencyTableOperationError as e:
                logger.error("Fallo al persistir idempotencia completed: %s", e)
                _raise_tts_api_error(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    error_code=TtsErrorCode.IDEMPOTENCY_TABLE_ERROR,
                    message="No se pudo registrar la generación de audio en la tabla de idempotencia.",
                    request_id=request_id,
                )
            idem_slot = None

        logger.info(
            "tts_request request_id=%s story_id=%s total_ms=%.0f",
            request_id,
            story_id,
            (time.perf_counter() - t_start) * 1000,
        )

        return TTSArticleChunkedMp3AudioResponse(
            url_audio=url_audio,
            duration_seconds=duration_seconds,
            success=True,
        )
    finally:
        if idem_slot is not None:
            idempo_rel, pk_rel, rk_rel = idem_slot
            try:
                await asyncio.to_thread(idempo_rel.delete_row, pk_rel, rk_rel)
            except IdempotencyTableOperationError as e:
                logger.warning("No se pudo liberar fila de idempotencia TTS: %s", e)


