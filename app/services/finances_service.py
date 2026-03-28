"""
app/services/finances_service.py
=================================
Service de gestion financière : revenus, commissions, clients rentables.
"""
from __future__ import annotations
from datetime import datetime, date, timedelta
from typing import Optional, List
from calendar import monthrange

from sqlalchemy import select, func, and_, extract, case
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finances import CommissionPartenaire, PaiementPartenaire, StatutCommission
from app.models.reservation import Reservation, StatutReservation, LigneReservationChambre
from app.models.utilisateur import Utilisateur
from app.schemas.finances import (
    RevenuPeriode, RevenusResponse, CommissionItem, CommissionListResponse,
    SoldePartenaire, SoldesPartenairesResponse, PayerPartenaireResponse,
    PaiementHistoriqueItem, PaiementHistoriqueResponse,
    ClientRentabilite, ClientsRentabiliteResponse, FinanceDashboard,
)

TAUX_COMMISSION = 10.0   # % fixe agence


# ═══════════════════════════════════════════════════════════
#  HELPER : créer/sync commission pour une réservation
# ═══════════════════════════════════════════════════════════

async def sync_commission_reservation(
    reservation_id: int,
    session: AsyncSession,
) -> Optional[CommissionPartenaire]:
    """
    Crée ou met à jour la commission pour une réservation confirmée.
    À appeler quand une réservation passe à CONFIRMEE.
    """
    # Vérifier si déjà créée
    existing = await session.execute(
        select(CommissionPartenaire).where(
            CommissionPartenaire.id_reservation == reservation_id
        )
    )
    if existing.scalar_one_or_none():
        return None   # déjà créée

    # Charger la réservation
    res = await session.execute(
        select(Reservation)
        .options(selectinload(Reservation.lignes_chambres))
        .where(Reservation.id == reservation_id)
    )
    resa = res.scalar_one_or_none()
    if not resa:
        return None

    # Trouver le partenaire
    id_partenaire = None
    type_resa = "voyage" if resa.id_voyage else "hotel"

    if resa.id_voyage:
        # Pour voyage : pas de partenaire direct → skip pour l'instant
        return None
    elif resa.lignes_chambres:
        from app.models.hotel import Hotel, Chambre
        lrc = resa.lignes_chambres[0]
        ch_res = await session.execute(
            select(Chambre).where(Chambre.id == lrc.id_chambre)
        )
        chambre = ch_res.scalar_one_or_none()
        if chambre:
            hotel_res = await session.execute(
                select(Hotel).where(Hotel.id == chambre.id_hotel)
            )
            hotel = hotel_res.scalar_one_or_none()
            if hotel:
                id_partenaire = hotel.id_partenaire

    if not id_partenaire:
        return None

    montant_total = float(resa.total_ttc)
    montant_commission = round(montant_total * TAUX_COMMISSION / 100, 2)
    montant_partenaire = round(montant_total - montant_commission, 2)

    commission = CommissionPartenaire(
        id_reservation     = reservation_id,
        id_partenaire      = id_partenaire,
        type_resa          = type_resa,
        montant_total_resa = montant_total,
        taux_commission    = TAUX_COMMISSION,
        montant_commission = montant_commission,
        montant_partenaire = montant_partenaire,
        statut             = StatutCommission.EN_ATTENTE,
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

    statuts_ok = [StatutReservation.CONFIRMEE, StatutReservation.TERMINEE]

    # Revenus mois
    r_mois = await session.execute(
        select(
            func.coalesce(func.sum(Reservation.total_ttc), 0),
            func.count(Reservation.id),
        ).where(
            Reservation.statut.in_(statuts_ok),
            extract("month", Reservation.date_reservation) == mois,
            extract("year",  Reservation.date_reservation) == annee,
        )
    )
    row_mois = r_mois.one()
    rev_mois = float(row_mois[0])
    nb_mois  = int(row_mois[1])

    # Revenus année
    r_annee = await session.execute(
        select(
            func.coalesce(func.sum(Reservation.total_ttc), 0),
            func.count(Reservation.id),
            func.coalesce(func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0),
            func.coalesce(func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)), 0),
        ).where(
            Reservation.statut.in_(statuts_ok),
            extract("year", Reservation.date_reservation) == annee,
        )
    )
    row_annee = r_annee.one()
    rev_annee      = float(row_annee[0])
    nb_annee       = int(row_annee[1])
    rev_hotel_annee  = float(row_annee[2])
    rev_voyage_annee = float(row_annee[3])

    # Commissions
    comm_mois  = round(rev_mois  * TAUX_COMMISSION / 100, 2)
    comm_annee = round(rev_annee * TAUX_COMMISSION / 100, 2)

    # Solde dû partenaires
    r_solde = await session.execute(
        select(
            func.coalesce(func.sum(CommissionPartenaire.montant_partenaire), 0),
            func.count(CommissionPartenaire.id_partenaire.distinct()),
        ).where(CommissionPartenaire.statut == StatutCommission.EN_ATTENTE)
    )
    row_solde = r_solde.one()
    total_du  = float(row_solde[0])
    nb_part_en_attente = int(row_solde[1])

    return FinanceDashboard(
        revenu_total_mois         = rev_mois,
        revenu_total_annee        = rev_annee,
        commission_mois           = comm_mois,
        commission_annee          = comm_annee,
        total_du_partenaires      = total_du,
        nb_partenaires_en_attente = nb_part_en_attente,
        revenu_hotel_annee        = rev_hotel_annee,
        revenu_voyage_annee       = rev_voyage_annee,
        nb_reservations_mois      = nb_mois,
        nb_reservations_annee     = nb_annee,
    )


