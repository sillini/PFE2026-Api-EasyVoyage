"""
Endpoints HeroSlide.

Public  : GET  /hero-slides               → slides actifs pour visiteur
Admin   : GET  /admin/hero-slides         → tous les slides
          POST /admin/hero-slides         → créer
          PUT  /admin/hero-slides/{id}    → modifier
          PATCH /admin/hero-slides/{id}/toggle → activer/désactiver
          DELETE /admin/hero-slides/{id}  → supprimer
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.hero_slide import (
    HeroSlideCreate, HeroSlideUpdate,
    HeroSlideResponse, HeroSlideListResponse,
)
import app.services.hero_slide_service as svc

router = APIRouter(tags=["Hero Slides"])


# ── Public — visiteur ─────────────────────────────────────
@router.get("/hero-slides", response_model=HeroSlideListResponse,
            summary="Slides actifs (visiteur)")
async def get_public_slides(session: AsyncSession = Depends(get_db)):
    return await svc.list_slides(session, actif_only=True)


# ── Admin ─────────────────────────────────────────────────
@router.get("/admin/hero-slides", response_model=HeroSlideListResponse,
            summary="Tous les slides [ADMIN]")
async def get_all_slides(
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await svc.list_slides(session, actif_only=False)


@router.post("/admin/hero-slides", response_model=HeroSlideResponse,
             status_code=status.HTTP_201_CREATED, summary="Créer un slide [ADMIN]")
async def create_slide(
    data: HeroSlideCreate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await svc.create_slide(data, session)


@router.put("/admin/hero-slides/{slide_id}", response_model=HeroSlideResponse,
            summary="Modifier un slide [ADMIN]")
async def update_slide(
    slide_id: int, data: HeroSlideUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await svc.update_slide(slide_id, data, session)


@router.patch("/admin/hero-slides/{slide_id}/toggle", response_model=HeroSlideResponse,
              summary="Activer/désactiver un slide [ADMIN]")
async def toggle_slide(
    slide_id: int, data: dict,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    from pydantic import BaseModel
    actif = data.get("actif", True)
    return await svc.toggle_slide(slide_id, actif, session)


@router.delete("/admin/hero-slides/{slide_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer un slide [ADMIN]")
async def delete_slide(
    slide_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    await svc.delete_slide(slide_id, session)