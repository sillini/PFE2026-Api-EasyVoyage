"""
app/services/finances/service.py
=================================
Couche service — orchestre repository + utils.

RÈGLES MÉTIER (appliquées ici, jamais dans repository ni endpoint) :
  1. commission_agence = TAUX % × revenu_hotel  (JAMAIS sur revenu_voyage)
  2. part_partenaire   = revenu_hotel − commission_agence
  3. solde_a_payer     = part calculée sur tout le revenu hôtel − montant_deja_paye
  4. Toutes les agrégations incluent systématiquement clients ET visiteurs.

COHÉRENCE DES CALCULS PARTENAIRE :
  Les agrégats financiers (revenu, commission, part, solde) sont calculés
  directement depuis les tables de réservations (clients + visiteurs) via
  fetch_revenu_hotel_par_chambres, et non depuis commission_partenaire qui
  ne couvre que les clients. commission_partenaire est utilisée uniquement
  pour l'historique de paiement et le détail par réservation.
"""
from __future__ import annotations

from datetime import datetime, date
from calendar import monthrange
from typing import Optional, List

from sqlalchemy import select, cast, String, func, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finances import CommissionPartenaire, PaiementPartenaire, StatutCommission
from app.models.reservation import Reservation, ReservationVisiteur
from app.models.utilisateur import Utilisateur

from app.schemas.finances import (
    FinanceDashboard,
    RevenuPeriode, RevenusResponse,
    CommissionItem, CommissionListResponse,
    SoldePartenaire, SoldesPartenairesResponse,
    PayerPartenaireResponse,
    PaiementHistoriqueItem, PaiementHistoriqueResponse,
    PartenaireFinanceDetail, PartenaireFinanceListResponse,
    HotelFinanceDetail, HotelFinanceListResponse,
    ReservationFinanceItem, ReservationFinanceListResponse,
    ClientsVisiteursRentabiliteResponse, ClientVisiteurItem,
)

from app.services.finances.repository import (
    fetch_revenus_bruts,
    fetch_revenu_hotel_par_chambres,
    fetch_montant_paye_partenaire,
    fetch_montant_paye_par_hotel,
    fetch_commission_totaux_globaux,
    fetch_total_paye_tous_partenaires,
    fetch_revenu_hotel_tous_partenaires,
    fetch_paiements_historique,
    fetch_reservation_ids_clients,
    fetch_partenaires_pagines,
    fetch_commissions_pour_hotel,
    fetch_stats_clients,
    fetch_stats_visiteurs,
)
from app.services.finances.utils import (
    calc_commission_agence,
    calc_part_partenaire,
    calc_solde_restant,
    TAUX_COMMISSION_DEFAULT,
)

_MOIS_NOMS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun",
              "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]


# ═══════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════

async def get_dashboard(session: AsyncSession) -> FinanceDashboard:
    from sqlalchemy import extract, and_
    now   = datetime.now()
    mois  = now.month
    annee = now.year

    rev_hotel_mois, rev_voyage_mois, nb_mois = await fetch_revenus_bruts(
        session,
        filtre_client=and_(
            extract("month", Reservation.date_reservation) == mois,
            extract("year",  Reservation.date_reservation) == annee,
        ),
        filtre_visiteur=and_(
            extract("month", ReservationVisiteur.created_at) == mois,
            extract("year",  ReservationVisiteur.created_at) == annee,
        ),
    )

    rev_hotel_annee, rev_voyage_annee, nb_annee = await fetch_revenus_bruts(
        session,
        filtre_client=extract("year", Reservation.date_reservation) == annee,
        filtre_visiteur=extract("year", ReservationVisiteur.created_at) == annee,
    )

    # Commission UNIQUEMENT sur revenu hôtel
    comm_mois  = calc_commission_agence(rev_hotel_mois)
    comm_annee = calc_commission_agence(rev_hotel_annee)

    nb_en_attente = await fetch_commission_totaux_globaux(session)

    # ── Totaux part partenaires calculés depuis revenus réels (clients + visiteurs) ──
    # rev_hotel_annee déjà calculé ci-dessus (clients + visiteurs de l'année courante)
    # Pour total_part et total_du, on a besoin de TOUTES les périodes confondues.
    rev_hotel_global   = await fetch_revenu_hotel_tous_partenaires(session)
    total_paye_global  = await fetch_total_paye_tous_partenaires(session)

    total_part = calc_part_partenaire(rev_hotel_global)   # 90% du revenu hôtel total
    total_du   = calc_solde_restant(total_part, total_paye_global)

    return FinanceDashboard(
        revenu_total_mois         = round(rev_hotel_mois  + rev_voyage_mois,  2),
        revenu_total_annee        = round(rev_hotel_annee + rev_voyage_annee, 2),
        revenu_hotel_annee        = round(rev_hotel_annee, 2),
        revenu_voyage_annee       = round(rev_voyage_annee, 2),
        commission_mois           = comm_mois,
        commission_annee          = comm_annee,
        nb_reservations_mois      = nb_mois,
        nb_reservations_annee     = nb_annee,
        total_part_partenaires    = round(total_part, 2),
        total_du_partenaires      = round(total_du,   2),
        nb_partenaires_en_attente = nb_en_attente,
        total_commissions_agence  = comm_annee,
    )


