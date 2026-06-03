## Configuracion central: Azure OpenAI (TTS), Blob Storage y JWT local (opcional).

import logging
import os
from typing import Optional

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

load_dotenv(override=True)


def _get_env(primary_name: str, fallback_name: Optional[str] = None, default: Optional[str] = None) -> Optional[str]:
    """Lee variable de entorno: acepta nombre con guiones o con guiones bajos."""
    if fallback_name is None:
        fallback_name = primary_name.replace("-", "_")
    return os.getenv(primary_name) or os.getenv(fallback_name) or default


class SecretManager:
    """
    Secretos: Azure Key Vault si esta configurado; si no, variables de entorno.
    """

    def __init__(self, use_key_vault: Optional[bool] = None):
        self.client: Optional[SecretClient] = None
        self.use_key_vault = False

        if use_key_vault is False:
            logging.info("Key Vault deshabilitado explicitamente. Usando variables de entorno.")
            return

        key_vault_name = _get_env("KEY_VAULT_NAME", "key-vault-name", None)
        if not key_vault_name:
            logging.info("key-vault-name no configurado. Usando variables de entorno.")
            return

        vault_url = f"https://{key_vault_name}.vault.azure.net"
        try:
            credential = DefaultAzureCredential()
            self.client = SecretClient(vault_url=vault_url, credential=credential)
            self.use_key_vault = True
            logging.info("SecretManager conectado a Key Vault: %s", vault_url)
        except Exception as e:
            logging.warning("No se pudo inicializar Key Vault (%s): %s. Usando entorno.", vault_url, e)

    def get_secret(self, name: str) -> Optional[str]:
        """
        Obtiene un secreto desde Key Vault o variables de entorno segun la configuracion.
        Si Key Vault esta activo, solo busca alli; si no, lee exclusivamente del entorno.
        """
        if self.use_key_vault and self.client:
            try:
                return self.client.get_secret(name).value
            except Exception as e:
                logging.error("Secreto '%s' no encontrado en Key Vault: %s.", name, e)
                return None
        upper = name.upper()
        upper_underscore = upper.replace("-", "_")
        return os.getenv(name) or os.getenv(upper) or os.getenv(upper_underscore)


