"""
Instrucciones de estilo de habla por voz para Azure TTS (noticias).

"""

from typing import Optional

_MARIN_INSTRUCTIONS_BODY = (
    "Narrar como presentador de noticiero central: voz neutra y profesional con acento "
    "ecuatoriano auténtico, habla al {speed}% de velocidad normal, "
    "Usar entonación característica del español ecuatoriano, "
    "ritmo parejo y cadencia descendente al final de cada oración. "
    "Evitar completamente sonidos con entonación 'sh' o 'shh'; reemplazar cualquier "
    "pronunciación similar por sonidos suaves y neutros propios del español ecuatoriano estándar. "
    "Pronunciar la Y y la LL siempre como el sonido vocal suave ecuatoriano, nunca como 'sh'. "
    "CONSISTENCIA DE VOZ: mantener exactamente el mismo tono, timbre, volumen, energía "
    "y acento desde la primera hasta la última palabra, como si todo el texto fuera "
    "grabado en una sola toma continua sin interrupciones. No reiniciar ni variar el "
    "registro vocal entre oraciones, párrafos ni secciones del texto."
)

_INSTRUCTIONS_MARIN1 = _MARIN_INSTRUCTIONS_BODY.format(speed=1500)
_INSTRUCTIONS_MARIN2 = _MARIN_INSTRUCTIONS_BODY.format(speed=2000)

_INSTRUCTIONS_CEDAR = (
    "Narrar como presentador de noticiero central: voz masculina grave y profesional con acento "
    "ecuatoriano auténtico, habla al 1500% de velocidad normal,"
    "ritmo parejo y cadencia descendente al final de cada oración. "
    "Evitar completamente sonidos con entonación 'sh' o 'shh'; reemplazar cualquier "
    "pronunciación similar por sonidos suaves y neutros propios del español ecuatoriano estándar. "
    "Pronunciar la Y y la LL siempre como el sonido vocal suave ecuatoriano, nunca como 'sh'. "
    "VOZ MASCULINA: mantener en todo momento una voz de hombre adulto, tono grave y resonante, "
    "timbre profundo característico de locutor masculino profesional. "
    "CONSISTENCIA DE VOZ: mantener exactamente el mismo tono, timbre, volumen, energía "
    "y acento desde la primera hasta la última palabra, como si todo el texto fuera "
    "grabado en una sola toma continua sin interrupciones. No reiniciar ni variar el "
    "registro vocal entre oraciones, párrafos ni secciones del texto."
)

# Claves alineadas con ``/api/tts/audio-tts`` (solo voces activas del producto).
VOICE_SPEECH_INSTRUCTIONS: dict[str, str] = {
    "marin": _INSTRUCTIONS_MARIN2,
    "marin1": _INSTRUCTIONS_MARIN1,
    "marin2": _INSTRUCTIONS_MARIN2,
    "cedar": _INSTRUCTIONS_CEDAR,
}

ALLOWED_TTS_VOICES: frozenset[str] = frozenset(VOICE_SPEECH_INSTRUCTIONS.keys())


def resolve_openai_speech_voice(api_voice: str) -> Optional[str]:
    """
    Devuelve el identificador de voz para la API ``audio/speech`` del proveedor (Azure OpenAI).

    Las claves ``marin``, ``marin1`` y ``marin2`` se sintetizan con el timbre ``marin`` del
    proveedor; la diferencia entre variantes está solo en las instrucciones de estilo.

    Args:
        api_voice: Clave de voz de esta API (se normaliza en minúsculas y sin espacios extremos).

    Returns:
        Nombre de voz admitido por el proveedor (p. ej. ``marin`` o ``cedar``), o None si la
        clave no está en ``VOICE_SPEECH_INSTRUCTIONS``.
    """
    normalized = (api_voice or "").strip().lower()
    if normalized not in VOICE_SPEECH_INSTRUCTIONS:
        return None
    if normalized in ("marin", "marin1", "marin2"):
        return "marin"
    return normalized


def get_default_speech_instructions_for_voice(voice: str) -> Optional[str]:
    """
    Devuelve las instrucciones de habla por defecto para una voz TTS permitida.

    Args:
        voice: Identificador de voz (se compara en minúsculas tras quitar espacios).

    Returns:
        Cadena de instrucciones si la voz está permitida; None si no es una voz válida.
    """
    normalized = (voice or "").strip().lower()
    if not normalized:
        return None
    return VOICE_SPEECH_INSTRUCTIONS.get(normalized)


def resolve_effective_speech_instructions_for_preview(
    voice: str,
    speech_instructions_override: Optional[str],
) -> Optional[str]:
    """
    Resuelve la cadena de instrucciones para el endpoint de preview de una voz.

    Si ``speech_instructions_override`` viene no vacío tras strip, sustituye el mapa
    por voz; si no, usa ``VOICE_SPEECH_INSTRUCTIONS`` para la voz normalizada.

    Args:
        voice: Identificador de voz (se normaliza en minúsculas).
        speech_instructions_override: Texto opcional enviado por el cliente (p. ej. QA).

    Returns:
        Instrucciones finales para Azure TTS, o None si la voz no está permitida.
    """
    normalized = (voice or "").strip().lower()
    if not normalized:
        return None
    if normalized not in VOICE_SPEECH_INSTRUCTIONS:
        return None
    override = (speech_instructions_override or "").strip()
    if override:
        return override
    return VOICE_SPEECH_INSTRUCTIONS[normalized]
