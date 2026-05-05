"""
app/services/notification_helper.py
======================================
Helper centralisé pour créer des notifications (admins ET partenaires).

Pourquoi ?
----------
Avant ce fichier, seuls les flux de support créaient des notifications.
Pour étendre ça à TOUS les événements de la plateforme (demandes
partenaire, promotions, retraits, réservations…), on a besoin de
points d'entrée uniques :

    notify_all_admins(session, type_, titre, message, id_conversation=None)
    notify_partenaire(session, partenaire_id, type_, titre, message)        ← ✨ NEW
    notify_partenaire_for_hotel(session, hotel_id, type_, titre, message)   ← ✨ NEW
    notify_user(session, user_id, type_, titre, message)

Ces fonctions :
  1. Créent une ligne dans la table `notification` (universelle).
  2. Ne commitent pas — c'est le caller qui gère sa transaction.
  3. Ne lèvent jamais d'exception : la création d'une notif ne doit
     JAMAIS faire échouer l'action métier.

Utilisation :
-------------
    from app.services.notification_helper import (
        notify_all_admins,
        notify_partenaire,
        notify_partenaire_for_hotel,
        NotifType,
    )

    # Notifier tous les admins
    await notify_all_admins(
        session,
        type_   = NotifType.NOUVELLE_DEMANDE_PARTENAIRE,
        titre   = "Nouvelle demande partenaire",
        message = f"{nom} ({entreprise}) souhaite rejoindre EasyVoyage",
    )

    # Notifier UN partenaire précis
    await notify_partenaire(
        session,
        partenaire_id = promo.id_partenaire,
        type_         = NotifType.PROMOTION_APPROUVEE,
        titre         = "✅ Promotion approuvée",
        message       = "Votre promotion ...",
    )

    # Notifier le propriétaire d'un hôtel (résa visiteur par exemple)
    await notify_partenaire_for_hotel(
        session,
        hotel_id = chambre.id_hotel,
        type_    = NotifType.NOUVELLE_RESERVATION_HOTEL,
        titre    = "🎉 Nouvelle réservation",
        message  = "...",
    )
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
# Le frontend (NotificationsBell.jsx admin & partenaire) utilise
# ces types pour rediriger vers la bonne page et choisir l'icône.

class NotifType:
    # ── Support (admin & partenaire) ──────────────────────
    NOUVELLE_DEMANDE_SUPPORT  = "NOUVELLE_DEMANDE_SUPPORT"
    NOUVEAU_MESSAGE           = "NOUVEAU_MESSAGE"
    CONVERSATION_ACCEPTEE     = "CONVERSATION_ACCEPTEE"
    CONVERSATION_FERMEE       = "CONVERSATION_FERMEE"

    # ── Partenaires (admin) ───────────────────────────────
    NOUVELLE_DEMANDE_PARTENAIRE = "NOUVELLE_DEMANDE_PARTENAIRE"

    # ── Promotions (admin) ────────────────────────────────
    NOUVELLE_PROMOTION = "NOUVELLE_PROMOTION"

    # ── Promotions (partenaire) — ✨ NEW ───────────────────
    PROMOTION_APPROUVEE = "PROMOTION_APPROUVEE"
    PROMOTION_REFUSEE   = "PROMOTION_REFUSEE"

    # ── Retraits / Finances (admin) ───────────────────────
    NOUVELLE_DEMANDE_RETRAIT = "NOUVELLE_DEMANDE_RETRAIT"

    # ── Retraits / Finances (partenaire) — ✨ NEW ──────────
    RETRAIT_APPROUVE = "RETRAIT_APPROUVE"
    RETRAIT_REFUSE   = "RETRAIT_REFUSE"
    PAIEMENT_RECU    = "PAIEMENT_RECU"

    # ── Réservations (admin) ──────────────────────────────
    NOUVELLE_RESERVATION          = "NOUVELLE_RESERVATION"
    NOUVELLE_RESERVATION_VISITEUR = "NOUVELLE_RESERVATION_VISITEUR"

    # ── Réservations (partenaire) — ✨ NEW ─────────────────
    NOUVELLE_RESERVATION_HOTEL = "NOUVELLE_RESERVATION_HOTEL"
    RESERVATION_ANNULEE        = "RESERVATION_ANNULEE"

    # ── Hôtels (partenaire) — ✨ NEW (futur) ───────────────
    HOTEL_MIS_EN_AVANT = "HOTEL_MIS_EN_AVANT"
    NOUVEL_AVIS        = "NOUVEL_AVIS"

    # ── Clients (admin) ───────────────────────────────────
    NOUVEAU_CLIENT = "NOUVEAU_CLIENT"


# ══════════════════════════════════════════════════════════
#  HELPER ADMIN (existant, inchangé)
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
    int : Nombre d'admins notifiés (0 en cas d'erreur).
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
#  ✨ NEW : HELPER PARTENAIRE
# ══════════════════════════════════════════════════════════

async def notify_partenaire(
    session:       AsyncSession,
    partenaire_id: int,
    type_:         str,
    titre:         str,
    message:       str,
    id_conversation: Optional[int] = None,
) -> bool:
    """
    Crée une notification pour UN partenaire spécifique.

    Ne commit pas la session.
    Ne lève jamais d'exception : en cas d'erreur, on log et on retourne False.

    Returns
    -------
    bool : True si la notification a été créée, False sinon.
    """
    try:
        from app.models.support import Notification

        session.add(Notification(
            id_destinataire = partenaire_id,
            type            = type_,
            titre           = titre,
            message         = message,
            id_conversation = id_conversation,
        ))
        await session.flush()

        logger.info(
            "[notify_partenaire] Partenaire %s notifié | type=%s",
            partenaire_id, type_,
        )
        return True

    except Exception as exc:
        logger.exception(
            "[notify_partenaire] Erreur (partenaire=%s, type=%s) : %s",
            partenaire_id, type_, exc,
        )
        return False


async def notify_partenaire_for_hotel(
    session:  AsyncSession,
    hotel_id: int,
    type_:    str,
    titre:    str,
    message:  str,
) -> bool:
    """
    Récupère le partenaire propriétaire d'un hôtel et le notifie.

    Utile pour les flux où on connaît l'ID de l'hôtel (réservations
    visiteur par exemple) mais pas directement celui du partenaire.

    Ne commit pas la session.
    Ne lève jamais d'exception.

    Returns
    -------
    bool : True si notifié, False si l'hôtel n'a pas de partenaire ou en cas d'erreur.
    """
    try:
        from app.models.hotel import Hotel

        result = await session.execute(
            select(Hotel.id_partenaire).where(Hotel.id == hotel_id)
        )
        partenaire_id = result.scalar_one_or_none()

        if not partenaire_id:
            logger.info(
                "[notify_partenaire_for_hotel] Hôtel %s sans partenaire — skip notif",
                hotel_id,
            )
            return False

        return await notify_partenaire(
            session,
            partenaire_id = partenaire_id,
            type_         = type_,
            titre         = titre,
            message       = message,
        )

    except Exception as exc:
        logger.exception(
            "[notify_partenaire_for_hotel] Erreur (hotel_id=%s, type=%s) : %s",
            hotel_id, type_, exc,
        )
        return False


# ══════════════════════════════════════════════════════════
#  HELPER GÉNÉRIQUE : notifier UN utilisateur
# ══════════════════════════════════════════════════════════

async def notify_user(
    session: AsyncSession,
    user_id: int,
    type_:   str,
    titre:   str,
    message: str,
    id_conversation: Optional[int] = None,
) -> bool:
    """Crée une notification pour UN utilisateur précis (alias générique)."""
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