# ═══════════════════════════════════════════════════════════
#  REVENUS PAR PÉRIODE
# ═══════════════════════════════════════════════════════════

async def get_revenus(
    session: AsyncSession,
    periode: str = "mois",   # jour | mois | annee
    annee: Optional[int] = None,
    mois: Optional[int]  = None,
) -> RevenusResponse:
    now    = datetime.now()
    annee  = annee or now.year
    mois   = mois  or now.month

    statuts_ok = [StatutReservation.CONFIRMEE, StatutReservation.TERMINEE]

    evolution: List[RevenuPeriode] = []

    if periode == "jour":
        # 30 derniers jours du mois sélectionné
        nb_jours = monthrange(annee, mois)[1]
        for jour in range(1, nb_jours + 1):
            d = date(annee, mois, jour)
            r = await session.execute(
                select(
                    func.coalesce(func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0),
                    func.coalesce(func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)), 0),
                    func.count(Reservation.id),
                ).where(
                    Reservation.statut.in_(statuts_ok),
                    func.date(Reservation.date_reservation) == d,
                )
            )
            row = r.one()
            rh = float(row[0]); rv = float(row[1]); nb = int(row[2])
            rt = rh + rv
            evolution.append(RevenuPeriode(
                periode           = d.strftime("%d/%m"),
                revenu_hotel      = rh,
                revenu_voyage     = rv,
                revenu_total      = rt,
                commission_total  = round(rt * TAUX_COMMISSION / 100, 2),
                nb_reservations   = nb,
            ))

    elif periode == "mois":
        # 12 mois de l'année sélectionnée
        for m in range(1, 13):
            r = await session.execute(
                select(
                    func.coalesce(func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0),
                    func.coalesce(func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)), 0),
                    func.count(Reservation.id),
                ).where(
                    Reservation.statut.in_(statuts_ok),
                    extract("month", Reservation.date_reservation) == m,
                    extract("year",  Reservation.date_reservation) == annee,
                )
            )
            row = r.one()
            rh = float(row[0]); rv = float(row[1]); nb = int(row[2])
            rt = rh + rv
            mois_noms = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
            evolution.append(RevenuPeriode(
                periode           = mois_noms[m-1],
                revenu_hotel      = rh,
                revenu_voyage     = rv,
                revenu_total      = rt,
                commission_total  = round(rt * TAUX_COMMISSION / 100, 2),
                nb_reservations   = nb,
            ))

    else:  # annee
        # 5 dernières années
        for a in range(now.year - 4, now.year + 1):
            r = await session.execute(
                select(
                    func.coalesce(func.sum(case((Reservation.id_voyage == None, Reservation.total_ttc), else_=0)), 0),
                    func.coalesce(func.sum(case((Reservation.id_voyage != None, Reservation.total_ttc), else_=0)), 0),
                    func.count(Reservation.id),
                ).where(
                    Reservation.statut.in_(statuts_ok),
                    extract("year", Reservation.date_reservation) == a,
                )
            )
            row = r.one()
            rh = float(row[0]); rv = float(row[1]); nb = int(row[2])
            rt = rh + rv
            evolution.append(RevenuPeriode(
                periode           = str(a),
                revenu_hotel      = rh,
                revenu_voyage     = rv,
                revenu_total      = rt,
                commission_total  = round(rt * TAUX_COMMISSION / 100, 2),
                nb_reservations   = nb,
            ))

    totaux = sum(p.revenu_total for p in evolution)
    comm   = round(totaux * TAUX_COMMISSION / 100, 2)
    rh_tot = sum(p.revenu_hotel  for p in evolution)
    rv_tot = sum(p.revenu_voyage for p in evolution)
    nb_tot = sum(p.nb_reservations for p in evolution)

    return RevenusResponse(
        periode          = periode,
        revenu_total     = round(totaux, 2),
        commission_total = comm,
        revenu_hotel     = round(rh_tot, 2),
        revenu_voyage    = round(rv_tot, 2),
        nb_reservations  = nb_tot,
        evolution        = evolution,
    )


