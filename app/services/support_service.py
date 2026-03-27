"""
Service Support Chat — logique métier complète.

Flux :
  1. Partenaire crée une conversation (statut EN_ATTENTE)
     → Notification envoyée à TOUS les admins
  2. Un admin accepte la conversation (statut ACCEPTEE, id_admin assigné)
     → Notification envoyée au partenaire
  3. Les deux peuvent envoyer des messages
     → Notification au destinataire à chaque message
  4. L'admin ou le partenaire peut fermer (statut FERMEE)
"""
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.support import Notification, SupportConversation, SupportMessage
from app.models.utilisateur import Utilisateur
from app.schemas.support import (
    ConversationCreate, ConversationListResponse, ConversationResponse,
    MessageCreate, MessageResponse,
    NotificationListResponse, NotificationResponse,
    UserCompact,
)


# ── Helpers ───────────────────────────────────────────────
def _user_compact(u: Optional[Utilisateur]) -> Optional[UserCompact]:
    if not u:
        return None
    return UserCompact(id=u.id, nom=u.nom, prenom=u.prenom, role=u.role.value)


async def _count_non_lus(conv_id: int, reader_id: int, session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(SupportMessage).where(
            SupportMessage.id_conversation == conv_id,
            SupportMessage.lu == False,
            SupportMessage.id_expediteur != reader_id,
        )
    )
    return result.scalar_one()


def _to_msg(m: SupportMessage) -> MessageResponse:
    return MessageResponse(
        id=m.id, id_conversation=m.id_conversation,
        id_expediteur=m.id_expediteur, contenu=m.contenu,
        lu=m.lu, created_at=m.created_at,
        expediteur=_user_compact(m.expediteur) if m.expediteur else None,
    )


async def _to_conv(c: SupportConversation, reader_id: int, session: AsyncSession) -> ConversationResponse:
    nb = await _count_non_lus(c.id, reader_id, session)
    return ConversationResponse(
        id=c.id, id_partenaire=c.id_partenaire, id_admin=c.id_admin,
        sujet=c.sujet, statut=c.statut,
        created_at=c.created_at, updated_at=c.updated_at,
        partenaire=_user_compact(c.partenaire),
        admin=_user_compact(c.admin),
        messages=[_to_msg(m) for m in (c.messages or [])],
        nb_non_lus=nb,
    )


async def _create_notif(
    session: AsyncSession,
    id_dest: int, type_: str, titre: str, message: str,
    id_conv: Optional[int] = None,
) -> None:
    notif = Notification(
        id_destinataire=id_dest, type=type_,
        titre=titre, message=message, id_conversation=id_conv,
    )
    session.add(notif)


# ══════════════════════════════════════════════════════════
#  CONVERSATIONS — Partenaire
# ══════════════════════════════════════════════════════════
async def create_conversation(
    partenaire_id: int, data: ConversationCreate, session: AsyncSession
) -> ConversationResponse:
    conv = SupportConversation(
        id_partenaire=partenaire_id,
        sujet=data.sujet,
        statut="EN_ATTENTE",
    )
    session.add(conv)
    await session.flush()

    # Notifier tous les admins
    admins = await session.execute(
        select(Utilisateur).where(Utilisateur.role == "ADMIN", Utilisateur.actif == True)
    )
    for admin in admins.scalars().all():
        await _create_notif(
            session, admin.id,
            "NOUVELLE_DEMANDE_SUPPORT",
            "Nouvelle demande de support",
            f"Un partenaire a ouvert une conversation : « {data.sujet} »",
            conv.id,
        )
    await session.flush()

    # Recharger avec relations
    result = await session.execute(
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .where(SupportConversation.id == conv.id)
    )
    conv = result.scalar_one()
    return await _to_conv(conv, partenaire_id, session)


async def get_my_conversations(
    partenaire_id: int, session: AsyncSession
) -> ConversationListResponse:
    result = await session.execute(
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .where(SupportConversation.id_partenaire == partenaire_id)
        .order_by(SupportConversation.updated_at.desc())
    )
    convs = result.scalars().all()
    items = [await _to_conv(c, partenaire_id, session) for c in convs]
    return ConversationListResponse(total=len(items), items=items)


# ══════════════════════════════════════════════════════════
#  CONVERSATIONS — Admin
# ══════════════════════════════════════════════════════════
async def get_all_conversations(
    admin_id: int, session: AsyncSession,
    statut: Optional[str] = None,
) -> ConversationListResponse:
    q = (
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .order_by(SupportConversation.updated_at.desc())
    )
    if statut:
        q = q.where(SupportConversation.statut == statut)

    result = await session.execute(q)
    convs = result.scalars().all()
    items = [await _to_conv(c, admin_id, session) for c in convs]
    return ConversationListResponse(total=len(items), items=items)


