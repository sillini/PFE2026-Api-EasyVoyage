"""
Service Hôtels — logique métier complète.

Index PostgreSQL exploités automatiquement :
  - idx_hotel_pays       → filtre par pays
  - idx_hotel_etoiles    → filtre par étoiles
  - idx_hotel_actif      → filtre actif=TRUE
  - idx_hotel_nom_trgm   → recherche trigramme sur le nom (pg_trgm)
  - idx_chambre_hotel    → jointure chambre → hotel
  - idx_tarif_dates      → filtre par période de tarif
"""
from datetime import date
from typing import Optional

from sqlalchemy import func, select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.hotel import Avis, Chambre, Hotel, Tarif, TypeChambre, TypeReservation
from app.models.utilisateur import Utilisateur
from app.schemas.hotel import (
    AvisCreate, AvisListResponse, AvisResponse,
    ChambreCreate, ChambreListResponse, ChambreResponse, ChambreUpdate,
    HotelAdminUpdate, HotelCreate, HotelListResponse, HotelResponse, HotelUpdate,
    PartenaireInfo,
    TarifCreate, TarifListResponse, TarifResponse,
    TypeChambreResponse, TypeReservationResponse,
)


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════
def _to_hotel_response(hotel: Hotel) -> HotelResponse:
    partenaire_info = None
    if hotel.partenaire:
        partenaire_info = PartenaireInfo(
            id=hotel.partenaire.id,
            nom=hotel.partenaire.nom,
            prenom=hotel.partenaire.prenom,
            email=hotel.partenaire.email,
        )
    return HotelResponse(
        id=hotel.id, nom=hotel.nom, etoiles=hotel.etoiles,
        adresse=hotel.adresse,
        ville=getattr(hotel, "ville", None),
        pays=hotel.pays,
        description=hotel.description,
        note_moyenne=float(hotel.note_moyenne) if hotel.note_moyenne else 0.0,
        actif=hotel.actif,
        mis_en_avant=getattr(hotel, "mis_en_avant", False),
        id_partenaire=hotel.id_partenaire,
        partenaire=partenaire_info,
        created_at=hotel.created_at, updated_at=hotel.updated_at,
    )


# ═══════════════════════════════════════════════════════════
#  HOTELS
# ═══════════════════════════════════════════════════════════
async def list_hotels(
    session: AsyncSession,
    ville: Optional[str] = None,
    etoiles_min: Optional[int] = None,
    etoiles_max: Optional[int] = None,
    note_min: Optional[float] = None,
    nom: Optional[str] = None,
    actif_only: bool = True,
    partenaire_nom: Optional[str] = None,
    partenaire_email: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> HotelListResponse:

    query = select(Hotel).options(selectinload(Hotel.partenaire))

    if actif_only:
        query = query.where(Hotel.actif == True)

    # Filtre par ville — ilike simple (sans unaccent pour compatibilité)
    if ville:
        query = query.where(Hotel.ville.ilike(f"%{ville}%"))
    if etoiles_min is not None:
        query = query.where(Hotel.etoiles >= etoiles_min)
    if etoiles_max is not None:
        query = query.where(Hotel.etoiles <= etoiles_max)
    if note_min is not None:
        query = query.where(Hotel.note_moyenne >= note_min)
    if nom:
        query = query.where(Hotel.nom.ilike(f"%{nom}%"))

    # Filtres partenaire (jointure Utilisateur)
    if partenaire_nom or partenaire_email:
        query = query.join(Utilisateur, Utilisateur.id == Hotel.id_partenaire)
        if partenaire_nom:
            search = f"%{partenaire_nom}%"
            query = query.where(
                Utilisateur.nom.ilike(search)
                | Utilisateur.prenom.ilike(search)
            )
        if partenaire_email:
            query = query.where(Utilisateur.email.ilike(f"%{partenaire_email}%"))

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Hotel.note_moyenne.desc(), Hotel.nom.asc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    hotels = result.scalars().all()

    return HotelListResponse(
        total=total, page=page, per_page=per_page,
        items=[_to_hotel_response(h) for h in hotels],
    )


async def get_hotel(hotel_id: int, session: AsyncSession) -> HotelResponse:
    result = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    return _to_hotel_response(hotel)


async def create_hotel(data: HotelCreate, session: AsyncSession, id_partenaire: Optional[int] = None) -> HotelResponse:
    hotel = Hotel(**data.model_dump(), id_partenaire=id_partenaire)
    session.add(hotel)
    await session.flush()
    result = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel.id)
    )
    return _to_hotel_response(result.scalar_one())


