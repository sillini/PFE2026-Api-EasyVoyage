"""
app/services/forgot_password_service.py
========================================
Service métier pour la fonctionnalité "Mot de passe oublié".

Architecture :
  - Réutilise le modèle existant `InvitationOTP` (table invitation_otp)
  - Utilise un préfixe "fp_" sur le tag email pour ne pas entrer en conflit
    avec les OTP de changement email/mot de passe profil ("chg_", "pwd_")
  - Réutilise le service email existant (Brevo via SMTP)

Sécurité :
  - Réponse identique que l'email existe ou non (anti-énumération)
  - Code à 6 chiffres expirant en `OTP_EXPIRE_MINUTES` (15 min)
  - Invalidation des anciens OTP à chaque nouvelle demande
  - Rate-limiting léger : max 3 demandes par fenêtre de 10 min par email
  - Hash bcrypt du nouveau mot de passe (réutilise hash_password)
  - Le code est marqué `used=True` après succès du reset

Note : à intégrer dans `app/services/auth_service.py` ou à importer comme module
       indépendant. Ici on garde séparé pour clarté.
"""
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ForbiddenException
from app.core.security import hash_password
from app.models.invitation_otp import InvitationOTP
from app.models.utilisateur import Utilisateur
from app.services.email_service import send_email
from app.schemas.auth_forgot_password import (
    ForgotPasswordResponse,
    ForgotPasswordVerifyResponse,
    ForgotPasswordResetResponse,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────
TAG_PREFIX = "fp_"               # Préfixe pour distinguer ces OTP des autres
RATE_LIMIT_WINDOW_MIN = 10       # Fenêtre de rate-limiting (minutes)
RATE_LIMIT_MAX_REQUESTS = 3      # Nombre max de demandes dans la fenêtre


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _gen_otp() -> str:
    """Génère un code OTP à 6 chiffres."""
    return f"{random.randint(0, 999999):06d}"


def _tag(email: str) -> str:
    """Construit le tag email-prefix pour le stockage OTP."""
    return f"{TAG_PREFIX}{email.lower().strip()}"


async def _check_rate_limit(email: str, session: AsyncSession) -> bool:
    """
    Anti-spam : refuse si plus de RATE_LIMIT_MAX_REQUESTS demandes
    ont été créées dans la fenêtre RATE_LIMIT_WINDOW_MIN.
    Retourne True si OK, False si limite atteinte.
    """
    window_start = datetime.now(timezone.utc) - timedelta(minutes=RATE_LIMIT_WINDOW_MIN)
    result = await session.execute(
        select(func.count(InvitationOTP.id)).where(
            InvitationOTP.email == _tag(email),
            InvitationOTP.created_at >= window_start,
        )
    )
    count = result.scalar() or 0
    return count < RATE_LIMIT_MAX_REQUESTS


async def _invalidate_existing(email: str, session: AsyncSession) -> None:
    """Invalide tous les OTP non-utilisés pour cet email."""
    result = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == _tag(email),
            InvitationOTP.used == False,
        )
    )
    for otp in result.scalars().all():
        otp.used = True
    await session.flush()


async def _create_otp(email: str, session: AsyncSession) -> str:
    """Crée et persiste un nouvel OTP, retourne le code."""
    code = _gen_otp()
    expire_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.OTP_EXPIRE_MINUTES
    )
    otp = InvitationOTP(email=_tag(email), code=code, expire_at=expire_at)
    session.add(otp)
    await session.flush()
    return code


