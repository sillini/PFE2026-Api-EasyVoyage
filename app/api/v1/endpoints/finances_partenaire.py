"""
app/api/v1/endpoints/finances_partenaire.py
============================================
Module Finance — Espace Partenaire.

Routes (toutes protégées [PARTENAIRE]) :
  GET  /finances-partenaire/dashboard
       → KPIs : solde dispo, revenus mois, nb réservations

  GET  /finances-partenaire/revenus
       → Graphique revenus mensuels (12 mois d'une année)
       Params : annee (int, défaut = année courante)

  GET  /finances-partenaire/mes-hotels
       → Liste des hôtels avec résumé financier (clients + visiteurs)

  GET  /finances-partenaire/mes-hotels/{id_hotel}/reservations
       → Réservations d'un hôtel (clients + visiteurs) — drill-down
       Params : page, per_page, statut (CONFIRMEE|TERMINEE|ANNULEE), search

  GET  /finances-partenaire/paiements
       → Historique des virements reçus de l'admin
       Params : page, per_page

  POST /finances-partenaire/demande-retrait
       → Envoie une demande de retrait à l'admin
       Body : { montant: float, note?: str }

Règles de sécurité :
  - require_partenaire → seul un PARTENAIRE peut accéder à ces routes.
  - token.user_id est utilisé dans chaque service → un partenaire ne
    voit JAMAIS les données d'un autre partenaire.
  - Ces routes sont INDÉPENDANTES de /finances (admin) → aucune
    modification des routes existantes.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_partenaire
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.finances_partenaire import (
    PartDashboard,
    PartRevenusResponse,
    PartHotelListResponse,
    PartReservationListResponse,
    PartPaiementsResponse,
    PartDemandeRetraitRequest,
    PartDemandeRetraitResponse,
)
import app.services.finances_partenaire_service as svc

router = APIRouter(
    prefix="/finances-partenaire",
    tags=["Finances — Partenaire"],
)


# ── Dashboard ─────────────────────────────────────────────
@router.get(
    "/dashboard",
    response_model=PartDashboard,
    summary="KPIs financiers du partenaire connecté [PARTENAIRE]",
)
async def dashboard(
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartDashboard:
    return await svc.get_dashboard(token.user_id, session)


# ── Revenus mensuels (graphique) ─────────────────────────
@router.get(
    "/revenus",
    response_model=PartRevenusResponse,
    summary="Revenus mensuels sur 12 mois [PARTENAIRE]",
)
async def revenus_mensuels(
    annee:   int           = Query(default=None, description="Année (défaut : année courante)"),
    session: AsyncSession  = Depends(get_db),
    token:   TokenData     = Depends(require_partenaire),
) -> PartRevenusResponse:
    if annee is None:
        annee = datetime.now().year
    return await svc.get_revenus_mensuels(token.user_id, annee, session)


# ── Mes hôtels ───────────────────────────────────────────
@router.get(
    "/mes-hotels",
    response_model=PartHotelListResponse,
    summary="Liste des hôtels avec résumé financier [PARTENAIRE]",
)
async def mes_hotels(
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartHotelListResponse:
    return await svc.get_mes_hotels(token.user_id, session)


# ── Réservations d'un hôtel (drill-down) ─────────────────
@router.get(
    "/mes-hotels/{id_hotel}/reservations",
    response_model=PartReservationListResponse,
    summary="Réservations d'un hôtel (clients + visiteurs) [PARTENAIRE]",
)
async def reservations_hotel(
    id_hotel:  int,
    page:      int           = Query(1,    ge=1),
    per_page:  int           = Query(20,   ge=1, le=100),
    statut:    Optional[str] = Query(None, description="CONFIRMEE | TERMINEE | ANNULEE"),
    search:    Optional[str] = Query(None, description="Recherche sur nom ou email"),
    session:   AsyncSession  = Depends(get_db),
    token:     TokenData     = Depends(require_partenaire),
) -> PartReservationListResponse:
    return await svc.get_reservations_hotel(
        id_partenaire=token.user_id,
        id_hotel=id_hotel,
        session=session,
        page=page,
        per_page=per_page,
        statut=statut,
        search=search,
    )


# ── Paiements reçus ───────────────────────────────────────
@router.get(
    "/paiements",
    response_model=PartPaiementsResponse,
    summary="Historique des paiements reçus de l'admin [PARTENAIRE]",
)
async def paiements_recus(
    page:     int           = Query(1,  ge=1),
    per_page: int           = Query(20, ge=1, le=100),
    session:  AsyncSession  = Depends(get_db),
    token:    TokenData     = Depends(require_partenaire),
) -> PartPaiementsResponse:
    return await svc.get_paiements_recus(token.user_id, session, page, per_page)


# ── Demande de retrait ────────────────────────────────────
@router.post(
    "/demande-retrait",
    response_model=PartDemandeRetraitResponse,
    summary="Envoyer une demande de retrait à l'admin [PARTENAIRE]",
)
async def demande_retrait(
    body:    PartDemandeRetraitRequest,
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartDemandeRetraitResponse:
    return await svc.demander_retrait(token.user_id, body, session)