async def update_hotel(hotel_id: int, data: HotelUpdate, session: AsyncSession) -> HotelResponse:
    result = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(hotel, field, value)
    await session.flush()
    result2 = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )
    return _to_hotel_response(result2.scalar_one())


async def admin_toggle_hotel(hotel_id: int, actif: bool, session: AsyncSession) -> HotelResponse:
    """Admin peut uniquement activer/désactiver un hotel."""
    result = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    hotel.actif = actif
    await session.flush()
    result2 = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )
    return _to_hotel_response(result2.scalar_one())


async def delete_hotel(hotel_id: int, session: AsyncSession) -> None:
    result = await session.execute(select(Hotel).where(Hotel.id == hotel_id))
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    hotel.actif = False
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  TYPES CHAMBRE & RESERVATION (référentiels)
# ═══════════════════════════════════════════════════════════
async def list_types_chambre(session: AsyncSession) -> list[TypeChambreResponse]:
    result = await session.execute(select(TypeChambre).order_by(TypeChambre.nom))
    return [TypeChambreResponse.model_validate(t) for t in result.scalars().all()]


async def list_types_reservation(session: AsyncSession) -> list[TypeReservationResponse]:
    result = await session.execute(select(TypeReservation).order_by(TypeReservation.nom))
    return [TypeReservationResponse.model_validate(t) for t in result.scalars().all()]


# ═══════════════════════════════════════════════════════════
#  CHAMBRES
# ═══════════════════════════════════════════════════════════
async def _check_hotel(hotel_id: int, session: AsyncSession) -> None:
    r = await session.execute(select(Hotel.id).where(Hotel.id == hotel_id))
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")


async def list_chambres(
    hotel_id: int,
    session: AsyncSession,
    capacite_min: Optional[int] = None,
    capacite_max: Optional[int] = None,
    id_type_chambre: Optional[int] = None,
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    actif_only: bool = True,
) -> ChambreListResponse:
    await _check_hotel(hotel_id, session)

    # idx_chambre_hotel utilisé automatiquement
    query = (
        select(Chambre)
        .options(selectinload(Chambre.type_chambre))
        .where(Chambre.id_hotel == hotel_id)
    )

    if actif_only:
        query = query.where(Chambre.actif == True)
    if capacite_min is not None:
        query = query.where(Chambre.capacite >= capacite_min)
    if capacite_max is not None:
        query = query.where(Chambre.capacite <= capacite_max)
    if id_type_chambre is not None:
        query = query.where(Chambre.id_type_chambre == id_type_chambre)

    result = await session.execute(query)
    chambres = result.scalars().all()

    # Enrichir avec les prix min/max du tarif courant (idx_tarif_dates)
    today = date.today()
    items = []
    for chambre in chambres:
        prix_result = await session.execute(
            select(func.min(Tarif.prix), func.max(Tarif.prix))
            .where(Tarif.id_chambre == chambre.id)
            .where(Tarif.date_debut <= today)
            .where(Tarif.date_fin >= today)
        )
        prix_row = prix_result.one()
        p_min, p_max = float(prix_row[0]) if prix_row[0] else None, float(prix_row[1]) if prix_row[1] else None

        # Filtre prix appliqué après calcul
        if prix_min is not None and (p_min is None or p_min < prix_min):
            continue
        if prix_max is not None and (p_max is None or p_max > prix_max):
            continue

        chambre_dict = {
            "id": chambre.id, "capacite": chambre.capacite,
            "description": chambre.description, "id_hotel": chambre.id_hotel,
            "id_type_chambre": chambre.id_type_chambre,
            "type_chambre": chambre.type_chambre,
            "actif": chambre.actif, "created_at": chambre.created_at,
            "updated_at": chambre.updated_at,
            "prix_min": p_min, "prix_max": p_max,
        }
        items.append(ChambreResponse.model_validate(chambre_dict))

    return ChambreListResponse(total=len(items), items=items)


