"""
Authentication endpoints:

  POST  /api/v1/auth/register/client       — Register a new client
  POST  /api/v1/auth/register/partenaire   — Register a new partenaire
  POST  /api/v1/auth/login                 — Login (any role)
  POST  /api/v1/auth/refresh               — Refresh access token
  GET   /api/v1/auth/me                    — Get current user profile
  POST  /api/v1/auth/logout                — Logout (client-side token invalidation)
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.db.session import get_db
from app.schemas.auth import (
    ClientRegisterRequest,
    LoginRequest,
    PartenaireRegisterRequest,
    RefreshTokenRequest,
    TokenData,
    TokenResponse,
    UserMeResponse,
)
import app.services.auth_service as auth_service
from app.services.contact_service import upsert_contact   # ← NOUVEAU

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register/client",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription client",
    description="Crée un nouveau compte client et retourne les tokens JWT.",
)
async def register_client(
    data: ClientRegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    token_response = await auth_service.register_client(data, session)

    # ── Sync contact ──────────────────────────────────────
    # Récupérer l'utilisateur créé pour obtenir son id
    user = await auth_service._get_user_by_email(session, data.email)
    if user:
        await upsert_contact(
            session,
            email     = user.email,
            telephone = user.telephone,
            nom       = user.nom,
            prenom    = user.prenom,
            type      = "client",
            source_id = user.id,
        )
        await session.commit()

    return token_response


@router.post(
    "/register/partenaire",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Inscription partenaire",
    description=(
        "Crée un nouveau compte partenaire (statut EN_ATTENTE). "
        "Un admin devra valider le compte avant activation."
    ),
)
async def register_partenaire(
    data: PartenaireRegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await auth_service.register_partenaire(data, session)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Connexion",
    description="Authentifie un utilisateur (client, partenaire ou admin) et retourne les tokens JWT.",
)
async def login(
    data: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await auth_service.login(data, session)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Renouveler le token",
    description="Échange un refresh token valide contre une nouvelle paire de tokens.",
)
async def refresh(
    data: RefreshTokenRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    return await auth_service.refresh_tokens(data.refresh_token, session)


@router.get(
    "/me",
    response_model=UserMeResponse,
    summary="Profil utilisateur courant",
    description="Retourne le profil complet de l'utilisateur authentifié.",
)
async def me(
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserMeResponse:
    return await auth_service.get_current_user_profile(token_data, session)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Déconnexion",
    description=(
        "Déconnecte l'utilisateur. "
        "Les tokens JWT sont stateless — la déconnexion côté serveur "
        "consiste à confirmer la suppression côté client. "
        "Pour une invalidation complète, utilisez une blacklist Redis (future évolution)."
    ),
)
async def logout(
    _: TokenData = Depends(get_current_user),
) -> None:
    # JWT is stateless. Client must discard both tokens.
    # Future: add token to Redis blacklist here.
    return


# ── Profil ────────────────────────────────────────────────
from app.schemas.auth import (
    UpdateProfileRequest, RequestEmailChangeRequest, ConfirmEmailChangeRequest,
    ConfirmPasswordChangeRequest, ProfileOTPResponse,
)


@router.put("/me", response_model=UserMeResponse,
            summary="Modifier le profil (nom, prénom, téléphone)")
async def update_profile(
    data: UpdateProfileRequest,
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await auth_service.update_profile(token_data.user_id, data, session)


@router.post("/me/request-email-change", response_model=ProfileOTPResponse,
             summary="Demander changement email — envoie OTP au nouvel email")
async def request_email_change(
    data: RequestEmailChangeRequest,
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await auth_service.request_email_change(
        token_data.user_id, data.new_email, session
    )


@router.post("/me/confirm-email-change", response_model=UserMeResponse,
             summary="Confirmer changement email avec OTP")
async def confirm_email_change(
    data: ConfirmEmailChangeRequest,
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await auth_service.confirm_email_change(
        token_data.user_id, data.new_email, data.code, session
    )


@router.post("/me/request-password-change", response_model=ProfileOTPResponse,
             summary="Demander changement mot de passe — envoie OTP à l'email courant")
async def request_password_change(
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await auth_service.request_password_change(token_data.user_id, session)


@router.post("/me/confirm-password-change",
             summary="Confirmer changement mot de passe avec OTP")
async def confirm_password_change(
    data: ConfirmPasswordChangeRequest,
    token_data: TokenData = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await auth_service.confirm_password_change(
        token_data.user_id, data.code, data.new_password, session
    )


# ── Google OAuth ──────────────────────────────────────────
from pydantic import BaseModel as _BM
import httpx as _httpx
from app.models.utilisateur import (
    Utilisateur as _Utilisateur,
    Client as _Client,
    RoleUtilisateur as _Role,
)
from app.core.security import hash_password as _hash_pw
import secrets as _secrets


class GoogleAuthRequest(_BM):
    credential: str  # JWT token from Google GSI


@router.post("/google", response_model=TokenResponse,
             summary="Connexion / inscription via Google OAuth")
async def google_auth(
    data: GoogleAuthRequest,
    session: AsyncSession = Depends(get_db),
):
    """Vérifie le credential JWT Google, crée le compte client si besoin, retourne les tokens."""
    # 1. Vérifier le token auprès de Google
    async with _httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://oauth2.googleapis.com/tokeninfo?id_token={data.credential}"
        )
    if resp.status_code != 200:
        from app.core.exceptions import UnauthorizedException
        raise UnauthorizedException("Token Google invalide")

    info   = resp.json()
    email  = info.get("email")
    nom    = info.get("family_name") or ""
    prenom = info.get("given_name")  or ""

    if not email:
        from app.core.exceptions import UnauthorizedException
        raise UnauthorizedException("Email Google non disponible")

    # 2. Chercher ou créer l'utilisateur
    user = await auth_service._get_user_by_email(session, email)
    if not user:
        user = _Utilisateur(
            nom          = nom    or email.split("@")[0],
            prenom       = prenom or "Utilisateur",
            email        = email,
            mot_de_passe = _hash_pw(_secrets.token_urlsafe(32)),
            role         = _Role.CLIENT,
        )
        session.add(user)
        await session.flush()
        session.add(_Client(id=user.id))
        await session.commit()
        await session.refresh(user)

        # ── Sync contact (nouveau compte Google uniquement) ──
        await upsert_contact(
            session,
            email     = user.email,
            telephone = None,
            nom       = user.nom,
            prenom    = user.prenom,
            type      = "client",
            source_id = user.id,
        )
        await session.commit()

    return auth_service._build_token_response(user)