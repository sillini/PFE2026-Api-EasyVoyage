# app/api/v1/endpoints/facebook_interactions.py
# ══════════════════════════════════════════════════════════════════════════
#  Endpoints — Interactions & Stats Facebook
#
#  POST  /admin/facebook/publications/{id}/sync-stats   → Sync 1 publication
#  POST  /admin/facebook/publications/sync-all-stats    → Sync toutes les publiées
#  GET   /admin/facebook/dashboard                      → Dashboard global
#
#  CORRECTION : On n'utilise QUE les champs de base (reactions, comments, shares)
#  qui fonctionnent avec n'importe quel Page Access Token.
#  Les "insights" nécessitent pages_read_insights (permission avancée Meta).
# ══════════════════════════════════════════════════════════════════════════

from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.models.publication_facebook import PublicationFacebook
from app.schemas.auth import TokenData
from app.schemas.publication_facebook import (
    PostInteractionsResponse,
    SyncAllResponse,
    DashboardResponse,
)
import app.services.publication_facebook_service as pub_service

router = APIRouter(
    prefix="/admin/facebook",
    tags=["Admin — Interactions Facebook"],
)


# ─── Helper : appel Graph API (champs de base uniquement) ───────────────────

async def _fetch_post_stats(fb_post_id: str, access_token: str) -> dict:
    """
    Récupère les stats d'une publication via l'API Graph Facebook.

    Champs utilisés (disponibles avec un Page Token standard) :
      - reactions.summary(total_count)  → total réactions (👍❤️😂😮😢😡)
      - comments.summary(total_count)   → nombre de commentaires
      - shares                          → nombre de partages

    NOTE : Les "insights" (portée, impressions, clics) nécessitent la permission
    pages_read_insights — non demandée ici pour rester compatible avec les tokens
    de base. Ces champs resteront à 0 sauf si vous activez cette permission sur
    votre app Meta.
    """
    fields = (
        "reactions.summary(total_count).limit(0),"
        "comments.summary(total_count).limit(0),"
        "shares"
    )

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v19.0/{fb_post_id}",
                params={
                    "fields":       fields,
                    "access_token": access_token,
                },
            )

        body = resp.json()

        # ── Vérifier les erreurs Graph API ────────────────
        if "error" in body:
            err = body["error"]
            code    = err.get("code", "?")
            message = err.get("message", "Erreur inconnue")
            subcode = err.get("error_subcode", "")

            # Erreurs communes et leurs causes
            hints = {
                190: "Token expiré ou invalide — renouvelez le token dans Config Facebook",
                200: "Permission manquante — ajoutez pages_read_engagement à votre app Meta",
                100: "fb_post_id invalide ou publication supprimée de Facebook",
            }
            hint = hints.get(code, "")
            detail = f"Graph API erreur {code}: {message}"
            if hint:
                detail += f" → {hint}"
            if subcode:
                detail += f" (subcode: {subcode})"

            return {"error": detail}

        # ── Extraire les valeurs ──────────────────────────

        # Réactions (like + love + haha + wow + sad + angry)
        reactions_count = (
            body.get("reactions", {})
                .get("summary", {})
                .get("total_count", 0) or 0
        )

        # Commentaires
        comments_count = (
            body.get("comments", {})
                .get("summary", {})
                .get("total_count", 0) or 0
        )

        # Partages (peut être absent si 0)
        shares_count = body.get("shares", {}).get("count", 0) or 0

        return {
            "likes_count":     reactions_count,   # likes ≃ réactions dans v19+
            "reactions_count": reactions_count,
            "comments_count":  comments_count,
            "shares_count":    shares_count,
            "clicks_count":    0,                  # nécessite pages_read_insights
            "reach_count":     0,                  # nécessite pages_read_insights
            "impressions":     0,                  # nécessite pages_read_insights
            "error":           None,
        }

    except httpx.TimeoutException:
        return {"error": "Timeout — l'API Facebook ne répond pas (>20s)"}
    except httpx.RequestError as e:
        return {"error": f"Erreur réseau : {str(e)}"}
    except Exception as e:
        return {"error": f"Erreur inattendue : {str(e)}"}


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post(
    "/publications/{pub_id}/sync-stats",
    response_model=PostInteractionsResponse,
    summary="Synchroniser les stats d'une publication depuis Facebook",
)
async def sync_post_stats(
    pub_id:  int,
    session: AsyncSession = Depends(get_db),
    _:       TokenData    = Depends(require_admin),
):
    """
    Appelle l'API Graph Facebook et met à jour les stats en BDD pour 1 publication.
    Utilise uniquement les champs de base (reactions, comments, shares).
    """
    pub = await pub_service.get_publication(pub_id, session)

    # Pas de fb_post_id → impossible de sync
    if not pub.fb_post_id:
        return PostInteractionsResponse(
            id=pub.id,
            fb_post_id=None,
            likes_count=0, comments_count=0, shares_count=0,
            reactions_count=0, clicks_count=0, reach_count=0, impressions=0,
            stats_updated_at=None,
            synced=False,
            error="Aucun fb_post_id — la publication n'a pas encore été publiée sur Facebook",
        )

    # Récupérer le token Page depuis la BDD
    config = await pub_service.get_facebook_config(session)
    if not config or not config.page_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token Facebook non configuré — allez dans ⚙️ Config Facebook",
        )

    # Appel Graph API
    stats = await _fetch_post_stats(pub.fb_post_id, config.page_access_token)

    # Si erreur Graph → retourner les stats actuelles + message d'erreur
    if stats.get("error"):
        return PostInteractionsResponse(
            id=pub.id,
            fb_post_id=pub.fb_post_id,
            likes_count=     getattr(pub, "likes_count",     0) or 0,
            comments_count=  getattr(pub, "comments_count",  0) or 0,
            shares_count=    getattr(pub, "shares_count",    0) or 0,
            reactions_count= getattr(pub, "reactions_count", 0) or 0,
            clicks_count=    getattr(pub, "clicks_count",    0) or 0,
            reach_count=     getattr(pub, "reach_count",     0) or 0,
            impressions=     getattr(pub, "impressions",     0) or 0,
            stats_updated_at=getattr(pub, "stats_updated_at", None),
            synced=False,
            error=stats["error"],
        )

    # ── Mise à jour en BDD ────────────────────────────────
    pub.likes_count      = stats["likes_count"]
    pub.comments_count   = stats["comments_count"]
    pub.shares_count     = stats["shares_count"]
    pub.reactions_count  = stats["reactions_count"]
    pub.clicks_count     = stats["clicks_count"]
    pub.reach_count      = stats["reach_count"]
    pub.impressions      = stats["impressions"]
    pub.stats_updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(pub)

    return PostInteractionsResponse(
        id=pub.id,
        fb_post_id=pub.fb_post_id,
        likes_count=     pub.likes_count     or 0,
        comments_count=  pub.comments_count  or 0,
        shares_count=    pub.shares_count    or 0,
        reactions_count= pub.reactions_count or 0,
        clicks_count=    pub.clicks_count    or 0,
        reach_count=     pub.reach_count     or 0,
        impressions=     pub.impressions     or 0,
        stats_updated_at=pub.stats_updated_at,
        synced=True,
        error=None,
    )