async def get_chambre(hotel_id: int, chambre_id: int, session: AsyncSession) -> ChambreResponse:
    result = await session.execute(
        select(Chambre)
        .options(selectinload(Chambre.type_chambre))
        .where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    chambre = result.scalar_one_or_none()
    if not chambre:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    return ChambreResponse.model_validate(chambre)


async def create_chambre(hotel_id: int, data: ChambreCreate, session: AsyncSession) -> ChambreResponse:
    await _check_hotel(hotel_id, session)
    # Vérifier que le type_chambre existe
    r = await session.execute(select(TypeChambre.id).where(TypeChambre.id == data.id_type_chambre))
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"TypeChambre {data.id_type_chambre} introuvable")

    chambre = Chambre(id_hotel=hotel_id, **data.model_dump())
    session.add(chambre)
    await session.flush()
    await session.refresh(chambre)

    result = await session.execute(
        select(Chambre).options(selectinload(Chambre.type_chambre)).where(Chambre.id == chambre.id)
    )
    return ChambreResponse.model_validate(result.scalar_one())


async def update_chambre(
    hotel_id: int, chambre_id: int, data: ChambreUpdate, session: AsyncSession
) -> ChambreResponse:
    result = await session.execute(
        select(Chambre).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    chambre = result.scalar_one_or_none()
    if not chambre:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(chambre, field, value)
    await session.flush()
    result2 = await session.execute(
        select(Chambre).options(selectinload(Chambre.type_chambre)).where(Chambre.id == chambre_id)
    )
    return ChambreResponse.model_validate(result2.scalar_one())


async def delete_chambre(hotel_id: int, chambre_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(Chambre).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    chambre = result.scalar_one_or_none()
    if not chambre:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    chambre.actif = False
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  TARIFS
# ═══════════════════════════════════════════════════════════
async def list_tarifs(hotel_id: int, chambre_id: int, session: AsyncSession) -> TarifListResponse:
    # Vérifier que la chambre appartient bien à l'hôtel
    r = await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")

    result = await session.execute(
        select(Tarif)
        .options(selectinload(Tarif.type_reservation))
        .where(Tarif.id_chambre == chambre_id)
        .order_by(Tarif.date_debut.asc())
    )
    tarifs = result.scalars().all()
    return TarifListResponse(total=len(tarifs), items=[TarifResponse.model_validate(t) for t in tarifs])


async def create_tarif(
    hotel_id: int, chambre_id: int, data: TarifCreate, session: AsyncSession
) -> TarifResponse:
    # Vérifier chambre + hôtel
    r = await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")

    # Vérifier type_reservation
    r2 = await session.execute(
        select(TypeReservation.id).where(TypeReservation.id == data.id_type_reservation)
    )
    if r2.scalar_one_or_none() is None:
        raise NotFoundException(f"TypeReservation {data.id_type_reservation} introuvable")

    tarif = Tarif(id_chambre=chambre_id, **data.model_dump())
    session.add(tarif)
    await session.flush()

    result = await session.execute(
        select(Tarif).options(selectinload(Tarif.type_reservation)).where(Tarif.id == tarif.id)
    )
    return TarifResponse.model_validate(result.scalar_one())


async def update_tarif(
    hotel_id: int, chambre_id: int, tarif_id: int,
    data: "TarifUpdate", session: AsyncSession
) -> TarifResponse:
    # Vérifier chambre + hôtel
    r = await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")

    result = await session.execute(
        select(Tarif).where(Tarif.id == tarif_id, Tarif.id_chambre == chambre_id)
    )
    tarif = result.scalar_one_or_none()
    if not tarif:
        raise NotFoundException(f"Tarif {tarif_id} introuvable")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tarif, field, value)

    await session.flush()
    result2 = await session.execute(
        select(Tarif).options(selectinload(Tarif.type_reservation)).where(Tarif.id == tarif_id)
    )
    return TarifResponse.model_validate(result2.scalar_one())


async def delete_tarif(
    hotel_id: int, chambre_id: int, tarif_id: int, session: AsyncSession
) -> None:
    # Vérifier chambre + hôtel
    r = await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")

    result = await session.execute(
        select(Tarif).where(Tarif.id == tarif_id, Tarif.id_chambre == chambre_id)
    )
    tarif = result.scalar_one_or_none()
    if not tarif:
        raise NotFoundException(f"Tarif {tarif_id} introuvable")
    await session.delete(tarif)
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  AVIS
# ═══════════════════════════════════════════════════════════
async def list_avis(hotel_id: int, session: AsyncSession) -> AvisListResponse:
    await _check_hotel(hotel_id, session)
    result = await session.execute(
        select(Avis)
        .where(Avis.id_hotel == hotel_id)
        .order_by(Avis.date.desc())
    )
    avis_list = result.scalars().all()

    note_moy = 0.0
    if avis_list:
        note_moy = round(sum(a.note for a in avis_list) / len(avis_list), 2)

    return AvisListResponse(
        total=len(avis_list),
        note_moyenne=note_moy,
        items=[AvisResponse.model_validate(a) for a in avis_list],
    )


async def create_avis(
    hotel_id: int, data: AvisCreate, client_id: int, session: AsyncSession
) -> AvisResponse:
    await _check_hotel(hotel_id, session)

    # Un client ne peut laisser qu'un seul avis par hôtel (contrainte DB)
    existing = await session.execute(
        select(Avis.id).where(Avis.id_client == client_id, Avis.id_hotel == hotel_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictException("Vous avez déjà laissé un avis pour cet hôtel")

    # Vérifier que le client a une réservation CONFIRMEE ou TERMINEE dans cet hôtel
    from app.models.reservation import Reservation, StatutReservation, LigneReservationChambre
    from app.models.hotel import Chambre
    resa_check = await session.execute(
        select(Reservation.id)
        .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
        .join(Chambre, Chambre.id == LigneReservationChambre.id_chambre)
        .where(
            Reservation.id_client == client_id,
            Chambre.id_hotel == hotel_id,
            Reservation.statut.in_([StatutReservation.CONFIRMEE, StatutReservation.TERMINEE])
        )
        .limit(1)
    )
    if resa_check.scalar_one_or_none() is None:
        raise ConflictException(
            "Vous devez avoir effectué une réservation confirmée dans cet hôtel pour laisser un avis"
        )

    avis = Avis(id_hotel=hotel_id, id_client=client_id, **data.model_dump())
    session.add(avis)
    await session.flush()
    await session.refresh(avis)
    return AvisResponse.model_validate(avis)


async def delete_avis(
    hotel_id: int, avis_id: int, client_id: int, role: str, session: AsyncSession
) -> None:
    result = await session.execute(
        select(Avis).where(Avis.id == avis_id, Avis.id_hotel == hotel_id)
    )
    avis = result.scalar_one_or_none()
    if not avis:
        raise NotFoundException(f"Avis {avis_id} introuvable")

    # Un client ne peut supprimer que son propre avis
    if role == "CLIENT" and avis.id_client != client_id:
        raise ForbiddenException("Vous ne pouvez supprimer que vos propres avis")

    await session.delete(avis)
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  DISPONIBILITÉS
# ═══════════════════════════════════════════════════════════
async def get_chambre_disponibilite(
    hotel_id: int,
    chambre_id: int,
    date_debut: date,
    date_fin: date,
    session: AsyncSession,
) -> "ChambreDisponibiliteResponse":
    """
    Vérifie si une chambre est disponible sur une période.
    Une chambre est indisponible si elle a une réservation CONFIRMEE
    qui chevauche la période demandée.
    """
    from app.schemas.hotel import ChambreDisponibiliteResponse, ReservationOccupation
    from app.models.reservation import Reservation, StatutReservation, LigneReservationChambre

    # Vérifier que la chambre appartient à l'hôtel
    r = await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )
    if r.scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")

    # Chercher réservations qui chevauchent la période
    result = await session.execute(
        select(Reservation)
        .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
        .where(
            LigneReservationChambre.id_chambre == chambre_id,
            Reservation.statut == StatutReservation.CONFIRMEE,
            Reservation.date_debut < date_fin,
            Reservation.date_fin > date_debut,
        )
        .order_by(Reservation.date_debut.asc())
    )
    reservations = result.scalars().all()

    occupations = [
        ReservationOccupation(
            id_reservation=res.id,
            date_debut=res.date_debut,
            date_fin=res.date_fin,
            statut=res.statut.value,
        )
        for res in reservations
    ]

    disponible = len(occupations) == 0

    return ChambreDisponibiliteResponse(
        id_chambre=chambre_id,
        disponible=disponible,
        occupations=occupations,
        message="Disponible" if disponible else f"Occupée ({len(occupations)} réservation(s) en conflit)",
    )


async def get_hotel_disponibilites(
    hotel_id: int,
    date_debut: date,
    date_fin: date,
    session: AsyncSession,
) -> "HotelDisponibilitesResponse":
    """
    Retourne la disponibilité de toutes les chambres actives d'un hôtel
    sur une période donnée.
    """
    from app.schemas.hotel import (
        HotelDisponibilitesResponse,
        ChambreDisponibiliteDetailResponse,
        ReservationOccupation,
    )
    from app.models.reservation import Reservation, StatutReservation, LigneReservationChambre

    await _check_hotel(hotel_id, session)

    # Toutes les chambres actives de l'hôtel
    result = await session.execute(
        select(Chambre)
        .options(selectinload(Chambre.type_chambre))
        .where(Chambre.id_hotel == hotel_id, Chambre.actif == True)
        .order_by(Chambre.id.asc())
    )
    chambres = result.scalars().all()

    today = date.today()
    chambres_dispo = []

    for chambre in chambres:
        # Réservations CONFIRMEE qui chevauchent la période
        res_result = await session.execute(
            select(Reservation)
            .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
            .where(
                LigneReservationChambre.id_chambre == chambre.id,
                Reservation.statut == StatutReservation.CONFIRMEE,
                Reservation.date_debut < date_fin,
                Reservation.date_fin > date_debut,
            )
            .order_by(Reservation.date_debut.asc())
        )
        reservations = res_result.scalars().all()

        # Prix courant
        prix_result = await session.execute(
            select(func.min(Tarif.prix), func.max(Tarif.prix))
            .where(
                Tarif.id_chambre == chambre.id,
                Tarif.date_debut <= today,
                Tarif.date_fin >= today,
            )
        )
        prix_row = prix_result.one()
        p_min = float(prix_row[0]) if prix_row[0] else None
        p_max = float(prix_row[1]) if prix_row[1] else None

        occupations = [
            ReservationOccupation(
                id_reservation=res.id,
                date_debut=res.date_debut,
                date_fin=res.date_fin,
                statut=res.statut.value,
            )
            for res in reservations
        ]

        chambres_dispo.append(
            ChambreDisponibiliteDetailResponse(
                id=chambre.id,
                capacite=chambre.capacite,
                description=chambre.description,
                type_chambre=chambre.type_chambre,
                actif=chambre.actif,
                disponible=len(occupations) == 0,
                occupations=occupations,
                prix_min=p_min,
                prix_max=p_max,
            )
        )

    return HotelDisponibilitesResponse(
        hotel_id=hotel_id,
        date_debut=date_debut,
        date_fin=date_fin,
        chambres=chambres_dispo,
    )


# ═══════════════════════════════════════════════════════════
#  MIS EN AVANT + VILLES VEDETTES
# ═══════════════════════════════════════════════════════════
async def toggle_mis_en_avant(
    hotel_id: int, mis_en_avant: bool, session: AsyncSession
) -> HotelResponse:
    from app.core.exceptions import NotFoundException
    result = await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )
    hotel = result.scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    hotel.mis_en_avant = mis_en_avant
    await session.flush()
    await session.refresh(hotel)
    return _to_hotel_response(hotel)


async def list_hotels_en_avant(session: AsyncSession) -> HotelListResponse:
    """Hôtels mis en avant actifs — pour la landing page.
    Si aucun n'est mis en avant, retourne tous les hôtels actifs."""
    q = (
        select(Hotel)
        .options(selectinload(Hotel.partenaire))
        .where(Hotel.actif == True, Hotel.mis_en_avant == True)
        .order_by(Hotel.note_moyenne.desc(), Hotel.nom.asc())
    )
    result = await session.execute(q)
    hotels = result.scalars().all()

    # Fallback : si aucun mis en avant, retourner tous les actifs
    if not hotels:
        q2 = (
            select(Hotel)
            .options(selectinload(Hotel.partenaire))
            .where(Hotel.actif == True)
            .order_by(Hotel.note_moyenne.desc(), Hotel.nom.asc())
            .limit(12)
        )
        result2 = await session.execute(q2)
        hotels = result2.scalars().all()

    return HotelListResponse(
        total=len(hotels), page=1, per_page=len(hotels),
        items=[_to_hotel_response(h) for h in hotels],
    )


# ── Villes vedettes ───────────────────────────────────────
async def list_villes_vedettes(session: AsyncSession, actif_only: bool = True):
    from app.models.hotel import VilleVedette
    from app.schemas.hotel import VilleVedetteResponse
    q = select(VilleVedette).order_by(VilleVedette.ordre.asc(), VilleVedette.nom.asc())
    if actif_only:
        q = q.where(VilleVedette.actif == True)
    result = await session.execute(q)
    villes = result.scalars().all()
    return [VilleVedetteResponse.model_validate(v) for v in villes]


async def create_ville_vedette(data, session: AsyncSession):
    from app.models.hotel import VilleVedette
    from app.schemas.hotel import VilleVedetteResponse
    v = VilleVedette(nom=data.nom, ordre=data.ordre, actif=data.actif)
    session.add(v)
    await session.flush()
    await session.refresh(v)
    return VilleVedetteResponse.model_validate(v)


async def update_ville_vedette(ville_id: int, data, session: AsyncSession):
    from app.models.hotel import VilleVedette
    from app.schemas.hotel import VilleVedetteResponse
    from app.core.exceptions import NotFoundException
    result = await session.execute(select(VilleVedette).where(VilleVedette.id == ville_id))
    v = result.scalar_one_or_none()
    if not v:
        raise NotFoundException(f"Ville {ville_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    await session.flush()
    await session.refresh(v)
    return VilleVedetteResponse.model_validate(v)


async def delete_ville_vedette(ville_id: int, session: AsyncSession) -> None:
    from app.models.hotel import VilleVedette
    from app.core.exceptions import NotFoundException
    result = await session.execute(select(VilleVedette).where(VilleVedette.id == ville_id))
    v = result.scalar_one_or_none()
    if not v:
        raise NotFoundException(f"Ville {ville_id} introuvable")
    await session.delete(v)
    await session.flush()