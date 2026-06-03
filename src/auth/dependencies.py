## _______________________________________________________________________________________
## Dependencias FastAPI para JWT local:
## - HTTPBearer en cabecera Authorization.
## - Singleton JwtAuthManager para firmar y validar tokens.
## - get_current_user / get_current_active_user para rutas protegidas.
## _______________________________________________________________________________________

# -----------------------------------------------------------------------------------------
# region                             IMPORTS Y CONFIGURACIÓN
# -----------------------------------------------------------------------------------------
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from pydantic import ValidationError

from core.config import settings
from .jwt_auth_manager import JwtAuthManager
from .models import User

security = HTTPBearer()

auth_manager = JwtAuthManager(settings.auth)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> User:
    """
    Obtiene el usuario actual a partir del JWT Bearer emitido por esta API.

    Args:
        credentials: Credenciales HTTP Bearer.

    Returns:
        User autenticado.

    Raises:
        HTTPException: 401 si el token es invalido o expiro.
    """
    try:
        return auth_manager.decode_user(credentials.credentials)
    except (JWTError, ValidationError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Comprueba que el usuario autenticado no este marcado como deshabilitado.

    Args:
        current_user: Usuario resuelto por get_current_user.

    Returns:
        Usuario activo.

    Raises:
        HTTPException: 400 si disabled es True.
    """
    if current_user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    return current_user
