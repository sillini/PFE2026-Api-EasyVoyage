"""
app/services/finances/repository.py
=====================================
Couche d'accès aux données — toutes les requêtes SQLAlchemy sont ici.

PRINCIPE FONDAMENTAL — DEUX SOURCES OBLIGATOIRES :
  Chaque agrégation financière interroge TOUJOURS les deux tables :
    • reservation          → réservations des clients enregistrés
    • reservation_visiteur → réservations des visiteurs (sans compte)

  Il n'existe AUCUNE fonction dans ce fichier qui n'interroge qu'une seule
  des deux sources. Toute nouvelle fonction doit respecter cette règle.

SÉPARATION HÔTEL / VOYAGE :
  • reservation_visiteur est 100% hôtel (pas de voyage visiteur possible).
  • Dans reservation, id_voyage IS NULL → hôtel, IS NOT NULL → voyage.
  • Commission et part partenaire ne concernent QUE les hôtels.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import select, func, case, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finances import CommissionPartenaire, PaiementPartenaire
from app.models.reservation import (
    Reservation, ReservationVisiteur, StatutReservation, LigneReservationChambre,
)
from app.models.utilisateur import Utilisateur

_STATUTS_CLIENT   = [StatutReservation.CONFIRMEE, StatutReservation.TERMINEE]
_STATUTS_VISITEUR = ["CONFIRMEE", "TERMINEE"]


# ═══════════════════════════════════════════════════════════
#  BLOC 1 — REVENUS BRUTS (clients + visiteurs)
# ═══════════════════════════════════════════════════════════

async def fetch_revenus_bruts(
    session: AsyncSession,
    filtre_client,
    filtre_visiteur,
) -> tuple[float, float, int]:
    """
    Retourne (revenu_hotel, revenu_voyage, nb_total).

    revenu_hotel  = hôtels clients (id_voyage IS NULL) + TOUS les visiteurs
    revenu_voyage = voyages clients uniquement (id_voyage IS NOT NULL)
    """
    r_c = await session.execute(
        select(
            func.coalesce(
                func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0
            ).label("hotel"),
            func.coalesce(
                func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)), 0
            ).label("voyage"),
            func.count(Reservation.id).label("nb"),
        ).where(Reservation.statut.in_(_STATUTS_CLIENT), filtre_client)
    )
    row_c = r_c.one()

    r_v = await session.execute(
        select(
            func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0).label("hotel"),
            func.count(ReservationVisiteur.id).label("nb"),
        ).where(ReservationVisiteur.statut.in_(_STATUTS_VISITEUR), filtre_visiteur)
    )
    row_v = r_v.one()

    return (
        float(row_c.hotel) + float(row_v.hotel),
        float(row_c.voyage),
        int(row_c.nb) + int(row_v.nb),
    )


# ═══════════════════════════════════════════════════════════
#  BLOC 2 — REVENUS HÔTEL PAR CHAMBRES (clients + visiteurs)
#  Utilisé pour le drill-down hôtel/partenaire
# ═══════════════════════════════════════════════════════════

async def fetch_revenu_hotel_par_chambres(
    session: AsyncSession,
    chambre_ids: list[int],
) -> tuple[float, int]:
    """
    Revenu hôtel pour un ensemble de chambres — les DEUX sources.
    Retourne (revenu_hotel, nb_reservations).
    """
    if not chambre_ids:
        return 0.0, 0

    # Clients via LigneReservationChambre (hôtel uniquement = id_voyage IS NULL)
    r_c = await session.execute(
        select(
            func.coalesce(func.sum(Reservation.total_ttc), 0).label("revenu"),
            func.count(Reservation.id.distinct()).label("nb"),
        )
        .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
        .where(
            LigneReservationChambre.id_chambre.in_(chambre_ids),
            Reservation.statut.in_(_STATUTS_CLIENT),
            Reservation.id_voyage == None,
        )
    )
    row_c = r_c.one()

    # Visiteurs via id_chambre direct (toujours hôtel)
    r_v = await session.execute(
        select(
            func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0).label("revenu"),
            func.count(ReservationVisiteur.id).label("nb"),
        ).where(
            ReservationVisiteur.id_chambre.in_(chambre_ids),
            ReservationVisiteur.statut.in_(_STATUTS_VISITEUR),
        )
    )
    row_v = r_v.one()

    return (
        float(row_c.revenu) + float(row_v.revenu),
        int(row_c.nb) + int(row_v.nb),
    )


async def fetch_montant_paye_partenaire(
    session: AsyncSession,
    id_partenaire: int,
) -> float:
    """Total déjà payé à un partenaire (depuis l'historique des paiements)."""
    r = await session.execute(
        select(func.coalesce(func.sum(PaiementPartenaire.montant), 0))
        .where(PaiementPartenaire.id_partenaire == id_partenaire)
    )
    return float(r.scalar_one() or 0)


async def fetch_montant_paye_par_hotel(
    session: AsyncSession,
    id_partenaire: int,
    chambre_ids: list[int],
    revenu_hotel_hotel: float = 0.0,
    revenu_hotel_total: float = 0.0,
) -> float:
    """
    Montant payé pour un hôtel précis — lecture directe des tables de commission.

    clients  : commission_partenaire PAYEE liées aux chambres de cet hôtel
    visiteurs: commission_visiteur   PAYEE liées aux chambres de cet hôtel
               (auto-peuplée par le trigger trg_commission_visiteur_auto)

    0 approximation — 0 ventilation — résultat exact par hôtel.
    """
    from sqlalchemy import text as sa_text

    if not chambre_ids:
        return 0.0

    # ── Clients : commission_partenaire PAYEE ─────────────────────────
    resa_ids = await fetch_reservation_ids_clients(session, chambre_ids)
    paye_clients = 0.0
    if resa_ids:
        r = await session.execute(
            select(func.coalesce(func.sum(CommissionPartenaire.montant_partenaire), 0))
            .where(
                CommissionPartenaire.id_partenaire == id_partenaire,
                CommissionPartenaire.id_reservation.in_(resa_ids),
                cast(CommissionPartenaire.statut, String) == "PAYEE",
            )
        )
        paye_clients = float(r.scalar_one() or 0)

    # ── Visiteurs : commission_visiteur PAYEE ─────────────────────────
    r_vis = await session.execute(
        sa_text("""
            SELECT COALESCE(SUM(cv.montant_partenaire), 0)
            FROM voyage_hotel.commission_visiteur cv
            JOIN voyage_hotel.reservation_visiteur rv
              ON rv.id = cv.id_reservation_visiteur
            WHERE rv.id_chambre = ANY(:ch_ids)
              AND cv.id_partenaire = :id_p
              AND cv.statut = 'PAYEE'
        """),
        {"ch_ids": list(chambre_ids), "id_p": id_partenaire}
    )
    paye_visiteurs = float(r_vis.scalar_one() or 0)

    return round(paye_clients + paye_visiteurs, 2)


# ═══════════════════════════════════════════════════════════
#  BLOC 3 — TOTAUX GLOBAUX COMMISSIONS
# ═══════════════════════════════════════════════════════════

async def fetch_commission_totaux_globaux(session: AsyncSession) -> int:
    """
    Retourne uniquement nb_partenaires_en_attente depuis commission_partenaire.
    total_part et total_du sont calculés dans le service depuis les revenus réels
    (clients + visiteurs) via fetch_totaux_part_partenaires_depuis_revenus.
    """
    r = await session.execute(
        select(
            func.count(CommissionPartenaire.id_partenaire.distinct()).filter(
                cast(CommissionPartenaire.statut, String) == "EN_ATTENTE"
            ).label("nb_en_attente"),
        )
    )
    row = r.one()
    return int(row.nb_en_attente)


async def fetch_total_paye_tous_partenaires(session: AsyncSession) -> float:
    """
    Somme de tous les paiements déjà effectués à tous les partenaires.
    Source : paiement_partenaire (historique réel des virements).
    """
    r = await session.execute(
        select(func.coalesce(func.sum(PaiementPartenaire.montant), 0))
    )
    return float(r.scalar_one() or 0)


async def fetch_revenu_hotel_tous_partenaires(
    session: AsyncSession,
    filtre_client=None,
    filtre_visiteur=None,
) -> float:
    """
    Revenu hôtel total sur TOUS les partenaires (clients + visiteurs).
    Utilisé pour calculer total_part et total_du dans le dashboard.
    Si aucun filtre n'est passé, agrège tout (toutes périodes).
    """
    # Clients hôtels
    q_c = select(
        func.coalesce(
            func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0
        ).label("hotel")
    ).where(Reservation.statut.in_(_STATUTS_CLIENT))
    if filtre_client is not None:
        q_c = q_c.where(filtre_client)
    row_c = (await session.execute(q_c)).one()

    # Visiteurs (toujours hôtel)
    q_v = select(
        func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0).label("hotel")
    ).where(ReservationVisiteur.statut.in_(_STATUTS_VISITEUR))
    if filtre_visiteur is not None:
        q_v = q_v.where(filtre_visiteur)
    row_v = (await session.execute(q_v)).one()

    return float(row_c.hotel) + float(row_v.hotel)


