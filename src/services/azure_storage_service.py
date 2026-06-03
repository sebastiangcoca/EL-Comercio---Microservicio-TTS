## Azure Storage: Blob (audio + SAS) y Table (idempotencia /audio-tts).

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import urlparse

from azure.core.credentials import AzureNamedKeyCredential
from azure.core.exceptions import HttpResponseError, ResourceExistsError, ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

from core.config import Settings, settings

logger = logging.getLogger(__name__)

_STATUS_PENDING = "pending"
_STATUS_COMPLETED = "completed"


class IdempotencyTableOperationError(Exception):
    """
    Error al leer o escribir la tabla de idempotencia (red, credenciales o servicio Table).
    """


class IdempotencyPendingTimeoutError(Exception):
    """
    Otra peticion mantuvo la clave en pending mas tiempo que el maximo de espera configurado.
    """


@dataclass
class ChunkedMp3TtsIdempotencyRow:
    """
    Fila completada para /audio-tts chunked MP3: un blob (una voz: marin o cedar) para un unico texto.
    """

    request_id: str
    voice: str
    path_audio: str
    url_audio: str
    sas_expires_at: Optional[datetime]
    output_format: str
    duration_seconds: float
    size_bytes: int


class AzureStorageService:
    """
    Almacena archivos de audio en Azure Blob Storage y emite SAS de solo lectura.
    """

    def __init__(self):
        """
        Inicializa el cliente de Blob con URL de cuenta y clave.

        Raises:
            ValueError: Si faltan URL de cuenta o clave.
        """
        cfg = settings.azure_storage
        self._container = cfg.container_name
        self._account_url = cfg.account_url.rstrip("/")
        self._account_key = cfg.account_key
        # TTL del SAS en horas (admite decimales, p. ej. 0.083333 ~= 5 min). Minimo 1 segundo.
        self._sas_ttl_hours = max(1.0 / 3600.0, float(cfg.sas_ttl_hours))
        self._prefix = cfg.blob_prefix.strip("/")

        if not self._account_url:
            raise ValueError("AZURE_STORAGE_ACCOUNT_URL no configurada")
        if not self._account_key:
            raise ValueError("AZURE_STORAGE_ACCOUNT_KEY no configurada")

        self._account_name = self._parse_account_name(self._account_url)
        self._client = BlobServiceClient(account_url=self._account_url, credential=self._account_key)

    @staticmethod
    def sanitize_article_id(article_id: str) -> str:
        """
        Normaliza el identificador de artículo para rutas de blob y claves de Table (PartitionKey).

        Args:
            article_id: Identificador de nota tal como llega en la API.

        Returns:
            Cadena segura y acotada para usar en rutas y particiones.
        """
        return re.sub(r"[^a-zA-Z0-9._-]", "_", article_id)[:200]

    @staticmethod
    def _parse_account_name(account_url: str) -> str:
        """
        Obtiene el nombre de la cuenta desde la URL del endpoint.

        Args:
            account_url: URL tipo https://nombre.blob.core.windows.net

        Returns:
            Nombre de la cuenta de almacenamiento.
        """
        parsed = urlparse(account_url)
        host = parsed.netloc or ""
        match = re.match(r"^([^.]+)\.blob\.core\.windows\.net$", host, re.I)
        if match:
            return match.group(1)
        raise ValueError(f"No se pudo derivar el nombre de cuenta desde: {account_url}")

    def upload_audio_bytes(
        self,
        data: bytes,
        blob_path: str,
        content_type: str,
    ) -> None:
        """
        Sube bytes al contenedor configurado.

        Args:
            data: Contenido binario del audio.
            blob_path: Ruta del blob dentro del contenedor (sin barra inicial).
            content_type: MIME del audio (p. ej. audio/mpeg para MP3).
        """
        from azure.storage.blob import ContentSettings

        blob_name = blob_path.lstrip("/")
        blob_client = self._client.get_blob_client(container=self._container, blob=blob_name)
        blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )
        logger.info("Blob subido: %s/%s", self._container, blob_name)

    def build_blob_path(self, article_id: str, request_id: str, variant: str, file_extension: str) -> str:
        """
        Construye la ruta lógica del blob bajo el prefijo configurado.

        Args:
            article_id: Identificador de la noticia.
            request_id: Identificador único de la solicitud.
            variant: Sufijo lógico (full, 1m, 1_5m).
            file_extension: Extensión con punto, p. ej. .mp3

        Returns:
            Ruta relativa del blob.
        """
        ext = file_extension if file_extension.startswith(".") else f".{file_extension}"
        safe_article = self.sanitize_article_id(article_id)
        return f"{self._prefix}/{safe_article}/{request_id}/{variant}{ext}"

    def generate_read_sas_url(
        self,
        blob_path: str,
        expiry: Optional[datetime] = None,
    ) -> Tuple[str, datetime]:
        """
        Genera una URL con SAS de solo lectura para el blob indicado.

        Args:
            blob_path: Ruta del blob en el contenedor.
            expiry: Fecha UTC de caducidad del SAS; si es None, se calcula con el TTL configurado.

        Returns:
            Tupla (url_completa, fecha UTC de expiración del SAS).
        """
        blob_name = blob_path.lstrip("/")
        if expiry is None:
            expiry = datetime.now(timezone.utc) + timedelta(hours=self._sas_ttl_hours)
        sas_token = generate_blob_sas(
            account_name=self._account_name,
            container_name=self._container,
            blob_name=blob_name,
            account_key=self._account_key,
            permission=BlobSasPermissions(read=True),
            expiry=expiry,
        )
        base = f"{self._account_url}/{self._container}/{blob_name}"
        url = f"{base}?{sas_token}"
        return url, expiry

    def blob_exists(self, blob_path: str) -> bool:
        """
        Indica si el blob existe en el contenedor configurado.

        Args:
            blob_path: Ruta del blob dentro del contenedor (sin barra inicial).

        Returns:
            True si existe; False si no o ante error de comprobación (conservador: False).
        """
        blob_name = blob_path.lstrip("/")
        blob_client = self._client.get_blob_client(container=self._container, blob=blob_name)
        try:
            return bool(blob_client.exists())
        except Exception as e:
            logger.warning("blob_exists fallo para %s: %s", blob_name, e)
            return False