class Settings:
    """Configuracion de la aplicacion TTS El Comercio."""

    class AIServices:
        """Azure OpenAI: sintesis de voz (TTS)."""

        def __init__(self, secret_manager: SecretManager):
            """
            Carga configuracion del servicio TTS de Azure OpenAI.
            """
            self.model_tts_deployment: str = (
                secret_manager.get_secret("model-tts-deployment")
                or "gpt-4o-mini-tts"
            )
            # Nombre de modelo en el cuerpo JSON de /audio/speech (suele coincidir con el deployment)
            self.model_tts_api_name: str = (
                secret_manager.get_secret("model-tts-api-name")
                or self.model_tts_deployment
            )

            self.tts_api_key: Optional[str] = secret_manager.get_secret("azure-openai-api-key")
            self.tts_endpoint: Optional[str] = secret_manager.get_secret("azure-openai-endpoint")
            self.tts_openai_api_version: str = (
                secret_manager.get_secret("openai-api-version-tts")
                or "2025-03-01-preview"
            )

            if not self.tts_api_key:
                logging.warning("azure-openai-api-key no configurada.")
            if not self.tts_endpoint:
                logging.warning("azure-openai-endpoint no configurada.")

    class AzureStorageConnector:
        """Blob Storage para audios y SAS de solo lectura."""

        def __init__(self, secret_manager: SecretManager):
            """
            Configuracion de conexion a Azure Blob Storage y calculo de TTL para SAS.
            """
            self.account_url: str = (
                secret_manager.get_secret("azure-storage-account-url")
                or ""
            ).rstrip("/")
            self.account_key: Optional[str] = secret_manager.get_secret("azure-storage-account-key")
            self.container_name: str = (
                secret_manager.get_secret("azure-storage-container")
                or "tts-audio"
            )
            self.blob_prefix: str = (
                secret_manager.get_secret("azure-storage-blob-prefix")
                or "tts"
            ).strip("/")
            _sas_raw = secret_manager.get_secret("sas-ttl-hours") or "24"
            try:
                _sas_ttl = float(_sas_raw)
            except (TypeError, ValueError):
                _sas_ttl = 24.0
                logging.warning("sas-ttl-hours no numerico (%r); usando 24.", _sas_raw)
            if _sas_ttl <= 0:
                logging.warning("sas-ttl-hours debe ser > 0 (recibido %s); usando 24.", _sas_ttl)
                _sas_ttl = 24.0
            self.sas_ttl_hours: float = _sas_ttl

            if not self.account_url:
                logging.warning("azure-storage-account-url no configurada.")
            if not self.account_key:
                logging.warning(
                    "azure-storage-account-key no configurada (necesaria para SAS con clave de cuenta)."
                )

    class TtsIdempotencyConnector:
        """
        Azure Table Storage: deduplicacion siempre activa para /audio-tts (misma cuenta que Blob)
        cuando existen URL y clave y la URL sigue el patron *.blob.core.windows.net.
        """

        def __init__(self, azure_storage: "Settings.AzureStorageConnector"):
            """
            Inicializa la conexion a Azure Table Storage para idempotencia de TTS.
            """
            self.enabled: bool = False
            self.table_name: str = (
                _get_env("azure-tts-idempotency-table-name", "AZURE-TTS-IDEMPOTENCY-TABLE-NAME", "TtsAudioIdempotency")
                or "TtsAudioIdempotency"
            ).strip()
            self.pending_poll_max_seconds: float = float(
                _get_env("tts-idempotency-pending-poll-max-seconds", "TTS-IDEMPOTENCY-PENDING-POLL-MAX-SECONDS", "60")
                or "60"
            )
            self.pending_poll_interval_seconds: float = float(
                _get_env("tts-idempotency-pending-poll-interval-seconds", "TTS-IDEMPOTENCY-PENDING-POLL-INTERVAL-SECONDS", "0.5")
                or "0.5"
            )
            self.pending_stale_seconds: float = float(
                _get_env("tts-idempotency-pending-stale-seconds", "TTS-IDEMPOTENCY-PENDING-STALE-SECONDS", "900")
                or "900"
            )
            self.account_url: str = azure_storage.account_url
            self.account_key: Optional[str] = azure_storage.account_key
            self.table_service_url: str = ""
            self.storage_account_name: str = ""

            if not self.account_url or not self.account_key:
                logging.warning(
                    "Idempotencia TTS no disponible: falta azure-storage-account-url o azure-storage-account-key."
                )
                return

            try:
                self.storage_account_name = self._parse_account_name_from_blob_url(self.account_url)
                self.table_service_url = f"https://{self.storage_account_name}.table.core.windows.net"
                self.enabled = True
            except ValueError as e:
                logging.warning(
                    "Idempotencia TTS no disponible: la URL de Blob debe ser https://<cuenta>.blob.core.windows.net. %s",
                    e,
                )

        @staticmethod
        def _parse_account_name_from_blob_url(account_url: str) -> str:
            """Deriva el nombre de cuenta desde la URL de Blob (misma cuenta para Table API)."""
            import re
            from urllib.parse import urlparse

            parsed = urlparse(account_url.rstrip("/"))
            host = parsed.netloc or ""
            match = re.match(r"^([^.]+)\.blob\.core\.windows\.net$", host, re.I)
            if match:
                return match.group(1)
            raise ValueError(f"No se pudo derivar el nombre de cuenta desde: {account_url}")

    class Auth:
        """JWT HS256 local y credenciales OAuth2 password grant (/api/auth/token)."""

        def __init__(self, secret_manager: SecretManager):
            """
            Carga configuracion JWT y credenciales de login desde Key Vault o variables de entorno.
            """
            self.jwt_secret_key: Optional[str] = secret_manager.get_secret("jwt-secret-key")
            self.jwt_algorithm: str = (
                secret_manager.get_secret("jwt-algorithm")
                or "HS256"
            ).strip().upper()
            _mins_raw = secret_manager.get_secret("access-token-expire-minutes") or "30"
            try:
                self.access_token_expire_minutes: int = max(1, int(float(_mins_raw)))
            except (TypeError, ValueError):
                self.access_token_expire_minutes = 30
                logging.warning("access-token-expire-minutes no numerico (%r); usando 30.", _mins_raw)

            self.jwt_auth_username: Optional[str] = secret_manager.get_secret("jwt-auth-username")
            self.jwt_auth_password_plain: Optional[str] = secret_manager.get_secret("jwt-auth-password")
            sk = self.jwt_secret_key or ""
            if sk and len(sk) < 32:
                logging.warning(
                    "jwt-secret-key corto (%s caracteres); recomendado >= 32 bytes aleatorios.",
                    len(sk),
                )

    def __init__(self):
        """
        Inicializa todos los bloques de configuracion de la aplicacion.
        """
        use_kv = (_get_env("USE_KEY_VAULT", "use-key-vault", "false") or "false").lower() == "true"
        self.secret_manager = SecretManager(use_key_vault=use_kv)
        self.app_name: str = _get_env("app-name", "APP-NAME", "El Comercio TTS API") or "El Comercio TTS API"
        self.ai_services: Settings.AIServices = Settings.AIServices(self.secret_manager)
        self.azure_storage: Settings.AzureStorageConnector = Settings.AzureStorageConnector(self.secret_manager)
        self.tts_idempotency: Settings.TtsIdempotencyConnector = Settings.TtsIdempotencyConnector(self.azure_storage)
        self.auth: Settings.Auth = Settings.Auth(self.secret_manager)


settings = Settings()
