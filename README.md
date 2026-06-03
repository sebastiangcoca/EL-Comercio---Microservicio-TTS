# El Comercio — TTS API (backend)

Microservicio **FastAPI** que convierte texto de noticias en **audio WAV** mediante **Azure OpenAI (TTS)**, almacena el resultado en **Azure Blob Storage** y devuelve una **URL con SAS de solo lectura**. Incluye **idempotencia** con **Azure Table Storage** para evitar generar el mismo audio dos veces cuando se repite la misma historia, texto y voz.

## Características

- Preprocesado de HTML/Markdown y segmentación por oraciones.
- Síntesis en paralelo por oración; ensamblado en un único WAV con pausas breves entre frases.
- Voces de producto: `marin1`, `marin2` (mismo timbre `marin` en el proveedor, distintas instrucciones de estilo) y `cedar`.
- Autenticación **JWT HS256** local (OAuth2 Password Grant).
- Errores HTTP con cuerpo estructurado (`detail.code`, `detail.message`, `request_id`).

## Requisitos

- Python **3.11+** (recomendado)
- Cuenta de **Azure OpenAI** con deployment TTS (p. ej. `gpt-4o-mini-tts`)
- **Azure Storage** (Blob + Table en la misma cuenta)
- Variables de entorno o **Azure Key Vault** (`USE_KEY_VAULT=true`)

## Estructura del proyecto

```
backend/
├── requirements.txt
├── .env                    # local (no commitear secretos)
└── src/
    ├── main.py             # Punto de entrada FastAPI
    ├── api/
    │   ├── auth_router.py  # /api/auth/*
    │   └── tts_router.py   # /api/tts/*
    ├── auth/               # JWT y dependencias
    ├── core/               # Config, esquemas, preprocesado, voces
    └── services/           # Azure OpenAI y Storage
```

## Inicio rápido

### 1. Entorno virtual e dependencias

```bash
cd backend
python -m venv venv

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Variables de entorno

Crea un archivo `.env` en la raíz de `backend/` (ver tabla más abajo). La aplicación carga `.env` al arrancar (`python-dotenv`).

### 3. Ejecutar el servidor

Los imports asumen que `src/` está en el path de Python:

```bash
# Desde backend/
uvicorn main:app --app-dir src --reload --host 0.0.0.0 --port 8000
```

- Documentación interactiva: [http://localhost:8000/docs](http://localhost:8000/docs)
- OpenAPI JSON: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
- Health: [http://localhost:8000/health](http://localhost:8000/health)

## Configuración

### Azure Key Vault (opcional)

| Variable | Descripción |
|----------|-------------|
| `USE_KEY_VAULT` | `true` para leer secretos solo desde Key Vault |
| `KEY_VAULT_NAME` | Nombre del vault (sin `.vault.azure.net`) |

Si `USE_KEY_VAULT` es `false` (por defecto), los secretos se leen desde variables de entorno. Los nombres admiten **guiones** o **guiones bajos** (p. ej. `azure-openai-api-key` o `AZURE_OPENAI_API_KEY`).

### Azure OpenAI (TTS)

| Variable / secreto | Obligatorio | Descripción |
|------------------|-------------|-------------|
| `azure-openai-api-key` | Sí | API key del recurso OpenAI |
| `azure-openai-endpoint` | Sí | URL base, p. ej. `https://<recurso>.openai.azure.com` |
| `openai-api-version-tts` | No | Versión API (default: `2025-03-01-preview`) |
| `model-tts-deployment` | No | Nombre del deployment (default: `gpt-4o-mini-tts`) |
| `model-tts-api-name` | No | Campo `model` en el body (default: mismo que deployment) |

### Azure Blob Storage

| Variable / secreto | Obligatorio | Descripción |
|------------------|-------------|-------------|
| `azure-storage-account-url` | Sí | `https://<cuenta>.blob.core.windows.net` |
| `azure-storage-account-key` | Sí | Clave de cuenta (SAS y Table) |
| `azure-storage-container` | No | Contenedor (default: `tts-audio`) |
| `azure-storage-blob-prefix` | No | Prefijo de rutas (default: `tts`) |
| `sas-ttl-hours` | No | TTL del SAS en horas (default: `24`) |

### Idempotencia (Table Storage)

Obligatoria para `POST /api/tts/audio-tts`. Usa la **misma cuenta** que Blob; la URL debe ser `*.blob.core.windows.net`.

| Variable | Default | Descripción |
|----------|---------|-------------|
| `AZURE_TTS_IDEMPOTENCY_TABLE_NAME` | `TtsAudioIdempotency` | Nombre de la tabla |
| `TTS_IDEMPOTENCY_PENDING_POLL_MAX_SECONDS` | `60` | Espera máxima si otra petición está en curso |
| `TTS_IDEMPOTENCY_PENDING_POLL_INTERVAL_SECONDS` | `0.5` | Intervalo entre consultas |
| `TTS_IDEMPOTENCY_PENDING_STALE_SECONDS` | `900` | Pending considerado obsoleto |

### Autenticación JWT

| Variable / secreto | Obligatorio | Descripción |
|------------------|-------------|-------------|
| `jwt-secret-key` | Sí* | Secreto HS256 (recomendado ≥ 32 caracteres) |
| `jwt-auth-username` | Sí* | Usuario del login |
| `jwt-auth-password` | Sí* | Contraseña en texto plano (se valida con bcrypt) |
| `jwt-algorithm` | No | Default: `HS256` |
| `access-token-expire-minutes` | No | Default: `30` |

\* Requeridos para emitir y validar tokens en rutas protegidas.

### Aplicación

| Variable | Default | Descripción |
|----------|---------|-------------|
| `APP_NAME` | `El Comercio TTS API` | Nombre mostrado en health y OpenAPI |

## API

### Autenticación

**Obtener token** — `POST /api/auth/token`

Content-Type: `application/x-www-form-urlencoded`

| Campo | Descripción |
|-------|-------------|
| `username` | Usuario configurado |
| `password` | Contraseña configurada |

Respuesta (200):

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**Perfil** — `GET /api/auth/me`  
Header: `Authorization: Bearer <token>`

### Síntesis de audio

**Generar audio** — `POST /api/tts/audio-tts`  
Header: `Authorization: Bearer <token>`  
Content-Type: `application/json`

Cuerpo de ejemplo:

```json
{
  "story_id": "nota-2026-001",
  "text": "<p>El Congreso aprobó la ley ayer.</p><p>El Ejecutivo anunció medidas.</p>",
  "audio": "marin2"
}
```

Alias de campos aceptados: `id_historia`, `textEnd`, `text`.

| Campo `audio` | Descripción |
|---------------|-------------|
| `marin1` | Misma voz; estilo con velocidad 1500 % en instrucciones |
| `marin2` | Misma voz; estilo con velocidad 2000 % en instrucciones |
| `cedar` | Voz masculina |

Respuesta exitosa (200):

```json
{
  "url_audio": "https://<cuenta>.blob.core.windows.net/tts-audio/tts/...?<sas>",
  "duration_seconds": 42.15,
  "success": true
}
```

## Flujo de procesamiento (`/audio-tts`)

1. Reserva o reutiliza fila en Table Storage (misma `story_id` + hash de texto + voz).
2. Preprocesa HTML/Markdown y divide en oraciones.
3. Llama a Azure OpenAI `audio/speech` por cada oración (WAV).
4. Concatena los WAV con ~50 ms de silencio entre oraciones.
5. Sube el archivo a Blob (`{prefix}/{story_id}/{request_id}/{voice}.wav`).
6. Devuelve URL SAS y duración; marca la fila de idempotencia como `completed`.

