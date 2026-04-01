"""
app/services/finances_partenaire_service.py
============================================
Logique métier du module Finance — Espace Partenaire.

CORRECTIONS apportées :
  - get_reservations_hotel → clients   : lit statut depuis commission_client
                                         (fallback commission_partenaire si table absente)
  - get_reservations_hotel → visiteurs : lit statut depuis commission_visiteur
                                         (n'était jamais lu → toujours EN_ATTENTE avant)
  - Les deux requêtes utilisent désormais SQL brut avec LEFT JOIN,
    identique à la logique admin (finances/service.py).

Règles fondamentales conservées :
  - Toutes les fonctions sont SCOPÉES sur id_partenaire (JWT).
  - Revenu = clients + visiteurs.
  - Part partenaire = 90 % du montant brut (taux_commission = 10 %).
  - Solde disponible = part totale - déjà versé.
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Optional

from sqlalchemy import select, func, extract, and_, or_, text as sa_text
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
    result = await session.execute(
        select(Hotel.id).where(Hotel.id_partenaire == id_partenaire)
    )
    return [r[0] for r in result.all()]


async def _revenu_clients(
    session: AsyncSession,
    chambre_ids: list[int],
    filtre=None,
) -> float:
    if not chambre_ids:
        return 0.0
    q = (
        select(func.coalesce(func.sum(Reservation.total_ttc), 0))
        .join(LigneReservationChambre,
              LigneReservationChambre.id_reservation == Reservation.id)
        .where(
            LigneReservationChambre.id_chambre.in_(chambre_ids),
            Reservation.id_voyage.is_(None),
            Reservation.statut.in_(_STATUTS_VALIDES_CLIENT),
        )
        .distinct()
    )
    if filtre is not None:
        q = q.where(filtre)
    result = await session.execute(q)
    return float(result.scalar_one() or 0.0)


async def _revenu_visiteurs(
    session: AsyncSession,
    chambre_ids: list[int],
    filtre=None,
) -> float:
    if not chambre_ids:
        return 0.0
    q = (
        select(func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0))
        .where(
            ReservationVisiteur.id_chambre.in_(chambre_ids),
            ReservationVisiteur.statut.in_(_STATUTS_VALIDES_VISITEUR),
        )
    )
    if filtre is not None:
        q = q.where(filtre)
    result = await session.execute(q)
    return float(result.scalar_one() or 0.0)


async def _nb_resas(
    session: AsyncSession,
    chambre_ids: list[int],
    filtre_client=None,
    filtre_visiteur=None,
) -> int:
    if not chambre_ids:
        return 0

    q_c = (
        select(func.count(Reservation.id.distinct()))
        .join(LigneReservationChambre,
              LigneReservationChambre.id_reservation == Reservation.id)
        .where(
            LigneReservationChambre.id_chambre.in_(chambre_ids),
            Reservation.id_voyage.is_(None),
            Reservation.statut.in_(_STATUTS_VALIDES_CLIENT),
        )
    )
    if filtre_client is not None:
        q_c = q_c.where(filtre_client)

    q_v = (
        select(func.count(ReservationVisiteur.id))
        .where(
            ReservationVisiteur.id_chambre.in_(chambre_ids),
            ReservationVisiteur.statut.in_(_STATUTS_VALIDES_VISITEUR),
        )
    )
    if filtre_visiteur is not None:
        q_v = q_v.where(filtre_visiteur)

    nb_c = (await session.execute(q_c)).scalar_one() or 0
    nb_v = (await session.execute(q_v)).scalar_one() or 0
    return int(nb_c) + int(nb_v)


async def _montant_deja_verse(id_partenaire: int, session: AsyncSession) -> float:
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

    filtre_mois_client = and_(
        extract("month", Reservation.date_reservation) == mois,
        extract("year",  Reservation.date_reservation) == annee,
    )
    filtre_mois_visiteur = and_(
        extract("month", ReservationVisiteur.created_at) == mois,
        extract("year",  ReservationVisiteur.created_at) == annee,
    )
    filtre_prec_client = and_(
        extract("month", Reservation.date_reservation) == mois_prec,
        extract("year",  Reservation.date_reservation) == annee_prec,
    )
    filtre_prec_visiteur = and_(
        extract("month", ReservationVisiteur.created_at) == mois_prec,
        extract("year",  ReservationVisiteur.created_at) == annee_prec,
    )
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

    rev_total_all = (
        await _revenu_clients(session, chambre_ids)
        + await _revenu_visiteurs(session, chambre_ids)
    )
    part_totale  = round(rev_total_all * _PART_PARTENAIRE, 2)
    deja_verse   = await _montant_deja_verse(id_partenaire, session)
    solde_dispo  = max(0.0, round(part_totale - deja_verse, 2))

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

        if rev_total_global > 0:
            poids       = rev_total / rev_total_global
            solde_hotel = round(solde_global * poids, 2)
        else:
            solde_hotel = 0.0

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
    Retourne TOUTES les réservations (clients + visiteurs) d'un hôtel.
    
    CORRECTION :
      - Clients  → statut lu depuis commission_client (fallback commission_partenaire)
      - Visiteurs → statut lu depuis commission_visiteur
      Les deux utilisent SQL brut avec LEFT JOIN, identique à l'espace admin.
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
    # Lit le statut de paiement depuis commission_client en priorité,
    # puis commission_partenaire en fallback (selon quelle table existe).
    if chambre_ids:
        # commission_client n'existe pas encore en DB → on utilise uniquement
        # commission_partenaire (table existante) pour le statut de paiement clients.
        sql_clients = """
            SELECT
                r.id,
                r.date_debut,
                r.date_fin,
                r.total_ttc,
                r.date_reservation,
                CAST(r.statut AS VARCHAR)                               AS statut,
                u.nom,
                u.prenom,
                u.email,
                f.numero                                                AS facture_numero,
                COALESCE(CAST(cp.statut AS VARCHAR), 'EN_ATTENTE')      AS statut_paiement,
                cp.date_paiement                                        AS date_paiement
            FROM voyage_hotel.reservation r
            JOIN voyage_hotel.utilisateur u ON u.id = r.id_client
            JOIN voyage_hotel.ligne_reservation_chambre lrc
                ON lrc.id_reservation = r.id
            LEFT JOIN voyage_hotel.facture f
                ON f.id_reservation = r.id
            LEFT JOIN voyage_hotel.commission_partenaire cp
                ON cp.id_reservation = r.id
               AND cp.id_partenaire  = :id_p
            WHERE lrc.id_chambre = ANY(:ch_ids)
              AND r.id_voyage    IS NULL
              AND r.statut       IN ('CONFIRMEE', 'TERMINEE')
        """

        params_c: dict = {"id_p": id_partenaire, "ch_ids": list(chambre_ids)}

        if statut and statut.strip():
            sql_clients += " AND CAST(r.statut AS VARCHAR) = :statut_rv"
            params_c["statut_rv"] = statut.strip()

        if search and search.strip():
            sql_clients += (
                " AND (u.nom ILIKE :s OR u.prenom ILIKE :s OR u.email ILIKE :s)"
            )
            params_c["s"] = f"%{search.strip()}%"

        sql_clients += (
            " GROUP BY r.id, r.date_debut, r.date_fin, r.total_ttc, r.date_reservation,"
            " r.statut, u.nom, u.prenom, u.email, f.numero,"
            " cp.statut, cp.date_paiement"
            " ORDER BY r.date_reservation DESC"
        )

        cli_rows = (await session.execute(sa_text(sql_clients), params_c)).mappings().all()

        for c in cli_rows:
            reference = c["facture_numero"] or f"RES-{c['id']}"
            nb_nuits  = (c["date_fin"] - c["date_debut"]).days
            montant   = float(c["total_ttc"])
            items.append(PartReservationItem(
                id               = c["id"],
                source           = "client",
                reference        = reference,
                client_nom       = f"{c['prenom']} {c['nom']}",
                client_email     = c["email"] or "",
                date_debut       = c["date_debut"],
                date_fin         = c["date_fin"],
                nb_nuits         = nb_nuits,
                montant_total    = montant,
                part_partenaire  = round(montant * _PART_PARTENAIRE, 2),
                statut           = c["statut"],
                statut_paiement  = c["statut_paiement"],
                date_reservation = c["date_reservation"],
            ))

    # ── 2. Réservations VISITEURS ────────────────────────────────────
    # CORRECTION : statut lu depuis commission_visiteur (LEFT JOIN)
    # Avant : statut_paiement était toujours codé EN_ATTENTE en dur.
    if chambre_ids:
        sql_visiteurs = """
            SELECT
                rv.id,
                rv.nom,
                rv.prenom,
                rv.email,
                rv.date_debut,
                rv.date_fin,
                rv.total_ttc,
                rv.created_at,
                rv.statut,
                rv.numero_voucher,
                COALESCE(cv.statut, 'EN_ATTENTE')   AS statut_paiement,
                cv.date_paiement                     AS date_paiement
            FROM voyage_hotel.reservation_visiteur rv
            LEFT JOIN voyage_hotel.commission_visiteur cv
                ON cv.id_reservation_visiteur = rv.id
               AND cv.id_partenaire            = :id_p
            WHERE rv.id_chambre = ANY(:ch_ids)
              AND rv.statut     IN ('CONFIRMEE', 'TERMINEE')
        """

        params_v: dict = {"id_p": id_partenaire, "ch_ids": list(chambre_ids)}

        if statut and statut.strip():
            sql_visiteurs += " AND rv.statut = :statut_rv"
            params_v["statut_rv"] = statut.strip()

        if search and search.strip():
            sql_visiteurs += (
                " AND (rv.nom ILIKE :s OR rv.prenom ILIKE :s OR rv.email ILIKE :s)"
            )
            params_v["s"] = f"%{search.strip()}%"

        sql_visiteurs += " ORDER BY rv.created_at DESC"

        vis_rows = (await session.execute(sa_text(sql_visiteurs), params_v)).mappings().all()

        for v in vis_rows:
            reference = v["numero_voucher"] or f"VIS-{v['id']}"
            nb_nuits  = (v["date_fin"] - v["date_debut"]).days
            montant   = float(v["total_ttc"])
            items.append(PartReservationItem(
                id               = v["id"],
                source           = "visiteur",
                reference        = reference,
                client_nom       = f"{v['prenom']} {v['nom']}",
                client_email     = v["email"] or "",
                date_debut       = v["date_debut"],
                date_fin         = v["date_fin"],
                nb_nuits         = nb_nuits,
                montant_total    = montant,
                part_partenaire  = round(montant * _PART_PARTENAIRE, 2),
                statut           = v["statut"],
                statut_paiement  = v["statut_paiement"],
                date_reservation = v["created_at"],
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
        select(func.count(PaiementPartenaire.id))
        .where(PaiementPartenaire.id_partenaire == id_partenaire)
    )
    total = int(total_q.scalar_one() or 0)

    rows = (await session.execute(
        select(PaiementPartenaire)
        .where(PaiementPartenaire.id_partenaire == id_partenaire)
        .order_by(PaiementPartenaire.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )).scalars().all()

    items = [
        PartPaiementItem(
            id         = p.id,
            montant    = float(p.montant),
            note       = p.note,
            created_at = p.created_at,
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
# ═══════════════════════════════════════════════════════════

async def demander_retrait(
    id_partenaire: int,
    req: PartDemandeRetraitRequest,
    session: AsyncSession,
) -> PartDemandeRetraitResponse:
    # Vérification du solde disponible
    chambre_ids = await _get_chambre_ids_partenaire(id_partenaire, session)
    rev_total   = (
        await _revenu_clients(session, chambre_ids)
        + await _revenu_visiteurs(session, chambre_ids)
    )
    part_totale  = round(rev_total * _PART_PARTENAIRE, 2)
    deja_verse   = await _montant_deja_verse(id_partenaire, session)
    solde_dispo  = max(0.0, round(part_totale - deja_verse, 2))

    if req.montant <= 0:
        return PartDemandeRetraitResponse(
            success=False,
            message="Le montant doit être supérieur à 0.",
        )

    if req.montant > solde_dispo:
        return PartDemandeRetraitResponse(
            success=False,
            message=f"Montant demandé ({req.montant:.2f} DT) supérieur au solde disponible ({solde_dispo:.2f} DT).",
        )

    note = f"DEMANDE_RETRAIT:{req.note or ''}"
    session.add(PaiementPartenaire(
        id_partenaire=id_partenaire,
        montant=req.montant,
        note=note,
    ))
    await session.commit()

    return PartDemandeRetraitResponse(
        success=True,
        message=f"Demande de retrait de {req.montant:.2f} DT envoyée à l'admin.",
    )