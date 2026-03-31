"""
app/services/finances_service.py  (version avancée)
=====================================================
Module financier complet :
  - Dashboard KPIs globaux
  - Revenus par période (jour/mois/année) — clients + visiteurs
  - Drill-down : Partenaires → Hôtels → Réservations
  - Soldes à payer avec drill-down
  - Historique paiements filtrable
  - Classement clients/visiteurs multi-critères
"""
from __future__ import annotations
from datetime import datetime, date
from typing import Optional, List
from calendar import monthrange

from sqlalchemy import select, func, and_, extract, case, update, text, cast, String
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finances import CommissionPartenaire, PaiementPartenaire, StatutCommission
from app.models.reservation import (
    Reservation, ReservationVisiteur, StatutReservation, LigneReservationChambre,
)
from app.models.utilisateur import Utilisateur
from app.schemas.finances import (
    RevenuPeriode, RevenusResponse,
    CommissionItem, CommissionListResponse,
    SoldePartenaire, SoldesPartenairesResponse,
    PayerPartenaireResponse,
    PaiementHistoriqueItem, PaiementHistoriqueResponse,
    ClientRentabilite, ClientsRentabiliteResponse,
    FinanceDashboard,
    # nouveaux schemas
    PartenaireFinanceDetail, HotelFinanceDetail, ReservationFinanceItem,
    PartenaireFinanceListResponse, HotelFinanceListResponse,
    ReservationFinanceListResponse, ClientsVisiteursRentabiliteResponse,
    ClientVisiteurItem,
)

TAUX_COMMISSION = 10.0
STATUTS_OK      = [StatutReservation.CONFIRMEE, StatutReservation.TERMINEE]
STATUTS_OK_VIS  = ["CONFIRMEE", "TERMINEE"]


# ═══════════════════════════════════════════════════════════
#  HELPER : revenus combinés clients + visiteurs
# ═══════════════════════════════════════════════════════════

async def _revenus_combines(
    session: AsyncSession,
    filtre_client,
    filtre_visiteur,
) -> tuple[float, float, float, int]:
    r_c = await session.execute(
        select(
            func.coalesce(func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0),
            func.coalesce(func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)), 0),
            func.count(Reservation.id),
        ).where(Reservation.statut.in_(STATUTS_OK), filtre_client)
    )
    row_c = r_c.one()
    rh_c, rv_c, nb_c = float(row_c[0]), float(row_c[1]), int(row_c[2])

    r_v = await session.execute(
        select(
            func.coalesce(func.sum(ReservationVisiteur.total_ttc), 0),
            func.count(ReservationVisiteur.id),
        ).where(ReservationVisiteur.statut.in_(STATUTS_OK_VIS), filtre_visiteur)
    )
    row_v = r_v.one()
    rh_v, nb_v = float(row_v[0]), int(row_v[1])

    rh = rh_c + rh_v
    rv = rv_c
    return rh, rv, rh + rv, nb_c + nb_v


# ═══════════════════════════════════════════════════════════
#  HELPER : infos hotel/partenaire depuis id_chambre
# ═══════════════════════════════════════════════════════════

async def _get_hotel_partenaire(id_chambre: int, session: AsyncSession):
    from app.models.hotel import Hotel, Chambre
    ch_res = await session.execute(select(Chambre).where(Chambre.id == id_chambre))
    ch = ch_res.scalar_one_or_none()
    if not ch:
        return None, None
    h_res = await session.execute(select(Hotel).where(Hotel.id == ch.id_hotel))
    hotel = h_res.scalar_one_or_none()
    return hotel, ch


# ═══════════════════════════════════════════════════════════
#  SYNC COMMISSION
# ═══════════════════════════════════════════════════════════

