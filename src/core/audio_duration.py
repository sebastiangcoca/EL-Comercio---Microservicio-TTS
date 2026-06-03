## Lectura de duración desde buffers WAV (p. ej. salida ensamblada de /audio-tts).

import wave
from io import BytesIO


def get_audio_duration_seconds(audio_bytes: bytes) -> float:
    """
    Obtiene la duración en segundos de un buffer WAV.

    Args:
        audio_bytes: Contenido binario del archivo WAV generado por TTS.

    Returns:
        Duración en segundos (>= 0). Devuelve 0.0 si el buffer está vacío o no se puede leer.
    """
    if not audio_bytes:
        return 0.0
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wf:
            frame_count = wf.getnframes()
            sample_rate = wf.getframerate()
            if sample_rate <= 0:
                return 0.0
            return max(0.0, frame_count / float(sample_rate))
    except Exception:
        return 0.0
