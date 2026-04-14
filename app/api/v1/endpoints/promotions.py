"""
app/api/v1/endpoints/promotions.py
====================================
Endpoints pour la gestion des promotions.

Routes PARTENAIRE :
  GET    /promotions/mes-promotions           → Liste des promos du partenaire
  GET    /promotions/{promo_id}               → Détail d'une promo
  POST   /promotions/hotels/{hotel_id}        → Créer une promo (statut PENDING)
  PUT    /promotions/{promo_id}               → Modifier (si PENDING ou REJECTED)
  DELETE /promotions/{promo_id}               → Supprimer (si non APPROVED)

Routes ADMIN :
  GET    /promotions/admin/all                → Toutes les promos avec filtres
  GET    /promotions/admin/pending-count      → Nombre de demandes en attente
  POST   /promotions/admin/{promo_id}/decision→ Accepter ou refuser
  PATCH  /promotions/admin/{promo_id}/toggle  → Activer/désactiver (si APPROVED)

Routes PUBLIC :
  GET    /promotions/hotels/{hotel_id}/active → Promo active d'un hôtel (visiteur)
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_admin, require_partenaire
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.promotion import (
    DecisionAdmin,
    PromotionCreate,
    PromotionListResponse,
    PromotionPendingCount,
    PromotionResponse,
    PromotionUpdate,
)
import app.services.promotion_service as svc

router = APIRouter(prefix="/promotions", tags=["Promotions"])


# ═══════════════════════════════════════════════════════════
#  PARTENAIRE
# ═══════════════════════════════════════════════════════════

@router.get(
    "/mes-promotions",
    response_model=PromotionListResponse,
    summary="Liste mes promotions [PARTENAIRE]",
)
async def list_mes_promotions(
    hotel_id: Optional[int] = Query(None),
    statut:   Optional[str] = Query(None, description="PENDING | APPROVED | REJECTED"),
    session:  AsyncSession  = Depends(get_db),
    token:    TokenData     = Depends(require_partenaire),
):
    return await svc.list_promotions_partenaire(
        partenaire_id=token.user_id,
        session=session,
        hotel_id=hotel_id,
        statut=statut,
    )


@router.get(
    "/{promo_id}",
    response_model=PromotionResponse,
    summary="Détail d'une promotion [PARTENAIRE]",
)
async def get_promotion(
    promo_id: int,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    return await svc.get_promotion(promo_id, token.user_id, session)


@router.post(
    "/hotels/{hotel_id}",
    response_model=PromotionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une promotion (statut PENDING) [PARTENAIRE]",
)
async def create_promotion(
    hotel_id: int,
    data:     PromotionCreate,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    return await svc.create_promotion(hotel_id, data, token.user_id, session)


@router.put(
    "/{promo_id}",
    response_model=PromotionResponse,
    summary="Modifier une promotion [PARTENAIRE — si PENDING ou REJECTED]",
)
async def update_promotion(
    promo_id: int,
    data:     PromotionUpdate,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    return await svc.update_promotion(promo_id, data, token.user_id, session)


@router.delete(
    "/{promo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une promotion [PARTENAIRE — si non APPROVED]",
)
async def delete_promotion(
    promo_id: int,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    await svc.delete_promotion(promo_id, token.user_id, session)


# ═══════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════

@router.get(
    "/admin/all",
    response_model=PromotionListResponse,
    summary="Toutes les promotions [ADMIN]",
)
async def list_all_promotions(
    statut:        Optional[str] = Query(None, description="PENDING | APPROVED | REJECTED"),
    hotel_id:      Optional[int] = Query(None),
    partenaire_id: Optional[int] = Query(None),
    page:          int           = Query(1, ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    session:       AsyncSession  = Depends(get_db),
    _:             TokenData     = Depends(require_admin),
):
    return await svc.list_promotions_admin(
        session=session,
        statut=statut,
        hotel_id=hotel_id,
        partenaire_id=partenaire_id,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/admin/pending-count",
    response_model=PromotionPendingCount,
    summary="Nombre de promotions en attente [ADMIN]",
)
async def get_pending_count(
    session: AsyncSession = Depends(get_db),
    _:       TokenData    = Depends(require_admin),
):
    count = await svc.get_pending_count(session)
    return PromotionPendingCount(pending=count)


@router.post(
    "/admin/{promo_id}/decision",
    response_model=PromotionResponse,
    summary="Accepter ou refuser une promotion [ADMIN]",
)
async def traiter_promotion(
    promo_id: int,
    data:     DecisionAdmin,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_admin),
):
    """
    action = "APPROVED" → promotion visible côté visiteur + email au partenaire
    action = "REJECTED" → promotion refusée + email avec raison au partenaire
    """
    return await svc.traiter_promotion(promo_id, data, token.user_id, session)


@router.patch(
    "/admin/{promo_id}/toggle",
    response_model=PromotionResponse,
    summary="Activer/désactiver une promotion approuvée [ADMIN]",
)
async def toggle_actif_admin(
    promo_id: int,
    actif:    bool        = Query(...),
    session:  AsyncSession = Depends(get_db),
    token:    TokenData   = Depends(require_admin),
):
    return await svc.toggle_actif_admin(promo_id, actif, token.user_id, session)


# ═══════════════════════════════════════════════════════════
#  PUBLIC — Affichage côté visiteur
# ═══════════════════════════════════════════════════════════

@router.get(
    "/hotels/{hotel_id}/active",
    response_model=Optional[PromotionResponse],
    summary="Promotion active d'un hôtel (PUBLIC — APPROVED uniquement)",
)
async def get_active_hotel_promo(
    hotel_id: int,
    session:  AsyncSession = Depends(get_db),
):
    """
    Retourne la meilleure promotion APPROVED + actif + dans dates pour un hôtel.
    Retourne null si aucune promotion éligible.
    """
    return await svc.get_promotion_active_hotel(hotel_id, session)