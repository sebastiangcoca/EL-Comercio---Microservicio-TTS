"""
Rutas de autenticacion: OAuth2 Password Grant (POST /token), prueba /test y perfil /me.
"""

# -----------------------------------------------------------------------------
# region                           IMPORTS
# -----------------------------------------------------------------------------
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, status
from fastapi.responses import JSONResponse

from auth.dependencies import auth_manager, get_current_active_user
from auth.models import User

# endregion

# -----------------------------------------------------------------------------
# region               ROUTER
# -----------------------------------------------------------------------------
router = APIRouter()


@router.post("/token")
async def login_access_token(
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    """
    Valida credenciales y devuelve JWT HS256.

    El cliente debe enviar `application/x-www-form-urlencoded` con `username` y `password`.

    Returns:
        Dict con access_token, token_type y expires_in (segundos).

    Raises:
        HTTPException: 401 si las credenciales son incorrectas; 503 si falta JWT-SECRET-KEY.
    """
    if not auth_manager.verify_login(username, password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        token, expires_in = auth_manager.create_access_token(username)
    except ValueError as e:
        logging.error("No se pudo emitir JWT: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service misconfigured",
        ) from e

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }


@router.get("/test")
async def test():
    """
    Endpoint ligero para comprobar que el router de auth esta activo.

    Returns:
        JSON con message ok.
    """
    return JSONResponse(content={"message": "ok"}, status_code=200)


@router.get("/me")
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user),
):
    """
    Devuelve claims del usuario autenticado segun el Bearer JWT.

    Returns:
        Diccionario con el username del usuario.
    """
    return {"username": current_user.username}
