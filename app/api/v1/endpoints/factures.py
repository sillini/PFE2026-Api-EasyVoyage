"""
Endpoints Factures.

  GET  /api/v1/factures                  — Liste toutes les factures [ADMIN]
  GET  /api/v1/factures/{id}             — Détail d'une facture [CLIENT (la sienne) | ADMIN]
  GET  /api/v1/factures/{id}/pdf         — Télécharger le PDF [CLIENT (la sienne) | ADMIN]
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.reservation import FactureResponse
import app.services.facture_service as facture_service

router = APIRouter(prefix="/factures", tags=["Factures"])


@router.get(
    "",
    summary="Toutes les factures [ADMIN]",
    response_model=dict,
)
async def list_factures(
    statut: Optional[str] = Query(
        None,
        description="Filtrer par statut : EMISE | PAYEE | ANNULEE | EN_RETARD"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await facture_service.list_factures(
        session, statut=statut, page=page, per_page=per_page
    )


@router.get(
    "/{facture_id}",
    response_model=FactureResponse,
    summary="Détail d'une facture [CLIENT (la sienne) | ADMIN]",
)
async def get_facture(
    facture_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
) -> FactureResponse:
    return await facture_service.get_facture(
        facture_id, token.user_id, token.role, session
    )


@router.get(
    "/{facture_id}/pdf",
    summary="Télécharger la facture en PDF [CLIENT (la sienne) | ADMIN]",
    description="""
Génère et retourne le PDF de la facture directement en téléchargement.

Le PDF contient :
- En-tête avec le nom de l'agence
- Informations du client
- Détail des prestations (voyage ou chambres)
- Récapitulatif des montants avec total TTC
    """,
    responses={
        200: {
            "content": {"application/pdf": {}},
            "description": "Fichier PDF de la facture",
        }
    },
)
async def telecharger_pdf(
    facture_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
):
    pdf_bytes = await facture_service.generer_pdf(
        facture_id, token.user_id, token.role, session
    )

    # Récupérer le numéro de facture pour le nom du fichier
    facture = await facture_service.get_facture(
        facture_id, token.user_id, token.role, session
    )
    filename = f"facture_{facture.numero}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )