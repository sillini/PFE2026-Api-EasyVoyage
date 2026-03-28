"""
Endpoints Support Chat — partenaire ↔ admin.

Partenaire :
  POST   /partenaire/support/conversations                    → créer demande
  GET    /partenaire/support/conversations                    → mes conversations
  GET    /partenaire/support/conversations/{id}               → détail + messages
  POST   /partenaire/support/conversations/{id}/messages      → envoyer message
  PATCH  /partenaire/support/conversations/{id}/close         → fermer

Admin :
  POST   /admin/support/conversations                         → créer conversation (admin → partenaire)
  GET    /admin/support/conversations                         → toutes (filtre statut)
  GET    /admin/support/conversations/{id}                    → détail + messages
  PATCH  /admin/support/conversations/{id}/accept             → accepter
  PATCH  /admin/support/conversations/{id}/close              → fermer
  POST   /admin/support/conversations/{id}/messages           → envoyer message

Commun :
  GET    /support/notifications                               → mes notifications
  PATCH  /support/notifications/{id}/read                    → marquer lue
  PATCH  /support/notifications/read-all                     → tout marquer lu
"""
from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user, require_admin, require_partenaire
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.support import (
    ConversationCreate, ConversationListResponse, ConversationResponse,
    MessageCreate, MessageResponse,
    NotificationListResponse,
    AdminConversationCreate,        # ← nouveau schéma
)
import app.services.support_service as svc

router = APIRouter(tags=["Support Chat"])


# ══════════════════════════════════════════════════════════
#  PARTENAIRE
# ══════════════════════════════════════════════════════════

@router.post(
    "/partenaire/support/conversations",
    response_model=ConversationResponse,
    status_code=201,
    summary="Créer une demande de support [PARTENAIRE]",
)
async def partenaire_create_conv(
    data: ConversationCreate,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_partenaire),
):
    return await svc.create_conversation(current.user_id, data, session)


@router.get(
    "/partenaire/support/conversations",
    response_model=ConversationListResponse,
    summary="Mes conversations [PARTENAIRE]",
)
async def partenaire_list_convs(
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_partenaire),
):
    return await svc.get_my_conversations(current.user_id, session)


@router.get(
    "/partenaire/support/conversations/{conv_id}",
    response_model=ConversationResponse,
    summary="Détail conversation + messages [PARTENAIRE]",
)
async def partenaire_get_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_partenaire),
):
    return await svc.get_conversation_messages(conv_id, current.user_id, session)


@router.post(
    "/partenaire/support/conversations/{conv_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    summary="Envoyer un message [PARTENAIRE]",
)
async def partenaire_send_msg(
    conv_id: int,
    data: MessageCreate,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_partenaire),
):
    return await svc.send_message(conv_id, current.user_id, data, session)


@router.patch(
    "/partenaire/support/conversations/{conv_id}/close",
    response_model=ConversationResponse,
    summary="Fermer conversation [PARTENAIRE]",
)
async def partenaire_close_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_partenaire),
):
    return await svc.close_conversation(conv_id, current.user_id, session)


# ══════════════════════════════════════════════════════════
#  ADMIN
# ══════════════════════════════════════════════════════════

@router.post(
    "/admin/support/conversations",
    response_model=ConversationResponse,
    status_code=201,
    summary="Créer une conversation vers un partenaire [ADMIN]",
    description=(
        "L'admin initie directement une conversation avec un partenaire. "
        "La conversation est créée en statut **ACCEPTEE** (pas de validation requise). "
        "Le partenaire reçoit une notification et peut répondre immédiatement."
    ),
)
async def admin_create_conv(
    data: AdminConversationCreate,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_admin),
):
    return await svc.admin_create_conversation(current.user_id, data, session)


@router.get(
    "/admin/support/conversations",
    response_model=ConversationListResponse,
    summary="Toutes les conversations [ADMIN]",
)
async def admin_list_convs(
    statut: Optional[str] = Query(None, description="EN_ATTENTE | ACCEPTEE | FERMEE"),
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_admin),
):
    return await svc.get_all_conversations(current.user_id, session, statut)


@router.get(
    "/admin/support/conversations/{conv_id}",
    response_model=ConversationResponse,
    summary="Détail conversation [ADMIN]",
)
async def admin_get_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_admin),
):
    return await svc.get_conversation_messages(conv_id, current.user_id, session)


@router.patch(
    "/admin/support/conversations/{conv_id}/accept",
    response_model=ConversationResponse,
    summary="Accepter une conversation [ADMIN]",
)
async def admin_accept_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_admin),
):
    return await svc.accept_conversation(conv_id, current.user_id, session)


@router.patch(
    "/admin/support/conversations/{conv_id}/close",
    response_model=ConversationResponse,
    summary="Fermer conversation [ADMIN]",
)
async def admin_close_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_admin),
):
    return await svc.close_conversation(conv_id, current.user_id, session)


@router.post(
    "/admin/support/conversations/{conv_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    summary="Envoyer un message [ADMIN]",
)
async def admin_send_msg(
    conv_id: int,
    data: MessageCreate,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(require_admin),
):
    return await svc.send_message(conv_id, current.user_id, data, session)


# ══════════════════════════════════════════════════════════
#  NOTIFICATIONS (commun)
# ══════════════════════════════════════════════════════════

@router.get(
    "/support/notifications",
    response_model=NotificationListResponse,
    summary="Mes notifications [PARTENAIRE | ADMIN]",
)
async def get_notifications(
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(get_current_user),
):
    return await svc.get_notifications(current.user_id, session)


@router.patch(
    "/support/notifications/{notif_id}/read",
    summary="Marquer une notification comme lue",
)
async def mark_notif_read(
    notif_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(get_current_user),
):
    return await svc.mark_notification_read(notif_id, current.user_id, session)


@router.patch(
    "/support/notifications/read-all",
    summary="Marquer toutes les notifications comme lues",
)
async def mark_all_read(
    session: AsyncSession = Depends(get_db),
    current: TokenData = Depends(get_current_user),
):
    return await svc.mark_all_notifications_read(current.user_id, session)