"""
Service Voyages — logique métier complète avec admin créateur.

Index utilisés :
  - idx_voyage_actif        → filtre actif
  - idx_voyage_destination  → recherche destination
  - idx_voyage_date_depart  → filtre/tri dates
  - idx_voyage_admin        → filtre par admin
  - idx_utilisateur_nom     → recherche admin par nom
  - idx_utilisateur_email   → recherche admin par email
"""
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundException
from app.models.voyage import Voyage
from app.models.utilisateur import Utilisateur
from app.schemas.voyage import (
    AdminInfo, VoyageCreate, VoyageListResponse, VoyageResponse, VoyageUpdate,
)


def _to_response(voyage: Voyage) -> VoyageResponse:
    """Convertit un objet Voyage ORM en VoyageResponse avec admin embarqué."""
    admin_info = None
    if voyage.admin:
        admin_info = AdminInfo(
            id=voyage.admin.id,
            nom=voyage.admin.nom,
            prenom=voyage.admin.prenom,
            email=voyage.admin.email,
        )
    data = {
        "id": voyage.id,
        "titre": voyage.titre,
        "description": voyage.description,
        "destination": voyage.destination,
        "duree": voyage.duree,
        "prix_base": float(voyage.prix_base),
        "date_depart": voyage.date_depart,
        "date_retour": voyage.date_retour,
        "capacite_max": voyage.capacite_max,
        "actif": voyage.actif,
        "id_admin": voyage.id_admin,
        "admin": admin_info,
        "created_at": voyage.created_at,
        "updated_at": voyage.updated_at,
    }
    return VoyageResponse.model_validate(data)


async def list_voyages(
    session: AsyncSession,
    destination: Optional[str] = None,
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    duree_min: Optional[int] = None,
    duree_max: Optional[int] = None,
    date_depart_min: Optional[str] = None,
    date_depart_max: Optional[str] = None,
    actif_only: bool = True,
    admin_nom: Optional[str] = None,
    admin_email: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> VoyageListResponse:

    # Jointure avec utilisateur pour filtres admin
    query = select(Voyage).options(selectinload(Voyage.admin))

    # Filtre actif (idx_voyage_actif)
    if actif_only:
        query = query.where(Voyage.actif == True)

    # Filtre destination (idx_voyage_destination + unaccent)
    if destination:
        query = query.where(
            func.unaccent(Voyage.destination).ilike(f"%{destination}%")
        )

    # Filtres prix
    if prix_min is not None:
        query = query.where(Voyage.prix_base >= prix_min)
    if prix_max is not None:
        query = query.where(Voyage.prix_base <= prix_max)

    # Filtres durée
    if duree_min is not None:
        query = query.where(Voyage.duree >= duree_min)
    if duree_max is not None:
        query = query.where(Voyage.duree <= duree_max)

    # Filtres date départ (idx_voyage_date_depart)
    if date_depart_min:
        query = query.where(Voyage.date_depart >= date_depart_min)
    if date_depart_max:
        query = query.where(Voyage.date_depart <= date_depart_max)

    # Filtres admin (jointure Utilisateur)
    if admin_nom or admin_email:
        query = query.join(Utilisateur, Utilisateur.id == Voyage.id_admin)
        if admin_nom:
            # Recherche dans nom + prenom (idx_utilisateur_nom)
            search = f"%{admin_nom}%"
            query = query.where(
                func.unaccent(Utilisateur.nom).ilike(search)
                | func.unaccent(Utilisateur.prenom).ilike(search)
            )
        if admin_email:
            # Recherche par email (idx_utilisateur_email)
            query = query.where(
                Utilisateur.email.ilike(f"%{admin_email}%")
            )

    # Total
    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    # Pagination + tri
    offset = (page - 1) * per_page
    query = query.order_by(Voyage.date_depart.asc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    voyages = result.scalars().all()

    return VoyageListResponse(
        total=total, page=page, per_page=per_page,
        items=[_to_response(v) for v in voyages],
    )


async def get_voyage(voyage_id: int, session: AsyncSession) -> VoyageResponse:
    result = await session.execute(
        select(Voyage)
        .options(selectinload(Voyage.admin))
        .where(Voyage.id == voyage_id)
    )
    voyage = result.scalar_one_or_none()
    if not voyage:
        raise NotFoundException(f"Voyage {voyage_id} introuvable")
    return _to_response(voyage)


async def create_voyage(
    data: VoyageCreate, session: AsyncSession, id_admin: Optional[int] = None
) -> VoyageResponse:
    voyage = Voyage(
        titre=data.titre,
        description=data.description,
        destination=data.destination,
        duree=data.duree,
        prix_base=data.prix_base,
        date_depart=data.date_depart,
        date_retour=data.date_retour,
        capacite_max=data.capacite_max,
        actif=True,
        id_admin=id_admin,
    )
    session.add(voyage)
    await session.flush()
    # Recharger avec la relation admin
    result = await session.execute(
        select(Voyage).options(selectinload(Voyage.admin)).where(Voyage.id == voyage.id)
    )
    return _to_response(result.scalar_one())


async def update_voyage(
    voyage_id: int, data: VoyageUpdate, session: AsyncSession
) -> VoyageResponse:
    result = await session.execute(
        select(Voyage).options(selectinload(Voyage.admin)).where(Voyage.id == voyage_id)
    )
    voyage = result.scalar_one_or_none()
    if not voyage:
        raise NotFoundException(f"Voyage {voyage_id} introuvable")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(voyage, field, value)

    await session.flush()
    result2 = await session.execute(
        select(Voyage).options(selectinload(Voyage.admin)).where(Voyage.id == voyage_id)
    )
    return _to_response(result2.scalar_one())


async def delete_voyage(voyage_id: int, session: AsyncSession) -> None:
    result = await session.execute(select(Voyage).where(Voyage.id == voyage_id))
    voyage = result.scalar_one_or_none()
    if not voyage:
        raise NotFoundException(f"Voyage {voyage_id} introuvable")
    voyage.actif = False
    await session.flush()