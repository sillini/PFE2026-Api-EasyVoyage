"""
app/api/v1/endpoints/promotions.py
====================================
Endpoints pour la gestion des promotions.

Routes PARTENAIRE :
  GET    /promotions/mes-promotions           → Liste des promos de ses hôtels
  GET    /promotions/{promo_id}                → Détail d'une promo
  POST   /promotions/hotels/{hotel_id}          → Créer une promo pour un hôtel
  PUT    /promotions/{promo_id}                 → Modifier une promo
  PATCH  /promotions/{promo_id}/toggle          → Activer/désactiver
  DELETE /promotions/{promo_id}                 → Supprimer une promo

Routes PUBLIC :
  GET    /promotions/hotels/{hotel_id}/active   → Promo active d'un hôtel (pour visiteur)
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_partenaire
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.promotion import (
    PromotionCreate,
    PromotionListResponse,
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
    hotel_id:   Optional[int] = Query(None, description="Filtrer par hôtel"),
    actif_only: bool          = Query(False, description="Uniquement les promos actives maintenant"),
    session:    AsyncSession  = Depends(get_db),
    token:      TokenData     = Depends(require_partenaire),
):
    return await svc.list_promotions_partenaire(
        partenaire_id=token.user_id,
        session=session,
        hotel_id=hotel_id,
        actif_only=actif_only,
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
    summary="Créer une promotion pour un hôtel [PARTENAIRE]",
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
    summary="Modifier une promotion [PARTENAIRE]",
)
async def update_promotion(
    promo_id: int,
    data:     PromotionUpdate,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    return await svc.update_promotion(promo_id, data, token.user_id, session)


@router.patch(
    "/{promo_id}/toggle",
    response_model=PromotionResponse,
    summary="Activer/désactiver une promotion [PARTENAIRE]",
)
async def toggle_promotion(
    promo_id: int,
    actif:    bool         = Query(..., description="true pour activer, false pour désactiver"),
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    return await svc.toggle_actif(promo_id, actif, token.user_id, session)


@router.delete(
    "/{promo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une promotion [PARTENAIRE]",
)
async def delete_promotion(
    promo_id: int,
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
):
    await svc.delete_promotion(promo_id, token.user_id, session)


# ═══════════════════════════════════════════════════════════
#  PUBLIC — Affichage sur les pages visiteur
# ═══════════════════════════════════════════════════════════

@router.get(
    "/hotels/{hotel_id}/active",
    response_model=Optional[PromotionResponse],
    summary="Promotion active d'un hôtel (PUBLIC)",
)
async def get_active_hotel_promo(
    hotel_id: int,
    session:  AsyncSession = Depends(get_db),
):
    """
    Retourne la meilleure promotion active pour un hôtel à la date actuelle.
    Retourne null si aucune promotion n'est active.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.promotion import Promotion

    promo = await svc.get_promotion_active_hotel(hotel_id, session)
    if not promo:
        return None

    # Recharger avec la relation hotel pour la réponse
    result = await session.execute(
        select(Promotion)
        .options(selectinload(Promotion.hotel))
        .where(Promotion.id == promo.id)
    )
    promo = result.scalar_one()
    return svc._to_response(promo)