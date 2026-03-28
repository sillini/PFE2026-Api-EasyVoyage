"""
app/services/hotel_service.py — VERSION FINALE CORRIGÉE

CORRECTION AVIS :
  Le modèle Avis n'a PAS de relation .client (seulement id_client FK → client.id).
  On ne peut pas faire selectinload(Avis.client) → AttributeError.

  SOLUTION : jointure manuelle sur Utilisateur pour charger prenom/nom,
  puis construction de AvisResponse à la main avec AvisClientInfo.
"""
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.hotel import Avis, Chambre, Hotel, Tarif, TypeChambre, TypeReservation
from app.models.utilisateur import Utilisateur
from app.schemas.hotel import (
    AvisClientInfo, AvisCreate, AvisListResponse, AvisResponse,
    ChambreCreate, ChambreListResponse, ChambreResponse, ChambreUpdate,
    HotelAdminUpdate, HotelCreate, HotelListResponse, HotelResponse, HotelUpdate,
    PartenaireInfo,
    TarifCreate, TarifListResponse, TarifResponse,
    TypeChambreResponse, TypeReservationResponse,
)


# ═══════════════════════════════════════════════════════════
#  HELPERS INTERNES
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
        id=hotel.id,
        nom=hotel.nom,
        etoiles=hotel.etoiles,
        adresse=hotel.adresse,
        ville=getattr(hotel, "ville", None),
        pays=hotel.pays,
        description=hotel.description,
        note_moyenne=float(hotel.note_moyenne) if hotel.note_moyenne else 0.0,
        actif=hotel.actif,
        mis_en_avant=getattr(hotel, "mis_en_avant", False),
        id_partenaire=hotel.id_partenaire,
        partenaire=partenaire_info,
        created_at=hotel.created_at,
        updated_at=hotel.updated_at,
    )


async def _get_prix_courant(chambre_id: int, session: AsyncSession):
    today = date.today()
    row = (await session.execute(
        select(func.min(Tarif.prix), func.max(Tarif.prix))
        .where(
            Tarif.id_chambre == chambre_id,
            Tarif.date_debut <= today,
            Tarif.date_fin   >= today,
        )
    )).one()
    return (
        float(row[0]) if row[0] is not None else None,
        float(row[1]) if row[1] is not None else None,
    )


def _chambre_to_dict(chambre: Chambre, p_min, p_max) -> dict:
    return {
        "id":              chambre.id,
        "capacite":        chambre.capacite,
        "description":     chambre.description,
        "id_hotel":        chambre.id_hotel,
        "id_type_chambre": chambre.id_type_chambre,
        "type_chambre":    chambre.type_chambre,
        "actif":           chambre.actif,
        "created_at":      chambre.created_at,
        "updated_at":      chambre.updated_at,
        "prix_min":        p_min,
        "prix_max":        p_max,
    }


