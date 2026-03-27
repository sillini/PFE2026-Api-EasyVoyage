"""Service HeroSlide — CRUD complet."""
from typing import Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.models.hero_slide import HeroSlide
from app.schemas.hero_slide import (
    HeroSlideCreate, HeroSlideUpdate,
    HeroSlideResponse, HeroSlideListResponse,
)


def _to_resp(s: HeroSlide) -> HeroSlideResponse:
    return HeroSlideResponse.model_validate(s)


async def list_slides(
    session: AsyncSession,
    actif_only: bool = False,
) -> HeroSlideListResponse:
    q = select(HeroSlide).order_by(HeroSlide.ordre.asc(), HeroSlide.created_at.asc())
    if actif_only:
        q = q.where(HeroSlide.actif == True)
    result = await session.execute(q)
    slides = result.scalars().all()
    return HeroSlideListResponse(total=len(slides), items=[_to_resp(s) for s in slides])


async def get_slide(slide_id: int, session: AsyncSession) -> HeroSlideResponse:
    result = await session.execute(select(HeroSlide).where(HeroSlide.id == slide_id))
    s = result.scalar_one_or_none()
    if not s:
        raise NotFoundException(f"Slide {slide_id} introuvable")
    return _to_resp(s)


async def create_slide(data: HeroSlideCreate, session: AsyncSession) -> HeroSlideResponse:
    slide = HeroSlide(**data.model_dump())
    session.add(slide)
    await session.flush()
    await session.refresh(slide)
    return _to_resp(slide)


async def update_slide(
    slide_id: int, data: HeroSlideUpdate, session: AsyncSession
) -> HeroSlideResponse:
    result = await session.execute(select(HeroSlide).where(HeroSlide.id == slide_id))
    slide = result.scalar_one_or_none()
    if not slide:
        raise NotFoundException(f"Slide {slide_id} introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(slide, field, value)
    from datetime import datetime, timezone
    slide.updated_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(slide)
    return _to_resp(slide)


async def delete_slide(slide_id: int, session: AsyncSession) -> None:
    result = await session.execute(select(HeroSlide).where(HeroSlide.id == slide_id))
    slide = result.scalar_one_or_none()
    if not slide:
        raise NotFoundException(f"Slide {slide_id} introuvable")
    await session.delete(slide)
    await session.flush()


async def toggle_slide(slide_id: int, actif: bool, session: AsyncSession) -> HeroSlideResponse:
    result = await session.execute(select(HeroSlide).where(HeroSlide.id == slide_id))
    slide = result.scalar_one_or_none()
    if not slide:
        raise NotFoundException(f"Slide {slide_id} introuvable")
    slide.actif = actif
    await session.flush()
    await session.refresh(slide)
    return _to_resp(slide)