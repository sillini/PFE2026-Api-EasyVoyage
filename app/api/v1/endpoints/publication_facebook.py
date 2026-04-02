"""
app/api/v1/endpoints/publication_facebook.py
=============================================
Endpoints Admin — Publications Facebook.

  GET    /admin/facebook/config                 → Lire la config (sans token)
  GET    /admin/facebook/config/token           → Lire token + page_id (pour publication)
  PUT    /admin/facebook/config                 → Sauvegarder le token FB

  GET    /admin/facebook/publications           → Liste
  POST   /admin/facebook/publications           → Créer
  GET    /admin/facebook/publications/{id}      → Détail
  PUT    /admin/facebook/publications/{id}      → Modifier
  DELETE /admin/facebook/publications/{id}      → Supprimer (+ optionnel FB)
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.publication_facebook import (
    PublicationCreate,
    PublicationListResponse,
    PublicationResponse,
    PublicationUpdate,
    FacebookConfigResponse,
    FacebookConfigUpdate,
    FacebookTokenResponse,
)
import app.services.publication_facebook_service as pub_service

router = APIRouter(
    prefix="/admin/facebook",
    tags=["Admin — Publications Facebook"],
)


# ═══════════════════════════════════════════════════════════
#  CONFIG FACEBOOK TOKEN
# ═══════════════════════════════════════════════════════════

@router.get(
    "/config",
    response_model=FacebookConfigResponse,
    summary="Lire la config Facebook (sans token — sécurité)",
)
async def get_config(
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    config = await pub_service.get_facebook_config(session)
    if not config:
        from datetime import datetime
        return {
            "id": 0,
            "page_id": None,
            "page_name": None,
            "token_actif": False,
            "token_expires_at": None,
            "updated_at": datetime.now(),
        }
    return config


@router.get(
    "/config/token",
    response_model=FacebookTokenResponse,
    summary="Récupérer le token complet pour les publications (admin seulement)",
)
async def get_config_token(
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    Retourne le token Facebook complet + page_id.
    Utilisé par le frontend pour envoyer le token au workflow n8n.
    """
    config = await pub_service.get_facebook_config(session)
    if not config or not config.page_access_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token Facebook non configuré — allez dans Config Facebook",
        )
    if not config.token_actif:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token Facebook inactif — veuillez le renouveler",
        )
    return {
        "page_access_token": config.page_access_token,
        "page_id":           config.page_id,
        "page_name":         config.page_name,
    }


@router.put(
    "/config",
    response_model=FacebookConfigResponse,
    summary="Sauvegarder le token Facebook",
)
async def update_config(
    data: FacebookConfigUpdate,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    return await pub_service.upsert_facebook_config(data, current_user.user_id, session)


# ═══════════════════════════════════════════════════════════
#  PUBLICATIONS — CRUD
# ═══════════════════════════════════════════════════════════

@router.get(
    "/publications",
    response_model=PublicationListResponse,
    summary="Liste des publications Facebook",
)
async def list_publications(
    statut:   Optional[str] = Query(None),
    page:     int           = Query(1, ge=1),
    per_page: int           = Query(20, ge=1, le=100),
    session:  AsyncSession  = Depends(get_db),
    _: TokenData            = Depends(require_admin),
):
    return await pub_service.list_publications(session, statut, page, per_page)


@router.post(
    "/publications",
    response_model=PublicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une publication",
)
async def create_publication(
    data:         PublicationCreate,
    session:      AsyncSession = Depends(get_db),
    current_user: TokenData    = Depends(require_admin),
):
    return await pub_service.create_publication(data, current_user.user_id, session)


@router.get(
    "/publications/{pub_id}",
    response_model=PublicationResponse,
    summary="Détail d'une publication",
)
async def get_publication(
    pub_id:  int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    return await pub_service.get_publication(pub_id, session)


@router.put(
    "/publications/{pub_id}",
    response_model=PublicationResponse,
    summary="Modifier une publication",
)
async def update_publication(
    pub_id:  int,
    data:    PublicationUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    return await pub_service.update_publication(pub_id, data, session)


@router.delete(
    "/publications/{pub_id}",
    summary="Supprimer une publication",
)
async def delete_publication(
    pub_id:               int,
    delete_from_facebook: bool         = Query(True),
    session:              AsyncSession = Depends(get_db),
    _: TokenData                       = Depends(require_admin),
):
    return await pub_service.delete_publication(pub_id, delete_from_facebook, session)