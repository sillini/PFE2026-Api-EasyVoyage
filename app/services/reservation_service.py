"""
Service Réservations — logique métier complète.

Deux types de réservation distincts :
  1. VOYAGE   : id_voyage renseigné dans reservation, pas de lignes chambres
                total = prix_base × (nb_adultes + nb_enfants)
                ► incrémente voyage.nb_inscrits au PAIEMENT (statut → CONFIRMEE)
                ► décrémente voyage.nb_inscrits à l'ANNULATION (statut → ANNULEE)
  2. CHAMBRES : id_voyage NULL, lignes dans ligne_reservation_chambre
                PK = (id_reservation, id_chambre) — chambre unique par réservation
                total = Σ (tarif_nuit × nb_nuits) par chambre
                ► application automatique des promotions actives sur l'hôtel

Flux paiement :
  EN_ATTENTE → payer()   → CONFIRMEE + facture FAC-YYYY-XXXXX créée automatiquement
                            + calcul fiscal dynamique (taxe séjour, TVA, timbre)
  CONFIRMEE  → annuler() → ANNULEE   (facture → ANNULEE)
  CONFIRMEE  → PostgreSQL scheduler  → TERMINEE (quand date_fin < aujourd'hui)

Notifications :
  ✅ Tous les admins notifiés à chaque nouvelle réservation
  ✅ ✨ NEW : Le partenaire propriétaire de l'hôtel notifié à chaque
       nouvelle réservation chambre (clients ET visiteurs)
  ✅ ✨ NEW : Le partenaire notifié à chaque annulation de résa chambre
"""
from datetime import date, datetime, timezone
from typing import Optional

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
# ✅ Helpers de notification centralisés
from app.services.notification_helper import (
    notify_all_admins,
    notify_partenaire_for_hotel,   # ← AJOUT
    NotifType,
)
from app.models.utilisateur import Utilisateur


# ── Helpers ───────────────────────────────────────────────────────────────────
def _nb_nuits(date_debut: date, date_fin: date) -> int:
    return (date_fin - date_debut).days


async def _generate_numero_facture(session: AsyncSession) -> str:
    """Génère un numéro unique : FAC-2026-00001"""
    annee  = datetime.now(timezone.utc).year
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


