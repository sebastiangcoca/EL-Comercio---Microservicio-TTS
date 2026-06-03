# Imagen de producción para el backend FastAPI (TTS) — despliegue en Azure Container Apps + ACR.
# Etiqueta ejemplo para subir a tu registro: docker build -t acrvoicetranscription.azurecr.io/el-comercio-tts-api:latest .

# -----------------------------------------------------------------------------
# Etapa de build: instala dependencias Python (rutas manylinux; sin Azure CLI).
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS build

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Etapa de producción: runtime mínimo, usuario no root, uvicorn.
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS production

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PORT=8000

# Certificados TLS para llamadas HTTPS a Azure OpenAI, Key Vault, Storage, etc.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Usuario sin privilegios; /config por si montas secretos o ficheros en Container Apps.
RUN adduser --disabled-password --gecos '' appuser \
    && mkdir -p /config \
    && chown -R appuser:appuser /config /app

COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

COPY --chown=appuser:appuser src/ ./
COPY --chown=appuser:appuser requirements.txt ./

# Garantiza escritura en /app (p. ej. `Path("./src").mkdir` en main) y en site-packages legibles por todos.
RUN chown -R appuser:appuser /app

EXPOSE 8000

USER appuser

# Container Apps puede inyectar PORT; JSON-CMD no expande variables, por eso se usa sh -c.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --timeout-keep-alive 300 --timeout-graceful-shutdown 30"]
