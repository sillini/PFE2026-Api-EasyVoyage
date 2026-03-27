"""
Service Images — logique métier pour les images de voyages (et hôtels plus tard).

Règles métier :
  - Un voyage ne peut avoir qu'une seule image de type PRINCIPALE
  - Si on ajoute une nouvelle PRINCIPALE, l'ancienne devient GALERIE automatiquement
  - Une image appartient soit à un voyage, soit à un hôtel — jamais les deux
"""
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException, ConflictException
from app.models.image import Image, TypeImage
from app.models.voyage import Voyage
from app.schemas.image import ImageCreate, ImageListResponse, ImageResponse, ImageUpdateType


# ── Vérifier que le voyage existe ─────────────────────────────────────────────
async def _check_voyage_exists(voyage_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(Voyage.id).where(Voyage.id == voyage_id)
    )
    if result.scalar_one_or_none() is None:
        raise NotFoundException(f"Voyage {voyage_id} introuvable")


# ── Lister les images d'un voyage ─────────────────────────────────────────────
async def list_images_voyage(
    voyage_id: int, session: AsyncSession
) -> ImageListResponse:
    await _check_voyage_exists(voyage_id, session)

    result = await session.execute(
        select(Image)
        .where(Image.id_voyage == voyage_id)
        .order_by(
            # PRINCIPALE en premier, puis le reste
            Image.type.asc(),
            Image.created_at.asc(),
        )
    )
    images = result.scalars().all()

    return ImageListResponse(
        total=len(images),
        items=[ImageResponse.model_validate(img) for img in images],
    )


# ── Ajouter une image à un voyage ─────────────────────────────────────────────
async def add_image_voyage(
    voyage_id: int, data: ImageCreate, session: AsyncSession
) -> ImageResponse:
    await _check_voyage_exists(voyage_id, session)

    # Règle : un seul PRINCIPALE par voyage
    # Si la nouvelle image est PRINCIPALE → l'ancienne passe en GALERIE
    if data.type == "PRINCIPALE":
        await session.execute(
            update(Image)
            .where(Image.id_voyage == voyage_id)
            .where(Image.type == TypeImage.PRINCIPALE)
            .values(type=TypeImage.GALERIE)
        )

    image = Image(
        url=data.url,
        type=TypeImage(data.type),
        id_voyage=voyage_id,
        id_hotel=None,
    )
    session.add(image)
    await session.flush()
    await session.refresh(image)

    return ImageResponse.model_validate(image)


# ── Changer le type d'une image ───────────────────────────────────────────────
async def update_image_type(
    voyage_id: int,
    image_id: int,
    data: ImageUpdateType,
    session: AsyncSession,
) -> ImageResponse:
    await _check_voyage_exists(voyage_id, session)

    result = await session.execute(
        select(Image).where(
            Image.id == image_id,
            Image.id_voyage == voyage_id,
        )
    )
    image = result.scalar_one_or_none()

    if not image:
        raise NotFoundException(f"Image {image_id} introuvable pour le voyage {voyage_id}")

    # Règle : si on change vers PRINCIPALE, l'ancienne PRINCIPALE passe en GALERIE
    if data.type == "PRINCIPALE":
        await session.execute(
            update(Image)
            .where(Image.id_voyage == voyage_id)
            .where(Image.type == TypeImage.PRINCIPALE)
            .where(Image.id != image_id)
            .values(type=TypeImage.GALERIE)
        )

    image.type = TypeImage(data.type)
    await session.flush()
    await session.refresh(image)

    return ImageResponse.model_validate(image)


# ── Supprimer une image ───────────────────────────────────────────────────────
async def delete_image(
    voyage_id: int, image_id: int, session: AsyncSession
) -> None:
    await _check_voyage_exists(voyage_id, session)

    result = await session.execute(
        select(Image).where(
            Image.id == image_id,
            Image.id_voyage == voyage_id,
        )
    )
    image = result.scalar_one_or_none()

    if not image:
        raise NotFoundException(f"Image {image_id} introuvable pour le voyage {voyage_id}")

    await session.delete(image)
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  IMAGES HOTEL
# ═══════════════════════════════════════════════════════════
async def _check_hotel_exists(hotel_id: int, session: AsyncSession) -> None:
    from app.models.hotel import Hotel
    result = await session.execute(select(Hotel.id).where(Hotel.id == hotel_id))
    if result.scalar_one_or_none() is None:
        raise NotFoundException(f"Hôtel {hotel_id} introuvable")


async def list_images_hotel(hotel_id: int, session: AsyncSession) -> ImageListResponse:
    await _check_hotel_exists(hotel_id, session)
    result = await session.execute(
        select(Image)
        .where(Image.id_hotel == hotel_id)
        .order_by(Image.type.asc(), Image.created_at.asc())
    )
    images = result.scalars().all()
    return ImageListResponse(total=len(images), items=[ImageResponse.model_validate(i) for i in images])


async def add_image_hotel(hotel_id: int, data: ImageCreate, session: AsyncSession) -> ImageResponse:
    await _check_hotel_exists(hotel_id, session)
    if data.type == "PRINCIPALE":
        await session.execute(
            update(Image)
            .where(Image.id_hotel == hotel_id)
            .where(Image.type == TypeImage.PRINCIPALE)
            .values(type=TypeImage.GALERIE)
        )
    image = Image(url=data.url, type=TypeImage(data.type), id_hotel=hotel_id, id_voyage=None)
    session.add(image)
    await session.flush()
    await session.refresh(image)
    return ImageResponse.model_validate(image)


async def update_image_type_hotel(
    hotel_id: int, image_id: int, data: ImageUpdateType, session: AsyncSession
) -> ImageResponse:
    await _check_hotel_exists(hotel_id, session)
    result = await session.execute(
        select(Image).where(Image.id == image_id, Image.id_hotel == hotel_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise NotFoundException(f"Image {image_id} introuvable pour l'hôtel {hotel_id}")
    if data.type == "PRINCIPALE":
        await session.execute(
            update(Image)
            .where(Image.id_hotel == hotel_id)
            .where(Image.type == TypeImage.PRINCIPALE)
            .where(Image.id != image_id)
            .values(type=TypeImage.GALERIE)
        )
    image.type = TypeImage(data.type)
    await session.flush()
    await session.refresh(image)
    return ImageResponse.model_validate(image)


async def delete_image_hotel(hotel_id: int, image_id: int, session: AsyncSession) -> None:
    await _check_hotel_exists(hotel_id, session)
    result = await session.execute(
        select(Image).where(Image.id == image_id, Image.id_hotel == hotel_id)
    )
    image = result.scalar_one_or_none()
    if not image:
        raise NotFoundException(f"Image {image_id} introuvable pour l'hôtel {hotel_id}")
    await session.delete(image)
    await session.flush()