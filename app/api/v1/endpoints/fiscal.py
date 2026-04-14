"""
app/api/v1/endpoints/fiscal.py
================================
Routes :
  GET    /api/v1/fiscal/rules            → Lister toutes les règles [ADMIN]
  PATCH  /api/v1/fiscal/rules/{id}       → Modifier une règle [ADMIN]
  GET    /api/v1/fiscal/simulate         → Simuler (admin, avec auth) [ADMIN]
  GET    /api/v1/fiscal/preview          → Prévisualiser pour client/visiteur [PUBLIC]
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.fiscal import (
    DetailFiscal,
    FiscalRuleListResponse,
    FiscalRuleResponse,
    FiscalRuleUpdate,
)
import app.services.fiscal_service as svc

router = APIRouter(prefix="/fiscal", tags=["Fiscal"])


# ── Admin : lister les règles ─────────────────────────────
@router.get("/rules", response_model=FiscalRuleListResponse,
            summary="Lister toutes les règles fiscales [ADMIN]")
async def list_rules(
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> FiscalRuleListResponse:
    return await svc.list_rules(session)


# ── Admin : modifier une règle ────────────────────────────
@router.patch("/rules/{rule_id}", response_model=FiscalRuleResponse,
              summary="Modifier une règle fiscale [ADMIN]")
async def update_rule(
    rule_id: int,
    data: FiscalRuleUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> FiscalRuleResponse:
    return await svc.update_rule(rule_id, data.model_dump(exclude_none=True), session)


# ── Admin : simulateur ────────────────────────────────────
@router.get("/simulate", response_model=DetailFiscal,
            summary="Simuler un calcul fiscal [ADMIN]")
async def simulate_fiscal(
    montant_ht:    float = Query(..., gt=0),
    nb_nuits:      int   = Query(..., gt=0),
    nb_personnes:  int   = Query(1,  ge=1, description="Adultes + enfants"),
    etoiles_hotel: int   = Query(..., ge=1, le=5),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> DetailFiscal:
    return await svc.calculer_fiscal(
        montant_ht    = montant_ht,
        nb_nuits      = nb_nuits,
        nb_personnes  = nb_personnes,
        etoiles_hotel = etoiles_hotel,
        session       = session,
    )


# ── PUBLIC : prévisualisation pour client/visiteur ────────
@router.get(
    "/preview",
    response_model=DetailFiscal,
    summary="Prévisualiser le détail fiscal d'une réservation [PUBLIC]",
    description="""
Endpoint PUBLIC (sans authentification) appelé par le frontend
pour afficher le détail fiscal dans le récapitulatif de réservation.

Paramètres :
- montant_ht    : prix HT de la chambre (après promo éventuelle)
- nb_nuits      : durée du séjour
- nb_personnes  : adultes + enfants
- etoiles_hotel : classement 1-5
    """,
)
async def preview_fiscal(
    montant_ht:    float = Query(..., gt=0,   description="Montant HT en DT"),
    nb_nuits:      int   = Query(..., gt=0,   description="Nombre de nuits"),
    nb_personnes:  int   = Query(1,  ge=1,   description="Adultes + enfants"),
    etoiles_hotel: int   = Query(..., ge=1, le=5, description="Classement hôtel"),
    session: AsyncSession = Depends(get_db),
) -> DetailFiscal:
    return await svc.calculer_fiscal(
        montant_ht    = montant_ht,
        nb_nuits      = nb_nuits,
        nb_personnes  = nb_personnes,
        etoiles_hotel = etoiles_hotel,
        session       = session,
    )