"""
Service métier — Favoris client.

Responsabilités :
  - toggle_favori   : ajoute ou retire un favori (hotel ou voyage)
  - list_favoris    : liste paginée des favoris d'un client
  - get_status      : vérifie si un item est en favori
  - get_ids         : retourne les IDs en favori (pour le frontend)

Index PostgreSQL exploités :
  - idx_favori_client         → filtre par client
  - idx_favori_client_hotel   → vérification favori hôtel
  - idx_favori_client_voyage  → vérification favori voyage
"""
from typing import Optional

from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.favori import Favori
from app.models.hotel import Hotel
from app.models.voyage import Voyage
from app.core.exceptions import BadRequestException, NotFoundException
from app.schemas.favori import (
    FavoriResponse, FavoriListResponse,
    FavoriToggleResponse, FavoriStatusResponse,
    HotelBriefFavori, VoyageBriefFavori,
)


# ── Helper de sérialisation ────────────────────────────────
def _serialize(f: Favori) -> FavoriResponse:
    type_ = "hotel" if f.id_hotel else "voyage"

    hotel_brief = None
    if f.hotel:
        hotel_brief = HotelBriefFavori(
            id=f.hotel.id,
            nom=f.hotel.nom,
            ville=getattr(f.hotel, "ville", None),
            pays=f.hotel.pays,
            etoiles=f.hotel.etoiles,
            note_moyenne=float(f.hotel.note_moyenne) if f.hotel.note_moyenne else 0.0,
        )

    voyage_brief = None
    if f.voyage:
        voyage_brief = VoyageBriefFavori(
            id=f.voyage.id,
            titre=f.voyage.titre,
            destination=f.voyage.destination,
            prix_base=float(f.voyage.prix_base),
            duree=f.voyage.duree,
            date_depart=str(f.voyage.date_depart),
        )

    return FavoriResponse(
        id=f.id,
        type=type_,
        id_hotel=f.id_hotel,
        id_voyage=f.id_voyage,
        hotel=hotel_brief,
        voyage=voyage_brief,
        created_at=f.created_at,
    )


# ══════════════════════════════════════════════════════════
#  TOGGLE — Ajouter / Retirer
# ══════════════════════════════════════════════════════════
async def toggle_favori(
    client_id: int,
    id_hotel: Optional[int],
    id_voyage: Optional[int],
    session: AsyncSession,
) -> FavoriToggleResponse:
    """
    Si le favori existe → le supprime (retirer).
    Sinon              → le crée   (ajouter).
    """
    if not id_hotel and not id_voyage:
        raise BadRequestException("id_hotel ou id_voyage est requis")
    if id_hotel and id_voyage:
        raise BadRequestException("Fournir uniquement id_hotel OU id_voyage, pas les deux")

    # Vérifier que la cible existe
    if id_hotel:
        r = await session.execute(select(Hotel).where(Hotel.id == id_hotel))
        if not r.scalar_one_or_none():
            raise NotFoundException(f"Hôtel {id_hotel} introuvable")
        cond = and_(Favori.id_client == client_id, Favori.id_hotel == id_hotel)
    else:
        r = await session.execute(select(Voyage).where(Voyage.id == id_voyage))
        if not r.scalar_one_or_none():
            raise NotFoundException(f"Voyage {id_voyage} introuvable")
        cond = and_(Favori.id_client == client_id, Favori.id_voyage == id_voyage)

    # Chercher favori existant — exploite idx_favori_client_hotel / idx_favori_client_voyage
    existing = (await session.execute(select(Favori).where(cond))).scalar_one_or_none()

    if existing:
        await session.delete(existing)
        return FavoriToggleResponse(favori=False, message="Retiré des favoris")
    else:
        new_fav = Favori(
            id_client=client_id,
            id_hotel=id_hotel,
            id_voyage=id_voyage,
        )
        session.add(new_fav)
        return FavoriToggleResponse(favori=True, message="Ajouté aux favoris")


# ══════════════════════════════════════════════════════════
#  LIST — Favoris paginés d'un client
# ══════════════════════════════════════════════════════════
async def list_favoris(
    client_id: int,
    type_filtre: Optional[str],   # "hotel" | "voyage" | None
    page: int,
    per_page: int,
    session: AsyncSession,
) -> FavoriListResponse:
    """
    Retourne les favoris d'un client avec objets hotel/voyage chargés.
    Exploite idx_favori_client pour le filtre principal.
    """
    base_q = select(Favori).where(Favori.id_client == client_id)

    if type_filtre == "hotel":
        base_q = base_q.where(Favori.id_hotel.isnot(None))
    elif type_filtre == "voyage":
        base_q = base_q.where(Favori.id_voyage.isnot(None))

    # Comptes
    count_q  = select(func.count()).select_from(base_q.subquery())
    total    = (await session.execute(count_q)).scalar_one()

    count_h  = (await session.execute(
        select(func.count()).where(Favori.id_client == client_id, Favori.id_hotel.isnot(None))
    )).scalar_one()
    count_v  = (await session.execute(
        select(func.count()).where(Favori.id_client == client_id, Favori.id_voyage.isnot(None))
    )).scalar_one()

    # Data paginée + eager loading hotel/voyage
    items_q = (
        base_q
        .options(
            selectinload(Favori.hotel),
            selectinload(Favori.voyage),
        )
        .order_by(Favori.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = (await session.execute(items_q)).scalars().all()

    return FavoriListResponse(
        total=total,
        nb_hotels=count_h,
        nb_voyages=count_v,
        items=[_serialize(f) for f in rows],
    )


# ══════════════════════════════════════════════════════════
#  STATUS — Un item est-il en favori ?
# ══════════════════════════════════════════════════════════
async def get_status(
    client_id: int,
    id_hotel: Optional[int],
    id_voyage: Optional[int],
    session: AsyncSession,
) -> FavoriStatusResponse:
    if id_hotel:
        cond = and_(Favori.id_client == client_id, Favori.id_hotel == id_hotel)
    elif id_voyage:
        cond = and_(Favori.id_client == client_id, Favori.id_voyage == id_voyage)
    else:
        raise BadRequestException("id_hotel ou id_voyage requis")

    existing = (await session.execute(select(Favori).where(cond))).scalar_one_or_none()
    return FavoriStatusResponse(
        id_hotel=id_hotel,
        id_voyage=id_voyage,
        favori=existing is not None,
    )


# ══════════════════════════════════════════════════════════
#  IDS — Tous les IDs en favori (pour badge frontend)
# ══════════════════════════════════════════════════════════
async def get_favori_ids(
    client_id: int,
    session: AsyncSession,
) -> dict:
    """Retourne {hotel_ids: [...], voyage_ids: [...]} pour le frontend."""
    rows = (
        await session.execute(
            select(Favori.id_hotel, Favori.id_voyage)
            .where(Favori.id_client == client_id)
        )
    ).all()

    hotel_ids  = [r.id_hotel  for r in rows if r.id_hotel]
    voyage_ids = [r.id_voyage for r in rows if r.id_voyage]
    return {"hotel_ids": hotel_ids, "voyage_ids": voyage_ids}