## _______________________________________________________________________________________
## Modelos Pydantic para autenticacion JWT local:
## - `UserBase`: Atributos comunes de usuario.
## - `User`: Usuario derivado del access token (claims).
## _______________________________________________________________________________________

# -----------------------------------------------------------------------------------------
# region                             Librerías
# -----------------------------------------------------------------------------------------

from pydantic import BaseModel


# -----------------------------------------------------------------------------------------
# region                       Modelos de Usuario
# -----------------------------------------------------------------------------------------

class UserBase(BaseModel):
    """
    Modelo base de usuario con atributos comunes.

    Attributes:
        username: Nombre de usuario unico para autenticacion.
        disabled: Indica si el usuario esta deshabilitado.
    """

    username: str
    disabled: bool = False


class User(UserBase):
    """
    Usuario expuesto en respuestas de API; proviene del JWT emitido por esta API.
    """

    @classmethod
    def from_access_token_claims(cls, payload: dict) -> "User":
        """
        Construye User desde claims JWT locales (sub).

        Args:
            payload: Payload decodificado del access token.

        Returns:
            User con datos no sensibles para el cliente.
        """
        sub = payload.get("sub") or "unknown"
        return cls(username=sub, disabled=False)