@router.post(
    "/publications/sync-all-stats",
    response_model=SyncAllResponse,
    summary="Synchroniser les stats de toutes les publications PUBLISHED",
)
async def sync_all_stats(
    session: AsyncSession = Depends(get_db),
    _:       TokenData    = Depends(require_admin),
):
    """
    Synchronise en masse toutes les publications PUBLISHED ayant un fb_post_id.
    """
    config = await pub_service.get_facebook_config(session)
    if not config or not config.page_access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token Facebook non configuré",
        )

    result = await session.execute(
        select(PublicationFacebook).where(
            PublicationFacebook.statut == "PUBLISHED",
            PublicationFacebook.fb_post_id.isnot(None),
        )
    )
    publications = result.scalars().all()

    synced = 0
    errors = []

    for pub in publications:
        stats = await _fetch_post_stats(pub.fb_post_id, config.page_access_token)

        if stats.get("error"):
            errors.append({"id": pub.id, "fb_post_id": pub.fb_post_id, "error": stats["error"]})
            continue

        pub.likes_count      = stats["likes_count"]
        pub.comments_count   = stats["comments_count"]
        pub.shares_count     = stats["shares_count"]
        pub.reactions_count  = stats["reactions_count"]
        pub.clicks_count     = stats["clicks_count"]
        pub.reach_count      = stats["reach_count"]
        pub.impressions      = stats["impressions"]
        pub.stats_updated_at = datetime.now(timezone.utc)
        synced += 1

    await session.commit()

    return SyncAllResponse(
        synced=synced,
        total=len(publications),
        errors=errors,
        message=f"{synced}/{len(publications)} publications synchronisées"
        + (f" ({len(errors)} erreur(s))" if errors else ""),
    )


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Tableau de bord global des interactions de la page",
)
async def get_dashboard(
    session: AsyncSession = Depends(get_db),
    _:       TokenData    = Depends(require_admin),
):
    """
    Agrège toutes les interactions des publications pour le dashboard global.
    """
    agg = await session.execute(
        select(
            func.count(PublicationFacebook.id).label("total"),
            func.sum(
                func.case((PublicationFacebook.statut == "PUBLISHED", 1), else_=0)
            ).label("published"),
            func.sum(
                func.case((PublicationFacebook.statut == "DRAFT", 1), else_=0)
            ).label("draft"),
            func.coalesce(func.sum(PublicationFacebook.likes_count),     0).label("total_likes"),
            func.coalesce(func.sum(PublicationFacebook.comments_count),  0).label("total_comments"),
            func.coalesce(func.sum(PublicationFacebook.shares_count),    0).label("total_shares"),
            func.coalesce(func.sum(PublicationFacebook.reactions_count), 0).label("total_reactions"),
            func.coalesce(func.sum(PublicationFacebook.clicks_count),    0).label("total_clicks"),
            func.coalesce(func.sum(PublicationFacebook.reach_count),     0).label("total_reach"),
            func.coalesce(func.sum(PublicationFacebook.impressions),     0).label("total_impressions"),
            func.max(PublicationFacebook.stats_updated_at).label("last_sync"),
        )
    )
    row = agg.first()

    # Top publication par engagement total
    top_result = await session.execute(
        select(PublicationFacebook)
        .where(PublicationFacebook.statut == "PUBLISHED")
        .order_by(
            (
                func.coalesce(PublicationFacebook.reactions_count, 0)
                + func.coalesce(PublicationFacebook.comments_count, 0)
                + func.coalesce(PublicationFacebook.shares_count, 0)
            ).desc()
        )
        .limit(1)
    )
    top = top_result.scalar_one_or_none()

    # Taux d'engagement moyen
    total_reach      = row.total_reach or 0
    total_engagement = (row.total_reactions or 0) + (row.total_comments or 0) + (row.total_shares or 0)
    avg_engagement_rate = (
        round((total_engagement / total_reach * 100), 2)
        if total_reach > 0 else 0.0
    )

    return DashboardResponse(
        total_publications  = row.total      or 0,
        published_count     = row.published  or 0,
        draft_count         = row.draft      or 0,
        total_likes         = row.total_likes      or 0,
        total_comments      = row.total_comments   or 0,
        total_shares        = row.total_shares     or 0,
        total_reactions     = row.total_reactions  or 0,
        total_clicks        = row.total_clicks     or 0,
        total_reach         = row.total_reach      or 0,
        total_impressions   = row.total_impressions or 0,
        top_post_id         = top.id          if top else None,
        top_post_fb_id      = top.fb_post_id  if top else None,
        top_post_message    = (top.message[:120] + "…") if top and len(top.message) > 120 else (top.message if top else None),
        top_post_likes      = (top.reactions_count or 0) if top else 0,
        top_post_engagement = (
            (top.reactions_count or 0) + (top.comments_count or 0) + (top.shares_count or 0)
        ) if top else 0,
        avg_engagement_rate = avg_engagement_rate,
        last_sync_at        = row.last_sync,
    )