# ✅ Convertit un Avis + Utilisateur → AvisResponse avec client embarqué
def _to_avis_response(avis: Avis, utilisateur: Optional[Utilisateur]) -> AvisResponse:
    client_info = None
    if utilisateur:
        client_info = AvisClientInfo(
            id=utilisateur.id,
            prenom=utilisateur.prenom,
            nom=utilisateur.nom,
        )
    return AvisResponse(
        id=avis.id,
        note=avis.note,
        commentaire=avis.commentaire,
        date=avis.date,
        id_client=avis.id_client,
        id_hotel=avis.id_hotel,
        created_at=avis.created_at,
        client=client_info,
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
    id_partenaire: Optional[int] = None,
    page: int = 1,
    per_page: int = 10,
) -> HotelListResponse:

    query = select(Hotel).options(selectinload(Hotel.partenaire))

    if actif_only:
        query = query.where(Hotel.actif == True)
    if id_partenaire is not None:
        query = query.where(Hotel.id_partenaire == id_partenaire)
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
    if partenaire_nom or partenaire_email:
        query = query.join(Utilisateur, Utilisateur.id == Hotel.id_partenaire)
        if partenaire_nom:
            s = f"%{partenaire_nom}%"
            query = query.where(Utilisateur.nom.ilike(s) | Utilisateur.prenom.ilike(s))
        if partenaire_email:
            query = query.where(Utilisateur.email.ilike(f"%{partenaire_email}%"))

    total = (await session.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar_one()

    query = query.order_by(Hotel.note_moyenne.desc(), Hotel.nom.asc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    hotels = (await session.execute(query)).scalars().all()

    return HotelListResponse(
        total=total, page=page, per_page=per_page,
        items=[_to_hotel_response(h) for h in hotels],
    )


async def get_hotel(hotel_id: int, session: AsyncSession) -> HotelResponse:
    hotel = (await session.execute(
        select(Hotel)
        .options(selectinload(Hotel.partenaire))
        .where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    return _to_hotel_response(hotel)


async def create_hotel(
    data: HotelCreate, session: AsyncSession, id_partenaire: Optional[int] = None
) -> HotelResponse:
    hotel = Hotel(**data.model_dump(), id_partenaire=id_partenaire)
    session.add(hotel)
    await session.flush()
    hotel = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel.id)
    )).scalar_one()
    return _to_hotel_response(hotel)


async def update_hotel(hotel_id: int, data: HotelUpdate, session: AsyncSession) -> HotelResponse:
    hotel = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(hotel, field, value)
    await session.flush()
    hotel = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )).scalar_one()
    return _to_hotel_response(hotel)


async def admin_toggle_hotel(hotel_id: int, actif: bool, session: AsyncSession) -> HotelResponse:
    hotel = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    hotel.actif = actif
    await session.flush()
    hotel = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )).scalar_one()
    return _to_hotel_response(hotel)


