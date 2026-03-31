"""
app/api/v1/endpoints/finances.py
=================================
Module de gestion financière / comptabilité — endpoints ADMIN.

Routes :
  GET  /finances/dashboard                                        → KPIs financiers globaux
  GET  /finances/revenus                                          → Revenus par période
  GET  /finances/commissions                                      → Liste des commissions
  GET  /finances/soldes-partenaires                               → Soldes dus aux partenaires
  POST /finances/payer/{id}                                       → Effectuer un paiement
  GET  /finances/paiements                                        → Historique des paiements
  GET  /finances/clients-rentables                                → Classement clients
  GET  /finances/partenaires                                      → Partenaires avec KPIs financiers
  GET  /finances/partenaires/{id}/hotels                          → Hôtels d'un partenaire
  GET  /finances/partenaires/{id}/hotels/{id}/reservations        → Réservations d'un hôtel
  GET  /finances/classement-clients                               → Clients + visiteurs multi-critères
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.finances import (
    FinanceDashboard, RevenusResponse,
    CommissionListResponse,
    SoldesPartenairesResponse, PayerPartenaireRequest, PayerPartenaireResponse,
    PaiementHistoriqueResponse, ClientsRentabiliteResponse,
    PartenaireFinanceListResponse, HotelFinanceListResponse,
    ReservationFinanceListResponse, ClientsVisiteursRentabiliteResponse,
)
import app.services.finances_service as svc

router = APIRouter(prefix="/finances", tags=["Finances"])


# ── Dashboard ─────────────────────────────────────────────
@router.get(
    "/dashboard",
    response_model=FinanceDashboard,
    summary="KPIs financiers globaux [ADMIN]",
)
async def dashboard(
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> FinanceDashboard:
    return await svc.get_dashboard(session)


# ── Revenus ───────────────────────────────────────────────
@router.get(
    "/revenus",
    response_model=RevenusResponse,
    summary="Revenus par période [ADMIN]",
)
async def revenus(
    periode: str           = Query("mois", description="jour | mois | annee"),
    annee:   Optional[int] = Query(None,   description="Année (défaut: année courante)"),
    mois:    Optional[int] = Query(None,   description="Mois 1-12 (pour période=jour)"),
    session: AsyncSession  = Depends(get_db),
    _: TokenData           = Depends(require_admin),
) -> RevenusResponse:
    return await svc.get_revenus(session, periode=periode, annee=annee, mois=mois)


# ── Commissions ───────────────────────────────────────────
@router.get(
    "/commissions",
    response_model=CommissionListResponse,
    summary="Liste des commissions partenaires [ADMIN]",
)
async def commissions(
    statut:        Optional[str] = Query(None, description="EN_ATTENTE | PAYEE"),
    id_partenaire: Optional[int] = Query(None),
    page:          int           = Query(1,  ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    session: AsyncSession        = Depends(get_db),
    _: TokenData                 = Depends(require_admin),
) -> CommissionListResponse:
    return await svc.list_commissions(
        session, statut=statut, id_partenaire=id_partenaire, page=page, per_page=per_page
    )


# ── Soldes partenaires ────────────────────────────────────
@router.get(
    "/soldes-partenaires",
    response_model=SoldesPartenairesResponse,
    summary="Soldes dus à chaque partenaire [ADMIN]",
)
async def soldes_partenaires(
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> SoldesPartenairesResponse:
    return await svc.get_soldes_partenaires(session)


# ── Payer un partenaire ───────────────────────────────────
@router.post(
    "/payer/{id_partenaire}",
    response_model=PayerPartenaireResponse,
    summary="Effectuer un paiement partenaire [ADMIN]",
)
async def payer_partenaire(
    id_partenaire: int,
    body:    PayerPartenaireRequest = PayerPartenaireRequest(),
    session: AsyncSession           = Depends(get_db),
    _: TokenData                    = Depends(require_admin),
) -> PayerPartenaireResponse:
    result = await svc.payer_partenaire(id_partenaire, body.note, session)
    await session.commit()
    return result


# ── Historique paiements ──────────────────────────────────
@router.get(
    "/paiements",
    response_model=PaiementHistoriqueResponse,
    summary="Historique des paiements aux partenaires [ADMIN]",
)
async def historique_paiements(
    id_partenaire: Optional[int]  = Query(None),
    date_debut:    Optional[date] = Query(None, description="Format: YYYY-MM-DD"),
    date_fin:      Optional[date] = Query(None, description="Format: YYYY-MM-DD"),
    page:          int            = Query(1,  ge=1),
    per_page:      int            = Query(20, ge=1, le=100),
    session: AsyncSession         = Depends(get_db),
    _: TokenData                  = Depends(require_admin),
) -> PaiementHistoriqueResponse:
    return await svc.get_historique_paiements(
        session, id_partenaire=id_partenaire,
        date_debut=date_debut, date_fin=date_fin,
        page=page, per_page=per_page,
    )


# ── Clients rentables ─────────────────────────────────────
@router.get(
    "/clients-rentables",
    response_model=ClientsRentabiliteResponse,
    summary="Classement clients par dépenses [ADMIN]",
)
async def clients_rentables(
    limit:   int          = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> ClientsRentabiliteResponse:
    return await svc.get_clients_rentables(session, limit=limit)


# ════════════════════════════════════════════════════════════
#  NOUVEAUX ENDPOINTS — DRILL-DOWN FINANCIER
# ════════════════════════════════════════════════════════════

# ── Partenaires avec KPIs financiers ─────────────────────
@router.get(
    "/partenaires",
    response_model=PartenaireFinanceListResponse,
    summary="Liste partenaires avec données financières [ADMIN]",
)
async def partenaires_finances(
    page:     int           = Query(1,  ge=1),
    per_page: int           = Query(20, ge=1, le=100),
    search:   Optional[str] = Query(None, description="Recherche par nom/entreprise"),
    session: AsyncSession   = Depends(get_db),
    _: TokenData            = Depends(require_admin),
) -> PartenaireFinanceListResponse:
    return await svc.get_partenaires_finances(session, page=page, per_page=per_page, search=search)


# ── Hôtels d'un partenaire avec KPIs ─────────────────────
@router.get(
    "/partenaires/{id_partenaire}/hotels",
    response_model=HotelFinanceListResponse,
    summary="Hôtels d'un partenaire avec données financières [ADMIN]",
)
async def hotels_finances_partenaire(
    id_partenaire: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> HotelFinanceListResponse:
    return await svc.get_hotels_finances_partenaire(id_partenaire, session)


# ── Réservations d'un hôtel avec KPIs ────────────────────
@router.get(
    "/partenaires/{id_partenaire}/hotels/{id_hotel}/reservations",
    response_model=ReservationFinanceListResponse,
    summary="Réservations d'un hôtel avec données financières [ADMIN]",
)
async def reservations_finances_hotel(
    id_partenaire:     int,
    id_hotel:          int,
    statut_commission: Optional[str] = Query(None, description="EN_ATTENTE | PAYEE"),
    page:              int           = Query(1,  ge=1),
    per_page:          int           = Query(20, ge=1, le=100),
    session: AsyncSession            = Depends(get_db),
    _: TokenData                     = Depends(require_admin),
) -> ReservationFinanceListResponse:
    return await svc.get_reservations_finances_hotel(
        id_hotel=id_hotel, id_partenaire=id_partenaire,
        session=session, statut_commission=statut_commission,
        page=page, per_page=per_page,
    )


# ── Classement clients + visiteurs multi-critères ─────────
@router.get(
    "/classement-clients",
    response_model=ClientsVisiteursRentabiliteResponse,
    summary="Classement clients et visiteurs multi-critères [ADMIN]",
)
async def classement_clients_visiteurs(
    critere: str = Query(
        "depenses",
        description="depenses | commissions | nb_hotel | nb_voyage | nb_reservations",
    ),
    limit:   int          = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> ClientsVisiteursRentabiliteResponse:
    return await svc.get_clients_visiteurs_classement(session, critere=critere, limit=limit)