async def sync_commission_reservation(
    reservation_id: int,
    session: AsyncSession,
) -> Optional[CommissionPartenaire]:
    existing = await session.execute(
        select(CommissionPartenaire).where(CommissionPartenaire.id_reservation == reservation_id)
    )
    if existing.scalar_one_or_none():
        return None

    res = await session.execute(
        select(Reservation)
        .options(selectinload(Reservation.lignes_chambres))
        .where(Reservation.id == reservation_id)
    )
    resa = res.scalar_one_or_none()
    if not resa:
        return None

    id_partenaire = None
    type_resa = "voyage" if resa.id_voyage else "hotel"

    if resa.id_voyage:
        return None
    elif resa.lignes_chambres:
        from app.models.hotel import Hotel, Chambre
        lrc = resa.lignes_chambres[0]
        ch_res = await session.execute(select(Chambre).where(Chambre.id == lrc.id_chambre))
        chambre = ch_res.scalar_one_or_none()
        if chambre:
            hotel_res = await session.execute(select(Hotel).where(Hotel.id == chambre.id_hotel))
            hotel = hotel_res.scalar_one_or_none()
            if hotel:
                id_partenaire = hotel.id_partenaire

    if not id_partenaire:
        return None

    montant_total      = float(resa.total_ttc)
    montant_commission = round(montant_total * TAUX_COMMISSION / 100, 2)
    montant_partenaire = round(montant_total - montant_commission, 2)

    commission = CommissionPartenaire(
        id_reservation=reservation_id, id_partenaire=id_partenaire,
        type_resa=type_resa, montant_total_resa=montant_total,
        taux_commission=TAUX_COMMISSION, montant_commission=montant_commission,
        montant_partenaire=montant_partenaire, statut="EN_ATTENTE",
    )
    session.add(commission)
    await session.flush()
    return commission


# ═══════════════════════════════════════════════════════════
#  DASHBOARD
# ═══════════════════════════════════════════════════════════

