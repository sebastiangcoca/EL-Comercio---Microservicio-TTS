## Preprocesado de texto para guiones y TTS (español).

import html
import re


def strip_html_tags(raw: str) -> str:
    """
    Elimina etiquetas HTML comunes y scripts, dejando texto plano.

    Args:
        raw: Contenido HTML o mezcla texto/HTML.

    Returns:
        Texto sin etiquetas, con entidades HTML decodificadas.
    """
    if not raw:
        return ""
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", " ", raw, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return text


def normalize_whitespace(text: str) -> str:
    """
    Colapsa espacios y saltos de línea redundantes.

    Args:
        text: Texto de entrada.

    Returns:
        Texto normalizado.
    """
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    joined = "\n".join(ln for ln in lines if ln)
    return re.sub(r"[ \t]+", " ", joined).strip()


def preprocess_article_body(raw: str, strip_md: bool = True) -> str:
    """
    Quita HTML, opcionalmente markdown liviano y normaliza espacios.

    Args:
        raw: Cuerpo de noticia (HTML o texto).
        strip_md: Si True, elimina marcadores comunes de markdown.

    Returns:
        Texto listo para guiones.
    """
    text = strip_html_tags(raw)
    if strip_md:
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"`([^`]+)`", r"\1", text)
    return normalize_whitespace(text)
