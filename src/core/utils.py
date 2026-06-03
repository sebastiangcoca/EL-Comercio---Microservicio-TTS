## Funciones auxiliares: IDs, zona horaria Colombia, decoradores de tiempo y lectura desde Blob.

#-----------------------------------------------------------------------------------------
#region                             Librerías
#-----------------------------------------------------------------------------------------

from azure.storage.blob import BlobServiceClient
from pytz import timezone

from datetime import datetime
import logging
import os
import timeit
import uuid


#-----------------------------------------------------------------------------------------
#region                     Generador de IDs con timestamp y UUID
#-----------------------------------------------------------------------------------------

def generate_id() -> str:
    """
    Genera un ID único combinando timestamp y UUID.

    Formato: YYYYMMDDHHMMSS-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    (timestamp corto + parte del UUID)

    Returns:
        str: ID único generado.
    """
    now = datetime.now()
    str_now = now.strftime("%Y%m%d%H%M%S")
    uuid_id = str(uuid.uuid4())
    short_uuid = "-".join(uuid_id.split("-")[:-1])
    chat_id = f"{short_uuid}-{str_now}"
    return chat_id


#-----------------------------------------------------------------------------------------
#region                  Obtener hora actual en la zona horaria de Colombia
#-----------------------------------------------------------------------------------------

def current_colombian_time_str() -> str:
    """
    Obtiene la hora actual en Colombia como string formateado.

    Returns:
        str: Hora actual en formato 'YYYY-MM-DD HH:MM:SS'.
    """
    current_time_str = (
        datetime.now(timezone("America/Bogota")).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    )
    return current_time_str


def current_colombian_time() -> datetime:
    """
    Obtiene la hora actual en Colombia como objeto datetime.

    Returns:
        datetime: Hora actual en zona horaria de Colombia.
    """
    current_time = datetime.now(timezone("America/Bogota")).replace(tzinfo=None).isoformat(
        timespec="microseconds"
    )
    return current_time


#-----------------------------------------------------------------------------------------
#region            Decorador para medir tiempo de ejecución de funciones (sync/async)
#-----------------------------------------------------------------------------------------

def timeit_decorator(func):
    """
    Decorador síncrono para medir tiempo de ejecución de funciones.

    Args:
        func: Función a decorar.

    Returns:
        wrapper: Función decorada que retorna (resultado, tiempo_ejecución).
    """

    def wrapper(*args, **kwargs):
        start_time = timeit.default_timer()
        result = func(*args, **kwargs)
        end_time = timeit.default_timer()
        elapsed_time = end_time - start_time
        return result, elapsed_time

    return wrapper


def timeit_decorator_async(func):
    """
    Decorador asíncrono para medir tiempo de ejecución de funciones async.

    Args:
        func: Función async a decorar.

    Returns:
        wrapper: Función async decorada que retorna (resultado, tiempo_ejecución).
    """

    async def wrapper(*args, **kwargs):
        start_time = timeit.default_timer()
        result = await func(*args, **kwargs)
        end_time = timeit.default_timer()
        elapsed_time = end_time - start_time
        return result, elapsed_time

    return wrapper


#-----------------------------------------------------------------------------------------
#region                  Funciones de manejo de Azure Blob Storage
#-----------------------------------------------------------------------------------------

def read_file_from_blob(blob_url):
    """
    Lee un archivo desde Azure Blob Storage usando URL de blob.

    Args:
        blob_url: URL completa del blob en Azure Storage.

    Returns:
        str: Contenido del archivo decodificado como string.
    """
    parts = blob_url.replace("https://", "").split("/")
    storage_account_with_domain = parts[0]
    container_name = parts[1]
    blob_path = "/".join(parts[2:])

    connection_string = os.getenv("AZURE-BLOB-STORAGE-CONNECTION-STRING") or os.getenv(
        "AZURE_BLOB_STORAGE_CONNECTION_STRING"
    )

    if connection_string:
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)

    blob_client = blob_service_client.get_blob_client(
        container=container_name,
        blob=blob_path,
    )

    download_stream = blob_client.download_blob()
    file_content = download_stream.readall()

    return file_content.decode("latin-1")
