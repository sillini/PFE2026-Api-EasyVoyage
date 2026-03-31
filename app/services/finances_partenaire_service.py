"""
app/services/finances_partenaire_service.py
============================================
Logique métier du module Finance — Espace Partenaire.

Règles fondamentales :
  - Toutes les fonctions sont SCOPÉES sur id_partenaire (JWT) → un partenaire
    ne voit JAMAIS les données d'un autre.
  - Chaque calcul de revenu combine TOUJOURS les deux sources :
      · table `reservation`         (clients connectés)
      · table `reservation_visiteur` (visiteurs sans compte)
  - La part partenaire = 90 % du montant brut (taux_commission = 10 %).
  - Le solde disponible = somme des parts partenaire non encore versées.
  - Ce fichier N'IMPORTE et NE MODIFIE RIEN dans finances/service.py ni
    dans finances/repository.py → zéro impact sur l'espace admin.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import select, func, extract, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.utilisateur import Utilisateur
from app.models.hotel import Hotel, Chambre
from app.models.reservation import (
    Reservation,
    ReservationVisiteur,
    LigneReservationChambre,
    StatutReservation,
)
from app.models.finances import CommissionPartenaire, PaiementPartenaire, StatutCommission
from app.schemas.finances_partenaire import (
    PartDashboard,
    PartRevenuMois,
    PartRevenusResponse,
    PartHotelItem,
    PartHotelListResponse,
    PartReservationItem,
    PartReservationListResponse,
    PartPaiementItem,
    PartPaiementsResponse,
    PartDemandeRetraitRequest,
    PartDemandeRetraitResponse,
)

# Taux de commission de l'agence (10 %) → part partenaire = 90 %
_TAUX_COMMISSION = 10.0
_PART_PARTENAIRE = 1.0 - (_TAUX_COMMISSION / 100.0)   # 0.90

# Statuts de réservation qui génèrent un revenu réel
_STATUTS_VALIDES_CLIENT   = [StatutReservation.CONFIRMEE, StatutReservation.TERMINEE]
_STATUTS_VALIDES_VISITEUR = ["CONFIRMEE", "TERMINEE"]


# ═══════════════════════════════════════════════════════════
#  HELPERS INTERNES
# ═══════════════════════════════════════════════════════════

async def _get_chambre_ids_partenaire(
    id_partenaire: int,
    session: AsyncSession,
    id_hotel: Optional[int] = None,
) -> list[int]:
    """
    Retourne les IDs de toutes les chambres appartenant au partenaire.
    Si id_hotel est précisé, filtre sur cet hôtel uniquement.
    """
    q = (
        select(Chambre.id)
        .join(Hotel, Hotel.id == Chambre.id_hotel)
        .where(Hotel.id_partenaire == id_partenaire)
    )
    if id_hotel is not None:
        q = q.where(Hotel.id == id_hotel)
    result = await session.execute(q)
    return [r[0] for r in result.all()]


async def _get_hotel_ids_partenaire(
    id_partenaire: int,
    session: AsyncSession,
) -> list[int]:
    """Retourne les IDs des hôtels appartenant au partenaire."""
    result = await session.execute(
        select(Hotel.id).where(Hotel.id_partenaire == id_partenaire)
    )
    return [r[0] for r in result.all()]


async def _revenu_clients(
    session: AsyncSession,
    chambre_ids: list[int],
    filtre_date=None,
) -> float:
    """
    Somme des total_ttc des réservations CLIENTS confirmées/terminées
    pour les chambres données, avec filtre date optionnel.
    """
    if not chambre_ids:
        return 0.0
    q = (
        select(func.coalesce(func.sum(Reservation.total_ttc), 0.0))
        .join(
            LigneReservationChambre,
            LigneReservationChambre.id_reservation == Reservation.id,
        )
        .where(
            LigneReservationChambre.id_chambre.in_(chambre_ids),
            Reservation.statut.in_(_STATUTS_VALIDES_CLIENT),
            Reservation.id_voyage.is_(None),   # hôtel uniquement
        )
    )
    if filtre_date is not None:
        q = q.where(filtre_date)
    result = await session.execute(q)
    return float(result.scalar_one() or 0.0)


async def _revenu_visiteurs(
    session: AsyncSession,
    chambre_ids: list[int],
    filtre_date=None,
) -> float:
    """
    Somme des total_ttc des réservations VISITEURS confirmées/terminées
    pour les chambres données, avec filtre date optionnel.
    """
    if not chambre_ids:
        return 0.0
    q = (
        select(func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0.0))
        .where(
            ReservationVisiteur.id_chambre.in_(chambre_ids),
            ReservationVisiteur.statut.in_(_STATUTS_VALIDES_VISITEUR),
        )
    )
    if filtre_date is not None:
        q = q.where(filtre_date)
    result = await session.execute(q)
    return float(result.scalar_one() or 0.0)


async def _nb_resas(
    session: AsyncSession,
    chambre_ids: list[int],
    filtre_date_client=None,
    filtre_date_visiteur=None,
) -> int:
    """Nombre total de réservations (clients + visiteurs) pour des chambres données."""
    if not chambre_ids:
        return 0

    q_clients = (
        select(func.count(Reservation.id.distinct()))
        .join(
            LigneReservationChambre,
            LigneReservationChambre.id_reservation == Reservation.id,
        )
        .where(
            LigneReservationChambre.id_chambre.in_(chambre_ids),
            Reservation.statut.in_(_STATUTS_VALIDES_CLIENT),
            Reservation.id_voyage.is_(None),
        )
    )
    if filtre_date_client is not None:
        q_clients = q_clients.where(filtre_date_client)

    q_visiteurs = (
        select(func.count())
        .where(
            ReservationVisiteur.id_chambre.in_(chambre_ids),
            ReservationVisiteur.statut.in_(_STATUTS_VALIDES_VISITEUR),
        )
    )
    if filtre_date_visiteur is not None:
        q_visiteurs = q_visiteurs.where(filtre_date_visiteur)

    nb_c = (await session.execute(q_clients)).scalar_one()
    nb_v = (await session.execute(q_visiteurs)).scalar_one()
    return int(nb_c) + int(nb_v)


async def _montant_deja_verse(
    id_partenaire: int,
    session: AsyncSession,
) -> float:
    """Somme de tous les paiements déjà effectués à ce partenaire."""
    result = await session.execute(
        select(func.coalesce(func.sum(PaiementPartenaire.montant), 0.0))
        .where(PaiementPartenaire.id_partenaire == id_partenaire)
    )
    return float(result.scalar_one() or 0.0)


# ═══════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════

async def get_dashboard(
    id_partenaire: int,
    session: AsyncSession,
) -> PartDashboard:
    now   = datetime.now()
    mois  = now.month
    annee = now.year
    mois_prec  = mois - 1 if mois > 1 else 12
    annee_prec = annee if mois > 1 else annee - 1

    chambre_ids = await _get_chambre_ids_partenaire(id_partenaire, session)

    # ── Filtres mois courant ──
    filtre_mois_client = and_(
        extract("month", Reservation.date_reservation) == mois,
        extract("year",  Reservation.date_reservation) == annee,
    )
    filtre_mois_visiteur = and_(
        extract("month", ReservationVisiteur.created_at) == mois,
        extract("year",  ReservationVisiteur.created_at) == annee,
    )

    # ── Filtres mois précédent ──
    filtre_prec_client = and_(
        extract("month", Reservation.date_reservation) == mois_prec,
        extract("year",  Reservation.date_reservation) == annee_prec,
    )
    filtre_prec_visiteur = and_(
        extract("month", ReservationVisiteur.created_at) == mois_prec,
        extract("year",  ReservationVisiteur.created_at) == annee_prec,
    )

    # ── Filtres année courante ──
    filtre_annee_client  = extract("year", Reservation.date_reservation) == annee
    filtre_annee_visiteur = extract("year", ReservationVisiteur.created_at) == annee

    rev_mois = (
        await _revenu_clients(session, chambre_ids, filtre_mois_client)
        + await _revenu_visiteurs(session, chambre_ids, filtre_mois_visiteur)
    )
    rev_prec = (
        await _revenu_clients(session, chambre_ids, filtre_prec_client)
        + await _revenu_visiteurs(session, chambre_ids, filtre_prec_visiteur)
    )
    rev_annee = (
        await _revenu_clients(session, chambre_ids, filtre_annee_client)
        + await _revenu_visiteurs(session, chambre_ids, filtre_annee_visiteur)
    )
    nb_resas_mois = await _nb_resas(
        session, chambre_ids, filtre_mois_client, filtre_mois_visiteur
    )

    # ── Solde disponible = part partenaire totale - déjà versé ──
    rev_total_all = (
        await _revenu_clients(session, chambre_ids)
        + await _revenu_visiteurs(session, chambre_ids)
    )
    part_totale  = round(rev_total_all * _PART_PARTENAIRE, 2)
    deja_verse   = await _montant_deja_verse(id_partenaire, session)
    solde_dispo  = max(0.0, round(part_totale - deja_verse, 2))

    # ── Évolution % ──
    if rev_prec > 0:
        evolution = round((rev_mois - rev_prec) / rev_prec * 100, 1)
    else:
        evolution = 0.0

    return PartDashboard(
        solde_disponible=solde_dispo,
        revenu_mois=round(rev_mois, 2),
        revenu_mois_precedent=round(rev_prec, 2),
        evolution_pct=evolution,
        nb_reservations_mois=nb_resas_mois,
        revenu_annee=round(rev_annee, 2),
    )


# ═══════════════════════════════════════════════════════════
#  REVENUS MENSUELS (graphique 12 mois)
# ═══════════════════════════════════════════════════════════

_MOIS_NOMS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun",
              "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]


async def get_revenus_mensuels(
    id_partenaire: int,
    annee: int,
    session: AsyncSession,
) -> PartRevenusResponse:
    chambre_ids = await _get_chambre_ids_partenaire(id_partenaire, session)
    mois_liste  = []

    for m in range(1, 13):
        f_client = and_(
            extract("month", Reservation.date_reservation) == m,
            extract("year",  Reservation.date_reservation) == annee,
        )
        f_visiteur = and_(
            extract("month", ReservationVisiteur.created_at) == m,
            extract("year",  ReservationVisiteur.created_at) == annee,
        )
        rev = (
            await _revenu_clients(session, chambre_ids, f_client)
            + await _revenu_visiteurs(session, chambre_ids, f_visiteur)
        )
        nb = await _nb_resas(session, chambre_ids, f_client, f_visiteur)

        mois_liste.append(PartRevenuMois(
            mois=_MOIS_NOMS[m - 1],
            annee=annee,
            revenu=round(rev, 2),
            nb_resas=nb,
        ))

    return PartRevenusResponse(annee=annee, mois_liste=mois_liste)


# ═══════════════════════════════════════════════════════════
#  MES HÔTELS
# ═══════════════════════════════════════════════════════════

async def get_mes_hotels(
    id_partenaire: int,
    session: AsyncSession,
) -> PartHotelListResponse:
    now   = datetime.now()
    mois  = now.month
    annee = now.year

    hotels = (await session.execute(
        select(Hotel)
        .where(Hotel.id_partenaire == id_partenaire)
        .order_by(Hotel.nom.asc())
    )).scalars().all()

    deja_verse_total = await _montant_deja_verse(id_partenaire, session)
    # Répartit le montant versé proportionnellement — simplification :
    # le solde restant global est réparti à l'affichage par hôtel via son poids

    # D'abord calcul du revenu total du partenaire pour la pondération
    chambre_ids_all = await _get_chambre_ids_partenaire(id_partenaire, session)
    rev_total_global = (
        await _revenu_clients(session, chambre_ids_all)
        + await _revenu_visiteurs(session, chambre_ids_all)
    )
    part_totale_global = round(rev_total_global * _PART_PARTENAIRE, 2)
    solde_global       = max(0.0, round(part_totale_global - deja_verse_total, 2))

    items = []
    for hotel in hotels:
        chambre_ids = await _get_chambre_ids_partenaire(
            id_partenaire, session, id_hotel=hotel.id
        )

        f_mois_c = and_(
            extract("month", Reservation.date_reservation) == mois,
            extract("year",  Reservation.date_reservation) == annee,
        )
        f_mois_v = and_(
            extract("month", ReservationVisiteur.created_at) == mois,
            extract("year",  ReservationVisiteur.created_at) == annee,
        )

        rev_mois  = (
            await _revenu_clients(session, chambre_ids, f_mois_c)
            + await _revenu_visiteurs(session, chambre_ids, f_mois_v)
        )
        rev_total = (
            await _revenu_clients(session, chambre_ids)
            + await _revenu_visiteurs(session, chambre_ids)
        )
        nb_mois  = await _nb_resas(session, chambre_ids, f_mois_c, f_mois_v)
        nb_total = await _nb_resas(session, chambre_ids)

        # Solde de cet hôtel = sa proportion du solde global
        if rev_total_global > 0:
            poids         = rev_total / rev_total_global
            solde_hotel   = round(solde_global * poids, 2)
        else:
            solde_hotel   = 0.0

        items.append(PartHotelItem(
            id_hotel=hotel.id,
            hotel_nom=hotel.nom,
            hotel_ville=hotel.ville,
            hotel_actif=hotel.actif,
            revenu_mois=round(rev_mois, 2),
            revenu_total=round(rev_total, 2),
            nb_resas_mois=nb_mois,
            nb_resas_total=nb_total,
            solde_restant=solde_hotel,
        ))

    return PartHotelListResponse(items=items)


# ═══════════════════════════════════════════════════════════
#  RÉSERVATIONS D'UN HÔTEL (drill-down)
# ═══════════════════════════════════════════════════════════

async def get_reservations_hotel(
    id_partenaire: int,
    id_hotel: int,
    session: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    statut: Optional[str] = None,
    search: Optional[str] = None,
) -> PartReservationListResponse:
    """
    Retourne TOUTES les réservations (clients + visiteurs) d'un hôtel,
    en vérifiant que l'hôtel appartient bien au partenaire connecté.
    """
    # ── Vérification sécurité : l'hôtel appartient au partenaire ──
    hotel = (await session.execute(
        select(Hotel).where(
            Hotel.id == id_hotel,
            Hotel.id_partenaire == id_partenaire,
        )
    )).scalar_one_or_none()

    if hotel is None:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Hôtel introuvable ou accès non autorisé")

    chambre_ids = await _get_chambre_ids_partenaire(
        id_partenaire, session, id_hotel=id_hotel
    )

    items: list[PartReservationItem] = []

    # ── 1. Réservations CLIENTS ──────────────────────────────────────
    if chambre_ids:
        q_c = (
            select(Reservation)
            .options(selectinload(Reservation.facture))
            .join(
                LigneReservationChambre,
                LigneReservationChambre.id_reservation == Reservation.id,
            )
            .where(
                LigneReservationChambre.id_chambre.in_(chambre_ids),
                Reservation.id_voyage.is_(None),
                Reservation.statut.in_(_STATUTS_VALIDES_CLIENT),
            )
            .distinct()
        )
        if statut:
            q_c = q_c.where(Reservation.statut == statut)
        if search:
            # Recherche sur le nom/email du client
            q_c = q_c.join(
                Utilisateur, Utilisateur.id == Reservation.id_client
            ).where(
                or_(
                    Utilisateur.nom.ilike(f"%{search}%"),
                    Utilisateur.prenom.ilike(f"%{search}%"),
                    Utilisateur.email.ilike(f"%{search}%"),
                )
            )

        resas_clients = (await session.execute(q_c)).scalars().all()

        for r in resas_clients:
            # Récupérer info client
            client = (await session.execute(
                select(Utilisateur).where(Utilisateur.id == r.id_client)
            )).scalar_one_or_none()
            client_nom   = f"{client.prenom} {client.nom}" if client else "Client"
            client_email = client.email if client else ""

            # Référence = numéro de facture si disponible
            reference = f"RES-{r.id}"
            if r.facture:
                reference = r.facture.numero

            # Statut paiement commission
            commission = (await session.execute(
                select(CommissionPartenaire).where(
                    CommissionPartenaire.id_reservation == r.id
                )
            )).scalar_one_or_none()
            statut_paiement = (
                commission.statut.value if commission
                else StatutCommission.EN_ATTENTE.value
            )

            nb_nuits = (r.date_fin - r.date_debut).days
            montant  = float(r.total_ttc)
            items.append(PartReservationItem(
                id=r.id,
                source="client",
                reference=reference,
                client_nom=client_nom,
                client_email=client_email,
                date_debut=r.date_debut,
                date_fin=r.date_fin,
                nb_nuits=nb_nuits,
                montant_total=montant,
                part_partenaire=round(montant * _PART_PARTENAIRE, 2),
                statut=r.statut.value if hasattr(r.statut, "value") else str(r.statut),
                statut_paiement=statut_paiement,
                date_reservation=r.date_reservation,
            ))

    # ── 2. Réservations VISITEURS ────────────────────────────────────
    if chambre_ids:
        q_v = (
            select(ReservationVisiteur)
            .options(selectinload(ReservationVisiteur.facture))
            .where(
                ReservationVisiteur.id_chambre.in_(chambre_ids),
                ReservationVisiteur.statut.in_(_STATUTS_VALIDES_VISITEUR),
            )
        )
        if statut:
            q_v = q_v.where(ReservationVisiteur.statut == statut)
        if search:
            q_v = q_v.where(
                or_(
                    ReservationVisiteur.nom.ilike(f"%{search}%"),
                    ReservationVisiteur.prenom.ilike(f"%{search}%"),
                    ReservationVisiteur.email.ilike(f"%{search}%"),
                )
            )

        resas_visiteurs = (await session.execute(q_v)).scalars().all()

        for v in resas_visiteurs:
            reference = v.numero_voucher
            if v.facture:
                reference = v.facture.numero

            # Les visiteurs n'ont pas de ligne dans commission_partenaire
            # → leur statut paiement est déterminé par le paiement global du partenaire
            # Pour simplifier : EN_ATTENTE sauf si un paiement partenaire couvre cette période
            # (logique identique à l'admin : visiteurs = toujours EN_ATTENTE jusqu'au prochain versement)
            statut_paiement = StatutCommission.EN_ATTENTE.value

            nb_nuits = (v.date_fin - v.date_debut).days
            montant  = float(v.total_ttc)
            items.append(PartReservationItem(
                id=v.id,
                source="visiteur",
                reference=reference,
                client_nom=f"{v.prenom} {v.nom}",
                client_email=v.email,
                date_debut=v.date_debut,
                date_fin=v.date_fin,
                nb_nuits=nb_nuits,
                montant_total=montant,
                part_partenaire=round(montant * _PART_PARTENAIRE, 2),
                statut=v.statut,
                statut_paiement=statut_paiement,
                date_reservation=v.created_at,
            ))

    # ── Tri par date décroissante ──
    items.sort(key=lambda x: x.date_reservation, reverse=True)

    # ── Pagination en mémoire ──
    total  = len(items)
    start  = (page - 1) * per_page
    end    = start + per_page
    paged  = items[start:end]

    return PartReservationListResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=paged,
    )


# ═══════════════════════════════════════════════════════════
#  PAIEMENTS REÇUS
# ═══════════════════════════════════════════════════════════

async def get_paiements_recus(
    id_partenaire: int,
    session: AsyncSession,
    page: int = 1,
    per_page: int = 20,
) -> PartPaiementsResponse:
    total_q = await session.execute(
        select(func.count())
        .where(PaiementPartenaire.id_partenaire == id_partenaire)
    )
    total = int(total_q.scalar_one())

    rows = (await session.execute(
        select(PaiementPartenaire)
        .where(PaiementPartenaire.id_partenaire == id_partenaire)
        .order_by(PaiementPartenaire.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    items = [
        PartPaiementItem(
            id=p.id,
            montant=float(p.montant),
            note=p.note,
            created_at=p.created_at,
        )
        for p in rows
    ]

    return PartPaiementsResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=items,
    )


# ═══════════════════════════════════════════════════════════
#  DEMANDE DE RETRAIT
#  Note : cette fonction crée un PaiementPartenaire avec note
#  "DEMANDE_RETRAIT — en attente de validation admin".
#  L'admin voit la demande dans son espace (onglet Soldes) et
#  peut ensuite valider via POST /finances/payer/{id}.
# ═══════════════════════════════════════════════════════════

async def demander_retrait(
    id_partenaire: int,
    body: PartDemandeRetraitRequest,
    session: AsyncSession,
) -> PartDemandeRetraitResponse:
    """
    Enregistre une demande de retrait comme un PaiementPartenaire
    avec montant = 0 et note indiquant le montant souhaité.
    L'admin traite ensuite la demande depuis son espace.

    Cette approche ne crée PAS un vrai paiement — elle alerte l'admin
    via la note. Le vrai paiement reste sous contrôle admin uniquement.
    """
    # ── Calcul du solde disponible ──
    chambre_ids = await _get_chambre_ids_partenaire(id_partenaire, session)
    rev_total = (
        await _revenu_clients(session, chambre_ids)
        + await _revenu_visiteurs(session, chambre_ids)
    )
    part_totale = round(rev_total * _PART_PARTENAIRE, 2)
    deja_verse  = await _montant_deja_verse(id_partenaire, session)
    solde_dispo = max(0.0, round(part_totale - deja_verse, 2))

    if body.montant <= 0:
        from fastapi import HTTPException
        raise HTTPException(400, "Le montant doit être supérieur à 0")

    if body.montant > solde_dispo:
        from fastapi import HTTPException
        raise HTTPException(
            400,
            f"Montant demandé ({body.montant} DT) supérieur au solde disponible ({solde_dispo} DT)",
        )

    # ── Créer la demande comme un PaiementPartenaire avec montant=0 ──
    # (montant=0 signifie "demande en attente" — l'admin voit la note)
    note_retrait = f"DEMANDE_RETRAIT:{body.montant}"
    if body.note:
        note_retrait += f" | {body.note}"

    demande = PaiementPartenaire(
        id_partenaire=id_partenaire,
        montant=0.0,          # 0 = pas encore versé, en attente admin
        note=note_retrait,
    )
    session.add(demande)
    await session.flush()

    return PartDemandeRetraitResponse(
        message="Demande de retrait envoyée à l'administrateur",
        montant_demande=body.montant,
        solde_disponible=solde_dispo,
    )