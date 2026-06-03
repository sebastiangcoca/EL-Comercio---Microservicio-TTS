## Esquemas Pydantic para validación de entrada y salida HTTP.

# -----------------------------------------------------------------------------------------
# region                             Librerías
# -----------------------------------------------------------------------------------------

from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


# -----------------------------------------------------------------------------------------
# region                             Esquemas TTS (El Comercio)
# -----------------------------------------------------------------------------------------

_TTS_MODEL_CONFIG = ConfigDict(populate_by_name=True)


class TtsErrorCode(StrEnum):
    """
    Códigos de error estables para integración (valor serializado = identificador API).

    Prefijos ``TTS_`` para dominio de síntesis; ``API_`` para validación HTTP compartida.
    El cliente debe ramificar por estos valores, no por el texto de message.
    """

    API_INVALID_JSON_BODY = "API_INVALID_JSON_BODY"
    API_REQUEST_VALIDATION_FAILED = "API_REQUEST_VALIDATION_FAILED"
    EMPTY_PREPROCESSED_TEXT = "TTS_EMPTY_PREPROCESSED_TEXT"
    OPENAI_UNAVAILABLE = "TTS_OPENAI_UNAVAILABLE"
    STORAGE_UNAVAILABLE = "TTS_STORAGE_UNAVAILABLE"
    SYNTHESIS_UPSTREAM_ERROR = "TTS_SYNTHESIS_UPSTREAM_ERROR"
    SYNTHESIS_FAILED = "TTS_SYNTHESIS_FAILED"
    BLOB_UPLOAD_FAILED = "TTS_BLOB_UPLOAD_FAILED"
    IDEMPOTENCY_TABLE_ERROR = "TTS_IDEMPOTENCY_TABLE_ERROR"
    IDEMPOTENCY_PENDING_TIMEOUT = "TTS_IDEMPOTENCY_PENDING_TIMEOUT"
    UNKNOWN_VOICE = "TTS_UNKNOWN_VOICE"


class TtsValidationIssue(BaseModel):
    """
    Un problema de validación o parseo, alineado con el detalle interno de Pydantic/FastAPI.

    Attributes:
        type: Tipo de error (p. ej. json_invalid, string_too_short).
        loc: Ruta al dato problemático (p. ej. body, posición en bytes, o nombre de campo).
        msg: Mensaje técnico del validador.
        ctx: Contexto adicional serializable (opcional).
    """

    type: str = Field(..., max_length=128)
    loc: list[str | int] = Field(default_factory=list)
    msg: str = Field(..., max_length=1024)
    ctx: Optional[dict[str, Any]] = None


class TtsApiErrorDetail(BaseModel):
    """
    Cuerpo de error bajo la clave estándar ``detail`` de FastAPI (integración formal).

    Attributes:
        code: Identificador estable (ver TtsErrorCode).
        message: Descripción humana en español para soporte o UI.
        request_id: Presente cuando el servidor ya generó id de trazabilidad.
        upstream_http_status: Status HTTP devuelto por el proveedor TTS (solo si aplica).
        issues: Lista de incidencias (422: JSON inválido o validación de campos).
    """

    code: TtsErrorCode
    message: str = Field(..., min_length=1, max_length=512)
    request_id: Optional[str] = Field(None, max_length=64)
    upstream_http_status: Optional[int] = Field(
        None,
        ge=100,
        le=599,
        description="Código HTTP del proveedor de síntesis cuando code es SYNTHESIS_UPSTREAM_ERROR",
    )
    issues: Optional[list[TtsValidationIssue]] = Field(
        None,
        description="Presente en errores 422: JSON inválido o campos que no pasan validación",
    )


class TtsStructuredHttpError(BaseModel):
    """
    Forma JSON de HTTPException con detail estructurado (misma forma que devuelve FastAPI).
    """

    detail: TtsApiErrorDetail


