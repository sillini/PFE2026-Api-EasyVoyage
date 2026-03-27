"""Endpoints Voyages — avec admin créateur et filtres avancés."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin, get_current_user
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.voyage import VoyageCreate, VoyageListResponse, VoyageResponse, VoyageUpdate
import app.services.voyage_service as voyage_service

router = APIRouter(prefix="/voyages", tags=["Voyages"])


@router.get("", response_model=VoyageListResponse, summary="Liste des voyages")
async def list_voyages(
    destination:      Optional[str]   = Query(None),
    prix_min:         Optional[float] = Query(None, ge=0),
    prix_max:         Optional[float] = Query(None, ge=0),
    duree_min:        Optional[int]   = Query(None, ge=1),
    duree_max:        Optional[int]   = Query(None, ge=1),
    date_depart_min:  Optional[str]   = Query(None),
    date_depart_max:  Optional[str]   = Query(None),
    actif_only:       Optional[str]   = Query("true"),
    admin_nom:        Optional[str]   = Query(None, description="Recherche par nom/prénom admin"),
    admin_email:      Optional[str]   = Query(None, description="Recherche par email admin"),
    page:     int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> VoyageListResponse:
    actif_bool = str(actif_only).lower() not in ("false", "0", "no")
    return await voyage_service.list_voyages(
        session=session,
        destination=destination,
        prix_min=prix_min, prix_max=prix_max,
        duree_min=duree_min, duree_max=duree_max,
        date_depart_min=date_depart_min, date_depart_max=date_depart_max,
        actif_only=actif_bool,
        admin_nom=admin_nom,
        admin_email=admin_email,
        page=page, per_page=per_page,
    )


@router.get("/{voyage_id}", response_model=VoyageResponse, summary="Détail d'un voyage")
async def get_voyage(voyage_id: int, session: AsyncSession = Depends(get_db)) -> VoyageResponse:
    return await voyage_service.get_voyage(voyage_id, session)


@router.post("", response_model=VoyageResponse, status_code=status.HTTP_201_CREATED,
             summary="Créer un voyage [ADMIN]")
async def create_voyage(
    data: VoyageCreate,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
) -> VoyageResponse:
    # Passer l'id de l'admin connecté
    return await voyage_service.create_voyage(data, session, id_admin=current_user.user_id)


@router.put("/{voyage_id}", response_model=VoyageResponse, summary="Modifier un voyage [ADMIN]")
async def update_voyage(
    voyage_id: int, data: VoyageUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VoyageResponse:
    return await voyage_service.update_voyage(voyage_id, data, session)


@router.delete("/{voyage_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer un voyage [ADMIN] (soft delete)")
async def delete_voyage(
    voyage_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> None:
    await voyage_service.delete_voyage(voyage_id, session)