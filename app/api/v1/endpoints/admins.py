"""
app/api/v1/endpoints/admins.py
================================
Endpoints — Gestion des administrateurs par le Super Admin.

⚠️ TOUTES les routes sont protégées par require_super_admin.
Un admin standard ne peut NI voir NI modifier d'autres admins.

Flux d'invitation en 3 étapes :
  POST /admin/admins/invite          → Envoie OTP par email
  POST /admin/admins/verify-code     → Vérifie le code OTP
  POST /admin/admins/create          → Crée le compte (+ envoie mdp par email)

CRUD :
  GET    /admin/admins                 → Liste avec filtres
  GET    /admin/admins/{id}            → Détail
  PATCH  /admin/admins/{id}/toggle     → Activer / désactiver
  PUT    /admin/admins/{id}            → Modifier (nom/prénom/tél)
  DELETE /admin/admins/{id}            → Supprimer
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_super_admin
from app.db.session import get_db
from app.models.utilisateur import Utilisateur
from app.schemas.auth import TokenData
from app.schemas.admin import (
    AdminListResponse,
    AdminResponse,
    CreateAdminRequest,
    CreateAdminResponse,
    InviteAdminRequest,
    InviteAdminResponse,
    ToggleAdminRequest,
    UpdateAdminRequest,
    VerifyAdminOTPRequest,
    VerifyAdminOTPResponse,
)
import app.services.admin_service as admin_service

router = APIRouter(
    prefix="/admin/admins",
    tags=["Super Admin — Administrateurs"],
)


# ═══════════════════════════════════════════════════════════
#  FLUX D'INVITATION EN 3 ÉTAPES
# ═══════════════════════════════════════════════════════════

@router.post(
    "/invite",
    response_model=InviteAdminResponse,
    status_code=status.HTTP_200_OK,
    summary="Étape 1 — Envoyer un code OTP au futur administrateur [SUPER ADMIN]",
)
async def invite_admin(
    data: InviteAdminRequest,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_super_admin),
):
    """
    Le Super Admin saisit l'email du futur administrateur.
    Un code OTP à 6 chiffres lui est envoyé par email.
    Validité : 15 minutes.
    """
    # Récupérer le nom du Super Admin connecté (pour personnaliser l'email)
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.id == current_user.user_id)
    )
    super_admin = result.scalar_one_or_none()
    invitant_prenom = super_admin.prenom if super_admin else "Le Super Administrateur"
    invitant_nom    = super_admin.nom    if super_admin else ""

    return await admin_service.invite_admin(
        email=data.email,
        invitant_prenom=invitant_prenom,
        invitant_nom=invitant_nom,
        session=session,
    )


@router.post(
    "/verify-code",
    response_model=VerifyAdminOTPResponse,
    summary="Étape 2 — Vérifier le code OTP [SUPER ADMIN]",
)
async def verify_code(
    data: VerifyAdminOTPRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_super_admin),
):
    """Vérifie le code OTP saisi par le Super Admin."""
    return await admin_service.verify_otp(data.email, data.code, session)


@router.post(
    "/create",
    response_model=CreateAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Étape 3 — Créer le compte administrateur [SUPER ADMIN]",
)
async def create_admin(
    data: CreateAdminRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_super_admin),
):
    """
    Le Super Admin complète les informations du nouvel administrateur.
    Un mot de passe temporaire est généré et envoyé par email.
    """
    return await admin_service.create_admin(data, session)


# ═══════════════════════════════════════════════════════════
#  LECTURE
# ═══════════════════════════════════════════════════════════

@router.get(
    "",
    response_model=AdminListResponse,
    summary="Liste des administrateurs [SUPER ADMIN]",
)
async def list_admins(
    search:     Optional[str] = Query(None, description="Recherche nom/prénom/email"),
    actif:      Optional[str] = Query(None, description="true/false/1/0"),
    super_only: Optional[str] = Query(None, description="true → seulement super admins"),
    page:       int           = Query(1, ge=1),
    per_page:   int           = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_super_admin),
):
    actif_bool = None
    if actif is not None:
        actif_bool = str(actif).lower() not in ("false", "0", "no")

    super_bool = None
    if super_only is not None:
        super_bool = str(super_only).lower() not in ("false", "0", "no")

    return await admin_service.list_admins(
        session     = session,
        search      = search,
        actif_only  = actif_bool,
        super_only  = super_bool,
        page        = page,
        per_page    = per_page,
    )


@router.get(
    "/{admin_id}",
    response_model=AdminResponse,
    summary="Détail d'un administrateur [SUPER ADMIN]",
)
async def get_admin(
    admin_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_super_admin),
):
    return await admin_service.get_admin(admin_id, session)


# ═══════════════════════════════════════════════════════════
#  ACTIONS
# ═══════════════════════════════════════════════════════════

@router.patch(
    "/{admin_id}/toggle",
    response_model=AdminResponse,
    summary="Activer / désactiver un administrateur [SUPER ADMIN]",
)
async def toggle_admin(
    admin_id: int,
    data: ToggleAdminRequest,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_super_admin),
):
    return await admin_service.toggle_admin(
        admin_id, data.actif, current_user.user_id, session
    )


@router.put(
    "/{admin_id}",
    response_model=AdminResponse,
    summary="Modifier un administrateur [SUPER ADMIN]",
)
async def update_admin(
    admin_id: int,
    data: UpdateAdminRequest,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_super_admin),
):
    return await admin_service.update_admin(
        admin_id, data, current_user.user_id, session
    )


@router.delete(
    "/{admin_id}",
    summary="Supprimer un administrateur [SUPER ADMIN]",
)
async def delete_admin(
    admin_id: int,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_super_admin),
):
    return await admin_service.delete_admin(
        admin_id, current_user.user_id, session
    )