"""
Endpoints — Demandes d'inscription partenaire.

Public (sans auth) :
  POST /demandes-partenaire          → Soumettre une demande

Admin :
  GET  /admin/demandes-partenaire              → Liste avec filtres
  GET  /admin/demandes-partenaire/{id}         → Détail d'une demande
  POST /admin/demandes-partenaire/{id}/traiter → Confirmer ou annuler
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.demande_partenaire import (
    DemandePartenaireCreate,
    DemandePartenairePublicResponse,
    DemandePartenaireResponse,
    DemandeListResponse,
    TraiterDemandeRequest,
    TraiterDemandeResponse,
)
import app.services.demande_partenaire_service as demande_service

# ── Routeur public ────────────────────────────────────────
public_router = APIRouter(
    prefix="/demandes-partenaire",
    tags=["Public — Demandes Partenaire"],
)

# ── Routeur admin ─────────────────────────────────────────
admin_router = APIRouter(
    prefix="/admin/demandes-partenaire",
    tags=["Admin — Demandes Partenaire"],
)


# ═══════════════════════════════════════════════════════════
#  PUBLIC
# ═══════════════════════════════════════════════════════════

@public_router.post(
    "",
    response_model=DemandePartenairePublicResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Soumettre une demande d'inscription partenaire (public)",
)
async def soumettre_demande(
    data: DemandePartenaireCreate,
    session: AsyncSession = Depends(get_db),
):
    """
    Endpoint public — aucun token requis.
    Un visiteur remplit le formulaire depuis la landing page.
    La demande est enregistrée en statut EN_ATTENTE.
    """
    return await demande_service.soumettre_demande(data, session)


# ═══════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════

@admin_router.get(
    "",
    response_model=DemandeListResponse,
    summary="Liste des demandes partenaire [ADMIN]",
)
async def list_demandes(
    statut:   Optional[str] = Query(None, description="EN_ATTENTE | CONFIRMEE | ANNULEE"),
    search:   Optional[str] = Query(None, description="Recherche nom/email/entreprise"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await demande_service.list_demandes(
        session=session, statut=statut, search=search, page=page, per_page=per_page,
    )


@admin_router.get(
    "/{demande_id}",
    response_model=DemandePartenaireResponse,
    summary="Détail d'une demande [ADMIN]",
)
async def get_demande(
    demande_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await demande_service.get_demande(demande_id, session)


@admin_router.post(
    "/{demande_id}/traiter",
    response_model=TraiterDemandeResponse,
    summary="Confirmer ou annuler une demande [ADMIN]",
)
async def traiter_demande(
    demande_id: int,
    data: TraiterDemandeRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    action = "CONFIRMER" → crée le compte partenaire + envoie email avec mot de passe temp
    action = "ANNULER"   → marque la demande comme annulée
    """
    return await demande_service.traiter_demande(demande_id, data, session)