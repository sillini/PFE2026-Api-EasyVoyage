"""
FastAPI injectable dependencies for authentication and authorization.

Usage in endpoints:
    @router.get("/me")
    async def me(token_data: TokenData = Depends(get_current_user)):
        ...

    @router.get("/admin-only")
    async def admin_route(_: TokenData = Depends(require_role("ADMIN"))):
        ...

    @router.post("/super-admin-only")
    async def super_admin_route(_: TokenData = Depends(require_super_admin)):
        ...
"""
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CredentialsException, ForbiddenException
from app.core.security import decode_token
from app.db.session import get_db
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


# ══════════════════════════════════════════════════════════
#  ✨ NEW : require_super_admin
# ══════════════════════════════════════════════════════════
async def require_super_admin(
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TokenData:
    """
    Dépendance FastAPI : vérifie que l'utilisateur est un Super Admin.

    Étapes de vérification :
      1. L'utilisateur doit avoir le rôle ADMIN (vérification rapide via JWT).
      2. Sa ligne dans la table `admin` doit avoir is_super_admin = true
         (vérification en base — un admin ne peut pas devenir super admin
         simplement en éditant son JWT).

    Si l'une des deux conditions est fausse → 403 Forbidden.

    Usage :
        @router.delete("/admin/admins/{id}")
        async def supprimer(_: TokenData = Depends(require_super_admin)):
            ...
    """
    # 1. Doit être ADMIN au minimum
    if token_data.role != "ADMIN":
        raise ForbiddenException(
            "Accès réservé aux Super Administrateurs."
        )

    # 2. Vérifier en base que c'est bien un Super Admin
    # (Import local pour éviter les cycles d'import au démarrage)
    from app.models.utilisateur import Admin

    result = await session.execute(
        select(Admin.is_super_admin).where(Admin.id == token_data.user_id)
    )
    is_super = result.scalar_one_or_none()

    if not is_super:
        raise ForbiddenException(
            "Cette action est réservée aux Super Administrateurs."
        )

    return token_data