# ═══════════════════════════════════════════════════════════
#  REVENUS PAR PÉRIODE
# ═══════════════════════════════════════════════════════════

async def get_revenus(
    session: AsyncSession,
    periode: str = "mois",
    annee: Optional[int] = None,
    mois: Optional[int] = None,
) -> RevenusResponse:
    from sqlalchemy import extract, and_
    now   = datetime.now()
    annee = annee or now.year
    mois  = mois  or now.month
    evolution: List[RevenuPeriode] = []

    if periode == "jour":
        for jour in range(1, monthrange(annee, mois)[1] + 1):
            d = date(annee, mois, jour)
            rh, rv, nb = await fetch_revenus_bruts(
                session,
                filtre_client=func.date(Reservation.date_reservation) == d,
                filtre_visiteur=func.date(ReservationVisiteur.created_at) == d,
            )
            evolution.append(_build_revenu_periode(d.strftime("%d/%m"), rh, rv, nb))

    elif periode == "mois":
        for m in range(1, 13):
            rh, rv, nb = await fetch_revenus_bruts(
                session,
                filtre_client=and_(
                    extract("month", Reservation.date_reservation) == m,
                    extract("year",  Reservation.date_reservation) == annee,
                ),
                filtre_visiteur=and_(
                    extract("month", ReservationVisiteur.created_at) == m,
                    extract("year",  ReservationVisiteur.created_at) == annee,
                ),
            )
            evolution.append(_build_revenu_periode(_MOIS_NOMS[m - 1], rh, rv, nb))

    else:  # annee
        for a in range(now.year - 4, now.year + 1):
            rh, rv, nb = await fetch_revenus_bruts(
                session,
                filtre_client=extract("year", Reservation.date_reservation) == a,
                filtre_visiteur=extract("year", ReservationVisiteur.created_at) == a,
            )
            evolution.append(_build_revenu_periode(str(a), rh, rv, nb))

    total_hotel  = round(sum(p.revenu_hotel  for p in evolution), 2)
    total_voyage = round(sum(p.revenu_voyage for p in evolution), 2)

    return RevenusResponse(
        periode          = periode,
        revenu_hotel     = total_hotel,
        revenu_voyage    = total_voyage,
        revenu_total     = round(total_hotel + total_voyage, 2),
        commission_total = calc_commission_agence(total_hotel),  # sur hôtels uniquement
        nb_reservations  = sum(p.nb_reservations for p in evolution),
        evolution        = evolution,
    )


def _build_revenu_periode(label: str, rh: float, rv: float, nb: int) -> RevenuPeriode:
    return RevenuPeriode(
        periode          = label,
        revenu_hotel     = round(rh, 2),
        revenu_voyage    = round(rv, 2),
        revenu_total     = round(rh + rv, 2),
        commission_total = calc_commission_agence(rh),  # sur hôtel uniquement
        nb_reservations  = nb,
    )


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN PARTENAIRES
# ═══════════════════════════════════════════════════════════

