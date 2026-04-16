# app/api/v1/endpoints/video_campaign.py
"""
Endpoints Video Campaigns.
CORRECTION : logger defini EN HAUT du fichier (etait defini apres utilisation).
"""
import logging
import traceback
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.video_campaign import (
    DestinataireCountResponse,
    EnvoyerVideoCampaignRequest,
    VideoCampaignCreate,
    VideoCampaignListResponse,
    VideoCampaignResponse,
    VideoStatusResponse,
)
import app.services.video_campaign_service as svc

router = APIRouter(prefix="/video-campaigns", tags=["Video Campaigns"])

# ← CORRECTION PRINCIPALE : logger AVANT toute utilisation
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  CRÉER
# ══════════════════════════════════════════════════════════
@router.post("", response_model=VideoCampaignResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Créer une campagne vidéo [ADMIN]")
async def creer_campaign(
    data: VideoCampaignCreate,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_admin),
) -> VideoCampaignResponse:
    return await svc.creer_campaign(data, token.user_id, session)


# ══════════════════════════════════════════════════════════
#  LISTER
# ══════════════════════════════════════════════════════════
@router.get("", response_model=VideoCampaignListResponse,
            summary="Lister les campagnes vidéo [ADMIN]")
async def lister_campaigns(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    statut: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoCampaignListResponse:
    return await svc.lister_campaigns(page, per_page, statut, session)


# ══════════════════════════════════════════════════════════
#  COMPTER DESTINATAIRES — AVANT /{id} pour éviter conflit
# ══════════════════════════════════════════════════════════
@router.get("/destinataires/compter",
            response_model=DestinataireCountResponse,
            summary="Compter les destinataires [ADMIN]")
async def compter_destinataires(
    segment: str = Query("tous"),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> DestinataireCountResponse:
    result = await svc.compter_destinataires(segment, session)
    return DestinataireCountResponse(**result)


# ══════════════════════════════════════════════════════════
#  DÉTAIL
# ══════════════════════════════════════════════════════════
@router.get("/{campaign_id}", response_model=VideoCampaignResponse,
            summary="Détail d'une campagne vidéo [ADMIN]")
async def get_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoCampaignResponse:
    return await svc.get_campaign(campaign_id, session)


# ══════════════════════════════════════════════════════════
#  SUPPRIMER
# ══════════════════════════════════════════════════════════
@router.delete("/{campaign_id}", summary="Supprimer une campagne vidéo [ADMIN]")
async def supprimer_campaign(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> dict:
    return await svc.supprimer_campaign(campaign_id, session)


# ══════════════════════════════════════════════════════════
#  ÉTAPE 1 : GÉNÉRER CONTENU (Claude AI)
# ══════════════════════════════════════════════════════════
@router.post("/{campaign_id}/generer-contenu",
             response_model=VideoCampaignResponse,
             summary="Générer le contenu via Claude AI [ADMIN]")
async def generer_contenu(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoCampaignResponse:
    try:
        return await svc.generer_contenu(campaign_id, session)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"[VIDEO_CAMPAIGN] ValueError generer_contenu #{campaign_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Log le traceback COMPLET dans les logs uvicorn
        logger.error(
            f"[VIDEO_CAMPAIGN] ERREUR generer_contenu #{campaign_id}:\n"
            f"{traceback.format_exc()}"
        )
        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {e}"
        )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 2 : GÉNÉRER VIDÉO (Replicate) — background task
# ══════════════════════════════════════════════════════════
@router.post("/{campaign_id}/generer-video",
             response_model=VideoCampaignResponse,
             summary="Générer la vidéo via Replicate [ADMIN]")
async def generer_video(
    campaign_id: int,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoCampaignResponse:
    camp = await svc.get_campaign(campaign_id, session)
    if not camp.prompts_images:
        raise HTTPException(400, "Générez d'abord le contenu via /generer-contenu")
    background_tasks.add_task(_generer_video_bg, campaign_id)
    return camp


async def _generer_video_bg(campaign_id: int):
    """Tâche background — utilise AsyncSessionLocal (nom correct dans ce projet)."""
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        try:
            await svc.generer_video(campaign_id, session)
        except Exception as e:
            logger.error(
                f"[VIDEO_CAMPAIGN] Background task erreur #{campaign_id}:\n"
                f"{traceback.format_exc()}"
            )


# ══════════════════════════════════════════════════════════
#  STATUT VIDÉO (polling)
# ══════════════════════════════════════════════════════════
@router.get("/{campaign_id}/video-status",
            response_model=VideoStatusResponse,
            summary="Statut de la génération vidéo [ADMIN]")
async def video_status(
    campaign_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoStatusResponse:
    camp = await svc.get_campaign(campaign_id, session)
    return VideoStatusResponse(
        campaign_id             = camp.id,
        statut                  = camp.statut,
        replicate_prediction_id = camp.replicate_prediction_id,
        video_url_landscape     = camp.video_url_landscape,
        video_url_portrait      = camp.video_url_portrait,
        video_url_square        = camp.video_url_square,
        thumbnail_url           = camp.thumbnail_url,
        erreur                  = camp.erreur,
    )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 3 : ENVOYER (Brevo)
# ══════════════════════════════════════════════════════════
@router.post("/{campaign_id}/envoyer",
             response_model=VideoCampaignResponse,
             summary="Envoyer la campagne vidéo par email [ADMIN]")
async def envoyer_campaign(
    campaign_id: int,
    data: EnvoyerVideoCampaignRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoCampaignResponse:
    try:
        return await svc.envoyer_campaign(campaign_id, data, session)
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"[VIDEO_CAMPAIGN] ValueError envoyer #{campaign_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"[VIDEO_CAMPAIGN] ERREUR envoyer #{campaign_id}:\n"
            f"{traceback.format_exc()}"
        )
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════
#  RENVOYER (renvoi d'une campagne déjà envoyée)
# ══════════════════════════════════════════════════════════
@router.post("/{campaign_id}/renvoyer",
             response_model=VideoCampaignResponse,
             summary="Renvoyer une campagne vidéo [ADMIN]")
async def renvoyer_campaign(
    campaign_id: int,
    data: EnvoyerVideoCampaignRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> VideoCampaignResponse:
    try:
        return await svc.renvoyer_campaign(campaign_id, data, session)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[VIDEO_CAMPAIGN] ERREUR renvoyer #{campaign_id}:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════
#  DESTINATAIRES — liste emails
# ══════════════════════════════════════════════════════════
@router.get("/{campaign_id}/destinataires",
            summary="Liste des destinataires [ADMIN]")
async def get_destinataires(
    campaign_id: int,
    search: str = Query("", description="Recherche par email, prénom ou nom"),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
) -> dict:
    contacts = await svc.get_destinataires(campaign_id, session, search=search)
    return {"total": len(contacts), "items": contacts}