# ═══════════════════════════════════════════════════════════
#  BLOC 4 — SOLDES ET PAIEMENTS
# ═══════════════════════════════════════════════════════════

async def fetch_soldes_partenaires(session: AsyncSession) -> list[dict]:
    """Partenaires avec solde EN_ATTENTE > 0."""
    r = await session.execute(
        select(
            CommissionPartenaire.id_partenaire,
            func.sum(CommissionPartenaire.montant_partenaire).label("solde_du"),
            func.count(CommissionPartenaire.id).label("nb_commissions"),
        )
        .where(cast(CommissionPartenaire.statut, String) == "EN_ATTENTE")
        .group_by(CommissionPartenaire.id_partenaire)
        .order_by(func.sum(CommissionPartenaire.montant_partenaire).desc())
    )
    return [
        {
            "id_partenaire":  row.id_partenaire,
            "solde_du":       float(row.solde_du),
            "nb_commissions": int(row.nb_commissions),
        }
        for row in r.all()
    ]


async def fetch_paiements_historique(
    session: AsyncSession,
    id_partenaire: Optional[int],
    date_debut: Optional[date],
    date_fin: Optional[date],
    montant_min: Optional[float],
    montant_max: Optional[float],
    search: Optional[str],
    page: int,
    per_page: int,
) -> tuple[list, int]:
    """
    Historique des paiements avec filtres complets côté SQL.

    Filtres disponibles :
      - id_partenaire  : partenaire précis
      - date_debut/fin : intervalle de dates
      - montant_min/max: fourchette de montant payé
      - search         : recherche textuelle sur nom, prénom, email,
                         nom_entreprise (Partenaire) et note (PaiementPartenaire)
    """
    from app.models.utilisateur import Partenaire as PartenaireModel

    # Jointure obligatoire pour la recherche sur nom/email/entreprise
    q = (
        select(PaiementPartenaire)
        .join(Utilisateur, Utilisateur.id == PaiementPartenaire.id_partenaire)
        .join(PartenaireModel, PartenaireModel.id == Utilisateur.id)
    )

    if id_partenaire:
        q = q.where(PaiementPartenaire.id_partenaire == id_partenaire)
    if date_debut:
        q = q.where(func.date(PaiementPartenaire.created_at) >= date_debut)
    if date_fin:
        q = q.where(func.date(PaiementPartenaire.created_at) <= date_fin)
    if montant_min is not None:
        q = q.where(PaiementPartenaire.montant >= montant_min)
    if montant_max is not None:
        q = q.where(PaiementPartenaire.montant <= montant_max)
    if search:
        t = f"%{search}%"
        q = q.where(
            Utilisateur.nom.ilike(t)
            | Utilisateur.prenom.ilike(t)
            | Utilisateur.email.ilike(t)
            | PartenaireModel.nom_entreprise.ilike(t)
            | PaiementPartenaire.note.ilike(t)
        )

    total = (await session.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar_one()

    rows = (await session.execute(
        q.order_by(PaiementPartenaire.created_at.desc())
         .offset((page - 1) * per_page)
         .limit(per_page)
    )).scalars().all()

    return rows, total


# ═══════════════════════════════════════════════════════════
#  BLOC 5 — IDS RÉSERVATIONS CLIENTS PAR CHAMBRES
# ═══════════════════════════════════════════════════════════

async def fetch_reservation_ids_clients(
    session: AsyncSession,
    chambre_ids: list[int],
) -> list[int]:
    """
    IDs des réservations clients confirmées/terminées pour des chambres données.
    Sert uniquement pour les lookups dans commission_partenaire.
    (Les visiteurs ne sont pas dans commission_partenaire.)
    """
    if not chambre_ids:
        return []
    r = await session.execute(
        select(Reservation.id)
        .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
        .where(
            LigneReservationChambre.id_chambre.in_(chambre_ids),
            Reservation.statut.in_(_STATUTS_CLIENT),
        )
    )
    return [row[0] for row in r.all()]


# ═══════════════════════════════════════════════════════════
#  BLOC 6 — PARTENAIRES PAGINÉS
# ═══════════════════════════════════════════════════════════

async def fetch_partenaires_pagines(
    session: AsyncSession,
    page: int,
    per_page: int,
    search: Optional[str],
) -> tuple[list, int]:
    """
    Retourne (rows, total) où chaque row est (Utilisateur, Partenaire).
    Jointure obligatoire : nom_entreprise et commission sont sur partenaire.
    """
    from app.models.utilisateur import RoleUtilisateur, Partenaire

    base_where = [Utilisateur.role == RoleUtilisateur.PARTENAIRE]
    search_where = []
    if search:
        t = f"%{search}%"
        search_where = [
            Utilisateur.nom.ilike(t)
            | Utilisateur.prenom.ilike(t)
            | Utilisateur.email.ilike(t)
            | Partenaire.nom_entreprise.ilike(t)
        ]
    all_where = base_where + search_where

    total = (await session.execute(
        select(func.count(Utilisateur.id))
        .join(Partenaire, Partenaire.id == Utilisateur.id)
        .where(*all_where)
    )).scalar_one()

    rows = (await session.execute(
        select(Utilisateur, Partenaire)
        .join(Partenaire, Partenaire.id == Utilisateur.id)
        .where(*all_where)
        .order_by(Utilisateur.nom)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).all()

    return rows, total


# ═══════════════════════════════════════════════════════════
#  BLOC 7 — DÉTAIL RÉSERVATIONS PAR HÔTEL (commission_partenaire)
# ═══════════════════════════════════════════════════════════

async def fetch_commissions_pour_hotel(
    session: AsyncSession,
    id_partenaire: int,
    chambre_ids: list[int],
    statut_commission: Optional[str],
    page: int,
    per_page: int,
) -> tuple[list, int]:
    """
    Lignes de commission_partenaire pour l'affichage détaillé d'un hôtel.
    Note : ne couvre que les réservations clients (pas les visiteurs,
    qui ne génèrent pas encore de ligne dans commission_partenaire).
    """
    if not chambre_ids:
        return [], 0

    resa_ids = await fetch_reservation_ids_clients(session, chambre_ids)
    if not resa_ids:
        return [], 0

    from sqlalchemy.orm import selectinload

    q = (
        select(CommissionPartenaire)
        .where(
            CommissionPartenaire.id_partenaire == id_partenaire,
            CommissionPartenaire.id_reservation.in_(resa_ids),
        )
        .options(selectinload(CommissionPartenaire.reservation))
    )
    if statut_commission:
        q = q.where(cast(CommissionPartenaire.statut, String) == statut_commission)

    total = (await session.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar_one()

    rows = (await session.execute(
        q.order_by(CommissionPartenaire.date_creation.desc())
         .offset((page - 1) * per_page)
         .limit(per_page)
    )).scalars().all()

    return rows, total


# ═══════════════════════════════════════════════════════════
#  BLOC 8 — STATS CLIENTS ET VISITEURS
# ═══════════════════════════════════════════════════════════

async def fetch_stats_clients(session: AsyncSession) -> list:
    """
    Agrégats par client : total_depenses, depenses_hotel,
    nb_reservations, nb_hotel, nb_voyage.
    """
    r = await session.execute(
        select(
            Utilisateur.id,
            Utilisateur.nom,
            Utilisateur.prenom,
            Utilisateur.email,
            func.coalesce(func.sum(Reservation.total_ttc), 0).label("total_depenses"),
            func.coalesce(
                func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0
            ).label("depenses_hotel"),
            func.count(Reservation.id).label("nb_reservations"),
            func.coalesce(
                func.sum(case((Reservation.id_voyage == None, 1), else_=0)), 0
            ).label("nb_hotel"),
            func.coalesce(
                func.sum(case((Reservation.id_voyage != None, 1), else_=0)), 0
            ).label("nb_voyage"),
        )
        .join(Reservation, Reservation.id_client == Utilisateur.id)
        .where(Reservation.statut.in_(_STATUTS_CLIENT))
        .group_by(Utilisateur.id)
    )
    return r.all()


async def fetch_stats_visiteurs(session: AsyncSession) -> list:
    """
    Agrégats par visiteur (email + nom + prenom) :
    total_depenses, nb_hotel.
    Les visiteurs n'ont que des réservations hôtel.
    """
    r = await session.execute(
        select(
            ReservationVisiteur.email,
            ReservationVisiteur.nom,
            ReservationVisiteur.prenom,
            func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0).label("total_depenses"),
            func.count(ReservationVisiteur.id).label("nb_hotel"),
        )
        .where(ReservationVisiteur.statut.in_(_STATUTS_VISITEUR))
        .group_by(
            ReservationVisiteur.email,
            ReservationVisiteur.nom,
            ReservationVisiteur.prenom,
        )
    )
    return r.all()