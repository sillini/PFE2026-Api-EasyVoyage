"""
app/services/promotion_service.py
==================================
Service pour la gestion des promotions et le calcul des prix remisés.

Expose :
  - CRUD standard (list, get, create, update, delete)
  - get_promotion_active_hotel() : récupère la meilleure promo en cours
  - calculer_prix_promo()        : applique un pourcentage à un prix
  - enrichir_hotels_avec_promos() : ajoute les champs promo à une liste
"""
import json
from datetime import date, datetime
from typing import List, Optional, Tuple

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException
from app.models.hotel import Hotel
from app.models.promotion import Promotion, TypePromotion
from app.schemas.promotion import (
    PromotionCreate, PromotionUpdate, PromotionResponse,
    PromotionListResponse, HotelMini,
)


# ═══════════════════════════════════════════════════════════
#  HELPERS — Conversion ORM → Response
# ═══════════════════════════════════════════════════════════

def _types_chambre_to_list(raw: Optional[str]) -> Optional[List[int]]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _types_chambre_to_json(lst: Optional[List[int]]) -> Optional[str]:
    if not lst:
        return None
    return json.dumps(lst)


def _to_response(promo: Promotion) -> PromotionResponse:
    today = date.today()
    est_valide = (
        promo.actif
        and promo.date_debut <= today <= promo.date_fin
    )
    jours_restants = (promo.date_fin - today).days if est_valide else None

    hotel_mini = None
    if promo.hotel:
        hotel_mini = HotelMini(
            id=promo.hotel.id,
            nom=promo.hotel.nom,
            ville=getattr(promo.hotel, "ville", None),
        )

    return PromotionResponse(
        id                    = promo.id,
        titre                 = promo.titre,
        description           = promo.description,
        id_hotel              = promo.id_hotel,
        hotel                 = hotel_mini,
        pourcentage           = float(promo.pourcentage),
        type_promotion        = promo.type_promotion.value if hasattr(promo.type_promotion, "value") else str(promo.type_promotion),
        jours_avant_min       = promo.jours_avant_min,
        jours_avant_max       = promo.jours_avant_max,
        date_debut            = promo.date_debut,
        date_fin              = promo.date_fin,
        types_chambre_ids     = _types_chambre_to_list(promo.types_chambre_ids),
        actif                 = promo.actif,
        created_at            = promo.created_at,
        updated_at            = promo.updated_at,
        est_valide_maintenant = est_valide,
        jours_restants        = jours_restants,
    )


# ═══════════════════════════════════════════════════════════
#  LOGIQUE DE CALCUL — PRIX AVEC PROMO
# ═══════════════════════════════════════════════════════════

def calculer_prix_promo(prix_original: float, pourcentage: float) -> float:
    """
    Applique un pourcentage de réduction à un prix.
    Retourne le prix arrondi à 2 décimales.
    """
    if prix_original is None or prix_original <= 0:
        return 0.0
    pct = max(0, min(100, float(pourcentage)))
    return round(prix_original * (1 - pct / 100), 2)