# ═══════════════════════════════════════════════════════════
#  COMMISSIONS
# ═══════════════════════════════════════════════════════════

async def list_commissions(
    session: AsyncSession,
    statut: Optional[str] = None,
    id_partenaire: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
) -> CommissionListResponse:
    query = select(CommissionPartenaire).options(
        selectinload(CommissionPartenaire.partenaire)
    )
    if statut:
        query = query.where(CommissionPartenaire.statut == StatutCommission(statut))
    if id_partenaire:
        query = query.where(CommissionPartenaire.id_partenaire == id_partenaire)

    count_q = select(func.count()).select_from(query.subquery())
    total   = (await session.execute(count_q)).scalar_one()

    query = query.order_by(CommissionPartenaire.date_creation.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    rows  = (await session.execute(query)).scalars().all()

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


async def get_soldes_partenaires(session: AsyncSession) -> SoldesPartenairesResponse:
    """Retourne le solde dû à chaque partenaire (commissions EN_ATTENTE)."""
    r = await session.execute(
        select(
            CommissionPartenaire.id_partenaire,
            func.sum(CommissionPartenaire.montant_partenaire),
            func.count(CommissionPartenaire.id),
        )
        .where(CommissionPartenaire.statut == StatutCommission.EN_ATTENTE)
        .group_by(CommissionPartenaire.id_partenaire)
        .order_by(func.sum(CommissionPartenaire.montant_partenaire).desc())
    )
    rows = r.all()

    items = []
    for row in rows:
        id_p, solde, nb = row[0], float(row[1]), int(row[2])
        # Charger infos partenaire
        usr_r = await session.execute(select(Utilisateur).where(Utilisateur.id == id_p))
        usr   = usr_r.scalar_one_or_none()
        if not usr:
            continue
        items.append(SoldePartenaire(
            id_partenaire     = id_p,
            partenaire_nom    = usr.nom,
            partenaire_prenom = usr.prenom,
            partenaire_email  = usr.email,
            nom_entreprise    = getattr(usr, "nom_entreprise", "—") or "—",
            solde_du          = round(solde, 2),
            nb_commissions    = nb,
        ))

    return SoldesPartenairesResponse(items=items)


async def payer_partenaire(
    id_partenaire: int,
    note: Optional[str],
    session: AsyncSession,
) -> PayerPartenaireResponse:
    """
    Marque toutes les commissions EN_ATTENTE d'un partenaire comme PAYÉE
    et enregistre le paiement dans l'historique.
    """
    # Calculer montant total dû
    r = await session.execute(
        select(func.sum(CommissionPartenaire.montant_partenaire))
        .where(
            CommissionPartenaire.id_partenaire == id_partenaire,
            CommissionPartenaire.statut        == StatutCommission.EN_ATTENTE,
        )
    )
    montant = float(r.scalar_one() or 0)
    if montant <= 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Aucun montant en attente pour ce partenaire.")

    # Marquer toutes les commissions comme PAYÉE
    from sqlalchemy import update
    await session.execute(
        update(CommissionPartenaire)
        .where(
            CommissionPartenaire.id_partenaire == id_partenaire,
            CommissionPartenaire.statut        == StatutCommission.EN_ATTENTE,
        )
        .values(statut=StatutCommission.PAYEE, date_paiement=datetime.now())
    )

    # Enregistrer dans l'historique
    paiement = PaiementPartenaire(
        id_partenaire = id_partenaire,
        montant       = montant,
        note          = note,
    )
    session.add(paiement)
    await session.flush()

    return PayerPartenaireResponse(
        id_partenaire = id_partenaire,
        montant_paye  = montant,
        message       = f"Paiement de {montant:.2f} DT enregistré avec succès.",
    )


async def get_historique_paiements(
    session: AsyncSession,
    id_partenaire: Optional[int] = None,
    page: int = 1,
    per_page: int = 20,
) -> PaiementHistoriqueResponse:
    query = select(PaiementPartenaire).options(
        selectinload(PaiementPartenaire.partenaire)
    )
    if id_partenaire:
        query = query.where(PaiementPartenaire.id_partenaire == id_partenaire)

    count_q = select(func.count()).select_from(query.subquery())
    total   = (await session.execute(count_q)).scalar_one()

    query = query.order_by(PaiementPartenaire.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)
    rows  = (await session.execute(query)).scalars().all()

    items = []
    for p in rows:
        usr = p.partenaire
        items.append(PaiementHistoriqueItem(
            id                = p.id,
            id_partenaire     = p.id_partenaire,
            partenaire_nom    = usr.nom    if usr else "—",
            partenaire_prenom = usr.prenom if usr else "—",
            montant           = float(p.montant),
            note              = p.note,
            created_at        = p.created_at,
        ))

    return PaiementHistoriqueResponse(total=total, page=page, per_page=per_page, items=items)


# ═══════════════════════════════════════════════════════════
#  ANALYSE CLIENTS
# ═══════════════════════════════════════════════════════════

async def get_clients_rentables(
    session: AsyncSession,
    limit: int = 50,
) -> ClientsRentabiliteResponse:
    statuts_ok = [StatutReservation.CONFIRMEE, StatutReservation.TERMINEE]

    r = await session.execute(
        select(
            Reservation.id_client,
            func.sum(Reservation.total_ttc),
            func.count(Reservation.id),
            func.max(Reservation.date_reservation),
        )
        .where(Reservation.statut.in_(statuts_ok), Reservation.id_client != None)
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
            id_client       = id_c,
            nom             = usr.nom,
            prenom          = usr.prenom,
            email           = usr.email,
            telephone       = getattr(usr, "telephone", None),
            total_depenses  = round(float(total), 2),
            nb_reservations = int(nb),
            derniere_resa   = derniere,
        ))

    return ClientsRentabiliteResponse(total=len(items), items=items)