async def _find_valid_otp(
    email: str, code: str, session: AsyncSession
) -> InvitationOTP | None:
    """Trouve un OTP valide (non utilisé, non expiré) pour cet email/code."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == _tag(email),
            InvitationOTP.code == code,
            InvitationOTP.used == False,
            InvitationOTP.expire_at > now,
        )
    )
    return result.scalar_one_or_none()


async def _get_user_by_email(
    email: str, session: AsyncSession
) -> Utilisateur | None:
    """Récupère un utilisateur actif par email."""
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.email == email)
    )
    return result.scalar_one_or_none()


# ══════════════════════════════════════════════════════════
#  EMAIL — TEMPLATE FORGOT PASSWORD (cohérent avec le design EasyVoyage)
# ══════════════════════════════════════════════════════════

async def _send_forgot_password_email(
    to: str, code: str, prenom: str = ""
) -> None:
    """
    Envoie l'email contenant le code OTP de réinitialisation via Brevo.
    Ne lève jamais d'exception — log les erreurs et continue.
    """
    greeting = f"Bonjour {prenom}," if prenom else "Bonjour,"
    expire_min = settings.OTP_EXPIRE_MINUTES

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F6F8;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6F8;">
  <tr><td align="center" style="padding:40px 20px;">
    <table width="560" cellpadding="0" cellspacing="0"
      style="background:#FFFFFF;border-radius:16px;overflow:hidden;
             box-shadow:0 4px 24px rgba(0,0,0,0.08);max-width:560px;width:100%;">

      <!-- En-tête -->
      <tr><td style="background:linear-gradient(135deg,#0F2235 0%,#1A3F63 100%);
                     padding:28px 44px;text-align:center;">
        <h1 style="color:#FFFFFF;font-size:24px;margin:0;font-family:Georgia,serif;
                   font-weight:700;letter-spacing:1px;">EasyVoyage</h1>
        <p style="color:rgba(255,255,255,0.55);margin:6px 0 0;font-size:12px;
                  text-transform:uppercase;letter-spacing:1px;">
          Réinitialisation du mot de passe
        </p>
      </td></tr>

      <!-- Corps -->
      <tr><td style="padding:36px 44px 12px;">
        <p style="color:#0F2235;font-size:15px;margin:0 0 6px;font-weight:600;">
          {greeting}
        </p>
        <p style="color:#4A5568;font-size:14px;line-height:1.7;margin:0 0 24px;">
          Vous avez demandé la réinitialisation du mot de passe de votre compte
          EasyVoyage. Saisissez le code ci-dessous dans la fenêtre ouverte sur
          notre site pour définir un nouveau mot de passe :
        </p>

        <!-- Code OTP -->
        <div style="text-align:center;margin:28px 0;">
          <div style="display:inline-block;background:#F0F4F8;
                      border:2px dashed #C4973A;border-radius:14px;
                      padding:18px 48px;">
            <span style="font-size:36px;font-weight:700;color:#0F2235;
                         letter-spacing:14px;font-family:Courier New,monospace;">
              {code}
            </span>
          </div>
        </div>

        <p style="color:#8A9BB0;font-size:13px;text-align:center;margin:0 0 28px;">
          ⏱ Ce code expire dans
          <strong style="color:#C0392B;">{expire_min} minutes</strong>
        </p>

        <div style="background:#FFF8EC;border:1px solid rgba(196,151,58,0.3);
                    border-radius:10px;padding:14px 18px;margin-bottom:20px;">
          <p style="color:#8A6914;font-size:13px;margin:0;line-height:1.5;">
            🔒 <strong>Sécurité :</strong> Si vous n'êtes pas à l'origine de
            cette demande, ignorez simplement cet email. Votre mot de passe
            actuel reste inchangé et votre compte est en sécurité.
          </p>
        </div>
      </td></tr>

      <!-- Pied de page -->
      <tr><td style="background:#F8FAFC;padding:16px 44px;text-align:center;
                     border-top:1px solid #EEF2F7;">
        <p style="color:#B0BEC8;font-size:11px;margin:0;">
          EasyVoyage — www.easyvoyage.tn
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

    try:
        await send_email(
            to=to,
            subject="🔑 Réinitialisation de votre mot de passe — EasyVoyage",
            html_body=html,
        )
        logger.info(f"[FORGOT_PWD] ✅ Email OTP envoyé à {to}")
    except Exception as exc:
        logger.error(
            f"[FORGOT_PWD] ❌ Échec envoi email à {to}: {exc}\n"
            f"[FORGOT_PWD] 💡 En dev, le code apparaît dans les logs uvicorn."
        )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 1 — Demande de code
# ══════════════════════════════════════════════════════════

async def request_forgot_password(
    email: str, session: AsyncSession
) -> ForgotPasswordResponse:
    """
    Étape 1 : reçoit un email, et SI l'email existe, envoie un code OTP.

    ⚠️ SÉCURITÉ : retourne TOUJOURS le même message — qu'il existe un compte
       avec cet email ou non — pour empêcher l'énumération des comptes.
    """
    email_norm = email.lower().strip()

    # Réponse standard (anti-énumération)
    standard_response = ForgotPasswordResponse(
        message=(
            "Si un compte est associé à cet email, "
            "vous recevrez un code de réinitialisation."
        ),
        email=email_norm,
    )

    # Rate-limiting (silencieux en cas de dépassement)
    if not await _check_rate_limit(email_norm, session):
        logger.warning(f"[FORGOT_PWD] Rate limit atteint pour {email_norm}")
        return standard_response

    # Vérifier l'existence du compte (sans révéler le résultat)
    user = await _get_user_by_email(email_norm, session)
    if not user:
        logger.info(f"[FORGOT_PWD] Tentative sur email inconnu : {email_norm}")
        return standard_response

    # Compte désactivé : on ne génère pas d'OTP non plus
    if not user.actif:
        logger.warning(
            f"[FORGOT_PWD] Tentative sur compte désactivé : {email_norm}"
        )
        return standard_response

    # Tout est bon : invalider les anciens OTP, créer un nouveau, envoyer email
    await _invalidate_existing(email_norm, session)
    code = await _create_otp(email_norm, session)
    await _send_forgot_password_email(email_norm, code, user.prenom)

    return standard_response


# ══════════════════════════════════════════════════════════
#  ÉTAPE 2 — Vérification du code (sans le consommer)
# ══════════════════════════════════════════════════════════

async def verify_forgot_password_code(
    email: str, code: str, session: AsyncSession
) -> ForgotPasswordVerifyResponse:
    """
    Étape 2 : vérifie qu'un OTP est valide.
    Le code n'est PAS consommé ici (on attend l'étape 3 pour le marquer used).
    """
    email_norm = email.lower().strip()
    otp = await _find_valid_otp(email_norm, code, session)

    if not otp:
        return ForgotPasswordVerifyResponse(
            valid=False,
            message="Code invalide ou expiré. Demandez un nouveau code.",
        )

    return ForgotPasswordVerifyResponse(
        valid=True,
        message="Code vérifié avec succès. Vous pouvez maintenant définir un nouveau mot de passe.",
    )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 3 — Reset du mot de passe
# ══════════════════════════════════════════════════════════

async def reset_forgot_password(
    email: str,
    code: str,
    new_password: str,
    session: AsyncSession,
) -> ForgotPasswordResetResponse:
    """
    Étape 3 : valide le code, hash le nouveau mot de passe, met à jour l'utilisateur.
    Marque l'OTP comme utilisé pour empêcher la réutilisation.
    """
    email_norm = email.lower().strip()

    # Vérifier OTP encore valide
    otp = await _find_valid_otp(email_norm, code, session)
    if not otp:
        raise ForbiddenException("Code invalide ou expiré. Demandez un nouveau code.")

    # Récupérer l'utilisateur
    user = await _get_user_by_email(email_norm, session)
    if not user:
        # Cas improbable mais on protège
        raise ForbiddenException("Compte introuvable.")
    if not user.actif:
        raise ForbiddenException("Ce compte est désactivé.")

    # Hash et mise à jour
    user.mot_de_passe = hash_password(new_password)

    # Consommer l'OTP
    otp.used = True
    await session.flush()

    logger.info(f"[FORGOT_PWD] ✅ Mot de passe réinitialisé pour user_id={user.id}")

    return ForgotPasswordResetResponse(
        message="Mot de passe réinitialisé avec succès. Vous pouvez maintenant vous connecter."
    )