def _nb_personnes_from_resa(resa: Reservation, voyage: Voyage) -> int:
    """
    Retourne le nombre de personnes d'une réservation voyage.
    """
    nb = (resa.nb_adultes or 0) + (resa.nb_enfants or 0)
    if nb > 0:
        return nb
    prix = float(voyage.prix_base)
    if prix > 0:
        return max(1, round(float(resa.total_ttc) / prix))
    return 1


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
        nb_adultes=resa.nb_adultes or 0,
        nb_enfants=resa.nb_enfants or 0,
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
    total_ttc = prix_base × nb_personnes (adultes + enfants).
    Vérifie la capacité disponible avant de créer.
    """
    result = await session.execute(
        select(Voyage).where(Voyage.id == data.id_voyage, Voyage.actif == True)
    )
    voyage = result.scalar_one_or_none()
    if not voyage:
        raise NotFoundException(f"Voyage {data.id_voyage} introuvable ou inactif")

    nb_personnes     = data.nb_adultes + data.nb_enfants
    places_restantes = max(0, voyage.capacite_max - (voyage.nb_inscrits or 0))

    if nb_personnes > places_restantes:
        raise ConflictException(
            f"Seulement {places_restantes} place(s) disponible(s) pour ce voyage "
            f"(vous demandez {nb_personnes} personne(s))."
        )

    total_ttc = float(voyage.prix_base) * nb_personnes

    resa = Reservation(
        date_debut=data.date_debut,
        date_fin=data.date_fin,
        id_client=client_id,
        id_voyage=data.id_voyage,
        total_ttc=total_ttc,
        nb_adultes=data.nb_adultes,
        nb_enfants=data.nb_enfants,
        statut=StatutReservation.EN_ATTENTE,
    )
    session.add(resa)
    await session.flush()

    # 🔔 Notifier tous les admins
    try:
        client = (await session.execute(
            select(Utilisateur).where(Utilisateur.id == client_id)
        )).scalar_one_or_none()
        client_nom = f"{client.prenom} {client.nom}" if client else "Un client"

        await notify_all_admins(
            session,
            type_   = NotifType.NOUVELLE_RESERVATION,
            titre   = "Nouvelle réservation voyage",
            message = f"{client_nom} a réservé « {voyage.titre} » ({total_ttc:.2f} DT)",
        )
    except Exception:
        pass  # ne jamais bloquer la création

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
#  CAS 2 — RÉSERVATION CHAMBRES (avec application auto des promos)
# ═══════════════════════════════════════════════════════════
async def create_reservation_chambres(
    data: ReservationChambresCreate,
    client_id: int,
    session: AsyncSession,
) -> ReservationResponse:
    """
    Crée une réservation pour des chambres d'hôtel.
    PK ligne = (id_reservation, id_chambre) → chambre unique par réservation.
    total_ttc = Σ (tarif × nb_nuits) pour chaque chambre, avec application
    automatique de la promotion active de l'hôtel si elle existe.

    Side-effects notifications :
      - Notifie tous les admins (existant)
      - ✨ NEW : Notifie chaque partenaire propriétaire des hôtels concernés
    """
    from app.services.promotion_service import (
        get_promotion_active_hotel,
        calculer_prix_promo,
    )

    nb_nuits = _nb_nuits(data.date_debut, data.date_fin)

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
    promo_cache: dict = {}

    # ✨ NEW : on garde une trace des hôtels concernés pour les notifs partenaires
    hotels_concernes: set = set()

    async def _get_promo_for_hotel(hotel_id: int):
        if hotel_id not in promo_cache:
            promo_cache[hotel_id] = await get_promotion_active_hotel(
                hotel_id, session, at_date=data.date_debut
            )
        return promo_cache[hotel_id]

    for ligne in data.chambres:
        r = await session.execute(
            select(Chambre).where(Chambre.id == ligne.id_chambre, Chambre.actif == True)
        )
        chambre = r.scalar_one_or_none()
        if not chambre:
            raise NotFoundException(f"Chambre {ligne.id_chambre} introuvable ou inactive")

        if ligne.nb_adultes + ligne.nb_enfants < 1:
            raise ConflictException(f"Chambre {ligne.id_chambre} : au moins 1 occupant requis")

        # ✨ NEW : mémoriser l'hôtel pour la notif partenaire
        hotels_concernes.add(chambre.id_hotel)

        r_tarif = await session.execute(
            select(Tarif)
            .where(
                Tarif.id_chambre == ligne.id_chambre,
                Tarif.date_debut <= data.date_debut,
                Tarif.date_fin   >= data.date_fin,
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

        prix_base = float(tarif.prix) * nb_nuits
        promo = await _get_promo_for_hotel(chambre.id_hotel)
        if promo:
            prix_unitaire = calculer_prix_promo(prix_base, float(promo.pourcentage))
        else:
            prix_unitaire = round(prix_base, 2)

        total_ttc += prix_unitaire

        session.add(LigneReservationChambre(
            id_reservation=resa.id,
            id_chambre=ligne.id_chambre,
            prix_unitaire=prix_unitaire,
            quantite=1,
            nb_adultes=ligne.nb_adultes,
            nb_enfants=ligne.nb_enfants,
        ))

    resa.total_ttc = round(total_ttc, 2)
    await session.flush()

    # 🔔 Notifier tous les admins ET les partenaires concernés
    try:
        client = (await session.execute(
            select(Utilisateur).where(Utilisateur.id == client_id)
        )).scalar_one_or_none()
        client_nom = f"{client.prenom} {client.nom}" if client else "Un client"
        nb_chambres = len(data.chambres)

        # 1. Notif admins (existant)
        await notify_all_admins(
            session,
            type_   = NotifType.NOUVELLE_RESERVATION,
            titre   = "Nouvelle réservation hôtel",
            message = f"{client_nom} a réservé {nb_chambres} chambre{'s' if nb_chambres > 1 else ''} ({total_ttc:.2f} DT)",
        )

        # 2. ✨ NEW : Notif partenaire(s) propriétaire(s) des hôtels concernés
        for hotel_id in hotels_concernes:
            await notify_partenaire_for_hotel(
                session,
                hotel_id = hotel_id,
                type_    = NotifType.NOUVELLE_RESERVATION_HOTEL,
                titre    = "🎉 Nouvelle réservation",
                message  = (
                    f"{client_nom} a réservé du "
                    f"{data.date_debut.strftime('%d/%m/%Y')} au "
                    f"{data.date_fin.strftime('%d/%m/%Y')} ({total_ttc:.2f} DT)"
                ),
            )
    except Exception:
        pass  # ne jamais bloquer la création

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
#  PAIEMENT → CONFIRMEE + FACTURE AUTO + CALCUL FISCAL
#  ► Pour voyage : incrémente nb_inscrits du voyage
# ═══════════════════════════════════════════════════════════
async def payer_reservation(
    reservation_id: int,
    data: PaiementRequest,
    client_id: int,
    session: AsyncSession,
) -> FactureResponse:

    resa = await _get_reservation_or_404(reservation_id, session)

    if resa.id_client != client_id:
        raise ForbiddenException("Cette réservation ne vous appartient pas")
    if resa.statut == StatutReservation.CONFIRMEE:
        raise ConflictException("Cette réservation est déjà confirmée")
    if resa.statut == StatutReservation.ANNULEE:
        raise ConflictException("Impossible de payer une réservation annulée")
    if resa.statut == StatutReservation.TERMINEE:
        raise ConflictException("Impossible de payer une réservation terminée")

    # ── Voyage : vérifier capacité et incrémenter nb_inscrits ────────────────
    if resa.id_voyage:
        v_result = await session.execute(
            select(Voyage).where(Voyage.id == resa.id_voyage)
        )
        voyage = v_result.scalar_one_or_none()
        if voyage:
            nb_personnes     = _nb_personnes_from_resa(resa, voyage)
            places_restantes = max(0, voyage.capacite_max - (voyage.nb_inscrits or 0))

            if nb_personnes > places_restantes:
                raise ConflictException(
                    f"Plus assez de places disponibles : il reste {places_restantes} place(s), "
                    f"vous demandez {nb_personnes}."
                )
            voyage.nb_inscrits = (voyage.nb_inscrits or 0) + nb_personnes
            await session.flush()

    # ── Calcul fiscal dynamique ───────────────────────────────────────────────
    from app.services.fiscal_service import calculer_fiscal, calculer_fiscal_voyage

    nb_nuits = _nb_nuits(resa.date_debut, resa.date_fin)

    if resa.id_voyage:
        fiscal = await calculer_fiscal_voyage(
            montant_ht = float(resa.total_ttc),
            session    = session,
        )
    else:
        # Chambre hôtel : récupérer les étoiles pour appliquer la bonne taxe de séjour
        etoiles = 3
        if resa.lignes_chambres:
            ch_res = await session.execute(
                select(Chambre)
                .options(selectinload(Chambre.hotel))
                .where(Chambre.id == resa.lignes_chambres[0].id_chambre)
            )
            chambre_obj = ch_res.scalar_one_or_none()
            if chambre_obj and chambre_obj.hotel:
                etoiles = chambre_obj.hotel.etoiles

        fiscal = await calculer_fiscal(
            montant_ht    = float(resa.total_ttc),
            nb_nuits      = nb_nuits,
            etoiles_hotel = etoiles,
            session       = session,
        )

    # 1. Confirmer la réservation et mettre à jour le total TTC
    resa.statut    = StatutReservation.CONFIRMEE
    resa.total_ttc = fiscal.total_ttc

    # 2. Créer la facture avec détail fiscal complet
    numero  = await _generate_numero_facture(session)
    facture = Facture(
        numero            = numero,
        montant_total     = fiscal.total_ttc,
        montant_ht        = fiscal.montant_ht,
        taxe_sejour       = fiscal.taxe_sejour,
        tva_montant       = fiscal.tva_montant,
        taux_tva          = fiscal.taux_tva,
        droit_timbre      = fiscal.droit_timbre,
        nb_nuits_taxables = fiscal.nb_nuits_taxables,
        statut            = StatutFacture.EMISE,
        id_reservation    = resa.id,
    )
    session.add(facture)
    await session.flush()

    # 3. Enregistrer le paiement
    paiement_obj = Paiement(
        montant        = fiscal.total_ttc,
        methode        = MethodePaiement(data.methode),
        statut         = StatutPaiement.CONFIRME,
        transaction_id = data.transaction_id,
        id_facture     = facture.id,
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
#  ► Pour voyage CONFIRMEE : décrémente nb_inscrits du voyage
#  ► ✨ NEW : Notifie le(s) partenaire(s) si résa hôtel
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

    # ── Voyage CONFIRMEE : décrémenter nb_inscrits ───────────────────────────
    if resa.id_voyage and resa.statut == StatutReservation.CONFIRMEE:
        v_result = await session.execute(
            select(Voyage).where(Voyage.id == resa.id_voyage)
        )
        voyage = v_result.scalar_one_or_none()
        if voyage:
            nb_personnes = _nb_personnes_from_resa(resa, voyage)
            voyage.nb_inscrits = max(0, (voyage.nb_inscrits or 0) - nb_personnes)
            await session.flush()

    # ── ✨ NEW : Notifier les partenaires si résa hôtel ─────────────────────
    if not resa.id_voyage and resa.lignes_chambres:
        try:
            client = (await session.execute(
                select(Utilisateur).where(Utilisateur.id == resa.id_client)
            )).scalar_one_or_none()
            client_nom = f"{client.prenom} {client.nom}" if client else "Un client"

            # Récupérer les hôtels uniques concernés
            hotels_concernes = set()
            for ligne in resa.lignes_chambres:
                ch = (await session.execute(
                    select(Chambre).where(Chambre.id == ligne.id_chambre)
                )).scalar_one_or_none()
                if ch:
                    hotels_concernes.add(ch.id_hotel)

            for hotel_id in hotels_concernes:
                await notify_partenaire_for_hotel(
                    session,
                    hotel_id = hotel_id,
                    type_    = NotifType.RESERVATION_ANNULEE,
                    titre    = "⚠️ Réservation annulée",
                    message  = (
                        f"{client_nom} a annulé sa réservation prévue du "
                        f"{resa.date_debut.strftime('%d/%m/%Y')} au "
                        f"{resa.date_fin.strftime('%d/%m/%Y')}"
                    ),
                )
        except Exception:
            pass  # ne jamais bloquer l'annulation

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
    query  = query.order_by(Reservation.date_reservation.desc()).offset(offset).limit(per_page)

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
    query  = query.order_by(Reservation.date_reservation.desc()).offset(offset).limit(per_page)

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