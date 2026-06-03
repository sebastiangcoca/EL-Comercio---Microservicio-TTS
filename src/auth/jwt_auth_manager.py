"""
Modulo: emision y validacion de JWT HS256 locales y verificacion de login con bcrypt en memoria.
"""

from __future__ import annotations

import time
from typing import Any

import bcrypt
from jose import JWTError, jwt

from core.config import Settings
from .models import User


def _secret_bytes_for_bcrypt(plain: str) -> bytes:
    """
    Convierte texto a bytes UTF-8 respetando el limite de 72 bytes de bcrypt.

    Args:
        plain: Contrasena en texto plano.

    Returns:
        Bytes truncados si superan el limite del algoritmo.
    """
    return plain.encode("utf-8")[:72]


class JwtAuthManager:
    """
    Emite y valida JWT firmados en esta API; comprueba login con bcrypt respecto a hash en memoria.
    """

    def __init__(self, auth_cfg: Settings.Auth) -> None:
        """
        Construye el gestor y calcula una vez el hash bcrypt de jwt-auth-password en memoria.

        Args:
            auth_cfg: Bloque Settings.Auth con secreto, TTL y credenciales de login.
        """
        self._secret = (auth_cfg.jwt_secret_key or "").strip()
        self._algorithm = auth_cfg.jwt_algorithm or "HS256"
        self._expire_minutes = auth_cfg.access_token_expire_minutes
        self._expected_username = (auth_cfg.jwt_auth_username or "").strip()
        plain_pw = auth_cfg.jwt_auth_password_plain or ""
        if plain_pw:
            self._password_hash_memory: bytes = bcrypt.hashpw(
                _secret_bytes_for_bcrypt(plain_pw),
                bcrypt.gensalt(rounds=12),
            )
        else:
            self._password_hash_memory = b""

    def verify_login(self, username: str, password: str) -> bool:
        """
        Verifica usuario y contrasena frente a jwt-auth-username y jwt-auth-password.

        Args:
            username: Usuario recibido en OAuth2 Password Grant.
            password: Contrasena recibida en OAuth2 Password Grant.

        Returns:
            True si las credenciales coinciden (bcrypt).
        """
        if not self._expected_username or not self._password_hash_memory:
            return False
        if username != self._expected_username:
            return False
        try:
            return bcrypt.checkpw(
                _secret_bytes_for_bcrypt(password),
                self._password_hash_memory,
            )
        except ValueError:
            return False

    def create_access_token(self, subject_username: str) -> tuple[str, int]:
        """
        Firma un access token JWT HS256 con exp e iat.

        Args:
            subject_username: Claim sub (nombre de usuario).

        Returns:
            Tupla (cadena JWT, segundos hasta expiracion efectivos).
        """
        if not self._secret:
            raise ValueError("JWT-SECRET-KEY no configurado")

        now_ts = int(time.time())
        ttl_seconds = max(60, self._expire_minutes * 60)
        expire_ts = now_ts + ttl_seconds

        claims: dict[str, Any] = {
            "sub": subject_username,
            "iat": now_ts,
            "exp": expire_ts,
        }

        encoded = jwt.encode(claims, self._secret, algorithm=self._algorithm)
        return encoded, ttl_seconds

    def decode_user(self, access_token: str) -> User:
        """
        Valida firma y exp del JWT y mapea claims a User.

        Args:
            access_token: Token sin prefijo Bearer.

        Returns:
            Instancia User para dependencias y middleware.

        Raises:
            JWTError: Token invalido o expirado.
        """
        if not self._secret:
            raise JWTError("JWT-SECRET-KEY no configurado")

        payload = jwt.decode(
            access_token,
            self._secret,
            algorithms=[self._algorithm],
            options={"verify_signature": True, "verify_exp": True},
        )
        return User.from_access_token_claims(payload)