class AzureTableTtsIdempotencyService:
    """
    Coordina filas Azure Table (PartitionKey = historia/nota sanitizada, RowKey = hash) para idempotencia TTS.

    Convenciones de RowKey: flujo chunked MP3 (un texto + voz) con ``compute_chunked_mp3_voice_text_hash``.
    """

    def __init__(self, cfg: Settings.TtsIdempotencyConnector) -> None:
        """
        Inicializa el cliente de Table con la misma cuenta que Blob Storage.

        Args:
            cfg: Conector de idempotencia ya validado (enabled y credenciales).

        Raises:
            ValueError: Si la configuracion no permite construir el cliente.
        """
        if not cfg.enabled or not cfg.table_service_url or not cfg.account_key or not cfg.storage_account_name:
            raise ValueError("AzureTableTtsIdempotencyService requiere idempotencia habilitada y credenciales completas.")
        self._cfg = cfg
        credential = AzureNamedKeyCredential(cfg.storage_account_name, cfg.account_key)
        table_service = TableServiceClient(endpoint=cfg.table_service_url, credential=credential)
        try:
            # create_table_if_not_exists pertenece a TableServiceClient, no a TableClient.
            self._table = table_service.create_table_if_not_exists(table_name=cfg.table_name)
        except HttpResponseError as e:
            logger.error("No se pudo crear o abrir la tabla de idempotencia TTS: %s", e)
            raise IdempotencyTableOperationError(str(e)) from e

    @staticmethod
    def compute_chunked_mp3_voice_text_hash(text_end: str, voice: str) -> str:
        """
        Calcula el hash SHA-256 del texto crudo + voz con esquema versionado (por oraciones, salida MP3).

        Args:
            text_end: Contenido del campo textEnd tal cual en la peticion.
            voice: Voz elegida (marin o cedar).

        Returns:
            Digest hex en minusculas (64 caracteres).
        """
        payload = json.dumps(
            {
                "schema": "chunked-sentences-wav-marin-cedar-v1",
                "text": text_end,
                "voice": (voice or "").strip().lower(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def try_create_pending_row(self, partition_key: str, row_key: str, request_id: str) -> bool:
        """
        Intenta crear una fila en estado pending para reservar la generacion.

        Args:
            partition_key: id_nota sanitizado (misma regla que rutas blob).
            row_key: Hash hex del texto crudo.
            request_id: UUID de esta ejecucion (se usara en rutas blob si se completa aqui).

        Returns:
            True si esta instancia creo la fila; False si ya existia (409).

        Raises:
            IdempotencyTableOperationError: Si la API Table falla de forma inesperada.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        entity = {
            "PartitionKey": partition_key,
            "RowKey": row_key,
            "Status": _STATUS_PENDING,
            "RequestId": request_id,
            "PendingSince": now_iso,
        }
        try:
            self._table.create_entity(entity=entity)
            return True
        except ResourceExistsError:
            return False
        except HttpResponseError as e:
            logger.exception("create_entity pending fallo: %s", e)
            raise IdempotencyTableOperationError(str(e)) from e

    def get_entity(self, partition_key: str, row_key: str) -> Optional[dict]:
        """
        Obtiene la entidad por clave o None si no existe.

        Args:
            partition_key: PartitionKey de la tabla.
            row_key: RowKey (hash).

        Returns:
            Diccionario de propiedades de la entidad, o None si 404.

        Raises:
            IdempotencyTableOperationError: Errores distintos de 404.
        """
        try:
            return dict(self._table.get_entity(partition_key=partition_key, row_key=row_key))
        except ResourceNotFoundError:
            return None
        except HttpResponseError as e:
            logger.exception("get_entity fallo: %s", e)
            raise IdempotencyTableOperationError(str(e)) from e

    def delete_row(self, partition_key: str, row_key: str) -> None:
        """
        Elimina la fila de idempotencia (reintento limpio o limpieza de pending obsoleto).

        Args:
            partition_key: PartitionKey.
            row_key: RowKey.

        Raises:
            IdempotencyTableOperationError: Si el borrado falla por motivo distinto a 404.
        """
        try:
            self._table.delete_entity(partition_key=partition_key, row_key=row_key)
        except ResourceNotFoundError:
            return
        except HttpResponseError as e:
            logger.exception("delete_entity fallo: %s", e)
            raise IdempotencyTableOperationError(str(e)) from e

    def mark_completed_chunked_mp3_row(
        self,
        partition_key: str,
        row_key: str,
        *,
        request_id: str,
        voice: str,
        path_audio: str,
        url_audio: str,
        sas_expires_at: datetime,
        output_format: str,
        duration_seconds: float,
        size_bytes: int,
    ) -> None:
        """
        Marca la fila como completed con una ruta de blob y metadatos (flujo chunked por oraciones, salida MP3).

        Args:
            partition_key: PartitionKey.
            row_key: RowKey (hash del texto con esquema chunked MP3 y voz).
            request_id: Identificador de la solicitud usado en rutas blob.
            voice: Voz usada (marin o cedar).
            path_audio: Ruta relativa del blob MP3 final.
            url_audio: URL SAS completa generada al momento de la subida.
            sas_expires_at: Fecha UTC de expiracion del token SAS de la URL de audio.
            output_format: Formato de audio (p. ej. mp3).
            duration_seconds: Duracion del audio final en segundos.
            size_bytes: Tamano del audio final en bytes.

        Raises:
            IdempotencyTableOperationError: Si update falla.
        """
        entity = {
            "PartitionKey": partition_key,
            "RowKey": row_key,
            "Status": _STATUS_COMPLETED,
            "RequestId": request_id,
            "Voice": (voice or "").strip().lower(),
            "PathAudio": path_audio,
            "UrlAudio": url_audio,
            "SasExpiresAt": sas_expires_at.isoformat(),
            "OutputFormat": output_format,
            "DurationSeconds": float(duration_seconds),
            "SizeBytes": int(size_bytes),
        }
        try:
            self._table.update_entity(mode=UpdateMode.MERGE, entity=entity)
        except HttpResponseError as e:
            logger.exception("update_entity chunked-mp3 completed fallo: %s", e)
            raise IdempotencyTableOperationError(str(e)) from e

    @staticmethod
    def row_from_completed_chunked_mp3_entity(entity: dict) -> Optional[ChunkedMp3TtsIdempotencyRow]:
        """
        Construye un DTO de cache chunked MP3 a partir de una entidad completed.

        Args:
            entity: Diccionario devuelto por get_entity.

        Returns:
            ChunkedMp3TtsIdempotencyRow si los campos requeridos estan presentes; None si incompleta o distinto flujo.
        """
        if entity.get("Status") != _STATUS_COMPLETED:
            return None
        if "PathAudio" not in entity:
            return None
        try:
            rid = str(entity["RequestId"])
            voice = str(entity.get("Voice", "")).strip().lower()
            path_audio = str(entity["PathAudio"])
            url_audio = str(entity.get("UrlAudio", ""))
            sas_expires_at_raw = entity.get("SasExpiresAt")
            sas_expires_at = datetime.fromisoformat(sas_expires_at_raw) if sas_expires_at_raw else None
            fmt = str(entity["OutputFormat"])
            duration = float(entity.get("DurationSeconds", 0.0))
            size_bytes = int(entity.get("SizeBytes", 0))
        except (KeyError, TypeError, ValueError):
            return None
        if not voice:
            return None
        return ChunkedMp3TtsIdempotencyRow(
            request_id=rid,
            voice=voice,
            path_audio=path_audio,
            url_audio=url_audio,
            sas_expires_at=sas_expires_at,
            output_format=fmt,
            duration_seconds=duration,
            size_bytes=size_bytes,
        )

    def _pending_is_stale(self, entity: dict) -> bool:
        """
        Determina si una fila pending supero el umbral de tiempo sin completarse.

        Args:
            entity: Entidad con Status pending y opcionalmente PendingSince ISO.

        Returns:
            True si debe tratarse como abandonada.
        """
        raw = entity.get("PendingSince")
        if not raw or not isinstance(raw, str):
            return False
        try:
            normalized = raw.replace("Z", "+00:00")
            started = datetime.fromisoformat(normalized)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        age = (datetime.now(timezone.utc) - started).total_seconds()
        return age > self._cfg.pending_stale_seconds

    async def resolve_generate_or_cache_hit_chunked_mp3(
        self,
        *,
        partition_key: str,
        row_key: str,
        request_id: str,
        storage: AzureStorageService,
    ) -> Optional[ChunkedMp3TtsIdempotencyRow]:
        """
        Cache o reserva pending para el flujo chunked MP3 (un blob, un texto, una voz).

        Args:
            partition_key: PartitionKey (historia sanitizada).
            row_key: RowKey (hash chunked MP3 del texto crudo + voz).
            request_id: UUID de esta peticion si se reserva pending.
            storage: Cliente Blob para comprobar existencia en hits de cache.

        Returns:
            ChunkedMp3TtsIdempotencyRow si hay cache valido; None si debe generarse TTS y subida.

        Raises:
            IdempotencyPendingTimeoutError: Si se agota la espera ante pending ajeno.
            IdempotencyTableOperationError: Errores de Table no recuperables.
        """
        import time

        deadline = time.monotonic() + self._cfg.pending_poll_max_seconds
        interval = self._cfg.pending_poll_interval_seconds

        while True:
            if time.monotonic() > deadline:
                raise IdempotencyPendingTimeoutError(
                    f"Tiempo de espera idempotencia ({self._cfg.pending_poll_max_seconds}s) agotado."
                )

            created = await asyncio.to_thread(self.try_create_pending_row, partition_key, row_key, request_id)
            if created:
                return None

            entity = await asyncio.to_thread(self.get_entity, partition_key, row_key)
            if entity is None:
                await asyncio.sleep(interval)
                continue

            status = entity.get("Status")
            if status == _STATUS_COMPLETED:
                row = self.row_from_completed_chunked_mp3_entity(entity)
                if row is None:
                    await asyncio.to_thread(self.delete_row, partition_key, row_key)
                    continue
                if not row.path_audio:
                    await asyncio.to_thread(self.delete_row, partition_key, row_key)
                    continue
                exists = await asyncio.to_thread(storage.blob_exists, row.path_audio)
                if exists:
                    return row
                await asyncio.to_thread(self.delete_row, partition_key, row_key)
                continue

            if status == _STATUS_PENDING:
                if self._pending_is_stale(entity):
                    await asyncio.to_thread(self.delete_row, partition_key, row_key)
                    continue
                await asyncio.sleep(interval)
                continue

            logger.warning("Estado de idempotencia desconocido Status=%s; reintentando.", status)
            await asyncio.sleep(interval)
