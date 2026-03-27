"""
Endpoints Images de voyage — imbriqués sous /voyages/{id}/images

  GET    /api/v1/voyages/{voyage_id}/images                      — Lister (public)
  POST   /api/v1/voyages/{voyage_id}/images                      — Ajouter (admin)
  PATCH  /api/v1/voyages/{voyage_id}/images/{image_id}           — Changer type (admin)
  DELETE /api/v1/voyages/{voyage_id}/images/{image_id}           — Supprimer (admin)
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.image import (
    ImageCreate,
    ImageListResponse,
    ImageResponse,
    ImageUpdateType,
)
import app.services.image_service as image_service

router = APIRouter(
    prefix="/voyages/{voyage_id}/images",
    tags=["Voyages — Images"],
)


@router.get(
    "",
    response_model=ImageListResponse,
    summary="Lister les images d'un voyage",
    description="Retourne toutes les images d'un voyage. L'image PRINCIPALE apparaît en premier.",
)
async def list_images(
    voyage_id: int,
    session: AsyncSession = Depends(get_db),
) -> ImageListResponse:
    return await image_service.list_images_voyage(voyage_id, session)


@router.post(
    "",
    response_model=ImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter une image à un voyage [ADMIN]",
    description="""
Ajoute une image à un voyage via son URL externe (Cloudinary, S3, etc.).

**Règle PRINCIPALE :** un voyage ne peut avoir qu'une seule image de type PRINCIPALE.
Si vous ajoutez une nouvelle PRINCIPALE, l'ancienne devient automatiquement GALERIE.
    """,
)
async def add_image(
    voyage_id: int,
    data: ImageCreate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> ImageResponse:
    return await image_service.add_image_voyage(voyage_id, data, session)


@router.patch(
    "/{image_id}",
    response_model=ImageResponse,
    summary="Changer le type d'une image [ADMIN]",
    description="Modifie le type d'une image : PRINCIPALE | GALERIE | MINIATURE | BANNIERE",
)
async def update_image_type(
    voyage_id: int,
    image_id: int,
    data: ImageUpdateType,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> ImageResponse:
    return await image_service.update_image_type(voyage_id, image_id, data, session)


@router.delete(
    "/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une image [ADMIN]",
)
async def delete_image(
    voyage_id: int,
    image_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> None:
    await image_service.delete_image(voyage_id, image_id, session)