"""
app/services/agent_ia_service.py
=================================
Service métier pour l'Agent IA :
  - Gestion des conversations (CRUD)
  - Proxy vers n8n (webhook AI Agent)
  - Persistance BDD (user + assistant messages)
  - Auto-génération du titre après le 1er échange

Configuration :
  N8N_AGENT_WEBHOOK (env) : http://localhost:5678/webhook/agent-admin-chat

⚠️ Le webhook n8n doit être configuré pour recevoir :
     {
       "session_id": "conv_<id>_<uuid>",
       "message":    "texte user",
       "user_id":    123,
       "user_role":  "ADMIN"
     }
   Et renvoyer :
     { "output": "réponse IA" }     (mode non-streaming)
   Ou un stream SSE (mode streaming — optionnel).
"""
from __future__ import annotations

import os
import time
import uuid
import httpx
from datetime import datetime, timezone
from typing import List, Optional, AsyncIterator

from fastapi import HTTPException, status
from sqlalchemy import select, func, desc, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai_conversation import AiConversation, AiMessage
from app.schemas.agent_ia import (
    ConversationListItem, ConversationListResponse, ConversationDetailResponse,
    MessageResponse, SendMessageRequest, SendMessageResponse,
)

# ── Configuration n8n ─────────────────────────────────────
N8N_AGENT_WEBHOOK = os.getenv(
    "N8N_AGENT_WEBHOOK",
    "http://localhost:5678/webhook/agent-admin-chat",
)
N8N_TIMEOUT = float(os.getenv("N8N_AGENT_TIMEOUT", "60.0"))  # secondes


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _new_session_id(conv_id: int) -> str:
    """Génère un session_id stable par conversation."""
    return f"conv_{conv_id}_{uuid.uuid4().hex[:8]}"


def _derive_titre(message: str) -> str:
    """Dérive un titre court à partir du 1er message."""
    clean = " ".join(message.strip().split())
    if len(clean) > 80:
        clean = clean[:77].rstrip() + "…"
    return clean or "Nouvelle conversation"


async def _call_n8n(payload: dict) -> tuple[str, int]:
    """
    Appelle le webhook n8n et retourne (reply, duree_ms).
    Lève HTTPException(502) en cas d'erreur.
    """
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=N8N_TIMEOUT) as client:
            r = await client.post(N8N_AGENT_WEBHOOK, json=payload)
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="L'agent IA n'a pas répondu à temps. Réessayez.",
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

    # n8n peut renvoyer un objet ou un tableau
    try:
        data = r.json()
    except Exception:
        return r.text.strip() or "(réponse vide)", duree_ms

    if isinstance(data, list) and data:
        data = data[0]

    # Clés possibles : output, reply, response, text
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
    """Liste des conversations (sidebar) — non archivées, plus récentes d'abord."""
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
    """Détail + tous les messages."""
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
    await session.delete(conv)  # CASCADE supprime les messages
    await session.flush()


async def clear_all_conversations(user_id: int, session: AsyncSession) -> int:
    """Supprime TOUTES les conversations de l'utilisateur. Retourne le nb supprimé."""
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
#  ENVOI DE MESSAGE — coeur du service
# ══════════════════════════════════════════════════════════

async def send_message(
    user_id:   int,
    user_role: str,
    data:      SendMessageRequest,
    session:   AsyncSession,
) -> SendMessageResponse:
    """
    Flux :
      1. Si conversation_id absent → créer une nouvelle conversation
      2. Persister le user_message
      3. Appeler n8n (avec session_id)
      4. Persister le assistant_message
      5. Auto-générer le titre si 1er échange
      6. Renvoyer les deux messages + conv_id
    """
    # ── 1. Trouver ou créer la conversation ──
    conv: Optional[AiConversation] = None

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
            id_utilisateur = user_id,
            session_id     = f"tmp_{uuid.uuid4().hex[:12]}",  # temporaire
            titre          = "Nouvelle conversation",
            role_contexte  = user_role,
        )
        session.add(conv)
        await session.flush()   # pour obtenir conv.id
        conv.session_id = _new_session_id(conv.id)
        await session.flush()

    # ── 2. Persister le user_message ──
    user_msg = AiMessage(
        id_conversation = conv.id,
        role            = "user",
        contenu         = data.message.strip(),
    )
    session.add(user_msg)
    await session.flush()
    await session.refresh(user_msg)

    # ── 3. Appeler n8n ──
    payload = {
        "session_id": conv.session_id,
        "message":    data.message,
        "user_id":    user_id,
        "user_role":  user_role,
        "conversation_id": conv.id,
    }
    try:
        reply_text, duree_ms = await _call_n8n(payload)
        is_error = False
    except HTTPException as e:
        reply_text = f"❌ {e.detail}"
        duree_ms   = 0
        is_error   = True

    # ── 4. Persister le assistant_message ──
    assistant_msg = AiMessage(
        id_conversation = conv.id,
        role            = "assistant",
        contenu         = reply_text,
        duree_ms        = duree_ms,
        is_error        = is_error,
    )
    session.add(assistant_msg)
    await session.flush()
    await session.refresh(assistant_msg)

    # ── 5. Auto-générer le titre si c'est le 1er échange ──
    if is_new_conv and not is_error:
        conv.titre = _derive_titre(data.message)
        await session.flush()

    # ── 6. Renvoyer la réponse ──
    return SendMessageResponse(
        conversation_id   = conv.id,
        session_id        = conv.session_id,
        user_message      = MessageResponse.model_validate(user_msg),
        assistant_message = MessageResponse.model_validate(assistant_msg),
        titre             = conv.titre,
    )


# ══════════════════════════════════════════════════════════
#  STREAMING (optionnel — si n8n est configuré pour streamer)
# ══════════════════════════════════════════════════════════

async def stream_message(
    user_id:   int,
    user_role: str,
    data:      SendMessageRequest,
    session:   AsyncSession,
) -> AsyncIterator[str]:
    """
    Mode streaming SSE.
    Le frontend consomme via EventSource ou fetch streaming.

    Format des events SSE :
      data: {"type":"conv","conversation_id":42,"session_id":"..."}\n\n
      data: {"type":"user_msg","message": {...}}\n\n
      data: {"type":"token","text":"chunk"}\n\n
      data: {"type":"done","assistant_message": {...},"titre":"..."}\n\n
      data: {"type":"error","detail":"..."}\n\n

    ⚠️ Implémentation simplifiée : on fait l'appel non-streaming à n8n,
       puis on simule des tokens pour le frontend.
       Pour du vrai streaming, il faudrait un webhook n8n qui renvoie
       un Response Stream (peu commun dans n8n standard).
    """
    import json

    # 1. Créer/récupérer la conversation
    result = await send_message(user_id, user_role, data, session)
    await session.commit()

    # 2. Event "conv"
    yield f"data: {json.dumps({'type':'conv', 'conversation_id': result.conversation_id, 'session_id': result.session_id})}\n\n"

    # 3. Event "user_msg"
    yield f"data: {json.dumps({'type':'user_msg', 'message': result.user_message.model_dump(mode='json')})}\n\n"

    # 4. Simuler des tokens (découpage mot par mot)
    text = result.assistant_message.contenu
    for word in text.split(" "):
        yield f"data: {json.dumps({'type':'token','text': word + ' '})}\n\n"

    # 5. Event "done"
    yield f"data: {json.dumps({'type':'done', 'assistant_message': result.assistant_message.model_dump(mode='json'), 'titre': result.titre})}\n\n"