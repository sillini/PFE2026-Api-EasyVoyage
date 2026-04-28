"""
app/services/agent_ia_partenaire_service.py
============================================
Service metier pour l'Agent IA — Espace PARTENAIRE.
VERSION AVEC CACHE JWT (plus de JWT dans le payload n8n).

Jumeau de agent_ia_client_service.py avec 3 differences :
  - Webhook n8n : N8N_PARTENAIRE_AGENT_WEBHOOK (agent-partenaire-chat)
  - Prefix session_id : "part_" au lieu de "cli_"
  - role_contexte     : "PARTENAIRE" au lieu de "CLIENT"
  - JWT genere avec role "PARTENAIRE"

Principe d'authentification :
  1. Frontend envoie message avec JWT partenaire dans Authorization Bearer
  2. Service cree la conversation si besoin (session_id = part_<id>_<uuid>)
  3. Service genere un fresh JWT partenaire
  4. Service enregistre le JWT dans le cache MCP (port 9100) avec session_id
  5. Service POST vers n8n webhook (sans JWT dans le payload)
  6. n8n AI Agent appelle les MCP tools avec session_id
  7. Tools MCP recuperent le JWT depuis le cache → appels HTTP authentifies
"""
from __future__ import annotations

import os
import time
import uuid
import httpx
import logging
from datetime import datetime, timezone
from typing import List, Optional, AsyncIterator

