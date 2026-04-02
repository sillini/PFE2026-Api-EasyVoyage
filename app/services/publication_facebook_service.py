"""
app/services/publication_facebook_service.py
=============================================
Service métier — Publications Facebook + Config token.

RÈGLE ENUMS :
  type_contenu → toujours .lower()  : hotel | voyage | promotion | offre
  statut       → toujours .upper()  : DRAFT | SCHEDULED | PUBLISHED | FAILED | DELETED
"""
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publication_facebook import (
    PublicationFacebook,
    FacebookConfig,
    StatutPublication,
    TypePublication,
)
from app.schemas.publication_facebook import (
    PublicationCreate,
    PublicationUpdate,
    FacebookConfigUpdate,
)


# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def _parse_type(val: Optional[str]) -> TypePublication:
    """Convertir une string en TypePublication — toujours en minuscules."""
    if not val:
        return TypePublication.HOTEL
    try:
        return TypePublication(val.lower())
    except ValueError:
        return TypePublication.HOTEL


def _parse_statut(val: Optional[str]) -> StatutPublication:
    """Convertir une string en StatutPublication — toujours en majuscules."""
    if not val:
        return StatutPublication.DRAFT
    try:
        return StatutPublication(val.upper())
    except ValueError:
        return StatutPublication.DRAFT


# ═══════════════════════════════════════════════════════════
#  CONFIG FACEBOOK
# ═══════════════════════════════════════════════════════════

async def get_facebook_config(session: AsyncSession) -> Optional[FacebookConfig]:
    """Récupérer la config Facebook (toujours la première ligne)."""
    result = await session.execute(select(FacebookConfig).limit(1))
    return result.scalar_one_or_none()


async def upsert_facebook_config(
    data: FacebookConfigUpdate,
    admin_id: int,
    session: AsyncSession,
) -> FacebookConfig:
    """Créer ou mettre à jour la config Facebook."""
    config = await get_facebook_config(session)

    if config is None:
        config = FacebookConfig()
        session.add(config)

    config.page_access_token = data.page_access_token
    config.page_id           = data.page_id
    config.page_name         = data.page_name or config.page_name
    config.token_expires_at  = data.token_expires_at
    config.token_actif       = True
    config.updated_by        = admin_id

    await session.commit()
    await session.refresh(config)
    return config


# ═══════════════════════════════════════════════════════════
#  PUBLICATIONS — CRUD
# ═══════════════════════════════════════════════════════════

async def list_publications(
    session:  AsyncSession,
    statut:   Optional[str] = None,
    page:     int = 1,
    per_page: int = 20,
) -> dict:
    """Lister les publications avec filtres et pagination."""
    query   = select(PublicationFacebook).order_by(PublicationFacebook.created_at.desc())
    count_q = select(func.count()).select_from(PublicationFacebook)

    if statut:
        statut_upper = statut.upper()
        query   = query.where(PublicationFacebook.statut == statut_upper)
        count_q = count_q.where(PublicationFacebook.statut == statut_upper)

    total = (await session.execute(count_q)).scalar_one()
    items = (await session.execute(query.offset((page - 1) * per_page).limit(per_page))).scalars().all()

    return {"total": total, "page": page, "items": list(items)}


async def get_publication(pub_id: int, session: AsyncSession) -> PublicationFacebook:
    """Récupérer une publication par ID — lève 404 si absente."""
    result = await session.execute(
        select(PublicationFacebook).where(PublicationFacebook.id == pub_id)
    )
    pub = result.scalar_one_or_none()
    if not pub:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publication non trouvée")
    return pub


async def create_publication(
    data:     PublicationCreate,
    admin_id: int,
    session:  AsyncSession,
) -> PublicationFacebook:
    """Créer une nouvelle publication."""
    pub = PublicationFacebook(
        message      = data.message,
        type_contenu = _parse_type(data.type_contenu),    # ← .lower() garanti
        image_url    = data.image_url,
        statut       = _parse_statut(data.statut),        # ← .upper() garanti
        scheduled_at = data.scheduled_at,
        fb_post_id   = data.fb_post_id,
        published_at = data.published_at,
        id_admin     = admin_id,
    )
    session.add(pub)
    await session.commit()
    await session.refresh(pub)
    return pub


async def update_publication(
    pub_id:  int,
    data:    PublicationUpdate,
    session: AsyncSession,
) -> PublicationFacebook:
    """Mettre à jour une publication existante."""
    pub = await get_publication(pub_id, session)

    if data.message       is not None: pub.message       = data.message
    if data.image_url     is not None: pub.image_url     = data.image_url
    if data.scheduled_at  is not None: pub.scheduled_at  = data.scheduled_at
    if data.fb_post_id    is not None: pub.fb_post_id    = data.fb_post_id
    if data.published_at  is not None: pub.published_at  = data.published_at
    if data.error_message is not None: pub.error_message = data.error_message

    # Conversions sécurisées
    if data.type_contenu is not None:
        pub.type_contenu = _parse_type(data.type_contenu)   # ← .lower()

    if data.statut is not None:
        pub.statut = _parse_statut(data.statut)              # ← .upper()

    await session.commit()
    await session.refresh(pub)
    return pub


async def delete_publication(
    pub_id:               int,
    delete_from_facebook: bool,
    session:              AsyncSession,
) -> dict:
    """
    Supprimer une publication.
    Si delete_from_facebook=True et fb_post_id existe → DELETE sur l'API Graph Facebook.
    """
    pub = await get_publication(pub_id, session)
    fb_deleted = False

    # ── Supprimer sur Facebook si demandé ────────────────
    if delete_from_facebook and pub.fb_post_id:
        config = await get_facebook_config(session)
        if config and config.page_access_token:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.delete(
                        f"https://graph.facebook.com/v25.0/{pub.fb_post_id}",
                        params={"access_token": config.page_access_token},
                    )
                    fb_deleted = resp.status_code == 200
            except Exception:
                pass  # On continue même si Facebook échoue

    # ── Supprimer de la base ──────────────────────────────
    await session.delete(pub)
    await session.commit()

    return {
        "success":    True,
        "fb_deleted": fb_deleted,
        "message":    "Publication supprimée" + (" et retirée de Facebook" if fb_deleted else ""),
    }