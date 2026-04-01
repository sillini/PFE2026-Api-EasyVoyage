"""
app/api/v1/endpoints/finances.py
=================================
Module de gestion financière — endpoints ADMIN.

Routes :
  GET  /finances/dashboard
  GET  /finances/revenus
  GET  /finances/commissions
  GET  /finances/soldes-partenaires
  POST /finances/payer/{id}
  GET  /finances/paiements
  GET  /finances/paiements/{id}/pdf
  POST /finances/paiements/{id}/renvoyer-email
  GET  /finances/partenaires
  GET  /finances/partenaires/{id}/hotels
  GET  /finances/partenaires/{id}/hotels/{id}/reservations
  GET  /finances/classement-clients
  GET  /finances/demandes-retrait
  POST /finances/demandes-retrait/{id}/valider
  POST /finances/demandes-retrait/{id}/refuser
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.models.finances import PaiementPartenaire
from app.models.utilisateur import Utilisateur
from app.schemas.auth import TokenData
from app.schemas.finances import (
    FinanceDashboard,
    RevenusResponse,
    CommissionListResponse,
    SoldesPartenairesResponse,
    PayerPartenaireRequest,
    PayerPartenaireResponse,
    PaiementHistoriqueResponse,
    PartenaireFinanceListResponse,
    HotelFinanceListResponse,
    ReservationFinanceListResponse,
    ClientsVisiteursRentabiliteResponse,
    DemandesRetraitResponse,
    ValiderDemandeRequest,
    RefuserDemandeRequest,
    DemandeActionResponse,
)
import app.services.finances as svc

router = APIRouter(prefix="/finances", tags=["Finances"])


# ── Dashboard ─────────────────────────────────────────────
@router.get("/dashboard", response_model=FinanceDashboard,
            summary="KPIs financiers globaux [ADMIN]")
async def dashboard(
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> FinanceDashboard:
    return await svc.get_dashboard(session)


# ── Revenus ───────────────────────────────────────────────
@router.get("/revenus", response_model=RevenusResponse,
            summary="Revenus par période [ADMIN]")
async def revenus(
    periode: str           = Query("mois", description="jour | mois | annee"),
    annee:   Optional[int] = Query(None),
    mois:    Optional[int] = Query(None),
    session: AsyncSession  = Depends(get_db),
    _: TokenData           = Depends(require_admin),
) -> RevenusResponse:
    return await svc.get_revenus(session, periode=periode, annee=annee, mois=mois)


# ── Commissions ───────────────────────────────────────────
@router.get("/commissions", response_model=CommissionListResponse,
            summary="Liste des commissions partenaires [ADMIN]")
async def commissions(
    statut:        Optional[str] = Query(None, description="EN_ATTENTE | PAYEE"),
    id_partenaire: Optional[int] = Query(None),
    page:          int           = Query(1,  ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    session: AsyncSession        = Depends(get_db),
    _: TokenData                 = Depends(require_admin),
) -> CommissionListResponse:
    return await svc.list_commissions(
        session, statut=statut, id_partenaire=id_partenaire, page=page, per_page=per_page,
    )


# ── Soldes partenaires ────────────────────────────────────
@router.get("/soldes-partenaires", response_model=SoldesPartenairesResponse,
            summary="Soldes dus à chaque partenaire [ADMIN]")
async def soldes_partenaires(
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> SoldesPartenairesResponse:
    return await svc.get_soldes_partenaires(session)


# ── Payer un partenaire ───────────────────────────────────
@router.post("/payer/{id_partenaire}", response_model=PayerPartenaireResponse,
             summary="Effectuer un paiement partenaire [ADMIN]")
async def payer_partenaire(
    id_partenaire: int,
    body:    PayerPartenaireRequest = PayerPartenaireRequest(),
    session: AsyncSession           = Depends(get_db),
    _: TokenData                    = Depends(require_admin),
) -> PayerPartenaireResponse:
    return await svc.payer_partenaire(
        id_partenaire=id_partenaire, note=body.note or "", session=session
    )


# ── Historique paiements ──────────────────────────────────
@router.get("/paiements", response_model=PaiementHistoriqueResponse,
            summary="Historique des paiements partenaires [ADMIN]")
async def historique_paiements(
    id_partenaire: Optional[int]   = Query(None),
    date_debut:    Optional[date]  = Query(None),
    date_fin:      Optional[date]  = Query(None),
    montant_min:   Optional[float] = Query(None, ge=0),
    montant_max:   Optional[float] = Query(None, ge=0),
    search:        Optional[str]   = Query(None),
    page:          int             = Query(1,  ge=1),
    per_page:      int             = Query(20, ge=1, le=100),
    session: AsyncSession          = Depends(get_db),
    _: TokenData                   = Depends(require_admin),
) -> PaiementHistoriqueResponse:
    return await svc.get_historique_paiements(
        session,
        id_partenaire=id_partenaire,
        date_debut=date_debut,
        date_fin=date_fin,
        montant_min=montant_min,
        montant_max=montant_max,
        search=search,
        page=page,
        per_page=per_page,
    )


# ── Télécharger facture PDF d'un paiement ─────────────────
@router.get("/paiements/{paiement_id}/pdf",
            summary="Télécharger la facture d'un paiement partenaire [ADMIN]")
async def telecharger_facture_paiement_admin(
    paiement_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    p = (await session.execute(
        select(PaiementPartenaire).where(PaiementPartenaire.id == paiement_id)
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


# ── Renvoyer email de paiement ────────────────────────────
@router.post("/paiements/{paiement_id}/renvoyer-email",
             summary="Renvoyer l'email de paiement au partenaire [ADMIN]")
async def renvoyer_email_paiement(
    paiement_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    from app.models.utilisateur import Partenaire as PartenaireModel
    from app.services.email_service import send_paiement_partenaire_email

    p = (await session.execute(
        select(PaiementPartenaire).where(PaiementPartenaire.id == paiement_id)
    )).scalar_one_or_none()

    if not p:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    if not p.pdf_data:
        raise HTTPException(status_code=404, detail="Aucune facture PDF disponible")

    usr = (await session.execute(
        select(Utilisateur).where(Utilisateur.id == p.id_partenaire)
    )).scalar_one_or_none()

    part = (await session.execute(
        select(PartenaireModel).where(PartenaireModel.id == p.id_partenaire)
    )).scalar_one_or_none()

    if not usr or not usr.email:
        raise HTTPException(status_code=400, detail="Email partenaire introuvable")

    await send_paiement_partenaire_email(
        to             = usr.email,
        prenom         = usr.prenom or "",
        nom            = usr.nom    or "",
        nom_entreprise = part.nom_entreprise if part else "—",
        numero_facture = p.numero_facture or f"PAY-{p.id}",
        montant        = float(p.montant),
        date_paiement  = p.created_at.strftime("%d/%m/%Y") if p.created_at else "—",
        note           = p.note or "",
        pdf_bytes      = bytes(p.pdf_data),
    )

    return {"success": True, "message": f"Email renvoyé à {usr.email}"}


# ── Partenaires avec KPIs financiers ─────────────────────
@router.get("/partenaires", response_model=PartenaireFinanceListResponse,
            summary="Partenaires avec données financières [ADMIN]")
async def partenaires_finances(
    search:   Optional[str] = Query(None),
    page:     int           = Query(1,  ge=1),
    per_page: int           = Query(20, ge=1, le=100),
    session: AsyncSession   = Depends(get_db),
    _: TokenData            = Depends(require_admin),
) -> PartenaireFinanceListResponse:
    return await svc.get_partenaires_finances(
        session, page=page, per_page=per_page, search=search,
    )


# ── Hôtels d'un partenaire ────────────────────────────────
@router.get("/partenaires/{id_partenaire}/hotels",
            response_model=HotelFinanceListResponse,
            summary="Hôtels d'un partenaire avec données financières [ADMIN]")
async def hotels_partenaire(
    id_partenaire: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> HotelFinanceListResponse:
    return await svc.get_hotels_finances_partenaire(id_partenaire, session)


# ── Réservations d'un hôtel ───────────────────────────────
@router.get("/partenaires/{id_partenaire}/hotels/{id_hotel}/reservations",
            response_model=ReservationFinanceListResponse,
            summary="Réservations d'un hôtel avec données financières [ADMIN]")
async def reservations_hotel(
    id_partenaire:     int,
    id_hotel:          int,
    statut_commission: Optional[str] = Query(None, description="EN_ATTENTE | PAYEE"),
    page:              int           = Query(1,   ge=1),
    per_page:          int           = Query(20,  ge=1, le=1000),
    session: AsyncSession            = Depends(get_db),
    _: TokenData                     = Depends(require_admin),
) -> ReservationFinanceListResponse:
    return await svc.get_reservations_finances_hotel(
        id_hotel=id_hotel, id_partenaire=id_partenaire,
        session=session, statut_commission=statut_commission,
        page=page, per_page=per_page,
    )


# ── Classement clients + visiteurs ────────────────────────
@router.get("/classement-clients", response_model=ClientsVisiteursRentabiliteResponse,
            summary="Classement clients et visiteurs [ADMIN]")
async def classement_clients(
    critere: str = Query("depenses"),
    limit:   int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> ClientsVisiteursRentabiliteResponse:
    return await svc.get_clients_visiteurs_classement(session, critere=critere, limit=limit)


# ── Demandes de retrait ───────────────────────────────────
@router.get("/demandes-retrait", response_model=DemandesRetraitResponse,
            summary="Liste des demandes de retrait partenaires [ADMIN]")
async def demandes_retrait(
    statut:        Optional[str] = Query(None, description="EN_ATTENTE | APPROUVEE | REFUSEE"),
    id_partenaire: Optional[int] = Query(None),
    page:          int           = Query(1,  ge=1),
    per_page:      int           = Query(20, ge=1, le=100),
    session: AsyncSession        = Depends(get_db),
    _: TokenData                 = Depends(require_admin),
) -> DemandesRetraitResponse:
    return await svc.get_demandes_retrait(session, statut, id_partenaire, page, per_page)


@router.post("/demandes-retrait/{demande_id}/valider",
             response_model=DemandeActionResponse,
             summary="Valider une demande de retrait [ADMIN]")
async def valider_demande(
    demande_id: int,
    body:    ValiderDemandeRequest = ValiderDemandeRequest(),
    session: AsyncSession          = Depends(get_db),
    _: TokenData                   = Depends(require_admin),
) -> DemandeActionResponse:
    return await svc.valider_demande_retrait(demande_id, body.note_admin, session)


@router.post("/demandes-retrait/{demande_id}/refuser",
             response_model=DemandeActionResponse,
             summary="Refuser une demande de retrait [ADMIN]")
async def refuser_demande(
    demande_id: int,
    body:    RefuserDemandeRequest = RefuserDemandeRequest(),
    session: AsyncSession          = Depends(get_db),
    _: TokenData                   = Depends(require_admin),
) -> DemandeActionResponse:
    return await svc.refuser_demande_retrait(demande_id, body.note_admin, session)