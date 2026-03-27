"""
FastAPI injectable dependencies for authentication and authorization.

Usage in endpoints:
    @router.get("/me")
    async def me(token_data: TokenData = Depends(get_current_user)):
        ...

    @router.get("/admin-only")
    async def admin_route(_: TokenData = Depends(require_role("ADMIN"))):
        ...
"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from app.core.exceptions import CredentialsException, ForbiddenException
from app.core.security import decode_token
from app.schemas.auth import TokenData

# HTTPBearer extracts the token from the Authorization: Bearer <token> header
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> TokenData:
    """
    Validate the JWT access token from the Authorization header.
    Returns decoded TokenData or raises 401.
    """
    if not credentials:
        raise CredentialsException("Token d'authentification manquant")

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise CredentialsException("Token invalide ou expiré")

    if payload.get("type") != "access":
        raise CredentialsException("Type de token invalide")

    user_id: str | None = payload.get("sub")
    role: str | None = payload.get("role")

    if user_id is None or role is None:
        raise CredentialsException("Payload du token incomplet")

    return TokenData(user_id=int(user_id), role=role, token_type="access")


def require_role(*roles: str):
    """
    Factory that returns a dependency enforcing one of the given roles.

    Example:
        Depends(require_role("ADMIN"))
        Depends(require_role("ADMIN", "PARTENAIRE"))
    """
    def _check(token_data: TokenData = Depends(get_current_user)) -> TokenData:
        if token_data.role not in roles:
            raise ForbiddenException(
                f"Accès réservé aux rôles : {', '.join(roles)}"
            )
        return token_data

    return _check


# Convenience shortcuts
require_admin = require_role("ADMIN")
require_client = require_role("CLIENT")
require_partenaire = require_role("PARTENAIRE")
require_admin_or_partenaire = require_role("ADMIN", "PARTENAIRE")