async def get_partenaires_finances(
    session: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
) -> PartenaireFinanceListResponse:
    from app.models.hotel import Hotel, Chambre

    rows, total = await fetch_partenaires_pagines(session, page, per_page, search)

    items = []
    for row in rows:
        usr  = row[0]   # Utilisateur
        part = row[1]   # Partenaire (nom_entreprise, commission taux)

        # Récupérer toutes les chambres de tous les hôtels de ce partenaire
        hotels_res = await session.execute(
            select(Hotel.id).where(Hotel.id_partenaire == usr.id)
        )
        hotel_ids = [r[0] for r in hotels_res.all()]

        if hotel_ids:
            ch_res = await session.execute(
                select(Chambre.id).where(Chambre.id_hotel.in_(hotel_ids))
            )
            chambre_ids = [r[0] for r in ch_res.all()]
        else:
            chambre_ids = []

        # Revenu hôtel = clients + visiteurs sur toutes ses chambres
        revenu_hotel, nb_resas = await fetch_revenu_hotel_par_chambres(session, chambre_ids)
        taux = float(part.commission) if part.commission else TAUX_COMMISSION_DEFAULT

        commission = calc_commission_agence(revenu_hotel, taux)
        part_rev   = calc_part_partenaire(revenu_hotel, taux)
        paye       = await fetch_montant_paye_partenaire(session, usr.id)
        solde      = calc_solde_restant(part_rev, paye)

        items.append(PartenaireFinanceDetail(
            id_partenaire     = usr.id,
            partenaire_nom    = usr.nom    or "—",
            partenaire_prenom = usr.prenom or "—",
            partenaire_email  = usr.email  or "—",
            nom_entreprise    = part.nom_entreprise or "—",
            commission_taux   = taux,
            revenu_total      = round(revenu_hotel, 2),
            commission_agence = commission,
            part_partenaire   = part_rev,
            montant_paye      = round(paye, 2),
            solde_restant     = solde,
            nb_reservations   = nb_resas,
        ))

    return PartenaireFinanceListResponse(
        total=total, page=page, per_page=per_page, items=items
    )


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN HÔTELS D'UN PARTENAIRE
# ═══════════════════════════════════════════════════════════

async def get_hotels_finances_partenaire(
    id_partenaire: int,
    session: AsyncSession,
) -> HotelFinanceListResponse:
    from app.models.hotel import Hotel, Chambre
    from app.models.utilisateur import Partenaire as PartenaireModel

    hotels_res = await session.execute(
        select(Hotel).where(Hotel.id_partenaire == id_partenaire)
    )
    hotels = hotels_res.scalars().all()

    # Taux de commission du partenaire
    part_res = await session.execute(
        select(PartenaireModel).where(PartenaireModel.id == id_partenaire)
    )
    part = part_res.scalar_one_or_none()
    taux = float(part.commission) if part and part.commission else TAUX_COMMISSION_DEFAULT

    # ── Pré-calcul : revenu total du partenaire (tous hôtels) pour la ventilation ──
    all_hotel_ids = [h.id for h in hotels]
    revenu_total_partenaire = 0.0
    if all_hotel_ids:
        all_ch = [r[0] for r in (await session.execute(
            select(Chambre.id).where(Chambre.id_hotel.in_(all_hotel_ids))
        )).all()]
        revenu_total_partenaire, _ = await fetch_revenu_hotel_par_chambres(session, all_ch)

    items = []
    for hotel in hotels:
        ch_res = await session.execute(
            select(Chambre.id).where(Chambre.id_hotel == hotel.id)
        )
        chambre_ids = [r[0] for r in ch_res.all()]

        if not chambre_ids:
            items.append(_empty_hotel_detail(hotel))
            continue

        # Revenu hôtel = clients + visiteurs
        revenu_hotel, nb_resas = await fetch_revenu_hotel_par_chambres(session, chambre_ids)

        commission = calc_commission_agence(revenu_hotel, taux)
        part_rev   = calc_part_partenaire(revenu_hotel, taux)

        # Montant payé ventilé : clients exacts + visiteurs proportionnels
        paye  = await fetch_montant_paye_par_hotel(
            session, id_partenaire, chambre_ids,
            revenu_hotel_hotel=revenu_hotel,
            revenu_hotel_total=revenu_total_partenaire,
        )
        solde = calc_solde_restant(part_rev, paye)

        items.append(HotelFinanceDetail(
            id_hotel          = hotel.id,
            hotel_nom         = hotel.nom,
            hotel_ville       = hotel.ville or "—",
            revenu_total      = round(revenu_hotel, 2),
            commission_agence = commission,
            part_partenaire   = part_rev,
            montant_paye      = round(paye, 2),
            solde_restant     = solde,
            nb_reservations   = nb_resas,
        ))

    return HotelFinanceListResponse(items=items)


def _empty_hotel_detail(hotel) -> HotelFinanceDetail:
    return HotelFinanceDetail(
        id_hotel=hotel.id, hotel_nom=hotel.nom, hotel_ville=hotel.ville or "—",
        revenu_total=0, commission_agence=0, part_partenaire=0,
        montant_paye=0, solde_restant=0, nb_reservations=0,
    )


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN RÉSERVATIONS D'UN HÔTEL
# ═══════════════════════════════════════════════════════════