async def accept_conversation(
    conv_id: int, admin_id: int, session: AsyncSession
) -> ConversationResponse:
    result = await session.execute(
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .where(SupportConversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundException(f"Conversation {conv_id} introuvable")
    if conv.statut != "EN_ATTENTE":
        raise ForbiddenException("Cette conversation a déjà été traitée")

    conv.id_admin = admin_id
    conv.statut = "ACCEPTEE"
    conv.updated_at = datetime.now(timezone.utc)
    await session.flush()

    # Notifier le partenaire
    await _create_notif(
        session, conv.id_partenaire,
        "CONVERSATION_ACCEPTEE",
        "Votre demande a été acceptée",
        "Un administrateur a accepté votre demande de support et est prêt à vous aider.",
        conv.id,
    )
    await session.flush()

    # Recharger
    result2 = await session.execute(
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .where(SupportConversation.id == conv_id)
    )
    return await _to_conv(result2.scalar_one(), admin_id, session)


async def close_conversation(
    conv_id: int, user_id: int, session: AsyncSession
) -> ConversationResponse:
    result = await session.execute(
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .where(SupportConversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundException(f"Conversation {conv_id} introuvable")
    if conv.id_partenaire != user_id and conv.id_admin != user_id:
        raise ForbiddenException("Accès refusé")

    conv.statut = "FERMEE"
    conv.updated_at = datetime.now(timezone.utc)
    await session.flush()

    # Notifier l'autre partie
    autre_id = conv.id_admin if user_id == conv.id_partenaire else conv.id_partenaire
    if autre_id:
        await _create_notif(
            session, autre_id,
            "CONVERSATION_FERMEE",
            "Conversation fermée",
            f"La conversation « {conv.sujet} » a été fermée.",
            conv.id,
        )
    await session.flush()
    return await _to_conv(conv, user_id, session)


# ══════════════════════════════════════════════════════════
#  MESSAGES
# ══════════════════════════════════════════════════════════
async def get_conversation_messages(
    conv_id: int, user_id: int, session: AsyncSession
) -> ConversationResponse:
    result = await session.execute(
        select(SupportConversation)
        .options(
            selectinload(SupportConversation.partenaire),
            selectinload(SupportConversation.admin),
            selectinload(SupportConversation.messages).selectinload(SupportMessage.expediteur),
        )
        .where(SupportConversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundException(f"Conversation {conv_id} introuvable")
    if conv.id_partenaire != user_id and conv.id_admin != user_id:
        raise ForbiddenException("Accès refusé")

    # Marquer les messages comme lus
    for msg in conv.messages:
        if not msg.lu and msg.id_expediteur != user_id:
            msg.lu = True
    await session.flush()

    return await _to_conv(conv, user_id, session)


async def send_message(
    conv_id: int, sender_id: int, data: MessageCreate, session: AsyncSession
) -> MessageResponse:
    result = await session.execute(
        select(SupportConversation)
        .options(selectinload(SupportConversation.partenaire), selectinload(SupportConversation.admin))
        .where(SupportConversation.id == conv_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundException(f"Conversation {conv_id} introuvable")
    if conv.statut == "FERMEE":
        raise ForbiddenException("Cette conversation est fermée")
    if conv.id_partenaire != sender_id and conv.id_admin != sender_id:
        raise ForbiddenException("Accès refusé")

    msg = SupportMessage(
        id_conversation=conv_id,
        id_expediteur=sender_id,
        contenu=data.contenu,
    )
    session.add(msg)

    # Mettre à jour updated_at
    conv.updated_at = datetime.now(timezone.utc)

    await session.flush()
    await session.refresh(msg)

    # Charger expéditeur
    result2 = await session.execute(
        select(SupportMessage)
        .options(selectinload(SupportMessage.expediteur))
        .where(SupportMessage.id == msg.id)
    )
    msg = result2.scalar_one()

    # Notifier le destinataire
    dest_id = conv.id_admin if sender_id == conv.id_partenaire else conv.id_partenaire
    if dest_id:
        sender_nom = f"{msg.expediteur.prenom} {msg.expediteur.nom}" if msg.expediteur else "Quelqu'un"
        await _create_notif(
            session, dest_id,
            "NOUVEAU_MESSAGE",
            f"Nouveau message de {sender_nom}",
            f"« {data.contenu[:80]}{'...' if len(data.contenu) > 80 else ''} »",
            conv_id,
        )
    await session.flush()

    return _to_msg(msg)


# ══════════════════════════════════════════════════════════
#  NOTIFICATIONS
# ══════════════════════════════════════════════════════════
async def get_notifications(
    user_id: int, session: AsyncSession
) -> NotificationListResponse:
    result = await session.execute(
        select(Notification)
        .where(Notification.id_destinataire == user_id)
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    notifs = result.scalars().all()
    nb_lues = sum(1 for n in notifs if not n.lue)
    return NotificationListResponse(
        total=len(notifs),
        nb_lues=nb_lues,
        items=[NotificationResponse.model_validate(n) for n in notifs],
    )


async def mark_notification_read(
    notif_id: int, user_id: int, session: AsyncSession
) -> None:
    result = await session.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.id_destinataire == user_id,
        )
    )
    notif = result.scalar_one_or_none()
    if notif:
        notif.lue = True
        await session.flush()


async def mark_all_read(user_id: int, session: AsyncSession) -> None:
    result = await session.execute(
        select(Notification).where(
            Notification.id_destinataire == user_id,
            Notification.lue == False,
        )
    )
    for n in result.scalars().all():
        n.lue = True
    await session.flush()