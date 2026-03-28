"""
app/api/v1/endpoints/favoris.py
=================================
Endpoints — Favoris Client.

Routes (toutes protégées [CLIENT]) :
  POST   /favoris/toggle         → Ajouter / Retirer un favori
  GET    /favoris                → Liste paginée des favoris
  GET    /favoris/ids            → IDs en favori (pour badges)
  GET    /favoris/status         → Statut d'un item spécifique
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_client
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.favori import (
    FavoriListResponse, FavoriToggleResponse, FavoriStatusResponse,
)
import app.services.favori_service as favori_service

router = APIRouter(prefix="/favoris", tags=["Favoris — Client"])


# ── Schéma du body toggle ──────────────────────────────────
class ToggleRequest(BaseModel):
    id_hotel:  Optional[int] = None
    id_voyage: Optional[int] = None


# ══════════════════════════════════════════════════════════
#  TOGGLE — Ajouter / Retirer
# ══════════════════════════════════════════════════════════
@router.post(
    "/toggle",
    response_model=FavoriToggleResponse,
    summary="Ajouter ou retirer un favori [CLIENT]",
)
async def toggle_favori(
    body: ToggleRequest,
    session: AsyncSession = Depends(get_db),
    token: TokenData      = Depends(require_client),
):
    """
    - Si le favori n'existe pas → l'ajoute (favori: true).
    - S'il existe déjà          → le retire (favori: false).
    """
    return await favori_service.toggle_favori(
        client_id=token.user_id,
        id_hotel=body.id_hotel,
        id_voyage=body.id_voyage,
        session=session,
    )


# ══════════════════════════════════════════════════════════
#  LIST — Tous mes favoris paginés
# ══════════════════════════════════════════════════════════
@router.get(
    "",
    response_model=FavoriListResponse,
    summary="Liste de mes favoris [CLIENT]",
)
async def list_favoris(
    type:     Optional[str] = Query(None, description="hotel | voyage"),
    page:     int           = Query(1, ge=1),
    per_page: int           = Query(12, ge=1, le=50),
    session: AsyncSession   = Depends(get_db),
    token:   TokenData      = Depends(require_client),
):
    return await favori_service.list_favoris(
        client_id=token.user_id,
        type_filtre=type,
        page=page,
        per_page=per_page,
        session=session,
    )


# ══════════════════════════════════════════════════════════
#  IDS — Pour afficher les badges côté frontend
# ══════════════════════════════════════════════════════════
@router.get(
    "/ids",
    summary="IDs de mes favoris [CLIENT]",
)
async def get_favori_ids(
    session: AsyncSession = Depends(get_db),
    token:   TokenData    = Depends(require_client),
):
    return await favori_service.get_favori_ids(
        client_id=token.user_id,
        session=session,
    )


# ══════════════════════════════════════════════════════════
#  STATUS — Est-ce que cet item est en favori ?
# ══════════════════════════════════════════════════════════
@router.get(
    "/status",
    response_model=FavoriStatusResponse,
    summary="Statut favori d'un item [CLIENT]",
)
async def get_status(
    id_hotel:  Optional[int] = Query(None),
    id_voyage: Optional[int] = Query(None),
    session: AsyncSession    = Depends(get_db),
    token:   TokenData       = Depends(require_client),
):
    return await favori_service.get_status(
        client_id=token.user_id,
        id_hotel=id_hotel,
        id_voyage=id_voyage,
        session=session,
    )