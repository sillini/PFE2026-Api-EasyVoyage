"""
app/services/notification_helper.py
======================================
Helper centralisé pour créer des notifications côté admin.

Pourquoi ?
----------
Avant ce fichier, seuls les flux de support créaient des notifications.
Pour étendre ça à TOUS les événements de la plateforme (demandes
partenaire, promotions, retraits, réservations…), on a besoin d'un
point d'entrée unique :

    notify_all_admins(session, type_, titre, message, id_conversation=None)

Cette fonction :
  1. Récupère TOUS les admins actifs.
  2. Crée une ligne dans la table `notification` pour chaque admin.
  3. Ne commit pas — c'est le caller qui gère sa transaction.

Utilisation :
-------------
    from app.services.notification_helper import notify_all_admins

    await notify_all_admins(
        session,
        type_   = "NOUVELLE_DEMANDE_PARTENAIRE",
        titre   = "Nouvelle demande partenaire",
        message = f"{nom} ({entreprise}) souhaite rejoindre EasyVoyage",
    )

Robustesse :
-----------
- Si une erreur survient (DB, modèle, etc.) → le helper log et passe en silence.
  La création d'une notification ne doit JAMAIS faire échouer l'action métier
  (créer une réservation, soumettre une demande, etc.).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  TYPES DE NOTIFICATIONS — référentiel central
# ══════════════════════════════════════════════════════════
# Le frontend (NotificationsBell.jsx) utilise ces types pour
# rediriger vers la bonne page et choisir l'icône.

class NotifType:
    # Support
    NOUVELLE_DEMANDE_SUPPORT  = "NOUVELLE_DEMANDE_SUPPORT"
    NOUVEAU_MESSAGE           = "NOUVEAU_MESSAGE"
    CONVERSATION_ACCEPTEE     = "CONVERSATION_ACCEPTEE"
    CONVERSATION_FERMEE       = "CONVERSATION_FERMEE"

    # Partenaires
    NOUVELLE_DEMANDE_PARTENAIRE = "NOUVELLE_DEMANDE_PARTENAIRE"

    # Promotions
    NOUVELLE_PROMOTION = "NOUVELLE_PROMOTION"

    # Retraits / Finances
    NOUVELLE_DEMANDE_RETRAIT = "NOUVELLE_DEMANDE_RETRAIT"

    # Réservations
    NOUVELLE_RESERVATION          = "NOUVELLE_RESERVATION"
    NOUVELLE_RESERVATION_VISITEUR = "NOUVELLE_RESERVATION_VISITEUR"

    # Clients
    NOUVEAU_CLIENT = "NOUVEAU_CLIENT"


# ══════════════════════════════════════════════════════════
#  HELPER PRINCIPAL
# ══════════════════════════════════════════════════════════

async def notify_all_admins(
    session: AsyncSession,
    type_:   str,
    titre:   str,
    message: str,
    id_conversation: Optional[int] = None,
) -> int:
    """
    Crée une notification pour TOUS les admins actifs.

    Ne commit pas la session (c'est le caller qui gère).
    Ne lève jamais d'exception : en cas d'erreur, on log et on retourne 0.

    Returns
    -------
    int
        Nombre d'admins notifiés (0 en cas d'erreur).
    """
    try:
        # Imports locaux pour éviter les cycles d'import au démarrage
        from app.models.support import Notification
        from app.models.utilisateur import Utilisateur, RoleUtilisateur

        # Récupérer tous les admins actifs
        try:
            admins_res = await session.execute(
                select(Utilisateur).where(
                    Utilisateur.role  == RoleUtilisateur.ADMIN,
                    Utilisateur.actif == True,
                )
            )
        except Exception:
            # Fallback si l'enum n'est pas exact (compat anciennes versions)
            admins_res = await session.execute(
                select(Utilisateur).where(
                    Utilisateur.role  == "ADMIN",
                    Utilisateur.actif == True,
                )
            )

        admins = admins_res.scalars().all()

        if not admins:
            logger.warning(
                "[notify_all_admins] Aucun admin actif trouvé pour le type=%s",
                type_,
            )
            return 0

        for admin in admins:
            session.add(Notification(
                id_destinataire = admin.id,
                type            = type_,
                titre           = titre,
                message         = message,
                id_conversation = id_conversation,
            ))

        # On flush mais on ne commit pas — le caller décide
        await session.flush()

        logger.info(
            "[notify_all_admins] %d admin(s) notifié(s) | type=%s",
            len(admins), type_,
        )
        return len(admins)

    except Exception as exc:
        # Une notif manquée ne doit jamais casser l'action métier
        logger.exception(
            "[notify_all_admins] Erreur lors de la création des notifs (type=%s) : %s",
            type_, exc,
        )
        return 0


# ══════════════════════════════════════════════════════════
#  HELPER : notifier UN utilisateur (réutilisable plus tard)
# ══════════════════════════════════════════════════════════

async def notify_user(
    session: AsyncSession,
    user_id: int,
    type_:   str,
    titre:   str,
    message: str,
    id_conversation: Optional[int] = None,
) -> bool:
    """Crée une notification pour UN utilisateur précis."""
    try:
        from app.models.support import Notification
        session.add(Notification(
            id_destinataire = user_id,
            type            = type_,
            titre           = titre,
            message         = message,
            id_conversation = id_conversation,
        ))
        await session.flush()
        return True
    except Exception as exc:
        logger.exception(
            "[notify_user] Erreur (user=%s, type=%s) : %s",
            user_id, type_, exc,
        )
        return False