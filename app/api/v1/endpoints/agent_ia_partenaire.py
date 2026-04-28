"""
app/api/v1/endpoints/agent_ia_partenaire.py
============================================
Endpoints Agent IA — Espace PARTENAIRE.

Jumeau de agent_ia_client.py (client) avec 2 differences :
  - Prefix : /partenaire/agent-ia au lieu de /client/agent-ia
  - Dependency : require_partenaire au lieu de require_client

Routes :
  GET    /partenaire/agent-ia/conversations                → liste (sidebar)
  GET    /partenaire/agent-ia/conversations/{id}           → detail + messages
  PATCH  /partenaire/agent-ia/conversations/{id}           → renommer
  DELETE /partenaire/agent-ia/conversations/{id}           → supprimer
  DELETE /partenaire/agent-ia/conversations                → tout supprimer

  POST   /partenaire/agent-ia/chat                         → envoyer un message (non-stream)
  POST   /partenaire/agent-ia/chat/stream                  → envoyer un message (SSE stream)

Toutes les routes exigent un JWT partenaire (role=PARTENAIRE).
"""
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_partenaire
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
import app.services.agent_ia_partenaire_service as svc

router = APIRouter(
    prefix="/partenaire/agent-ia",
    tags=["Partenaire — Agent IA"],
)


# ══════════════════════════════════════════════════════════
#  CONVERSATIONS
# ══════════════════════════════════════════════════════════

@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="Liste des conversations du partenaire [PARTENAIRE]",
)
async def list_convs(
    limit:   int  = Query(50, ge=1, le=200),
    offset:  int  = Query(0,  ge=0),
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_partenaire),
):
    return await svc.list_conversations(current.user_id, session, limit, offset)


@router.get(
    "/conversations/{conv_id}",
    response_model=ConversationDetailResponse,
    summary="Détail d'une conversation + ses messages [PARTENAIRE]",
)
async def get_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_partenaire),
):
    return await svc.get_conversation(conv_id, current.user_id, session)


@router.patch(
    "/conversations/{conv_id}",
    response_model=SimpleOkResponse,
    summary="Renommer une conversation [PARTENAIRE]",
)
async def rename_conv(
    conv_id: int,
    data:    UpdateConversationRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_partenaire),
):
    await svc.rename_conversation(conv_id, current.user_id, data.titre, session)
    return SimpleOkResponse(ok=True, message="Conversation renommée")


@router.delete(
    "/conversations/{conv_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une conversation [PARTENAIRE]",
)
async def delete_conv(
    conv_id: int,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_partenaire),
):
    await svc.delete_conversation(conv_id, current.user_id, session)


@router.delete(
    "/conversations",
    response_model=SimpleOkResponse,
    summary="Supprimer TOUTES les conversations [PARTENAIRE]",
)
async def clear_all(
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_partenaire),
):
    n = await svc.clear_all_conversations(current.user_id, session)
    return SimpleOkResponse(ok=True, message=f"{n} conversation(s) supprimée(s)")


# ══════════════════════════════════════════════════════════
#  CHAT — ENVOI DE MESSAGE
# ══════════════════════════════════════════════════════════

@router.post(
    "/chat",
    response_model=SendMessageResponse,
    summary="Envoyer un message à l'Assistant EasyVoyage (non-streaming) [PARTENAIRE]",
    description=(
        "Si `conversation_id` est absent, une nouvelle conversation est créée. "
        "Le titre est auto-généré à partir du 1er message. "
        "La mémoire côté n8n est gérée via le `session_id` persistant.\n\n"
        "**Important** : le JWT du partenaire est enregistré automatiquement dans "
        "le cache MCP (port 9100) via le `session_id`, permettant aux tools MCP "
        "d'appeler les endpoints authentifiés `/hotels/mes-hotels`, "
        "`/finances-partenaire/*`, `/promotions/mes-promotions`, etc."
    ),
)
async def chat(
    data:    SendMessageRequest,
    session: AsyncSession = Depends(get_db),
    current: TokenData    = Depends(require_partenaire),
):
    return await svc.send_message(current.user_id, current.role, data, session)


@router.post(
    "/chat/stream",
    summary="Envoyer un message avec streaming SSE [PARTENAIRE]",
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
    current: TokenData    = Depends(require_partenaire),
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