from fastapi import HTTPException, status
from sqlalchemy import select, func, desc, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import create_access_token
from app.models.ai_conversation import AiConversation, AiMessage
from app.schemas.agent_ia import (
    ConversationListItem, ConversationListResponse, ConversationDetailResponse,
    MessageResponse, SendMessageRequest, SendMessageResponse,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────
N8N_PARTENAIRE_AGENT_WEBHOOK = settings.N8N_PARTENAIRE_AGENT_WEBHOOK

N8N_TIMEOUT = float(os.getenv("N8N_AGENT_TIMEOUT", "60.0"))

# Cache JWT cote MCP (meme cache que pour le CLIENT)
MCP_SESSION_CACHE_URL = settings.MCP_SESSION_CACHE_URL


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _new_session_id(conv_id: int) -> str:
    """Genere un session_id stable par conversation partenaire."""
    return f"part_{conv_id}_{uuid.uuid4().hex[:8]}"


def _derive_titre(message: str) -> str:
    """Derive un titre court a partir du 1er message."""
    clean = " ".join(message.strip().split())
    if len(clean) > 80:
        clean = clean[:77].rstrip() + "…"
    return clean or "Nouvelle conversation"


async def _register_jwt_in_mcp_cache(session_id: str, jwt: str) -> bool:
    """Enregistre le JWT dans le cache MCP avant d'appeler n8n."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{MCP_SESSION_CACHE_URL}/register_session",
                json={"session_id": session_id, "jwt_token": jwt},
            )
        if r.status_code == 200:
            print(f"[MCP CACHE] JWT registered for session {session_id}")
            return True
        print(f"[MCP CACHE] register failed: HTTP {r.status_code}")
        return False
    except Exception as e:
        print(f"[MCP CACHE] register error: {e}")
        return False


async def _call_n8n(payload: dict) -> tuple[str, int]:
    """Appelle le webhook n8n partenaire et retourne (reply, duree_ms)."""
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=N8N_TIMEOUT) as client:
            r = await client.post(N8N_PARTENAIRE_AGENT_WEBHOOK, json=payload)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="L'assistant n'a pas répondu à temps. Réessayez.",
        )
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur réseau n8n: {e}",
        )

    duree_ms = int((time.perf_counter() - t0) * 1000)

    if r.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"n8n a renvoyé un code {r.status_code}",
        )

    try:
        data = r.json()
    except Exception:
        return r.text.strip() or "(réponse vide)", duree_ms

    if isinstance(data, list) and data:
        data = data[0]

    reply = (
        data.get("output")
        or data.get("reply")
        or data.get("response")
        or data.get("text")
        or ""
    )
    if not reply:
        reply = "(réponse vide — vérifiez le node 'Respond to Webhook' dans n8n)"

    return str(reply).strip(), duree_ms


# ══════════════════════════════════════════════════════════
#  CRUD CONVERSATIONS
# ══════════════════════════════════════════════════════════

async def list_conversations(
    user_id: int,
    session: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> ConversationListResponse:
    """Liste des conversations (sidebar) — non archivees, plus recentes d'abord."""
    total_q = select(func.count(AiConversation.id)).where(
        AiConversation.id_utilisateur == user_id,
        AiConversation.archivee.is_(False),
    )
    total = (await session.execute(total_q)).scalar_one()

    items_q = (
        select(AiConversation)
        .where(
            AiConversation.id_utilisateur == user_id,
            AiConversation.archivee.is_(False),
        )
        .order_by(desc(AiConversation.last_message_at))
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(items_q)).scalars().all()
    items = [ConversationListItem.model_validate(c) for c in rows]

    return ConversationListResponse(total=total, items=items)


async def get_conversation(
    conv_id: int,
    user_id: int,
    session: AsyncSession,
) -> ConversationDetailResponse:
    """Detail + tous les messages."""
    q = (
        select(AiConversation)
        .options(selectinload(AiConversation.messages))
        .where(AiConversation.id == conv_id, AiConversation.id_utilisateur == user_id)
    )
    conv = (await session.execute(q)).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation introuvable")
    if conv.archivee:
        raise HTTPException(404, "Conversation archivée")

    messages = [MessageResponse.model_validate(m) for m in conv.messages]

    return ConversationDetailResponse(
        id              = conv.id,
        session_id      = conv.session_id,
        titre           = conv.titre,
        nb_messages     = conv.nb_messages,
        tokens_total    = conv.tokens_total,
        created_at      = conv.created_at,
        updated_at      = conv.updated_at,
        last_message_at = conv.last_message_at,
        messages        = messages,
    )


async def rename_conversation(
    conv_id: int,
    user_id: int,
    new_titre: str,
    session: AsyncSession,
) -> None:
    q = select(AiConversation).where(
        AiConversation.id == conv_id,
        AiConversation.id_utilisateur == user_id,
    )
    conv = (await session.execute(q)).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation introuvable")
    conv.titre = new_titre[:200]
    await session.flush()


async def delete_conversation(
    conv_id: int,
    user_id: int,
    session: AsyncSession,
) -> None:
    q = select(AiConversation).where(
        AiConversation.id == conv_id,
        AiConversation.id_utilisateur == user_id,
    )
    conv = (await session.execute(q)).scalar_one_or_none()
    if not conv:
        raise HTTPException(404, "Conversation introuvable")
    await session.delete(conv)
    await session.flush()


async def clear_all_conversations(user_id: int, session: AsyncSession) -> int:
    """Supprime TOUTES les conversations de l'utilisateur."""
    q = select(func.count(AiConversation.id)).where(
        AiConversation.id_utilisateur == user_id
    )
    n = (await session.execute(q)).scalar_one()
    await session.execute(
        delete(AiConversation).where(AiConversation.id_utilisateur == user_id)
    )
    await session.flush()
    return n


# ══════════════════════════════════════════════════════════
#  ENVOI DE MESSAGE
# ══════════════════════════════════════════════════════════

async def send_message(user_id, user_role, data, session):
    conv = None

    if data.conversation_id:
        q = select(AiConversation).where(
            AiConversation.id == data.conversation_id,
            AiConversation.id_utilisateur == user_id,
        )
        conv = (await session.execute(q)).scalar_one_or_none()
        if not conv:
            raise HTTPException(404, "Conversation introuvable")
        if conv.archivee:
            raise HTTPException(403, "Conversation archivée")

    is_new_conv = conv is None
    if is_new_conv:
        conv = AiConversation(
            id_utilisateur=user_id,
            session_id=f"tmp_{uuid.uuid4().hex[:12]}",
            titre="Nouvelle conversation",
            role_contexte="PARTENAIRE",
        )
        session.add(conv)
        await session.flush()
        conv.session_id = _new_session_id(conv.id)
        await session.flush()

    user_msg = AiMessage(
        id_conversation=conv.id,
        role="user",
        contenu=data.message.strip(),
    )
    session.add(user_msg)
    await session.flush()
    await session.refresh(user_msg)

    # ═══════════════════════════════════════════════════════
    #  ETAPE CRITIQUE — REGISTRER LE JWT DANS LE CACHE MCP
    # ═══════════════════════════════════════════════════════
    fresh_jwt = create_access_token(user_id, "PARTENAIRE")
    print(f"[AGENT PARTENAIRE] session_id={conv.session_id}, jwt_len={len(fresh_jwt)}")
    registered = await _register_jwt_in_mcp_cache(conv.session_id, fresh_jwt)
    if not registered:
        print(f"[AGENT PARTENAIRE] ATTENTION: JWT non enregistre dans le cache MCP !")

    payload = {
        "session_id":      conv.session_id,
        "message":         data.message,
        "user_id":         user_id,
        "user_role":       "PARTENAIRE",
        "conversation_id": conv.id,
        "jwt_token":       fresh_jwt,  # fallback compat
    }

    try:
        reply_text, duree_ms = await _call_n8n(payload)
        is_error = False
    except HTTPException as e:
        reply_text = f"❌ {e.detail}"
        duree_ms = 0
        is_error = True

    assistant_msg = AiMessage(
        id_conversation=conv.id,
        role="assistant",
        contenu=reply_text,
        duree_ms=duree_ms,
        is_error=is_error,
    )
    session.add(assistant_msg)
    await session.flush()
    await session.refresh(assistant_msg)

    if is_new_conv and not is_error:
        conv.titre = _derive_titre(data.message)
        await session.flush()

    return SendMessageResponse(
        conversation_id=conv.id,
        session_id=conv.session_id,
        user_message=MessageResponse.model_validate(user_msg),
        assistant_message=MessageResponse.model_validate(assistant_msg),
        titre=conv.titre,
    )


# ══════════════════════════════════════════════════════════
#  STREAMING (SSE)
# ══════════════════════════════════════════════════════════

async def stream_message(user_id, user_role, data, session):
    """
    Mode streaming SSE.
    Le frontend consomme via fetch streaming.

    Format des events SSE :
      data: {"type":"conv","conversation_id":42,"session_id":"..."}\n\n
      data: {"type":"user_msg","message": {...}}\n\n
      data: {"type":"token","text":"chunk"}\n\n
      data: {"type":"done","assistant_message": {...},"titre":"..."}\n\n
      data: {"type":"error","detail":"..."}\n\n
    """
    import json
    result = await send_message(user_id, user_role, data, session)
    await session.commit()

    yield f"data: {json.dumps({'type':'conv', 'conversation_id': result.conversation_id, 'session_id': result.session_id})}\n\n"
    yield f"data: {json.dumps({'type':'user_msg', 'message': result.user_message.model_dump(mode='json')})}\n\n"

    text = result.assistant_message.contenu
    for word in text.split(" "):
        yield f"data: {json.dumps({'type':'token','text': word + ' '})}\n\n"

    yield f"data: {json.dumps({'type':'done', 'assistant_message': result.assistant_message.model_dump(mode='json'), 'titre': result.titre})}\n\n"