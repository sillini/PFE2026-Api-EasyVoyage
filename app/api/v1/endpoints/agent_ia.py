"""
app/api/v1/endpoints/agent_ia.py
=================================
Endpoints Agent IA — Espace Admin.

Routes :
  GET    /admin/agent-ia/conversations                → liste (sidebar)
  POST   /admin/agent-ia/conversations                → créer (vide, optionnel)
  GET    /admin/agent-ia/conversations/{id}           → détail + messages
  PATCH  /admin/agent-ia/conversations/{id}           → renommer
  DELETE /admin/agent-ia/conversations/{id}           → supprimer
  DELETE /admin/agent-ia/conversations                → tout supprimer

  POST   /admin/agent-ia/chat                         → envoyer un message (non-stream)
  POST   /admin/agent-ia/chat/stream                  → envoyer un message (SSE stream)

Toutes les routes exigent un token JWT admin.
"""
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.agent_ia import (
    ConversationListResponse,
    ConversationDetailResponse,
    SendMessageRequest,
    SendMessageResponse,
    UpdateConversationRequest,
    SimpleOkResponse,
)
import app.services.agent_ia_service as svc

router = APIRouter(
    prefix="/admin/agent-ia",
    tags=["Admin — Agent IA"],
)


# ══════════════════════════════════════════════════════════
#  CONVERSATIONS
# ══════════════════════════════════════════════════════════

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="Liste des conversations de l'utilisateur [ADMIN]",
)
async def list_convs(
    limit:   int  = Query(50, ge=1, le=200),
    offset:  int  = Query(0,  ge=0),
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    return await svc.list_conversations(current.user_id, session, limit, offset)


@router.get(
    "/conversations/{conv_id}",
    response_model=ConversationDetailResponse,
    summary="Détail d'une conversation + ses messages [ADMIN]",
)
async def get_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    return await svc.get_conversation(conv_id, current.user_id, session)


@router.patch(
    "/conversations/{conv_id}",
    response_model=SimpleOkResponse,
    summary="Renommer une conversation [ADMIN]",
)
async def rename_conv(
    conv_id: int,
    data:    UpdateConversationRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    await svc.rename_conversation(conv_id, current.user_id, data.titre, session)
    return SimpleOkResponse(ok=True, message="Conversation renommée")


@router.delete(
    "/conversations/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une conversation [ADMIN]",
)
async def delete_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    await svc.delete_conversation(conv_id, current.user_id, session)


@router.delete(
    "/conversations",
    response_model=SimpleOkResponse,
    summary="Supprimer TOUTES les conversations [ADMIN]",
)
async def clear_all(
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    n = await svc.clear_all_conversations(current.user_id, session)
    return SimpleOkResponse(ok=True, message=f"{n} conversation(s) supprimée(s)")


# ══════════════════════════════════════════════════════════
#  CHAT — ENVOI DE MESSAGE
# ══════════════════════════════════════════════════════════

@router.post(
    "/chat",
    response_model=SendMessageResponse,
    summary="Envoyer un message à l'Agent IA (non-streaming) [ADMIN]",
    description=(
        "Si `conversation_id` est absent, une nouvelle conversation est créée. "
        "Le titre est auto-généré à partir du 1er message. "
        "La mémoire côté n8n est gérée via le `session_id` persistant."
    ),
)
async def chat(
    data:    SendMessageRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    return await svc.send_message(current.user_id, current.role, data, session)


@router.post(
    "/chat/stream",
    summary="Envoyer un message avec streaming SSE [ADMIN]",
    description=(
        "Mode streaming via Server-Sent Events.\n\n"
        "Le frontend consomme via `fetch()` avec lecture incrémentale du body "
        "(ou une lib SSE). Chaque event est un JSON `{type, ...}`. "
        "Types : `conv`, `user_msg`, `token`, `done`, `error`."
    ),
)
async def chat_stream(
    data:    SendMessageRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_admin),
):
    async def event_gen():
        async for chunk in svc.stream_message(current.user_id, current.role, data, session):
            yield chunk

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "Connection":       "keep-alive",
            "X-Accel-Buffering": "no",   # Nginx : désactive le buffering
        },
    )