async def get_reservations_finances_hotel(
    id_hotel: int,
    id_partenaire: int,
    session: AsyncSession,
    statut_commission: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> ReservationFinanceListResponse:
    """
    Retourne les réservations de l'hôtel en fusionnant CLIENTS + VISITEURS.
    - Clients  : via commission_partenaire (statut de paiement géré)
    - Visiteurs: via reservation_visiteur WHERE id_chambre IN chambre_ids
    """
    from app.models.hotel import Chambre
    from app.models.reservation import ReservationVisiteur
    from app.services.finances.utils import TAUX_COMMISSION_DEFAULT
    from app.models.utilisateur import Partenaire as PartenaireModel

    ch_res = await session.execute(
        select(Chambre.id).where(Chambre.id_hotel == id_hotel)
    )
    chambre_ids = [r[0] for r in ch_res.all()]

    if not chambre_ids:
        return ReservationFinanceListResponse(total=0, page=page, per_page=per_page, items=[])

    # ── Taux du partenaire ────────────────────────────────
    part_row = (await session.execute(
        select(PartenaireModel).where(PartenaireModel.id == id_partenaire)
    )).scalar_one_or_none()
    taux = float(part_row.commission) if part_row and part_row.commission else TAUX_COMMISSION_DEFAULT

    # ── 1. Clients (commission_partenaire) — charge tout pour fusion ──
    commissions, _ = await fetch_commissions_pour_hotel(
        session, id_partenaire, chambre_ids,
        statut_commission if statut_commission in ("EN_ATTENTE", "PAYEE") else None,
        1, 10000,
    )

    items = []
    for c in commissions:
        r = c.reservation
        client_nom   = "—"
        client_email = None
        if r and r.id_client:
            usr = (await session.execute(
                select(Utilisateur).where(Utilisateur.id == r.id_client)
            )).scalar_one_or_none()
            if usr:
                client_nom   = f"{usr.prenom} {usr.nom}"
                client_email = usr.email

        items.append(ReservationFinanceItem(
            type_source       = "client",
            client_nom        = client_nom,
            client_email      = client_email,
            date_debut        = r.date_debut if r else None,
            date_fin          = r.date_fin   if r else None,
            montant_total     = float(c.montant_total_resa),
            commission_agence = float(c.montant_commission),
            part_partenaire   = float(c.montant_partenaire),
            taux_commission   = float(c.taux_commission),
            statut_commission = c.statut.value,
            date_paiement     = c.date_paiement,
        ))

    # ── 2. Visiteurs (reservation_visiteur) ──────────────
    # Le statut est lu depuis commission_visiteur (table créée par migration)
    # ce qui permet d'afficher PAYEE après paiement du partenaire
    from sqlalchemy import text as sa_text

    # Requête jointe : visiteur + statut depuis commission_visiteur
    vis_query = sa_text("""
        SELECT
            rv.id, rv.nom, rv.prenom, rv.email,
            rv.date_debut, rv.date_fin, rv.total_ttc, rv.created_at,
            COALESCE(cv.statut, 'EN_ATTENTE') AS statut_comm,
            cv.date_paiement                 AS date_paiement_comm
        FROM voyage_hotel.reservation_visiteur rv
        LEFT JOIN voyage_hotel.commission_visiteur cv ON cv.id_reservation_visiteur = rv.id
            AND cv.id_partenaire = :id_p
        WHERE rv.id_chambre = ANY(:chambre_ids)
          AND rv.statut IN ('CONFIRMEE', 'TERMINEE')
        ORDER BY rv.date_debut DESC
    """)

    # Filtre statut si demandé
    if statut_commission in ("EN_ATTENTE", "PAYEE"):
        vis_query = sa_text("""
            SELECT
                rv.id, rv.nom, rv.prenom, rv.email,
                rv.date_debut, rv.date_fin, rv.total_ttc, rv.created_at,
                COALESCE(cv.statut, 'EN_ATTENTE') AS statut_comm,
                cv.date_paiement                  AS date_paiement_comm
            FROM voyage_hotel.reservation_visiteur rv
            LEFT JOIN voyage_hotel.commission_visiteur cv ON cv.id_reservation_visiteur = rv.id
                AND cv.id_partenaire = :id_p
            WHERE rv.id_chambre = ANY(:chambre_ids)
              AND rv.statut IN ('CONFIRMEE', 'TERMINEE')
              AND COALESCE(cv.statut, 'EN_ATTENTE') = :statut
            ORDER BY rv.date_debut DESC
        """)
        vis_result = await session.execute(
            vis_query,
            {"id_p": id_partenaire, "chambre_ids": list(chambre_ids), "statut": statut_commission}
        )
    else:
        vis_result = await session.execute(
            vis_query,
            {"id_p": id_partenaire, "chambre_ids": list(chambre_ids)}
        )

    vis_rows = vis_result.mappings().all()

    for v in vis_rows:
        montant    = float(v["total_ttc"])
        commission = calc_commission_agence(montant, taux)
        part       = calc_part_partenaire(montant, taux)

        items.append(ReservationFinanceItem(
            type_source       = "visiteur",
            client_nom        = f"{v['prenom']} {v['nom']}",
            client_email      = v["email"],
            date_debut        = v["date_debut"],
            date_fin          = v["date_fin"],
            montant_total     = montant,
            commission_agence = commission,
            part_partenaire   = part,
            taux_commission   = taux,
            statut_commission = v["statut_comm"],
            date_paiement     = v["date_paiement_comm"],
        ))

    # ── 3. Tri par date décroissante + pagination manuelle ──
    items.sort(key=lambda x: x.date_debut or date.min, reverse=True)
    total  = len(items)
    start  = (page - 1) * per_page
    paged  = items[start: start + per_page]

    return ReservationFinanceListResponse(total=total, page=page, per_page=per_page, items=paged)


# ═══════════════════════════════════════════════════════════
#  SOLDES À PAYER
# ═══════════════════════════════════════════════════════════

async def get_soldes_partenaires(session: AsyncSession) -> SoldesPartenairesResponse:
    """
    Calcule le solde réel de chaque partenaire depuis les revenus hôtels
    (clients + visiteurs).

    nb_commissions = commissions clients EN_ATTENTE (commission_partenaire)
                   + réservations visiteurs confirmées/terminées non payées
    Soit le vrai total des "transactions en attente de règlement".
    """
    from app.models.utilisateur import Partenaire as PartenaireModel, RoleUtilisateur
    from app.models.hotel import Hotel, Chambre
    from app.models.reservation import ReservationVisiteur
    from sqlalchemy import cast, String

    # ── 1. Tous les partenaires (jointure pour nom_entreprise) ──
    all_parts = (await session.execute(
        select(Utilisateur, PartenaireModel)
        .join(PartenaireModel, PartenaireModel.id == Utilisateur.id)
        .where(Utilisateur.role == RoleUtilisateur.PARTENAIRE)
    )).all()

    # ── 2. Commissions clients EN_ATTENTE groupées par partenaire ──
    nb_clients_map = {
        row.id_partenaire: int(row.nb)
        for row in (await session.execute(
            select(
                CommissionPartenaire.id_partenaire,
                func.count(CommissionPartenaire.id).label("nb"),
            )
            .where(cast(CommissionPartenaire.statut, String) == "EN_ATTENTE")
            .group_by(CommissionPartenaire.id_partenaire)
        )).all()
    }

    items = []
    for row in all_parts:
        usr  = row[0]
        part = row[1]
        taux = float(part.commission) if part.commission else TAUX_COMMISSION_DEFAULT

        # ── 3. Chambres de tous les hôtels du partenaire ──
        hotel_ids = [r[0] for r in (await session.execute(
            select(Hotel.id).where(Hotel.id_partenaire == usr.id)
        )).all()]

        chambre_ids = []
        if hotel_ids:
            chambre_ids = [r[0] for r in (await session.execute(
                select(Chambre.id).where(Chambre.id_hotel.in_(hotel_ids))
            )).all()]

        # ── 4. Revenu hôtel = clients + visiteurs ──
        revenu_hotel, nb_resas_total = await fetch_revenu_hotel_par_chambres(
            session, chambre_ids
        )

        # ── 5. Nombre de réservations visiteurs EN ATTENTE de paiement ──
        # Lu depuis commission_visiteur pour respecter le statut réel après paiement
        nb_visiteurs = 0
        if chambre_ids:
            from sqlalchemy import text as sa_text
            r_vis = await session.execute(
                sa_text("""
                    SELECT COUNT(rv.id)
                    FROM voyage_hotel.reservation_visiteur rv
                    LEFT JOIN voyage_hotel.commission_visiteur cv
                        ON cv.id_reservation_visiteur = rv.id
                        AND cv.id_partenaire = :id_p
                    WHERE rv.id_chambre = ANY(:ch_ids)
                      AND rv.statut IN ('CONFIRMEE', 'TERMINEE')
                      AND COALESCE(cv.statut, 'EN_ATTENTE') = 'EN_ATTENTE'
                """),
                {"id_p": usr.id, "ch_ids": list(chambre_ids) if chambre_ids else [0]}
            )
            nb_visiteurs = int(r_vis.scalar_one() or 0)

        # ── 6. Calculs financiers ──
        commission_agence = calc_commission_agence(revenu_hotel, taux)
        part_due  = calc_part_partenaire(revenu_hotel, taux)
        paye      = await fetch_montant_paye_partenaire(session, usr.id)
        solde     = calc_solde_restant(part_due, paye)

        # N'inclure que les partenaires avec un solde > 0
        if solde <= 0:
            continue

        nb_clients_en_attente = nb_clients_map.get(usr.id, 0)

        items.append(SoldePartenaire(
            id_partenaire              = usr.id,
            partenaire_nom             = usr.nom    or "—",
            partenaire_prenom          = usr.prenom or "—",
            partenaire_email           = usr.email  or "—",
            nom_entreprise             = part.nom_entreprise or "—",
            solde_du                   = round(solde, 2),
            revenu_hotel               = round(revenu_hotel, 2),
            commission_agence          = round(commission_agence, 2),
            montant_paye               = round(paye, 2),
            # ✅ TOTAL = clients EN_ATTENTE + visiteurs confirmés (les deux sources)
            nb_commissions             = nb_clients_en_attente + nb_visiteurs,
            nb_reservations_visiteurs  = int(nb_visiteurs),
            nb_reservations_total      = nb_resas_total,
        ))

    # Trier par montant dû décroissant
    items.sort(key=lambda x: x.solde_du, reverse=True)
    return SoldesPartenairesResponse(items=items)


# ═══════════════════════════════════════════════════════════
#  PAYER UN PARTENAIRE
# ═══════════════════════════════════════════════════════════

async def payer_partenaire(
    id_partenaire: int,
    note: str,
    session: AsyncSession,
) -> PayerPartenaireResponse:
    """
    Enregistre le paiement du solde réel dû au partenaire.

    Le montant payé = solde calculé depuis revenus hôtels réels (clients + visiteurs)
    moins ce qui a déjà été payé.
    Seules les commissions clients (commission_partenaire EN_ATTENTE) sont marquées PAYEE.
    Les visiteurs n'ont pas de ligne dans commission_partenaire donc on n'y touche pas.
    """
    from sqlalchemy import text
    from app.models.hotel import Hotel, Chambre
    from app.models.utilisateur import Partenaire as PartenaireModel
    from app.models.reservation import ReservationVisiteur

    # ── 1. Commissions clients EN_ATTENTE ──────────────────
    r = await session.execute(
        select(CommissionPartenaire).where(
            CommissionPartenaire.id_partenaire == id_partenaire,
            cast(CommissionPartenaire.statut, String) == "EN_ATTENTE",
        )
    )
    commissions_clients = r.scalars().all()

    # ── 2. Récupérer le taux du partenaire ─────────────────
    part_row = (await session.execute(
        select(PartenaireModel).where(PartenaireModel.id == id_partenaire)
    )).scalar_one_or_none()
    taux = float(part_row.commission) if part_row and part_row.commission else TAUX_COMMISSION_DEFAULT

    # ── 3. Toutes les chambres du partenaire ───────────────
    hotel_ids = [r[0] for r in (await session.execute(
        select(Hotel.id).where(Hotel.id_partenaire == id_partenaire)
    )).all()]

    chambre_ids = []
    if hotel_ids:
        chambre_ids = [r[0] for r in (await session.execute(
            select(Chambre.id).where(Chambre.id_hotel.in_(hotel_ids))
        )).all()]

    # ── 4. Revenu hôtel réel (clients + visiteurs) ─────────
    revenu_hotel, _ = await fetch_revenu_hotel_par_chambres(session, chambre_ids)

    # ── 5. Montant total dû = part partenaire - déjà payé ──
    part_totale = calc_part_partenaire(revenu_hotel, taux)
    deja_paye   = await fetch_montant_paye_partenaire(session, id_partenaire)
    solde_reel  = calc_solde_restant(part_totale, deja_paye)

    # ── 6. Nb de réservations visiteurs concernées ─────────
    nb_visiteurs = 0
    if chambre_ids:
        nb_visiteurs = (await session.execute(
            select(func.count(ReservationVisiteur.id))
            .where(
                ReservationVisiteur.id_chambre.in_(chambre_ids),
                ReservationVisiteur.statut.in_(["CONFIRMEE", "TERMINEE"]),
            )
        )).scalar_one() or 0

    nb_clients = len(commissions_clients)
    nb_total   = nb_clients + nb_visiteurs

    if solde_reel <= 0 and nb_total == 0:
        return PayerPartenaireResponse(
            success=False,
            id_partenaire=id_partenaire,
            message="Aucun solde en attente pour ce partenaire.",
            montant_paye=0,
            nb_commissions=0,
        )

    now = datetime.now()

    # ── 7. Marquer les commissions clients PAYEE (SQL brut — évite le cast enum) ──
    if commissions_clients:
        await session.execute(
            text(
                "UPDATE commission_partenaire "
                "SET statut = 'PAYEE', date_paiement = :dt "
                "WHERE id_partenaire = :id_p "
                "AND CAST(statut AS VARCHAR) = 'EN_ATTENTE'"
            ),
            {"dt": now, "id_p": id_partenaire},
        )

    # ── 8. Marquer les visiteurs PAYEE dans commission_visiteur ───────────
    # commission_visiteur est la table symétrique de commission_partenaire
    # pour les réservations visiteurs (créée par migration_commission_visiteur.sql)
    if chambre_ids:
        await session.execute(
            text(
                "UPDATE voyage_hotel.commission_visiteur cv "
                "SET statut = 'PAYEE', date_paiement = :dt "
                "FROM voyage_hotel.reservation_visiteur rv "
                "JOIN chambre c ON c.id = rv.id_chambre "
                "WHERE cv.id_reservation_visiteur = rv.id "
                "AND cv.id_partenaire = :id_p "
                "AND cv.statut = 'EN_ATTENTE' "
                "AND rv.statut IN ('CONFIRMEE', 'TERMINEE')"
            ),
            {"dt": now, "id_p": id_partenaire},
        )

    # ── 9. Enregistrer le vrai montant (clients + visiteurs) ──
    montant_final = round(solde_reel if solde_reel > 0 else
                          sum(float(c.montant_partenaire) for c in commissions_clients), 2)

    session.add(PaiementPartenaire(
        id_partenaire=id_partenaire,
        montant=montant_final,
        note=note or "",
    ))
    await session.commit()

    return PayerPartenaireResponse(
        success=True,
        id_partenaire=id_partenaire,
        message=f"Paiement de {montant_final:.2f} DT effectué ({nb_clients} client(s) + {nb_visiteurs} visiteur(s)).",
        montant_paye=montant_final,
        nb_commissions=nb_total,
    )


# ═══════════════════════════════════════════════════════════
#  HISTORIQUE DES PAIEMENTS
# ═══════════════════════════════════════════════════════════

async def get_historique_paiements(
    session: AsyncSession,
    id_partenaire: Optional[int] = None,
    date_debut: Optional[date] = None,
    date_fin: Optional[date] = None,
    montant_min: Optional[float] = None,
    montant_max: Optional[float] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> PaiementHistoriqueResponse:
    rows, total = await fetch_paiements_historique(
        session, id_partenaire, date_debut, date_fin,
        montant_min, montant_max, search, page, per_page
    )

    from app.models.utilisateur import Partenaire as PartenaireModel

    items = []
    for p in rows:
        # Jointure Utilisateur + Partenaire pour email, entreprise, téléphone
        joined = (await session.execute(
            select(Utilisateur, PartenaireModel)
            .join(PartenaireModel, PartenaireModel.id == Utilisateur.id)
            .where(Utilisateur.id == p.id_partenaire)
        )).one_or_none()

        usr  = joined[0] if joined else None
        part = joined[1] if joined else None

        items.append(PaiementHistoriqueItem(
            id_partenaire      = p.id_partenaire,
            partenaire_nom     = usr.nom       if usr  else "—",
            partenaire_prenom  = usr.prenom    if usr  else "—",
            partenaire_email   = usr.email     if usr  else "—",
            partenaire_tel     = usr.telephone if usr  else None,
            nom_entreprise     = part.nom_entreprise if part else "—",
            montant            = float(p.montant),
            note               = p.note or "",
            created_at         = p.created_at,
        ))

    return PaiementHistoriqueResponse(
        total=total, page=page, per_page=per_page, items=items
    )


# ═══════════════════════════════════════════════════════════
#  CLASSEMENT CLIENTS + VISITEURS
# ═══════════════════════════════════════════════════════════

async def get_clients_visiteurs_classement(
    session: AsyncSession,
    critere: str = "depenses",
    limit: int = 50,
) -> ClientsVisiteursRentabiliteResponse:

    # ── Clients ──────────────────────────────────────────
    items: List[ClientVisiteurItem] = []

    for row in await fetch_stats_clients(session):
        comm_gen = calc_commission_agence(float(row.depenses_hotel))
        items.append(ClientVisiteurItem(
            type_source          = "client",
            nom                  = f"{row.prenom} {row.nom}",
            email                = row.email or "—",
            total_depenses       = float(row.total_depenses),
            commissions_generees = comm_gen,
            nb_reservations      = int(row.nb_reservations),
            nb_hotel             = int(row.nb_hotel),
            nb_voyage            = int(row.nb_voyage),
        ))

    # ── Visiteurs ─────────────────────────────────────────
    for row in await fetch_stats_visiteurs(session):
        total_dep = float(row.total_depenses)
        # Visiteurs = uniquement hôtels → commission sur 100% du montant
        comm_gen = calc_commission_agence(total_dep)
        items.append(ClientVisiteurItem(
            type_source          = "visiteur",
            nom                  = f"{row.prenom} {row.nom}",
            email                = row.email or "—",
            total_depenses       = total_dep,
            commissions_generees = comm_gen,
            nb_reservations      = int(row.nb_hotel),
            nb_hotel             = int(row.nb_hotel),
            nb_voyage            = 0,
        ))

    # ── Tri + troncature ──────────────────────────────────
    sort_key_map = {
        "depenses":        lambda x: x.total_depenses,
        "commissions":     lambda x: x.commissions_generees,
        "nb_hotel":        lambda x: x.nb_hotel,
        "nb_voyage":       lambda x: x.nb_voyage,
        "nb_reservations": lambda x: x.nb_reservations,
    }
    items.sort(key=sort_key_map.get(critere, lambda x: x.total_depenses), reverse=True)
    sliced = items[:limit]

    return ClientsVisiteursRentabiliteResponse(
        total=len(sliced), critere=critere, items=sliced
    )


# ═══════════════════════════════════════════════════════════
#  SYNC COMMISSION (appelé depuis les endpoints réservation)
# ═══════════════════════════════════════════════════════════

async def sync_commission_reservation(
    reservation_id: int,
    session: AsyncSession,
) -> Optional[CommissionPartenaire]:
    """
    Crée une entrée commission_partenaire pour une réservation hôtel confirmée.
    Ne crée RIEN pour les voyages.
    """
    existing = (await session.execute(
        select(CommissionPartenaire).where(
            CommissionPartenaire.id_reservation == reservation_id
        )
    )).scalar_one_or_none()
    if existing:
        return None

    resa = (await session.execute(
        select(Reservation)
        .options(selectinload(Reservation.lignes_chambres))
        .where(Reservation.id == reservation_id)
    )).scalar_one_or_none()

    if not resa or resa.id_voyage or not resa.lignes_chambres:
        return None

    from app.models.hotel import Hotel, Chambre

    lrc     = resa.lignes_chambres[0]
    chambre = (await session.execute(
        select(Chambre).where(Chambre.id == lrc.id_chambre)
    )).scalar_one_or_none()
    if not chambre:
        return None

    hotel = (await session.execute(
        select(Hotel).where(Hotel.id == chambre.id_hotel)
    )).scalar_one_or_none()
    if not hotel or not hotel.id_partenaire:
        return None

    montant_total = float(resa.total_ttc)
    commission    = calc_commission_agence(montant_total)
    part          = round(montant_total - commission, 2)

    c = CommissionPartenaire(
        id_reservation     = reservation_id,
        id_partenaire      = hotel.id_partenaire,
        type_resa          = "hotel",
        montant_total_resa = montant_total,
        taux_commission    = TAUX_COMMISSION_DEFAULT,
        montant_commission = commission,
        montant_partenaire = part,
        statut             = StatutCommission.EN_ATTENTE,
    )
    session.add(c)
    await session.flush()
    return c


# ═══════════════════════════════════════════════════════════
#  LISTE COMMISSIONS (admin général)
# ═══════════════════════════════════════════════════════════

async def list_commissions(
    session: AsyncSession,
    statut: Optional[str] = None,
    id_partenaire: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
) -> CommissionListResponse:
    q = select(CommissionPartenaire).options(selectinload(CommissionPartenaire.partenaire))
    if statut:
        q = q.where(cast(CommissionPartenaire.statut, String) == statut)
    if id_partenaire:
        q = q.where(CommissionPartenaire.id_partenaire == id_partenaire)

    total = (await session.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar_one()

    rows = (await session.execute(
        q.order_by(CommissionPartenaire.date_creation.desc())
         .offset((page - 1) * per_page)
         .limit(per_page)
    )).scalars().all()

    items = []
    for c in rows:
        p = c.partenaire
        items.append(CommissionItem(
            id                 = c.id,
            id_reservation     = c.id_reservation,
            id_partenaire      = c.id_partenaire,
            partenaire_nom     = p.nom    if p else "—",
            partenaire_prenom  = p.prenom if p else "—",
            partenaire_email   = p.email  if p else "—",
            type_resa          = c.type_resa,
            montant_total_resa = float(c.montant_total_resa),
            taux_commission    = float(c.taux_commission),
            montant_commission = float(c.montant_commission),
            montant_partenaire = float(c.montant_partenaire),
            statut             = c.statut.value,
            date_creation      = c.date_creation,
            date_paiement      = c.date_paiement,
        ))

    return CommissionListResponse(total=total, page=page, per_page=per_page, items=items)