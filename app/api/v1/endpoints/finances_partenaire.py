"""
app/api/v1/endpoints/finances_partenaire.py
============================================
Routes Finance — Espace Partenaire.

  GET  /finances-partenaire/dashboard
  GET  /finances-partenaire/revenus
  GET  /finances-partenaire/mes-hotels
  GET  /finances-partenaire/mes-hotels/{id_hotel}/reservations
  GET  /finances-partenaire/paiements
  GET  /finances-partenaire/paiements/{paiement_id}/pdf
  POST /finances-partenaire/demande-retrait
  GET  /finances-partenaire/mes-demandes
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
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
    PartDemandesResponse,
)
import app.services.finances_partenaire_service as svc

router = APIRouter(
    prefix="/finances-partenaire",
    tags=["Finances — Partenaire"],
)


# ── Dashboard ─────────────────────────────────────────────
@router.get("/dashboard", response_model=PartDashboard,
            summary="KPIs financiers du partenaire connecté [PARTENAIRE]")
async def dashboard(
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartDashboard:
    return await svc.get_dashboard(token.user_id, session)


# ── Revenus mensuels ──────────────────────────────────────
@router.get("/revenus", response_model=PartRevenusResponse,
            summary="Revenus mensuels sur 12 mois [PARTENAIRE]")
async def revenus_mensuels(
    annee:   int          = Query(default=None, description="Année (défaut : année courante)"),
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartRevenusResponse:
    if annee is None:
        annee = datetime.now().year
    return await svc.get_revenus_mensuels(token.user_id, annee, session)


# ── Mes hôtels ────────────────────────────────────────────
@router.get("/mes-hotels", response_model=PartHotelListResponse,
            summary="Liste des hôtels avec résumé financier [PARTENAIRE]")
async def mes_hotels(
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartHotelListResponse:
    return await svc.get_mes_hotels(token.user_id, session)


# ── Réservations d'un hôtel ───────────────────────────────
 
@router.get("/mes-hotels/{id_hotel}/reservations",
            response_model=PartReservationListResponse,
            summary="Réservations d'un hôtel (clients + visiteurs) [PARTENAIRE]")
async def reservations_hotel(
    id_hotel:       int,
    page:           int           = Query(1,    ge=1),
    per_page:       int           = Query(20,   ge=1, le=200),
    statut:         Optional[str] = Query(None, description="CONFIRMEE | TERMINEE | ANNULEE"),
    search:         Optional[str] = Query(None, description="Recherche sur nom ou email"),
    numero_facture: Optional[str] = Query(None, description="Recherche par N° facture"),
    session:   AsyncSession  = Depends(get_db),
    token:     TokenData     = Depends(require_partenaire),
) -> PartReservationListResponse:
    return await svc.get_reservations_hotel(
        id_partenaire  = token.user_id,
        id_hotel       = id_hotel,
        session        = session,
        page           = page,
        per_page       = per_page,
        statut         = statut,
        search         = search,
        numero_facture = numero_facture,
    )

# ── Paiements reçus ───────────────────────────────────────
@router.get("/paiements", response_model=PartPaiementsResponse,
            summary="Historique des paiements reçus de l'admin [PARTENAIRE]")
async def paiements_recus(
    page:     int          = Query(1,  ge=1),
    per_page: int          = Query(20, ge=1, le=100),
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
) -> PartPaiementsResponse:
    return await svc.get_paiements_recus(token.user_id, session, page, per_page)


# ── Télécharger facture PDF d'un paiement ─────────────────
@router.get("/paiements/{paiement_id}/pdf",
            summary="Télécharger ma facture de paiement [PARTENAIRE]")
async def telecharger_ma_facture(
    paiement_id: int,
    session:     AsyncSession = Depends(get_db),
    token:       TokenData    = Depends(require_partenaire),
):
    from app.models.finances import PaiementPartenaire as PP

    p = (await session.execute(
        select(PP).where(
            PP.id == paiement_id,
            PP.id_partenaire == token.user_id,  # sécurité : son paiement uniquement
        )
    )).scalar_one_or_none()

    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    if not p.pdf_data:
        raise HTTPException(status_code=404, detail="Aucune facture PDF disponible pour ce paiement")

    filename = f"{p.numero_facture}.pdf" if p.numero_facture else f"facture_{paiement_id}.pdf"
    return Response(
        content=bytes(p.pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Demande de retrait ────────────────────────────────────
@router.post("/demande-retrait", response_model=PartDemandeRetraitResponse,
             summary="Envoyer une demande de retrait à l'admin [PARTENAIRE]")
async def demande_retrait(
    body:    PartDemandeRetraitRequest,
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_partenaire),
) -> PartDemandeRetraitResponse:
    return await svc.demander_retrait(token.user_id, body, session)


# ── Historique de mes demandes ────────────────────────────
@router.get("/mes-demandes", response_model=PartDemandesResponse,
            summary="Historique de mes demandes de retrait [PARTENAIRE]")
async def mes_demandes(
    page:     int          = Query(1,  ge=1),
    per_page: int          = Query(20, ge=1, le=100),
    session:  AsyncSession = Depends(get_db),
    token:    TokenData    = Depends(require_partenaire),
) -> PartDemandesResponse:
    return await svc.get_mes_demandes(token.user_id, session, page, per_page)