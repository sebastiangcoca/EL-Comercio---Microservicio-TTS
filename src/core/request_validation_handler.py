## Manejador global de RequestValidationError: mismo JSON de error que el dominio TTS.

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT

from core.schema_http import TtsApiErrorDetail, TtsErrorCode, TtsValidationIssue

_MAX_ISSUES = 50


def _normalize_loc(loc: Any) -> list[str | int]:
    """
    Convierte la tupla ``loc`` de Pydantic a lista JSON-serializable.

    Args:
        loc: Secuencia de segmentos de ruta (str, int u otros).

    Returns:
        Lista de segmentos como str o int.
    """
    if not loc:
        return []
    out: list[str | int] = []
    for part in loc:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, int):
            out.append(part)
        else:
            out.append(str(part))
    return out


def _issue_from_raw(err: dict[str, Any]) -> TtsValidationIssue:
    """
    Construye un TtsValidationIssue a partir de un dict devuelto por ``exc.errors()``.

    Args:
        err: Entrada cruda del validador.

    Returns:
        Modelo normalizado para el cuerpo de respuesta.
    """
    ctx_raw = err.get("ctx")
    ctx_encoded = jsonable_encoder(ctx_raw) if ctx_raw is not None else None
    ctx_final = ctx_encoded if isinstance(ctx_encoded, dict) else None
    return TtsValidationIssue(
        type=str(err.get("type", "unknown"))[:128],
        loc=_normalize_loc(err.get("loc")),
        msg=str(err.get("msg", ""))[:1024],
        ctx=ctx_final,
    )


def _build_validation_payload(exc: RequestValidationError) -> dict[str, Any]:
    """
    Arma el objeto ``detail`` unificado para un RequestValidationError.

    Args:
        exc: Excepción de validación de FastAPI.

    Returns:
        Diccionario compatible con TtsApiErrorDetail (sin envoltorio HTTP).
    """
    raw_errors = exc.errors()
    trimmed = raw_errors[:_MAX_ISSUES]
    issues = [_issue_from_raw(e) for e in trimmed]

    if not raw_errors:
        code = TtsErrorCode.API_REQUEST_VALIDATION_FAILED
        message = "La petición no pudo ser validada."
    else:
        first_type = str(raw_errors[0].get("type", ""))
        if first_type == "json_invalid":
            code = TtsErrorCode.API_INVALID_JSON_BODY
            ctx0 = raw_errors[0].get("ctx") or {}
            reason = ""
            if isinstance(ctx0, dict):
                reason = str(ctx0.get("error", "") or "")
            message = "El cuerpo de la petición no es JSON válido."
            if reason:
                message = f"{message} {reason}".strip()
        else:
            code = TtsErrorCode.API_REQUEST_VALIDATION_FAILED
            message = (
                "La petición no cumple el esquema esperado "
                "(campos obligatorios, tipos, alias JSON o límites)."
            )

    message = message.strip()
    if len(raw_errors) > _MAX_ISSUES:
        suffix = f" (Se listan solo las primeras {_MAX_ISSUES} incidencias.)"
        message = (message[: max(0, 512 - len(suffix))] + suffix)[:512]
    else:
        message = message[:512]

    detail_model = TtsApiErrorDetail(
        code=code,
        message=message,
        issues=issues,
    )
    return detail_model.model_dump(mode="json", exclude_none=True)


async def structured_request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Responde 422 con el mismo formato ``detail`` que los errores TTS estructurados.

    Args:
        request: Petición HTTP entrante.
        exc: Error de validación o parseo del cuerpo.

    Returns:
        JSONResponse con cuerpo ``{"detail": {...}}``.
    """
    payload = _build_validation_payload(exc)
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": payload},
    )


def register_structured_validation_handler(app: FastAPI) -> None:
    """
    Sustituye el manejador por defecto de FastAPI para RequestValidationError.

    Args:
        app: Instancia FastAPI.
    """
    app.add_exception_handler(
        RequestValidationError,
        structured_request_validation_handler,
    )
