"""
Endpoints Admin — Gestion des partenaires.

Flux d'invitation en 3 étapes :
  POST /admin/partenaires/invite          → Envoie OTP par email
  POST /admin/partenaires/verify-code     → Vérifie le code OTP
  POST /admin/partenaires/create          → Crée le compte (envoie mdp par email)

CRUD lecture + toggle :
  GET  /admin/partenaires                 → Liste avec filtres
  GET  /admin/partenaires/{id}            → Détail + hôtels
  PATCH /admin/partenaires/{id}/toggle    → Activer / désactiver
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin, get_current_user
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.partenaire import (
    CreatePartenaireRequest, CreatePartenaireResponse,
    InvitePartenaireRequest, InvitePartenaireResponse,
    PartenaireAdminResponse, PartenaireListResponse,
    TogglePartenaireRequest, VerifyOTPRequest, VerifyOTPResponse,
)
import app.services.partenaire_service as partenaire_service

router = APIRouter(prefix="/admin/partenaires", tags=["Admin — Partenaires"])


# ═══════════════════════════════════════════════════════════
#  FLUX D'INVITATION EN 3 ÉTAPES
# ═══════════════════════════════════════════════════════════

@router.post(
    "/invite",
    response_model=InvitePartenaireResponse,
    status_code=status.HTTP_200_OK,
    summary="Étape 1 — Envoyer un code OTP au futur partenaire",
)
async def invite_partenaire(
    data: InvitePartenaireRequest,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    """
    L'admin saisit l'email du futur partenaire.
    Un code OTP à 6 chiffres est envoyé à cet email.
    Durée de validité : 15 minutes.
    """
    from app.services.auth_service import _get_user_by_email as get_user
    from sqlalchemy.ext.asyncio import AsyncSession as AS
    from app.models.utilisateur import Utilisateur
    from sqlalchemy import select

    # Récupérer le nom de l'admin connecté
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.id == current_user.user_id)
    )
    admin = result.scalar_one_or_none()
    admin_prenom = admin.prenom if admin else "L'administrateur"
    admin_nom    = admin.nom    if admin else ""

    return await partenaire_service.invite_partenaire(
        email=data.email,
        admin_prenom=admin_prenom,
        admin_nom=admin_nom,
        session=session,
    )


@router.post(
    "/verify-code",
    response_model=VerifyOTPResponse,
    summary="Étape 2 — Vérifier le code OTP saisi par l'admin",
)
async def verify_code(
    data: VerifyOTPRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    L'admin saisit le code que le futur partenaire lui a communiqué.
    Retourne valid=true si le code est correct et non expiré.
    """
    return await partenaire_service.verify_otp(data.email, data.code, session)


@router.post(
    "/create",
    response_model=CreatePartenaireResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Étape 3 — Créer le compte partenaire",
)
async def create_partenaire(
    data: CreatePartenaireRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    L'admin complète les informations du partenaire.
    Un mot de passe temporaire est généré et envoyé par email au partenaire.
    """
    return await partenaire_service.create_partenaire(data, session)


# ═══════════════════════════════════════════════════════════
#  LECTURE
# ═══════════════════════════════════════════════════════════

@router.get(
    "",
    response_model=PartenaireListResponse,
    summary="Liste des partenaires avec filtres",
)
async def list_partenaires(
    search:          Optional[str]  = Query(None, description="Recherche globale nom/prénom/email"),
    nom_entreprise:  Optional[str]  = Query(None, description="Filtrer par nom d'entreprise"),
    type_partenaire: Optional[str]  = Query(None, description="HOTEL | AGENCE | AUTRE"),
    statut:          Optional[str]  = Query(None, description="ACTIF | SUSPENDU | EN_ATTENTE"),
    actif:           Optional[str]  = Query(None, description="true/false/1/0"),
    page:            int            = Query(1, ge=1),
    per_page:        int            = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    actif_bool = None
    if actif is not None:
        actif_bool = str(actif).lower() not in ("false", "0", "no")

    return await partenaire_service.list_partenaires(
        session=session,
        search=search,
        nom_entreprise=nom_entreprise,
        type_partenaire=type_partenaire,
        statut=statut,
        actif_only=actif_bool,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/{partenaire_id}",
    response_model=PartenaireAdminResponse,
    summary="Détail d'un partenaire + ses hôtels",
)
async def get_partenaire(
    partenaire_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await partenaire_service.get_partenaire(partenaire_id, session)


# ═══════════════════════════════════════════════════════════
#  TOGGLE ACTIF / INACTIF
# ═══════════════════════════════════════════════════════════

@router.patch(
    "/{partenaire_id}/toggle",
    response_model=PartenaireAdminResponse,
    summary="Activer ou désactiver un partenaire [ADMIN]",
)
async def toggle_partenaire(
    partenaire_id: int,
    data: TogglePartenaireRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    - actif=true  → statut ACTIF, accès restauré
    - actif=false → statut SUSPENDU, connexion bloquée
    L'admin ne peut pas supprimer ni modifier les données du partenaire.
    """
    return await partenaire_service.toggle_partenaire(partenaire_id, data.actif, session)