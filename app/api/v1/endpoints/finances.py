"""
app/api/v1/endpoints/finances.py
=================================
Module de gestion financière / comptabilité — endpoints ADMIN.

Routes :
  GET  /finances/dashboard           → KPIs financiers globaux
  GET  /finances/revenus             → Revenus par période (jour/mois/année)
  GET  /finances/commissions         → Liste des commissions
  GET  /finances/soldes-partenaires  → Soldes dus aux partenaires
  POST /finances/payer/{id}          → Effectuer un paiement partenaire
  GET  /finances/paiements           → Historique des paiements
  GET  /finances/clients-rentables   → Classement clients par dépenses
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.finances import (
    FinanceDashboard, RevenusResponse, CommissionListResponse,
    SoldesPartenairesResponse, PayerPartenaireRequest, PayerPartenaireResponse,
    PaiementHistoriqueResponse, ClientsRentabiliteResponse,
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
    _: TokenData = Depends(require_admin),
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
    page:          int           = Query(1, ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    session: AsyncSession        = Depends(get_db),
    _: TokenData                 = Depends(require_admin),
) -> CommissionListResponse:
    return await svc.list_commissions(session, statut=statut, id_partenaire=id_partenaire, page=page, per_page=per_page)


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
    description="""
Marque toutes les commissions EN_ATTENTE du partenaire comme PAYÉE
et enregistre le paiement dans l'historique.
Le solde du partenaire est remis à 0 après paiement.
    """,
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
    id_partenaire: Optional[int] = Query(None),
    page:          int           = Query(1, ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    session: AsyncSession        = Depends(get_db),
    _: TokenData                 = Depends(require_admin),
) -> PaiementHistoriqueResponse:
    return await svc.get_historique_paiements(session, id_partenaire=id_partenaire, page=page, per_page=per_page)


# ── Clients rentables ─────────────────────────────────────
@router.get(
    "/clients-rentables",
    response_model=ClientsRentabiliteResponse,
    summary="Classement clients par dépenses [ADMIN]",
)
async def clients_rentables(
    limit:   int           = Query(50, ge=1, le=200),
    session: AsyncSession  = Depends(get_db),
    _: TokenData           = Depends(require_admin),
) -> ClientsRentabiliteResponse:
    return await svc.get_clients_rentables(session, limit=limit)