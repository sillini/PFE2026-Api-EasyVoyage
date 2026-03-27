"""
Service Réservations — logique métier complète.

Deux types de réservation distincts :
  1. VOYAGE   : id_voyage renseigné dans reservation, pas de lignes chambres
                total = prix_base du voyage
  2. CHAMBRES : id_voyage NULL, lignes dans ligne_reservation_chambre
                PK = (id_reservation, id_chambre) — chambre unique par réservation
                total = Σ (tarif_nuit × nb_nuits) par chambre

Flux paiement :
  EN_ATTENTE → payer() → CONFIRMEE + facture FAC-YYYY-XXXXX créée automatiquement
  CONFIRMEE  → annuler() → ANNULEE  (facture → ANNULEE)
  CONFIRMEE  → PostgreSQL scheduler → TERMINEE (quand date_fin < aujourd'hui)
"""
from datetime import date, datetime, timezone
from typing import Optional, Union

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.hotel import Chambre, Tarif
from app.models.reservation import (
    Facture, LigneReservationChambre, MethodePaiement,
    Paiement, Reservation, StatutFacture,
    StatutPaiement, StatutReservation,
)
from app.models.voyage import Voyage
from app.schemas.reservation import (
    FactureResponse,
    PaiementRequest,
    ReservationChambresCreate,
    ReservationListResponse,
    ReservationResponse,
    ReservationVoyageCreate,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _nb_nuits(date_debut: date, date_fin: date) -> int:
    return (date_fin - date_debut).days


async def _generate_numero_facture(session: AsyncSession) -> str:
    """Génère un numéro unique : FAC-2026-00001"""
    annee = datetime.now(timezone.utc).year
    result = await session.execute(
        select(func.count(Facture.id)).where(
            func.extract("year", Facture.date_emission) == annee
        )
    )
    count = result.scalar_one() + 1
    return f"FAC-{annee}-{count:05d}"


async def _get_reservation_or_404(
    reservation_id: int, session: AsyncSession
) -> Reservation:
    result = await session.execute(
        select(Reservation)
        .options(
            selectinload(Reservation.lignes_chambres),
            selectinload(Reservation.facture).selectinload(Facture.paiements),
        )
        .where(Reservation.id == reservation_id)
    )
    resa = result.scalar_one_or_none()
    if not resa:
        raise NotFoundException(f"Réservation {reservation_id} introuvable")
    return resa


def _build_response(resa: Reservation) -> ReservationResponse:
    return ReservationResponse(
        id=resa.id,
        date_reservation=resa.date_reservation,
        date_debut=resa.date_debut,
        date_fin=resa.date_fin,
        statut=resa.statut.value,
        total_ttc=float(resa.total_ttc),
        id_client=resa.id_client,
        id_voyage=resa.id_voyage,
        lignes_chambres=resa.lignes_chambres,
        numero_facture=resa.facture.numero if resa.facture else None,
        statut_facture=resa.facture.statut.value if resa.facture else None,
        created_at=resa.created_at,
        updated_at=resa.updated_at,
    )


# ═══════════════════════════════════════════════════════════
#  CAS 1 — RÉSERVATION VOYAGE
# ═══════════════════════════════════════════════════════════
async def create_reservation_voyage(
    data: ReservationVoyageCreate,
    client_id: int,
    session: AsyncSession,
) -> ReservationResponse:
    """
    Crée une réservation pour un voyage.
    total_ttc = prix_base du voyage.
    """
    result = await session.execute(
        select(Voyage).where(Voyage.id == data.id_voyage, Voyage.actif == True)
    )
    voyage = result.scalar_one_or_none()
    if not voyage:
        raise NotFoundException(f"Voyage {data.id_voyage} introuvable ou inactif")

    resa = Reservation(
        date_debut=data.date_debut,
        date_fin=data.date_fin,
        id_client=client_id,
        id_voyage=data.id_voyage,
        total_ttc=float(voyage.prix_base),
        statut=StatutReservation.EN_ATTENTE,
    )
    session.add(resa)
    await session.flush()

    result2 = await session.execute(
        select(Reservation)
        .options(
            selectinload(Reservation.lignes_chambres),
            selectinload(Reservation.facture),
        )
        .where(Reservation.id == resa.id)
    )
    return _build_response(result2.scalar_one())


# ═══════════════════════════════════════════════════════════
#  CAS 2 — RÉSERVATION CHAMBRES
# ═══════════════════════════════════════════════════════════
async def create_reservation_chambres(
    data: ReservationChambresCreate,
    client_id: int,
    session: AsyncSession,
) -> ReservationResponse:
    """
    Crée une réservation pour des chambres d'hôtel.
    PK ligne = (id_reservation, id_chambre) → chambre unique par réservation.
    total_ttc = Σ (tarif × nb_nuits) pour chaque chambre.
    """
    nb_nuits = _nb_nuits(data.date_debut, data.date_fin)

    # Créer la réservation (id_voyage = NULL)
    resa = Reservation(
        date_debut=data.date_debut,
        date_fin=data.date_fin,
        id_client=client_id,
        id_voyage=None,
        total_ttc=0.0,
        statut=StatutReservation.EN_ATTENTE,
    )
    session.add(resa)
    await session.flush()

    total_ttc = 0.0

    for ligne in data.chambres:
        # Vérifier que la chambre existe et est active
        r = await session.execute(
            select(Chambre).where(
                Chambre.id == ligne.id_chambre,
                Chambre.actif == True,
            )
        )
        chambre = r.scalar_one_or_none()
        if not chambre:
            raise NotFoundException(
                f"Chambre {ligne.id_chambre} introuvable ou inactive"
            )

        # Vérifier nb_adultes + nb_enfants >= 1 (contrainte DB chk_lrc_occupants)
        if ligne.nb_adultes + ligne.nb_enfants < 1:
            raise ConflictException(
                f"Chambre {ligne.id_chambre} : au moins 1 occupant requis"
            )

        # Chercher le tarif applicable — idx_tarif_dates utilisé
        r_tarif = await session.execute(
            select(Tarif)
            .where(
                Tarif.id_chambre == ligne.id_chambre,
                Tarif.date_debut <= data.date_debut,
                Tarif.date_fin >= data.date_fin,
            )
            .order_by(Tarif.prix.asc())
            .limit(1)
        )
        tarif = r_tarif.scalar_one_or_none()
        if not tarif:
            raise ConflictException(
                f"Aucun tarif disponible pour la chambre {ligne.id_chambre} "
                f"sur la période {data.date_debut} → {data.date_fin}"
            )

        # prix_unitaire = tarif par nuit × nb_nuits
        prix_unitaire = float(tarif.prix) * nb_nuits
        total_ttc += prix_unitaire

        # Insérer la ligne — quantite=1 par défaut (PK = id_reservation + id_chambre)
        ligne_resa = LigneReservationChambre(
            id_reservation=resa.id,
            id_chambre=ligne.id_chambre,
            prix_unitaire=prix_unitaire,
            quantite=1,
            nb_adultes=ligne.nb_adultes,
            nb_enfants=ligne.nb_enfants,
        )
        session.add(ligne_resa)

    resa.total_ttc = total_ttc
    await session.flush()

    result2 = await session.execute(
        select(Reservation)
        .options(
            selectinload(Reservation.lignes_chambres),
            selectinload(Reservation.facture),
        )
        .where(Reservation.id == resa.id)
    )
    return _build_response(result2.scalar_one())


"""
CORRECTION À APPLIQUER dans app/services/reservation_service.py
================================================================
Chercher la fonction payer_reservation et remplacer UNIQUEMENT
la ligne avec StatutPaiement.CONFIRME ou StatutPaiement.VALIDE
selon ce que votre enum définit réellement.

Voici la fonction payer_reservation COMPLÈTE et corrigée.
Remplacez toute la fonction dans votre fichier.
"""

# ═══════════════════════════════════════════════════════════
#  PAIEMENT → CONFIRMEE + FACTURE AUTO
# ═══════════════════════════════════════════════════════════
async def payer_reservation(
    reservation_id: int,
    data: "PaiementRequest",
    client_id: int,
    session: "AsyncSession",
) -> "FactureResponse":

    resa = await _get_reservation_or_404(reservation_id, session)

    if resa.id_client != client_id:
        raise ForbiddenException("Cette réservation ne vous appartient pas")
    if resa.statut == StatutReservation.CONFIRMEE:
        raise ConflictException("Cette réservation est déjà confirmée")
    if resa.statut == StatutReservation.ANNULEE:
        raise ConflictException("Impossible de payer une réservation annulée")
    if resa.statut == StatutReservation.TERMINEE:
        raise ConflictException("Impossible de payer une réservation terminée")

    # 1. Confirmer la réservation
    resa.statut = StatutReservation.CONFIRMEE

    # 2. Créer la facture
    numero = await _generate_numero_facture(session)
    facture = Facture(
        numero=numero,
        montant_total=resa.total_ttc,
        statut=StatutFacture.EMISE,
        id_reservation=resa.id,
    )
    session.add(facture)
    await session.flush()

    # 3. Enregistrer le paiement
    # ──────────────────────────────────────────────────────
    # CORRECTION : utiliser le bon nom d'enum selon models/reservation.py
    #
    # Si votre StatutPaiement définit CONFIRME  → statut=StatutPaiement.CONFIRME
    # Si votre StatutPaiement définit VALIDE    → statut=StatutPaiement.VALIDE
    #
    # D'après la traceback, votre modèle original utilise CONFIRME.
    # ──────────────────────────────────────────────────────
    paiement_obj = Paiement(
        montant=resa.total_ttc,
        methode=MethodePaiement(data.methode),
        statut=StatutPaiement.CONFIRME,      # ← valeur correcte pour votre projet
        transaction_id=data.transaction_id,
        id_facture=facture.id,
    )
    session.add(paiement_obj)
    facture.statut = StatutFacture.PAYEE
    await session.flush()

    result = await session.execute(
        select(Facture)
        .options(selectinload(Facture.paiements))
        .where(Facture.id == facture.id)
    )
    return FactureResponse.model_validate(result.scalar_one())

# ═══════════════════════════════════════════════════════════
#  ANNULER
# ═══════════════════════════════════════════════════════════
async def annuler_reservation(
    reservation_id: int, client_id: int, role: str, session: AsyncSession
) -> ReservationResponse:

    resa = await _get_reservation_or_404(reservation_id, session)

    if role == "CLIENT" and resa.id_client != client_id:
        raise ForbiddenException("Cette réservation ne vous appartient pas")
    if resa.statut == StatutReservation.TERMINEE:
        raise ConflictException("Impossible d'annuler une réservation terminée")
    if resa.statut == StatutReservation.ANNULEE:
        raise ConflictException("Cette réservation est déjà annulée")

    resa.statut = StatutReservation.ANNULEE
    if resa.facture:
        resa.facture.statut = StatutFacture.ANNULEE

    await session.flush()
    await session.refresh(resa)
    return _build_response(resa)


# ═══════════════════════════════════════════════════════════
#  MES RÉSERVATIONS (client)
# ═══════════════════════════════════════════════════════════
async def mes_reservations(
    client_id: int,
    session: AsyncSession,
    statut: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> ReservationListResponse:

    query = (
        select(Reservation)
        .options(
            selectinload(Reservation.lignes_chambres),
            selectinload(Reservation.facture),
        )
        .where(Reservation.id_client == client_id)
    )
    if statut:
        query = query.where(Reservation.statut == StatutReservation(statut))

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Reservation.date_reservation.desc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    return ReservationListResponse(
        total=total, page=page, per_page=per_page,
        items=[_build_response(r) for r in result.scalars().all()],
    )


# ═══════════════════════════════════════════════════════════
#  TOUTES LES RÉSERVATIONS (admin)
# ═══════════════════════════════════════════════════════════
async def list_all_reservations(
    session: AsyncSession,
    statut: Optional[str] = None,
    client_id: Optional[int] = None,
    page: int = 1,
    per_page: int = 10,
) -> ReservationListResponse:

    query = (
        select(Reservation)
        .options(
            selectinload(Reservation.lignes_chambres),
            selectinload(Reservation.facture),
        )
    )
    if statut:
        query = query.where(Reservation.statut == StatutReservation(statut))
    if client_id:
        query = query.where(Reservation.id_client == client_id)

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Reservation.date_reservation.desc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    return ReservationListResponse(
        total=total, page=page, per_page=per_page,
        items=[_build_response(r) for r in result.scalars().all()],
    )


# ═══════════════════════════════════════════════════════════
#  DÉTAIL
# ═══════════════════════════════════════════════════════════
async def get_reservation(
    reservation_id: int, client_id: int, role: str, session: AsyncSession
) -> ReservationResponse:

    resa = await _get_reservation_or_404(reservation_id, session)
    if role == "CLIENT" and resa.id_client != client_id:
        raise ForbiddenException("Cette réservation ne vous appartient pas")
    return _build_response(resa)