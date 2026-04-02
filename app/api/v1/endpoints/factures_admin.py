"""
app/api/v1/endpoints/factures_admin.py
========================================
Endpoints Admin — Page Factures.

Routes :
  GET  /factures/admin/kpis              → KPIs globaux [ADMIN]
  GET  /factures/admin                   → Liste unifiée paginée [ADMIN]
  GET  /factures/admin/{id}/detail       → Détail enrichi [ADMIN]
  GET  /factures/admin/{id}/pdf          → Télécharger PDF [ADMIN]

Paramètres de filtre (GET /factures/admin) :
  - type       : "client" | "visiteur" | "partenaire"  (onglet actif)
  - statut     : "EMISE" | "PAYEE" | "ANNULEE" | "EN_RETARD"
  - search     : recherche libre (nom, email, n° facture)
  - date_debut : YYYY-MM-DD
  - date_fin   : YYYY-MM-DD
  - page       : int (défaut 1)
  - per_page   : int (défaut 20, max 100)

⚠️  Ce fichier doit être inclus dans app/api/v1/router.py :
    from app.api.v1.endpoints.factures_admin import router as factures_admin_router
    api_router.include_router(factures_admin_router)
"""
from datetime import date
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.factures_admin import (
    FacturesKpis,
    FactureAdminDetail,
    FacturesAdminListResponse,
)
import app.services.factures_admin_service as svc

router = APIRouter(prefix="/factures/admin", tags=["Admin — Factures"])


# ═══════════════════════════════════════════════════════════
#  KPIs GLOBAUX
# ═══════════════════════════════════════════════════════════

@router.get(
    "/kpis",
    response_model=FacturesKpis,
    summary="KPIs globaux de la page Factures [ADMIN]",
    description="""
Retourne les compteurs et totaux affichés dans les cartes en haut de la page :
- Total facturé (clients + visiteurs)
- Nombre de factures payées / émises / en retard
- Total versé aux partenaires
    """,
)
async def get_kpis(
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> FacturesKpis:
    return await svc.get_kpis(session)


# ═══════════════════════════════════════════════════════════
#  LISTE UNIFIÉE
# ═══════════════════════════════════════════════════════════

@router.get(
    "",
    response_model=FacturesAdminListResponse,
    summary="Liste unifiée des factures [ADMIN]",
    description="""
Retourne une liste paginée et filtrée fusionnant les trois types de factures :
- **client** : factures des réservations clients connectés
- **visiteur** : factures des réservations sans compte
- **partenaire** : paiements admin → partenaires (avec leur PDF)

Le paramètre `type` permet de n'afficher qu'un seul onglet à la fois.
Sans `type`, les trois catégories sont fusionnées et triées par date décroissante.
    """,
)
async def list_factures_admin(
    type_: Optional[str] = Query(
        None,
        alias="type",
        description="Filtrer par type : client | visiteur | partenaire",
    ),
    statut: Optional[str] = Query(
        None,
        description="Statut facture : EMISE | PAYEE | ANNULEE | EN_RETARD (ignoré pour les partenaires)",
    ),
    search: Optional[str] = Query(
        None,
        description="Recherche libre : nom, email, numéro facture, hôtel…",
    ),
    date_debut: Optional[date] = Query(
        None,
        description="Date d'émission minimale (YYYY-MM-DD)",
    ),
    date_fin: Optional[date] = Query(
        None,
        description="Date d'émission maximale (YYYY-MM-DD)",
    ),
    page:     int = Query(1,  ge=1),
    per_page: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> FacturesAdminListResponse:
    # Valider le type si fourni
    valid_types = ("client", "visiteur", "partenaire")
    if type_ and type_ not in valid_types:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"type invalide. Valeurs acceptées : {', '.join(valid_types)}",
        )

    return await svc.list_factures_admin(
        session    = session,
        type_      = type_,       # type: ignore
        statut     = statut,
        search     = search,
        date_debut = date_debut,
        date_fin   = date_fin,
        page       = page,
        per_page   = per_page,
    )


# ═══════════════════════════════════════════════════════════
#  DÉTAIL D'UNE FACTURE
# ═══════════════════════════════════════════════════════════

@router.get(
    "/{facture_id}/detail",
    response_model=FactureAdminDetail,
    summary="Détail enrichi d'une facture [ADMIN]",
    description="""
Retourne toutes les informations d'une facture :
- Informations client / visiteur / partenaire
- Lignes de détail (chambre, voyage, commission)
- Statut, montant, numéro

Le paramètre `type` est **obligatoire** pour savoir dans quelle table chercher.
    """,
)
async def get_facture_detail(
    facture_id: int,
    type_: str = Query(
        ...,
        alias="type",
        description="Type : client | visiteur | partenaire",
    ),
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> FactureAdminDetail:
    valid_types = ("client", "visiteur", "partenaire")
    if type_ not in valid_types:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"type invalide. Valeurs acceptées : {', '.join(valid_types)}",
        )

    return await svc.get_facture_detail(
        facture_id = facture_id,
        type_      = type_,  # type: ignore
        session    = session,
    )


# ═══════════════════════════════════════════════════════════
#  TÉLÉCHARGER PDF
# ═══════════════════════════════════════════════════════════

@router.get(
    "/{facture_id}/pdf",
    summary="Télécharger le PDF d'une facture [ADMIN]",
    description="""
Génère et retourne le PDF de la facture en téléchargement.

- Pour les **clients** : facture standard avec détail de la réservation
- Pour les **visiteurs** : voucher PDF avec le détail de la réservation
- Pour les **partenaires** : PDF de paiement commission stocké en base

Le paramètre `type` est **obligatoire**.
    """,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Fichier PDF",
        }
    },
)
async def telecharger_pdf(
    facture_id: int,
    type_: str = Query(
        ...,
        alias="type",
        description="Type : client | visiteur | partenaire",
    ),
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
) -> Response:
    valid_types = ("client", "visiteur", "partenaire")
    if type_ not in valid_types:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422,
            detail=f"type invalide. Valeurs acceptées : {', '.join(valid_types)}",
        )

    pdf_bytes, filename = await svc.get_pdf_bytes(
        facture_id = facture_id,
        type_      = type_,  # type: ignore
        session    = session,
    )

    return Response(
        content    = pdf_bytes,
        media_type = "application/pdf",
        headers    = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length":      str(len(pdf_bytes)),
        },
    )