async def delete_hotel(hotel_id: int, session: AsyncSession) -> None:
    hotel = (await session.execute(
        select(Hotel).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    hotel.actif = False
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  TYPES CHAMBRE & RESERVATION
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
    if (await session.execute(
        select(Hotel.id).where(Hotel.id == hotel_id)
    )).scalar_one_or_none() is None:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")


async def list_chambres(
    hotel_id: int, session: AsyncSession,
    capacite_min: Optional[int] = None,
    capacite_max: Optional[int] = None,
    id_type_chambre: Optional[int] = None,
    prix_min: Optional[float] = None,
    prix_max: Optional[float] = None,
    actif_only: bool = True,
) -> ChambreListResponse:
    await _check_hotel(hotel_id, session)
    query = (
        select(Chambre)
        .options(selectinload(Chambre.type_chambre))
        .where(Chambre.id_hotel == hotel_id)
    )
    if actif_only:    query = query.where(Chambre.actif == True)
    if capacite_min:  query = query.where(Chambre.capacite >= capacite_min)
    if capacite_max:  query = query.where(Chambre.capacite <= capacite_max)
    if id_type_chambre: query = query.where(Chambre.id_type_chambre == id_type_chambre)

    chambres = (await session.execute(query)).scalars().all()
    items = []
    for ch in chambres:
        p_min, p_max = await _get_prix_courant(ch.id, session)
        if prix_min is not None and (p_min is None or p_min < prix_min): continue
        if prix_max is not None and (p_max is None or p_max > prix_max): continue
        items.append(ChambreResponse.model_validate(_chambre_to_dict(ch, p_min, p_max)))
    return ChambreListResponse(total=len(items), items=items)


async def get_chambre(hotel_id: int, chambre_id: int, session: AsyncSession) -> ChambreResponse:
    ch = (await session.execute(
        select(Chambre)
        .options(selectinload(Chambre.type_chambre))
        .where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none()
    if not ch:
        raise NotFoundException(f"Chambre {chambre_id} introuvable dans l'hôtel {hotel_id}")
    p_min, p_max = await _get_prix_courant(chambre_id, session)
    return ChambreResponse.model_validate(_chambre_to_dict(ch, p_min, p_max))


async def create_chambre(hotel_id: int, data: ChambreCreate, session: AsyncSession) -> ChambreResponse:
    await _check_hotel(hotel_id, session)
    ch = Chambre(**data.model_dump(), id_hotel=hotel_id)
    session.add(ch)
    await session.flush()
    ch = (await session.execute(
        select(Chambre).options(selectinload(Chambre.type_chambre)).where(Chambre.id == ch.id)
    )).scalar_one()
    return ChambreResponse.model_validate(_chambre_to_dict(ch, None, None))


async def update_chambre(
    hotel_id: int, chambre_id: int, data: ChambreUpdate, session: AsyncSession
) -> ChambreResponse:
    ch = (await session.execute(
        select(Chambre).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none()
    if not ch:
        raise NotFoundException(f"Chambre {chambre_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ch, field, value)
    await session.flush()
    return await get_chambre(hotel_id, chambre_id, session)


async def delete_chambre(hotel_id: int, chambre_id: int, session: AsyncSession) -> None:
    ch = (await session.execute(
        select(Chambre).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none()
    if not ch:
        raise NotFoundException(f"Chambre {chambre_id} introuvable")
    await session.delete(ch)
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  TARIFS
# ═══════════════════════════════════════════════════════════

async def list_tarifs(hotel_id: int, chambre_id: int, session: AsyncSession) -> TarifListResponse:
    if (await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    tarifs = (await session.execute(
        select(Tarif)
        .options(selectinload(Tarif.type_reservation))
        .where(Tarif.id_chambre == chambre_id)
        .order_by(Tarif.date_debut.asc())
    )).scalars().all()
    return TarifListResponse(total=len(tarifs), items=[TarifResponse.model_validate(t) for t in tarifs])


async def create_tarif(
    hotel_id: int, chambre_id: int, data: TarifCreate, session: AsyncSession
) -> TarifResponse:
    if (await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    if (await session.execute(
        select(TypeReservation.id).where(TypeReservation.id == data.id_type_reservation)
    )).scalar_one_or_none() is None:
        raise NotFoundException(f"TypeReservation {data.id_type_reservation} introuvable")
    tarif = Tarif(id_chambre=chambre_id, **data.model_dump())
    session.add(tarif)
    await session.flush()
    tarif = (await session.execute(
        select(Tarif).options(selectinload(Tarif.type_reservation)).where(Tarif.id == tarif.id)
    )).scalar_one()
    return TarifResponse.model_validate(tarif)


async def update_tarif(
    hotel_id: int, chambre_id: int, tarif_id: int, data, session: AsyncSession
) -> TarifResponse:
    if (await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    tarif = (await session.execute(
        select(Tarif).where(Tarif.id == tarif_id, Tarif.id_chambre == chambre_id)
    )).scalar_one_or_none()
    if not tarif:
        raise NotFoundException(f"Tarif {tarif_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tarif, field, value)
    await session.flush()
    tarif = (await session.execute(
        select(Tarif).options(selectinload(Tarif.type_reservation)).where(Tarif.id == tarif_id)
    )).scalar_one()
    return TarifResponse.model_validate(tarif)


async def delete_tarif(
    hotel_id: int, chambre_id: int, tarif_id: int, session: AsyncSession
) -> None:
    if (await session.execute(
        select(Chambre.id).where(Chambre.id == chambre_id, Chambre.id_hotel == hotel_id)
    )).scalar_one_or_none() is None:
        raise NotFoundException(f"Chambre {chambre_id} introuvable pour l'hôtel {hotel_id}")
    tarif = (await session.execute(
        select(Tarif).where(Tarif.id == tarif_id, Tarif.id_chambre == chambre_id)
    )).scalar_one_or_none()
    if not tarif:
        raise NotFoundException(f"Tarif {tarif_id} introuvable")
    await session.delete(tarif)
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  AVIS
#
#  IMPORTANT : Avis.client n'existe PAS comme relation ORM.
#  On charge Utilisateur manuellement via id_client.
# ═══════════════════════════════════════════════════════════

async def _get_utilisateur(client_id: int, session: AsyncSession) -> Optional[Utilisateur]:
    """Charge l'Utilisateur depuis id_client (FK de Avis vers Client)."""
    return (await session.execute(
        select(Utilisateur).where(Utilisateur.id == client_id)
    )).scalar_one_or_none()


async def list_avis(
    hotel_id: int,
    session: AsyncSession,
    page: int = 1,
    per_page: int = 20,
) -> AvisListResponse:
    await _check_hotel(hotel_id, session)

    query = select(Avis).where(Avis.id_hotel == hotel_id)

    total = (await session.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar_one()

    avis_list = (await session.execute(
        query.order_by(Avis.date.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    note_moy = round(sum(a.note for a in avis_list) / len(avis_list), 2) if avis_list else 0.0

    # ✅ Charger les utilisateurs en une seule requête IN (efficace)
    client_ids = list({a.id_client for a in avis_list})
    utilisateurs = {}
    if client_ids:
        rows = (await session.execute(
            select(Utilisateur).where(Utilisateur.id.in_(client_ids))
        )).scalars().all()
        utilisateurs = {u.id: u for u in rows}

    items = [_to_avis_response(a, utilisateurs.get(a.id_client)) for a in avis_list]

    return AvisListResponse(
        total=total,
        note_moyenne=note_moy,
        items=items,
    )


async def create_avis(
    hotel_id:  int,
    data:      AvisCreate,
    client_id: int,          # ✅ client_id AVANT session
    session:   AsyncSession, # ✅ session EN DERNIER
) -> AvisResponse:
    await _check_hotel(hotel_id, session)

    # Un client ne peut laisser qu'un seul avis par hôtel
    existing = await session.execute(
        select(Avis.id).where(Avis.id_hotel == hotel_id, Avis.id_client == client_id)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictException("Vous avez déjà laissé un avis pour cet hôtel")

    avis = Avis(
        id_hotel=hotel_id,
        id_client=client_id,
        note=data.note,
        commentaire=data.commentaire,
    )
    session.add(avis)
    await session.flush()

    # ✅ Charger l'Utilisateur manuellement (pas de relation .client sur Avis)
    utilisateur = await _get_utilisateur(client_id, session)
    return _to_avis_response(avis, utilisateur)


# ═══════════════════════════════════════════════════════════
#  DISPONIBILITÉS
# ═══════════════════════════════════════════════════════════

async def get_hotel_disponibilites(
    hotel_id: int, date_debut, date_fin, session: AsyncSession
):
    from app.models.reservation import Reservation, StatutReservation, LigneReservationChambre
    from app.schemas.hotel import (
        HotelDisponibilitesResponse, ChambreDisponibiliteResponse, OccupationPeriode,
    )
    await _check_hotel(hotel_id, session)
    chambres = (await session.execute(
        select(Chambre)
        .options(selectinload(Chambre.type_chambre))
        .where(Chambre.id_hotel == hotel_id, Chambre.actif == True)
        .order_by(Chambre.id.asc())
    )).scalars().all()

    chambres_dispo = []
    for ch in chambres:
        reservations = (await session.execute(
            select(Reservation)
            .join(LigneReservationChambre,
                  LigneReservationChambre.id_reservation == Reservation.id)
            .where(
                LigneReservationChambre.id_chambre == ch.id,
                Reservation.statut == StatutReservation.CONFIRMEE,
                Reservation.date_debut < date_fin,
                Reservation.date_fin   > date_debut,
            )
            .order_by(Reservation.date_debut.asc())
        )).scalars().all()

        tarif = (await session.execute(
            select(Tarif)
            .where(Tarif.id_chambre == ch.id, Tarif.date_debut <= date_debut, Tarif.date_fin >= date_fin)
            .order_by(Tarif.prix.asc()).limit(1)
        )).scalar_one_or_none()

        p = float(tarif.prix) if tarif else None
        chambres_dispo.append(ChambreDisponibiliteResponse(
            chambre_id=ch.id,
            disponible=len(reservations) == 0,
            occupations=[OccupationPeriode(date_debut=r.date_debut, date_fin=r.date_fin) for r in reservations],
            prix_min=p, prix_max=p,
        ))

    return HotelDisponibilitesResponse(
        hotel_id=hotel_id, date_debut=date_debut, date_fin=date_fin, chambres=chambres_dispo,
    )


async def get_chambre_disponibilite(
    hotel_id: int, chambre_id: int, date_debut, date_fin, session: AsyncSession
):
    from app.models.reservation import Reservation, StatutReservation, LigneReservationChambre
    from app.schemas.hotel import ChambreDisponibiliteResponse, OccupationPeriode
    await get_chambre(hotel_id, chambre_id, session)
    reservations = (await session.execute(
        select(Reservation)
        .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
        .where(
            LigneReservationChambre.id_chambre == chambre_id,
            Reservation.statut == StatutReservation.CONFIRMEE,
            Reservation.date_debut < date_fin,
            Reservation.date_fin   > date_debut,
        )
    )).scalars().all()
    return ChambreDisponibiliteResponse(
        chambre_id=chambre_id,
        disponible=len(reservations) == 0,
        occupations=[OccupationPeriode(date_debut=r.date_debut, date_fin=r.date_fin) for r in reservations],
        prix_min=None, prix_max=None,
    )


# ═══════════════════════════════════════════════════════════
#  MIS EN AVANT + VILLES VEDETTES
# ═══════════════════════════════════════════════════════════

async def toggle_mis_en_avant(hotel_id: int, mis_en_avant: bool, session: AsyncSession) -> HotelResponse:
    hotel = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire)).where(Hotel.id == hotel_id)
    )).scalar_one_or_none()
    if not hotel:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")
    hotel.mis_en_avant = mis_en_avant
    await session.flush()
    await session.refresh(hotel)
    return _to_hotel_response(hotel)


async def list_hotels_en_avant(session: AsyncSession) -> HotelListResponse:
    hotels = (await session.execute(
        select(Hotel).options(selectinload(Hotel.partenaire))
        .where(Hotel.actif == True, Hotel.mis_en_avant == True)
        .order_by(Hotel.note_moyenne.desc(), Hotel.nom.asc())
    )).scalars().all()
    if not hotels:
        hotels = (await session.execute(
            select(Hotel).options(selectinload(Hotel.partenaire))
            .where(Hotel.actif == True)
            .order_by(Hotel.note_moyenne.desc(), Hotel.nom.asc())
            .limit(12)
        )).scalars().all()
    return HotelListResponse(total=len(hotels), page=1, per_page=len(hotels),
                             items=[_to_hotel_response(h) for h in hotels])


async def list_villes_vedettes(session: AsyncSession, actif_only: bool = True):
    from app.models.hotel import VilleVedette
    from app.schemas.hotel import VilleVedetteResponse
    q = select(VilleVedette).order_by(VilleVedette.ordre.asc(), VilleVedette.nom.asc())
    if actif_only:
        q = q.where(VilleVedette.actif == True)
    villes = (await session.execute(q)).scalars().all()
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
    v = (await session.execute(
        select(VilleVedette).where(VilleVedette.id == ville_id)
    )).scalar_one_or_none()
    if not v:
        raise NotFoundException(f"Ville {ville_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    await session.flush()
    await session.refresh(v)
    return VilleVedetteResponse.model_validate(v)


async def delete_ville_vedette(ville_id: int, session: AsyncSession) -> None:
    from app.models.hotel import VilleVedette
    v = (await session.execute(
        select(VilleVedette).where(VilleVedette.id == ville_id)
    )).scalar_one_or_none()
    if not v:
        raise NotFoundException(f"Ville {ville_id} introuvable")
    await session.delete(v)
    await session.flush()