async def get_dashboard(session: AsyncSession) -> FinanceDashboard:
    now   = datetime.now()
    mois  = now.month
    annee = now.year

    _, _, rev_mois, nb_mois = await _revenus_combines(
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

    rev_hotel_annee, rev_voyage_annee, rev_annee, nb_annee = await _revenus_combines(
        session,
        filtre_client=extract("year", Reservation.date_reservation) == annee,
        filtre_visiteur=extract("year", ReservationVisiteur.created_at) == annee,
    )

    comm_mois  = round(rev_mois  * TAUX_COMMISSION / 100, 2)
    comm_annee = round(rev_annee * TAUX_COMMISSION / 100, 2)

    r_solde = await session.execute(
        select(
            func.coalesce(func.sum(CommissionPartenaire.montant_partenaire), 0),
            func.count(CommissionPartenaire.id_partenaire.distinct()),
        ).where(cast(CommissionPartenaire.statut, String) == "EN_ATTENTE")
    )
    row_solde = r_solde.one()

    # Total part partenaires (payées + en attente)
    r_part = await session.execute(
        select(func.coalesce(func.sum(CommissionPartenaire.montant_partenaire), 0))
    )
    total_part_partenaires = float(r_part.scalar_one() or 0)

    # Total commissions agence perçues
    r_comm = await session.execute(
        select(func.coalesce(func.sum(CommissionPartenaire.montant_commission), 0))
    )
    total_commissions_agence = float(r_comm.scalar_one() or 0)

    return FinanceDashboard(
        revenu_total_mois         = rev_mois,
        revenu_total_annee        = rev_annee,
        commission_mois           = comm_mois,
        commission_annee          = comm_annee,
        total_du_partenaires      = float(row_solde[0]),
        nb_partenaires_en_attente = int(row_solde[1]),
        revenu_hotel_annee        = rev_hotel_annee,
        revenu_voyage_annee       = rev_voyage_annee,
        nb_reservations_mois      = nb_mois,
        nb_reservations_annee     = nb_annee,
        total_part_partenaires    = total_part_partenaires,
        total_commissions_agence  = total_commissions_agence,
    )


# ═══════════════════════════════════════════════════════════
#  REVENUS PAR PÉRIODE
# ═══════════════════════════════════════════════════════════

async def get_revenus(
    session: AsyncSession,
    periode: str = "mois",
    annee: Optional[int] = None,
    mois: Optional[int]  = None,
) -> RevenusResponse:
    now   = datetime.now()
    annee = annee or now.year
    mois  = mois  or now.month
    mois_noms = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
    evolution: List[RevenuPeriode] = []

    if periode == "jour":
        for jour in range(1, monthrange(annee, mois)[1] + 1):
            d = date(annee, mois, jour)
            rh, rv, rt, nb = await _revenus_combines(
                session,
                filtre_client=func.date(Reservation.date_reservation) == d,
                filtre_visiteur=func.date(ReservationVisiteur.created_at) == d,
            )
            evolution.append(RevenuPeriode(
                periode=d.strftime("%d/%m"), revenu_hotel=rh, revenu_voyage=rv,
                revenu_total=rt, commission_total=round(rt * TAUX_COMMISSION / 100, 2), nb_reservations=nb,
            ))
    elif periode == "mois":
        for m in range(1, 13):
            rh, rv, rt, nb = await _revenus_combines(
                session,
                filtre_client=and_(extract("month", Reservation.date_reservation) == m, extract("year", Reservation.date_reservation) == annee),
                filtre_visiteur=and_(extract("month", ReservationVisiteur.created_at) == m, extract("year", ReservationVisiteur.created_at) == annee),
            )
            evolution.append(RevenuPeriode(
                periode=mois_noms[m-1], revenu_hotel=rh, revenu_voyage=rv,
                revenu_total=rt, commission_total=round(rt * TAUX_COMMISSION / 100, 2), nb_reservations=nb,
            ))
    else:
        for a in range(now.year - 4, now.year + 1):
            rh, rv, rt, nb = await _revenus_combines(
                session,
                filtre_client=extract("year", Reservation.date_reservation) == a,
                filtre_visiteur=extract("year", ReservationVisiteur.created_at) == a,
            )
            evolution.append(RevenuPeriode(
                periode=str(a), revenu_hotel=rh, revenu_voyage=rv,
                revenu_total=rt, commission_total=round(rt * TAUX_COMMISSION / 100, 2), nb_reservations=nb,
            ))

    totaux = sum(p.revenu_total for p in evolution)
    return RevenusResponse(
        periode=periode, revenu_total=round(totaux, 2),
        commission_total=round(totaux * TAUX_COMMISSION / 100, 2),
        revenu_hotel=round(sum(p.revenu_hotel for p in evolution), 2),
        revenu_voyage=round(sum(p.revenu_voyage for p in evolution), 2),
        nb_reservations=sum(p.nb_reservations for p in evolution),
        evolution=evolution,
    )


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN : LISTE PARTENAIRES AVEC FINANCES
# ═══════════════════════════════════════════════════════════

async def get_partenaires_finances(
    session: AsyncSession,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
) -> PartenaireFinanceListResponse:
    """
    Retourne chaque partenaire avec : revenu total, commission agence,
    part partenaire, montant payé, solde restant, nb réservations.
    """
    from app.models.utilisateur import Partenaire

    # Joindre Utilisateur systématiquement pour charger nom/prénom/email
    query = (
        select(Partenaire, Utilisateur)
        .join(Utilisateur, Utilisateur.id == Partenaire.id)
    )
    if search:
        query = query.where(
            Utilisateur.nom.ilike(f"%{search}%") |
            Utilisateur.prenom.ilike(f"%{search}%") |
            Partenaire.nom_entreprise.ilike(f"%{search}%")
        )

    count_q = select(func.count()).select_from(
        select(Partenaire).join(Utilisateur, Utilisateur.id == Partenaire.id).subquery()
    )
    total   = (await session.execute(count_q)).scalar_one()

    query   = query.offset((page - 1) * per_page).limit(per_page)
    rows_p  = (await session.execute(query)).all()

    items = []
    for row_p in rows_p:
        p   = row_p[0]
        usr = row_p[1]

        # Agréger commissions
        r = await session.execute(
            select(
                func.coalesce(func.sum(CommissionPartenaire.montant_total_resa), 0),
                func.coalesce(func.sum(CommissionPartenaire.montant_commission), 0),
                func.coalesce(func.sum(CommissionPartenaire.montant_partenaire), 0),
                func.coalesce(func.sum(case(
                    (cast(CommissionPartenaire.statut, String) == "PAYEE", CommissionPartenaire.montant_partenaire),
                    else_=0
                )), 0),
                func.coalesce(func.sum(case(
                    (cast(CommissionPartenaire.statut, String) == "EN_ATTENTE", CommissionPartenaire.montant_partenaire),
                    else_=0
                )), 0),
                func.count(CommissionPartenaire.id),
            ).where(CommissionPartenaire.id_partenaire == p.id)
        )
        row = r.one()

        items.append(PartenaireFinanceDetail(
            id_partenaire     = p.id,
            partenaire_nom    = usr.nom    if usr else "—",
            partenaire_prenom = usr.prenom if usr else "—",
            partenaire_email  = usr.email  if usr else "—",
            nom_entreprise    = p.nom_entreprise or "—",
            commission_taux   = float(p.commission) if hasattr(p, "commission") and p.commission else TAUX_COMMISSION,
            revenu_total      = float(row[0]),
            commission_agence = float(row[1]),
            part_partenaire   = float(row[2]),
            montant_paye      = float(row[3]),
            solde_restant     = float(row[4]),
            nb_reservations   = int(row[5]),
        ))

    return PartenaireFinanceListResponse(total=total, page=page, per_page=per_page, items=items)


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN : HÔTELS D'UN PARTENAIRE AVEC FINANCES
# ═══════════════════════════════════════════════════════════

async def get_hotels_finances_partenaire(
    id_partenaire: int,
    session: AsyncSession,
) -> HotelFinanceListResponse:
    from app.models.hotel import Hotel, Chambre

    hotels_res = await session.execute(
        select(Hotel).where(Hotel.id_partenaire == id_partenaire)
    )
    hotels = hotels_res.scalars().all()

    items = []
    for hotel in hotels:
        # Chambres de cet hôtel
        ch_res = await session.execute(
            select(Chambre.id).where(Chambre.id_hotel == hotel.id)
        )
        chambre_ids = [r[0] for r in ch_res.all()]

        if not chambre_ids:
            items.append(HotelFinanceDetail(
                id_hotel=hotel.id, hotel_nom=hotel.nom, hotel_ville=hotel.ville or "—",
                revenu_total=0, commission_agence=0, part_partenaire=0,
                montant_paye=0, solde_restant=0, nb_reservations=0,
            ))
            continue

        # Commissions liées aux réservations de cet hôtel
        # Via reservation → ligne_reservation_chambre → chambre_ids
        subq = (
            select(Reservation.id)
            .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
            .where(
                LigneReservationChambre.id_chambre.in_(chambre_ids),
                Reservation.statut.in_(STATUTS_OK),
            )
        )
        r = await session.execute(
            select(
                func.coalesce(func.sum(CommissionPartenaire.montant_total_resa), 0),
                func.coalesce(func.sum(CommissionPartenaire.montant_commission), 0),
                func.coalesce(func.sum(CommissionPartenaire.montant_partenaire), 0),
                func.coalesce(func.sum(case(
                    (cast(CommissionPartenaire.statut, String) == "PAYEE", CommissionPartenaire.montant_partenaire),
                    else_=0
                )), 0),
                func.coalesce(func.sum(case(
                    (cast(CommissionPartenaire.statut, String) == "EN_ATTENTE", CommissionPartenaire.montant_partenaire),
                    else_=0
                )), 0),
                func.count(CommissionPartenaire.id),
            ).where(
                CommissionPartenaire.id_partenaire == id_partenaire,
                CommissionPartenaire.id_reservation.in_(subq),
            )
        )
        row = r.one()

        items.append(HotelFinanceDetail(
            id_hotel          = hotel.id,
            hotel_nom         = hotel.nom,
            hotel_ville       = hotel.ville or "—",
            revenu_total      = float(row[0]),
            commission_agence = float(row[1]),
            part_partenaire   = float(row[2]),
            montant_paye      = float(row[3]),
            solde_restant     = float(row[4]),
            nb_reservations   = int(row[5]),
        ))

    return HotelFinanceListResponse(items=items)


# ═══════════════════════════════════════════════════════════
#  DRILL-DOWN : RÉSERVATIONS D'UN HÔTEL AVEC FINANCES
# ═══════════════════════════════════════════════════════════

async def get_reservations_finances_hotel(
    id_hotel: int,
    id_partenaire: int,
    session: AsyncSession,
    statut_commission: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> ReservationFinanceListResponse:
    from app.models.hotel import Chambre

    ch_res = await session.execute(
        select(Chambre.id).where(Chambre.id_hotel == id_hotel)
    )
    chambre_ids = [r[0] for r in ch_res.all()]

    if not chambre_ids:
        return ReservationFinanceListResponse(total=0, page=page, per_page=per_page, items=[])

    query = (
        select(CommissionPartenaire)
        .options(selectinload(CommissionPartenaire.reservation))
        .where(
            CommissionPartenaire.id_partenaire == id_partenaire,
            CommissionPartenaire.id_reservation.in_(
                select(Reservation.id)
                .join(LigneReservationChambre, LigneReservationChambre.id_reservation == Reservation.id)
                .where(LigneReservationChambre.id_chambre.in_(chambre_ids))
            ),
        )
    )
    if statut_commission:
        query = query.where(cast(CommissionPartenaire.statut, String) == statut_commission)

    count_q = select(func.count()).select_from(query.subquery())
    total   = (await session.execute(count_q)).scalar_one()

    query = query.order_by(CommissionPartenaire.date_creation.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    rows  = (await session.execute(query)).scalars().all()

    items = []
    for c in rows:
        resa = c.reservation
        # Client info
        client_nom = "—"
        if resa and resa.id_client:
            usr_r = await session.execute(select(Utilisateur).where(Utilisateur.id == resa.id_client))
            usr = usr_r.scalar_one_or_none()
            if usr:
                client_nom = f"{usr.prenom} {usr.nom}"

        items.append(ReservationFinanceItem(
            id_commission     = c.id,
            id_reservation    = c.id_reservation,
            client_nom        = client_nom,
            date_reservation  = resa.date_reservation if resa else c.date_creation,
            date_debut        = resa.date_debut if resa else None,
            date_fin          = resa.date_fin if resa else None,
            montant_total     = float(c.montant_total_resa),
            commission_agence = float(c.montant_commission),
            part_partenaire   = float(c.montant_partenaire),
            taux_commission   = float(c.taux_commission),
            statut_commission = c.statut.value,
            date_paiement     = c.date_paiement,
        ))

    return ReservationFinanceListResponse(total=total, page=page, per_page=per_page, items=items)


# ═══════════════════════════════════════════════════════════
#  COMMISSIONS (liste globale)
# ═══════════════════════════════════════════════════════════

async def list_commissions(
    session: AsyncSession,
    statut: Optional[str] = None,
    id_partenaire: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
) -> CommissionListResponse:
    query = select(CommissionPartenaire).options(selectinload(CommissionPartenaire.partenaire))
    if statut:
        query = query.where(cast(CommissionPartenaire.statut, String) == statut)
    if id_partenaire:
        query = query.where(CommissionPartenaire.id_partenaire == id_partenaire)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    query = query.order_by(CommissionPartenaire.date_creation.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    rows  = (await session.execute(query)).scalars().all()

    items = []
    for c in rows:
        p = c.partenaire
        items.append(CommissionItem(
            id=c.id, id_reservation=c.id_reservation, id_partenaire=c.id_partenaire,
            partenaire_nom=p.nom if p else "—", partenaire_prenom=p.prenom if p else "—",
            partenaire_email=p.email if p else "—", type_resa=c.type_resa,
            montant_total_resa=float(c.montant_total_resa), taux_commission=float(c.taux_commission),
            montant_commission=float(c.montant_commission), montant_partenaire=float(c.montant_partenaire),
            statut=c.statut.value, date_creation=c.date_creation, date_paiement=c.date_paiement,
        ))
    return CommissionListResponse(total=total, page=page, per_page=per_page, items=items)


# ═══════════════════════════════════════════════════════════
#  SOLDES PARTENAIRES
# ═══════════════════════════════════════════════════════════

async def get_soldes_partenaires(session: AsyncSession) -> SoldesPartenairesResponse:
    r = await session.execute(
        select(
            CommissionPartenaire.id_partenaire,
            func.sum(CommissionPartenaire.montant_partenaire),
            func.count(CommissionPartenaire.id),
        )
        .where(cast(CommissionPartenaire.statut, String) == "EN_ATTENTE")
        .group_by(CommissionPartenaire.id_partenaire)
        .order_by(func.sum(CommissionPartenaire.montant_partenaire).desc())
    )
    rows = r.all()
    items = []
    for row in rows:
        id_p, solde, nb = row[0], float(row[1]), int(row[2])
        usr_r = await session.execute(select(Utilisateur).where(Utilisateur.id == id_p))
        usr   = usr_r.scalar_one_or_none()
        if not usr:
            continue
        items.append(SoldePartenaire(
            id_partenaire=id_p, partenaire_nom=usr.nom, partenaire_prenom=usr.prenom,
            partenaire_email=usr.email,
            nom_entreprise=getattr(usr, "nom_entreprise", "—") or "—",
            solde_du=round(solde, 2), nb_commissions=nb,
        ))
    return SoldesPartenairesResponse(items=items)


# ═══════════════════════════════════════════════════════════
#  PAYER UN PARTENAIRE
# ═══════════════════════════════════════════════════════════

async def payer_partenaire(
    id_partenaire: int,
    note: Optional[str],
    session: AsyncSession,
) -> PayerPartenaireResponse:
    r = await session.execute(
        select(func.sum(CommissionPartenaire.montant_partenaire))
        .where(CommissionPartenaire.id_partenaire == id_partenaire, cast(CommissionPartenaire.statut, String) == "EN_ATTENTE")
    )
    montant = float(r.scalar_one() or 0)
    if montant <= 0:
        from fastapi import HTTPException
        raise HTTPException(400, "Aucun montant en attente pour ce partenaire.")

    await session.execute(
        update(CommissionPartenaire)
        .where(CommissionPartenaire.id_partenaire == id_partenaire, cast(CommissionPartenaire.statut, String) == "EN_ATTENTE")
        .values(statut="PAYEE", date_paiement=datetime.now())
    )
    session.add(PaiementPartenaire(id_partenaire=id_partenaire, montant=montant, note=note))
    await session.flush()
    return PayerPartenaireResponse(id_partenaire=id_partenaire, montant_paye=montant,
                                   message=f"Paiement de {montant:.2f} DT enregistré.")


# ═══════════════════════════════════════════════════════════
#  HISTORIQUE PAIEMENTS
# ═══════════════════════════════════════════════════════════

async def get_historique_paiements(
    session: AsyncSession,
    id_partenaire: Optional[int] = None,
    date_debut: Optional[date] = None,
    date_fin: Optional[date] = None,
    page: int = 1,
    per_page: int = 20,
) -> PaiementHistoriqueResponse:
    query = select(PaiementPartenaire).options(selectinload(PaiementPartenaire.partenaire))
    if id_partenaire:
        query = query.where(PaiementPartenaire.id_partenaire == id_partenaire)
    if date_debut:
        query = query.where(func.date(PaiementPartenaire.created_at) >= date_debut)
    if date_fin:
        query = query.where(func.date(PaiementPartenaire.created_at) <= date_fin)

    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    query = query.order_by(PaiementPartenaire.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    rows  = (await session.execute(query)).scalars().all()

    items = []
    for p in rows:
        usr = p.partenaire
        items.append(PaiementHistoriqueItem(
            id=p.id, id_partenaire=p.id_partenaire,
            partenaire_nom=usr.nom if usr else "—",
            partenaire_prenom=usr.prenom if usr else "—",
            montant=float(p.montant), note=p.note, created_at=p.created_at,
        ))
    return PaiementHistoriqueResponse(total=total, page=page, per_page=per_page, items=items)


# ═══════════════════════════════════════════════════════════
#  CLIENTS RENTABLES (+ visiteurs)
# ═══════════════════════════════════════════════════════════

async def get_clients_rentables(
    session: AsyncSession,
    limit: int = 50,
) -> ClientsRentabiliteResponse:
    r = await session.execute(
        select(
            Reservation.id_client,
            func.sum(Reservation.total_ttc),
            func.count(Reservation.id),
            func.max(Reservation.date_reservation),
        )
        .where(Reservation.statut.in_(STATUTS_OK), Reservation.id_client != None)
        .group_by(Reservation.id_client)
        .order_by(func.sum(Reservation.total_ttc).desc())
        .limit(limit)
    )
    rows = r.all()
    items = []
    for row in rows:
        id_c, total, nb, derniere = row
        usr_r = await session.execute(select(Utilisateur).where(Utilisateur.id == id_c))
        usr   = usr_r.scalar_one_or_none()
        if not usr:
            continue
        items.append(ClientRentabilite(
            id_client=id_c, nom=usr.nom, prenom=usr.prenom, email=usr.email,
            telephone=getattr(usr, "telephone", None),
            total_depenses=round(float(total), 2), nb_reservations=int(nb), derniere_resa=derniere,
        ))
    return ClientsRentabiliteResponse(total=len(items), items=items)


# ═══════════════════════════════════════════════════════════
#  CLIENTS + VISITEURS CLASSEMENT MULTI-CRITÈRES
# ═══════════════════════════════════════════════════════════

async def get_clients_visiteurs_classement(
    session: AsyncSession,
    critere: str = "depenses",   # depenses | commissions | nb_hotel | nb_voyage
    limit: int = 50,
) -> ClientsVisiteursRentabiliteResponse:
    """
    Classement combiné clients (reservation) + visiteurs (reservation_visiteur).
    critere : depenses | commissions | nb_hotel | nb_voyage | nb_reservations
    """
    items: List[ClientVisiteurItem] = []

    # ── Clients ──────────────────────────────────────────────
    r_clients = await session.execute(
        select(
            Reservation.id_client,
            func.sum(Reservation.total_ttc).label("total"),
            func.count(Reservation.id).label("nb"),
            func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)).label("hotel"),
            func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)).label("voyage"),
            func.count(case((Reservation.id_voyage == None, Reservation.id), else_=None)).label("nb_hotel"),
            func.count(case((Reservation.id_voyage != None, Reservation.id), else_=None)).label("nb_voyage"),
        )
        .where(Reservation.statut.in_(STATUTS_OK), Reservation.id_client != None)
        .group_by(Reservation.id_client)
    )
    for row in r_clients.all():
        id_c = row[0]
        usr_r = await session.execute(select(Utilisateur).where(Utilisateur.id == id_c))
        usr   = usr_r.scalar_one_or_none()
        if not usr:
            continue
        total = float(row[1])
        comm  = round(total * TAUX_COMMISSION / 100, 2)
        items.append(ClientVisiteurItem(
            type_source="client",
            id=id_c,
            nom=f"{usr.prenom} {usr.nom}",
            email=usr.email,
            total_depenses=round(total, 2),
            commissions_generees=comm,
            nb_reservations=int(row[2]),
            nb_hotel=int(row[5]),
            nb_voyage=int(row[6]),
        ))

    # ── Visiteurs ─────────────────────────────────────────────
    r_vis = await session.execute(
        select(
            ReservationVisiteur.email,
            ReservationVisiteur.nom,
            ReservationVisiteur.prenom,
            func.sum(ReservationVisiteur.total_ttc).label("total"),
            func.count(ReservationVisiteur.id).label("nb"),
        )
        .where(ReservationVisiteur.statut.in_(STATUTS_OK_VIS))
        .group_by(ReservationVisiteur.email, ReservationVisiteur.nom, ReservationVisiteur.prenom)
    )
    for row in r_vis.all():
        total = float(row[3])
        comm  = round(total * TAUX_COMMISSION / 100, 2)
        items.append(ClientVisiteurItem(
            type_source="visiteur",
            id=None,
            nom=f"{row[2]} {row[1]}",
            email=row[0],
            total_depenses=round(total, 2),
            commissions_generees=comm,
            nb_reservations=int(row[4]),
            nb_hotel=int(row[4]),
            nb_voyage=0,
        ))

    # Tri selon critère
    sort_key = {
        "depenses":    lambda x: x.total_depenses,
        "commissions": lambda x: x.commissions_generees,
        "nb_hotel":    lambda x: x.nb_hotel,
        "nb_voyage":   lambda x: x.nb_voyage,
        "nb_reservations": lambda x: x.nb_reservations,
    }.get(critere, lambda x: x.total_depenses)

    items.sort(key=sort_key, reverse=True)
    items = items[:limit]

    return ClientsVisiteursRentabiliteResponse(
        total=len(items), critere=critere, items=items
    )