class TTSArticleChunkedMp3AudioRequest(BaseModel):
    """
    Solicitud para generar un audio WAV por oraciones (una voz: marin, marin1, marin2 o cedar) a partir de un solo texto.

    Attributes:
        story_id: Identificador de la historia (JSON: story_id o id_historia).
        text_end: Texto a narrar (JSON: text).
        audio: Voz a usar (marin/marin1/marin2: misma voz femenina; marin1=1500% marin2=2000% en instrucciones; cedar).
    """

    model_config = _TTS_MODEL_CONFIG

    story_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        validation_alias=AliasChoices("story_id", "id_historia"),
    )
    text_end: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("text", "textEnd"),
        description="Texto resumido o cuerpo (HTML o plano).",
    )
    audio: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Voz: marin, marin1 (1500%), marin2 (2000%) o cedar.",
    )


class TTSArticleFullOnlyAudioRequest(BaseModel):
    """
    Solicitud para TTS del texto completo ya preprocesado.

    Attributes:
        note_id: Identificador de la nota (JSON: id_nota).
        article_text: Cuerpo de la noticia (JSON: texto).
        voice: Voz TTS para la síntesis.
        speech_instructions: Estilo de habla opcional para Azure TTS.
    """

    model_config = _TTS_MODEL_CONFIG

    note_id: str = Field(..., alias="id_nota", min_length=1, max_length=256)
    article_text: str = Field(
        ...,
        alias="texto",
        min_length=1,
        description="Texto de la noticia (HTML o plano)",
    )
    voice: str = Field(..., min_length=1, max_length=64)
    speech_instructions: Optional[str] = Field(
        None,
        max_length=2000,
    )


class TTSSingleVoicePreviewRequest(BaseModel):
    """
    Solicitud para previsualizar TTS de una sola voz con instrucciones del mapa por defecto.

    Attributes:
        voice: Voz TTS (marin, marin1, marin2 o cedar).
        text: Texto a narrar (alias textEnd).
        speech_instructions: Si se envía no vacío, sustituye las instrucciones del mapa (p. ej. QA).
    """

    model_config = _TTS_MODEL_CONFIG

    voice: str = Field(..., min_length=1, max_length=64)
    text: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("text", "textEnd"),
        description="Texto a sintetizar (HTML o plano)",
    )
    speech_instructions: Optional[str] = Field(
        None,
        max_length=2000,
        description="Opcional: si no es vacío, reemplaza las instrucciones por defecto de la voz",
    )


class TTSArticleChunkedMp3AudioResponse(BaseModel):
    """
    Respuesta del endpoint /audio-tts: URL SAS del audio, duración e indicador de éxito.

    Attributes:
        url_audio: URL SAS del WAV final.
        duration_seconds: Duración en segundos.
        success: True cuando la síntesis y el almacenamiento finalizaron correctamente (siempre en 200).
    """

    url_audio: str
    duration_seconds: float = Field(..., ge=0.0)
    success: bool = Field(
        True,
        description="Indica que la conversión a audio se completó correctamente.",
    )


class TTSArticleFullOnlyAudioResponse(BaseModel):
    """
    Respuesta con una URL SAS: audio del texto completo preprocesado.

    Attributes:
        request_id: Identificador único de esta ejecución.
        note_id: Mismo identificador enviado (JSON: id_nota).
        url_full: Audio del texto completo.
        expires_on_full: Caducidad del SAS en UTC.
        voice_used: Voz usada en la síntesis.
        speech_instructions_applied: True si se enviaron instrucciones no vacías a Azure.
        output_format: Extensión o formato del archivo de audio (JSON: formato).
        duration_seconds: Duración del audio en segundos (JSON: duracion).
    """

    model_config = _TTS_MODEL_CONFIG

    request_id: str
    note_id: str = Field(..., alias="id_nota")
    url_full: str
    expires_on_full: datetime
    voice_used: str
    speech_instructions_applied: bool
    output_format: str = Field(..., alias="formato", max_length=32)
    duration_seconds: float = Field(..., alias="duracion", ge=0.0)