async def get_promotion_active_hotel(
    hotel_id: int,
    session: AsyncSession,
    at_date: Optional[date] = None,
) -> Optional[Promotion]:
    """
    Retourne la MEILLEURE promotion active pour un hôtel à une date donnée.
    Si plusieurs promotions sont valides, retourne celle avec le plus haut pourcentage.
    """
    ref_date = at_date or date.today()
    result = await session.execute(
        select(Promotion)
        .where(
            Promotion.id_hotel == hotel_id,
            Promotion.actif == True,  # noqa: E712
            Promotion.date_debut <= ref_date,
            Promotion.date_fin   >= ref_date,
        )
        .order_by(Promotion.pourcentage.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_promotions_actives_multi_hotels(
    hotel_ids: List[int],
    session: AsyncSession,
) -> dict:
    """
    Optimisation : récupère en UNE requête la meilleure promo active
    pour chaque hôtel d'une liste. Retourne un dict {hotel_id: Promotion}.
    """
    if not hotel_ids:
        return {}

    today = date.today()
    result = await session.execute(
        select(Promotion)
        .where(
            Promotion.id_hotel.in_(hotel_ids),
            Promotion.actif == True,  # noqa: E712
            Promotion.date_debut <= today,
            Promotion.date_fin   >= today,
        )
        .order_by(Promotion.id_hotel, Promotion.pourcentage.desc())
    )
    promos = result.scalars().all()

    # Garder uniquement la meilleure par hôtel (plus haut pourcentage)
    best_per_hotel = {}
    for p in promos:
        if p.id_hotel not in best_per_hotel:
            best_per_hotel[p.id_hotel] = p
    return best_per_hotel


# ═══════════════════════════════════════════════════════════
#  CRUD — PARTENAIRE
# ═══════════════════════════════════════════════════════════

async def _check_hotel_owner(hotel_id: int, partenaire_id: int, session: AsyncSession):
    """Vérifie qu'un hôtel appartient bien au partenaire connecté."""
    hotel = (await session.execute(
        select(Hotel).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    if hotel.id_partenaire != partenaire_id:
        raise ConflictException("Cet hôtel ne vous appartient pas")
    return hotel


async def list_promotions_partenaire(
    partenaire_id: int,
    session: AsyncSession,
    hotel_id: Optional[int] = None,
    actif_only: bool = False,
) -> PromotionListResponse:
    """Liste toutes les promotions des hôtels du partenaire connecté."""
    query = (
        select(Promotion)
        .join(Hotel, Promotion.id_hotel == Hotel.id)
        .options(selectinload(Promotion.hotel))
        .where(Hotel.id_partenaire == partenaire_id)
    )
    if hotel_id:
        query = query.where(Promotion.id_hotel == hotel_id)
    if actif_only:
        today = date.today()
        query = query.where(
            Promotion.actif == True,  # noqa: E712
            Promotion.date_debut <= today,
            Promotion.date_fin   >= today,
        )
    query = query.order_by(Promotion.date_debut.desc())

    result = await session.execute(query)
    promos = result.scalars().all()
    items = [_to_response(p) for p in promos]
    return PromotionListResponse(total=len(items), items=items)


async def get_promotion(promo_id: int, partenaire_id: int, session: AsyncSession) -> PromotionResponse:
    result = await session.execute(
        select(Promotion)
        .options(selectinload(Promotion.hotel))
        .where(Promotion.id == promo_id)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise NotFoundException(f"Promotion {promo_id} introuvable")
    await _check_hotel_owner(promo.id_hotel, partenaire_id, session)
    return _to_response(promo)


async def create_promotion(
    hotel_id: int,
    data: PromotionCreate,
    partenaire_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    await _check_hotel_owner(hotel_id, partenaire_id, session)

    promo = Promotion(
        titre             = data.titre,
        description       = data.description,
        id_hotel          = hotel_id,
        pourcentage       = data.pourcentage,
        type_promotion    = TypePromotion(data.type_promotion),
        jours_avant_min   = data.jours_avant_min,
        jours_avant_max   = data.jours_avant_max,
        date_debut        = data.date_debut,
        date_fin          = data.date_fin,
        types_chambre_ids = _types_chambre_to_json(data.types_chambre_ids),
        actif             = data.actif,
    )
    session.add(promo)
    await session.flush()

    # Recharger avec la relation hotel
    result = await session.execute(
        select(Promotion)
        .options(selectinload(Promotion.hotel))
        .where(Promotion.id == promo.id)
    )
    promo = result.scalar_one()
    await session.commit()
    return _to_response(promo)


async def update_promotion(
    promo_id: int,
    data: PromotionUpdate,
    partenaire_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    result = await session.execute(
        select(Promotion)
        .options(selectinload(Promotion.hotel))
        .where(Promotion.id == promo_id)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise NotFoundException(f"Promotion {promo_id} introuvable")
    await _check_hotel_owner(promo.id_hotel, partenaire_id, session)

    update_data = data.model_dump(exclude_unset=True)
    if "types_chambre_ids" in update_data:
        update_data["types_chambre_ids"] = _types_chambre_to_json(update_data["types_chambre_ids"])
    if "type_promotion" in update_data and update_data["type_promotion"]:
        update_data["type_promotion"] = TypePromotion(update_data["type_promotion"])

    for k, v in update_data.items():
        setattr(promo, k, v)

    await session.flush()
    await session.commit()
    await session.refresh(promo)
    return _to_response(promo)


async def delete_promotion(
    promo_id: int,
    partenaire_id: int,
    session: AsyncSession,
) -> None:
    result = await session.execute(
        select(Promotion).where(Promotion.id == promo_id)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise NotFoundException(f"Promotion {promo_id} introuvable")
    await _check_hotel_owner(promo.id_hotel, partenaire_id, session)

    await session.delete(promo)
    await session.commit()


async def toggle_actif(
    promo_id: int,
    actif: bool,
    partenaire_id: int,
    session: AsyncSession,
) -> PromotionResponse:
    result = await session.execute(
        select(Promotion)
        .options(selectinload(Promotion.hotel))
        .where(Promotion.id == promo_id)
    )
    promo = result.scalar_one_or_none()
    if not promo:
        raise NotFoundException(f"Promotion {promo_id} introuvable")
    await _check_hotel_owner(promo.id_hotel, partenaire_id, session)

    promo.actif = actif
    await session.flush()
    await session.commit()
    await session.refresh(promo)
    return _to_response(promo)