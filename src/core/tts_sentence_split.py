"""
Utilidades para dividir un texto en oraciones para TTS.
"""

from __future__ import annotations

import re

_PUNCTUATION_ONLY: frozenset[str] = frozenset({".", "!", "?"})


def split_sentences(text: str) -> list[str]:
    """
    Divide un texto en oraciones usando una heurística simple basada en puntuación final.

    Esta función está inspirada en el prototipo de `convercion-oraciones.py`, pero sin dependencias de audio.

    Args:
        text: Texto ya preprocesado (idealmente sin HTML), en español.

    Returns:
        Lista de oraciones limpias, sin entradas vacías ni fragmentos de solo puntuación.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    candidates = re.split(r"(?<=[.!?])\s+", raw)
    out: list[str] = []
    for sentence in candidates:
        s = (sentence or "").strip()
        if not s:
            continue
        if len(s) <= 1:
            continue
        if s in _PUNCTUATION_ONLY:
            continue
        out.append(s)
    return out

