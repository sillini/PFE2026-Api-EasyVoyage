"""
app/api/v1/endpoints/agent_ia_client.py
========================================
Endpoints Agent IA — Espace CLIENT.

Jumeau de agent_ia.py (admin) avec 2 différences :
  - Prefix : /client/agent-ia au lieu de /admin/agent-ia
  - Dependency : require_client au lieu de require_admin

Routes :
  GET    /client/agent-ia/conversations                → liste (sidebar)
  GET    /client/agent-ia/conversations/{id}           → détail + messages
  PATCH  /client/agent-ia/conversations/{id}           → renommer
  DELETE /client/agent-ia/conversations/{id}           → supprimer
  DELETE /client/agent-ia/conversations                → tout supprimer

  POST   /client/agent-ia/chat                         → envoyer un message (non-stream)
  POST   /client/agent-ia/chat/stream                  → envoyer un message (SSE stream)

Toutes les routes exigent un JWT client (role=CLIENT).
"""
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_client
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
import app.services.agent_ia_client_service as svc

router = APIRouter(
    prefix="/client/agent-ia",
    tags=["Client — Agent IA"],
)


# ══════════════════════════════════════════════════════════
#  CONVERSATIONS
# ══════════════════════════════════════════════════════════

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="Liste des conversations du client [CLIENT]",
)
async def list_convs(
    limit:   int  = Query(50, ge=1, le=200),
    offset:  int  = Query(0,  ge=0),
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
):
    return await svc.list_conversations(current.user_id, session, limit, offset)


@router.get(
    "/conversations/{conv_id}",
    response_model=ConversationDetailResponse,
    summary="Détail d'une conversation + ses messages [CLIENT]",
)
async def get_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
):
    return await svc.get_conversation(conv_id, current.user_id, session)


@router.patch(
    "/conversations/{conv_id}",
    response_model=SimpleOkResponse,
    summary="Renommer une conversation [CLIENT]",
)
async def rename_conv(
    conv_id: int,
    data:    UpdateConversationRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
):
    await svc.rename_conversation(conv_id, current.user_id, data.titre, session)
    return SimpleOkResponse(ok=True, message="Conversation renommée")


@router.delete(
    "/conversations/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une conversation [CLIENT]",
)
async def delete_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
):
    await svc.delete_conversation(conv_id, current.user_id, session)


@router.delete(
    "/conversations",
    response_model=SimpleOkResponse,
    summary="Supprimer TOUTES les conversations [CLIENT]",
)
async def clear_all(
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
):
    n = await svc.clear_all_conversations(current.user_id, session)
    return SimpleOkResponse(ok=True, message=f"{n} conversation(s) supprimée(s)")


# ══════════════════════════════════════════════════════════
#  CHAT — ENVOI DE MESSAGE
# ══════════════════════════════════════════════════════════

@router.post(
    "/chat",
    response_model=SendMessageResponse,
    summary="Envoyer un message à l'Assistant EasyVoyage (non-streaming) [CLIENT]",
    description=(
        "Si `conversation_id` est absent, une nouvelle conversation est créée. "
        "Le titre est auto-généré à partir du 1er message. "
        "La mémoire côté n8n est gérée via le `session_id` persistant.\n\n"
        "**Important** : le JWT du client est injecté automatiquement dans le "
        "payload envoyé à n8n (champ `jwt_token`) pour permettre aux tools MCP "
        "d'appeler les endpoints authentifiés."
    ),
)
async def chat(
    data:    SendMessageRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
):
    return await svc.send_message(current.user_id, current.role, data, session)


@router.post(
    "/chat/stream",
    summary="Envoyer un message avec streaming SSE [CLIENT]",
    description=(
        "Mode streaming via Server-Sent Events.\n\n"
        "Le frontend consomme via `fetch()` avec lecture incrémentale du body. "
        "Chaque event est un JSON `{type, ...}`. "
        "Types : `conv`, `user_msg`, `token`, `done`, `error`."
    ),
)
async def chat_stream(
    data:    SendMessageRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_client),
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
            "X-Accel-Buffering": "no",
        },
    )