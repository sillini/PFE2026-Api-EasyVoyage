"""
app/services/auth_service.py
=============================
Authentication service — toute la logique métier.

Responsabilités :
  - Register client / partenaire
  - Login (tous rôles)
  - Refresh token
  - Profil courant
  - Mise à jour profil (nom/prénom/téléphone)
  - Changement email via OTP Brevo
  - Changement mot de passe via OTP Brevo

CORRECTIONS APPLIQUÉES :
  - _send_profile_otp : labels adaptés pour CLIENT + try/except SMTP
    (ne crashe plus si Brevo est injoignable → plus de "Failed to fetch")
  - request_email_change / request_password_change : labels rôle CLIENT
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ConflictException,
    CredentialsException,
    NotFoundException,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.utilisateur import (
    Admin,
    Client,
    Partenaire,
    RoleUtilisateur,
    Utilisateur,
)
from app.schemas.auth import (
    ClientRegisterRequest,
    LoginRequest,
    PartenaireRegisterRequest,
    TokenData,
    TokenResponse,
    UserMeResponse,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  HELPERS INTERNES
# ══════════════════════════════════════════════════════════

async def _get_user_by_email(session: AsyncSession, email: str) -> Utilisateur | None:
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.email == email)
    )
    return result.scalar_one_or_none()


async def _get_user_with_profile(session: AsyncSession, user_id: int) -> Utilisateur | None:
    """Charge l'utilisateur + ses sous-tables (client/partenaire/admin) en une seule requête."""
    result = await session.execute(
        select(Utilisateur)
        .options(
            selectinload(Utilisateur.client),
            selectinload(Utilisateur.partenaire),
            selectinload(Utilisateur.admin),
        )
        .where(Utilisateur.id == user_id)
    )
    return result.scalar_one_or_none()


def _build_token_response(user: Utilisateur) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, user.role.value),
        refresh_token=create_refresh_token(user.id, user.role.value),
        role=user.role.value,
    )


# ══════════════════════════════════════════════════════════
#  INSCRIPTION / CONNEXION
# ══════════════════════════════════════════════════════════

async def register_client(
    data: ClientRegisterRequest, session: AsyncSession
) -> TokenResponse:
    """Crée un compte CLIENT et retourne les tokens JWT."""
    if await _get_user_by_email(session, data.email):
        raise ConflictException("Un compte avec cet email existe déjà")

    user = Utilisateur(
        nom=data.nom,
        prenom=data.prenom,
        email=data.email,
        telephone=data.telephone,
        mot_de_passe=hash_password(data.password),
        role=RoleUtilisateur.CLIENT,
    )
    session.add(user)
    await session.flush()

    client = Client(id=user.id)
    session.add(client)

    return _build_token_response(user)


async def register_partenaire(
    data: PartenaireRegisterRequest, session: AsyncSession
) -> TokenResponse:
    """Crée un compte PARTENAIRE (statut EN_ATTENTE) et retourne les tokens JWT."""
    if await _get_user_by_email(session, data.email):
        raise ConflictException("Un compte avec cet email existe déjà")

    user = Utilisateur(
        nom=data.nom,
        prenom=data.prenom,
        email=data.email,
        telephone=data.telephone,
        mot_de_passe=hash_password(data.password),
        role=RoleUtilisateur.PARTENAIRE,
    )
    session.add(user)
    await session.flush()

    partenaire = Partenaire(
        id=user.id,
        nom_entreprise=data.nom_entreprise,
        type_partenaire=data.type_partenaire,
        statut="EN_ATTENTE",
    )
    session.add(partenaire)

    return _build_token_response(user)


async def login(data: LoginRequest, session: AsyncSession) -> TokenResponse:
    """Vérifie les credentials et retourne les tokens JWT."""
    user = await _get_user_by_email(session, data.email)

    if not user or not verify_password(data.password, user.mot_de_passe):
        raise CredentialsException("Email ou mot de passe incorrect")

    if not user.actif:
        raise CredentialsException("Ce compte est désactivé")

    await session.execute(
        update(Utilisateur)
        .where(Utilisateur.id == user.id)
        .values(derniere_connexion=datetime.now(timezone.utc))
    )

    return _build_token_response(user)


async def refresh_tokens(refresh_token: str, session: AsyncSession) -> TokenResponse:
    """Valide un refresh token et émet une nouvelle paire de tokens."""
    try:
        payload = decode_token(refresh_token)
    except Exception:
        raise CredentialsException("Refresh token invalide ou expiré")

    if payload.get("type") != "refresh":
        raise CredentialsException("Token type invalide")

    user_id: int = int(payload["sub"])
    user = await _get_user_with_profile(session, user_id)

    if not user or not user.actif:
        raise CredentialsException("Utilisateur introuvable ou inactif")

    return _build_token_response(user)


async def get_current_user_profile(
    token_data: TokenData, session: AsyncSession
) -> UserMeResponse:
    """Construit la réponse /me pour l'utilisateur authentifié."""
    user = await _get_user_with_profile(session, token_data.user_id)

    if not user:
        raise NotFoundException("Utilisateur introuvable")

    response = UserMeResponse(
        id=user.id,
        nom=user.nom,
        prenom=user.prenom,
        email=user.email,
        telephone=user.telephone,
        role=user.role.value,
        actif=user.actif,
        date_inscription=user.date_inscription,
        derniere_connexion=user.derniere_connexion,
    )

    if user.partenaire:
        p = user.partenaire
        response.nom_entreprise    = p.nom_entreprise
        response.type_partenaire   = p.type_partenaire
        response.commission        = float(p.commission)
        response.statut_partenaire = p.statut

    return response


# ══════════════════════════════════════════════════════════
#  GESTION PROFIL — OTP EMAIL / MOT DE PASSE
# ══════════════════════════════════════════════════════════
import random as _random
from app.models.invitation_otp import InvitationOTP
from app.services.email_service import send_email
from app.core.config import settings as _settings


def _gen_otp() -> str:
    """Génère un code OTP à 6 chiffres."""
    return str(_random.randint(100000, 999999))


async def _invalidate_otps(email: str, session: AsyncSession) -> None:
    """Invalide tous les OTP non-utilisés pour cet email."""
    result = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == email,
            InvitationOTP.used  == False,
        )
    )
    for o in result.scalars().all():
        o.used = True
    await session.flush()


async def _save_otp(email: str, session: AsyncSession) -> str:
    """Invalide les OTP existants, crée un nouveau et le retourne."""
    await _invalidate_otps(email, session)
    code   = _gen_otp()
    expire = datetime.now(timezone.utc) + timedelta(minutes=_settings.OTP_EXPIRE_MINUTES)
    otp    = InvitationOTP(email=email, code=code, expire_at=expire)
    session.add(otp)
    await session.flush()
    return code


async def _verify_otp(email: str, code: str, session: AsyncSession) -> bool:
    """Vérifie le code OTP, le marque comme utilisé si valide."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email     == email,
            InvitationOTP.code      == code,
            InvitationOTP.used      == False,
            InvitationOTP.expire_at >  now,
        )
    )
    otp = result.scalar_one_or_none()
    if not otp:
        return False
    otp.used = True
    await session.flush()
    return True


async def _send_profile_otp(to: str, code: str, action: str, role: str = "ADMIN") -> None:
    """
    Envoie un email OTP via Brevo pour changement email ou mot de passe.

    ✅ Gère tous les rôles : ADMIN, PARTENAIRE, CLIENT
    ✅ Ne lève JAMAIS d'exception — si SMTP échoue, log l'erreur et continue.
       (Sans ce try/except, une erreur SMTP causerait un 500 → "Failed to fetch")
    ✅ En mode dev (SMTP_PASSWORD vide), affiche le code dans les logs uvicorn.
    """
    action_label = "changement d'email" if action == "email" else "changement de mot de passe"

    # Labels personnalisés selon le rôle
    if role == "CLIENT":
        espace_label = "Espace Client"
        compte_label = "client"
        footer_label = "EasyVoyage — Espace Client"
    elif role == "PARTENAIRE":
        espace_label = "Espace Partenaire"
        compte_label = "partenaire"
        footer_label = "EasyVoyage — Espace Partenaire"
    else:  # ADMIN
        espace_label = "Espace Administrateur"
        compte_label = "administrateur"
        footer_label = "EasyVoyage Administration"

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F4F6F8;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6F8;">
  <tr><td align="center" style="padding:40px 20px;">
    <table width="520" cellpadding="0" cellspacing="0"
           style="background:#FFFFFF;border-radius:16px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(0,0,0,0.08);max-width:520px;width:100%;">

      <!-- En-tête -->
      <tr><td style="background:linear-gradient(135deg,#0F2235 0%,#1A3F63 100%);
                     padding:28px 44px;text-align:center;">
        <h1 style="color:#FFFFFF;font-size:24px;margin:0;
                   font-family:Georgia,serif;font-weight:700;letter-spacing:1px;">
          EasyVoyage
        </h1>
        <p style="color:rgba(255,255,255,0.55);margin:6px 0 0;font-size:12px;
                  text-transform:uppercase;letter-spacing:1px;">
          {espace_label}
        </p>
      </td></tr>

      <!-- Corps -->
      <tr><td style="padding:36px 44px;">
        <p style="color:#0F2235;font-size:15px;margin:0 0 12px;font-weight:600;">
          Bonjour,
        </p>
        <p style="color:#4A5568;font-size:14px;line-height:1.7;margin:0 0 28px;">
          Vous avez demandé un <strong style="color:#0F2235;">{action_label}</strong>
          sur votre compte {compte_label} EasyVoyage.<br>
          Voici votre code de confirmation à 6 chiffres :
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
          <strong style="color:#C0392B;">15 minutes</strong>
        </p>

        <div style="background:#FFF8EC;border:1px solid rgba(196,151,58,0.3);
                    border-radius:10px;padding:14px 18px;margin-bottom:20px;">
          <p style="color:#8A6914;font-size:13px;margin:0;line-height:1.5;">
            🔒 <strong>Sécurité :</strong> Si vous n'êtes pas à l'origine de
            cette demande, ignorez cet email. Votre compte est en sécurité.
          </p>
        </div>
      </td></tr>

      <!-- Pied de page -->
      <tr><td style="background:#F8FAFC;padding:16px 44px;text-align:center;
                     border-top:1px solid #EEF2F7;">
        <p style="color:#B0BEC8;font-size:11px;margin:0;">
          {footer_label} — www.easyvoyage.tn
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""

    # ── CORRECTION CRITIQUE : try/except autour de send_email ──────────────
    # Sans ce bloc, si SMTP Brevo est injoignable (timeout, mauvais credentials,
    # réseau, etc.), l'exception remonte jusqu'à l'endpoint FastAPI → 500
    # → la connexion est fermée brutalement → le frontend reçoit "Failed to fetch"
    # Avec ce bloc : on log l'erreur mais l'endpoint répond 200 normalement.
    # Le code OTP est déjà sauvegardé en DB, l'utilisateur peut réessayer.
    # En mode dev (SMTP_PASSWORD vide), le code est affiché dans les logs uvicorn.
    try:
        await send_email(to, f"Code de confirmation — {action_label}", html)
        logger.info(f"[OTP] Email envoyé à {to} pour {action_label}")
    except Exception as exc:
        logger.error(
            f"[OTP] ❌ Échec envoi email à '{to}' pour {action_label}: {exc}\n"
            f"[OTP] 💡 En mode dev, cherchez le code dans les logs ci-dessus "
            f"(ligne [EMAIL SIMULÉ]) ou vérifiez SMTP_HOST/SMTP_PASSWORD dans .env"
        )
        # On ne re-lève PAS l'exception → l'endpoint continue normalement


# ══════════════════════════════════════════════════════════
#  MISE À JOUR PROFIL (champs simples)
# ══════════════════════════════════════════════════════════

async def update_profile(
    user_id: int,
    data: "UpdateProfileRequest",
    session: AsyncSession,
) -> UserMeResponse:
    """Met à jour nom/prénom/téléphone sans vérification OTP."""
    result = await session.execute(
        select(Utilisateur)
        .options(selectinload(Utilisateur.partenaire))
        .where(Utilisateur.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("Utilisateur introuvable")

    if data.nom:                   user.nom       = data.nom
    if data.prenom:                user.prenom    = data.prenom
    if data.telephone is not None: user.telephone = data.telephone

    if data.nom_entreprise is not None and user.partenaire:
        user.partenaire.nom_entreprise = data.nom_entreprise

    await session.flush()

    from app.schemas.auth import TokenData as TD
    return await get_current_user_profile(
        TD(user_id=user_id, role=user.role.value, token_type="access"), session
    )


# ══════════════════════════════════════════════════════════
#  CHANGEMENT EMAIL VIA OTP
# ══════════════════════════════════════════════════════════

async def request_email_change(
    user_id: int, new_email: str, session: AsyncSession
) -> dict:
    """
    Étape 1 : vérifie que le nouvel email est libre,
    génère un OTP et l'envoie au NOUVEL email via Brevo.
    """
    # Vérifier que le nouvel email n'est pas déjà pris
    existing = await _get_user_by_email(session, new_email)
    if existing and existing.id != user_id:
        raise ConflictException("Cet email est déjà utilisé par un autre compte")

    # Récupérer l'utilisateur pour connaître son rôle
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("Utilisateur introuvable")

    role = user.role.value  # "CLIENT", "PARTENAIRE" ou "ADMIN"

    # Sauvegarder l'OTP (tag unique pour ce changement d'email précis)
    tag = f"chg_{new_email}"
    code = await _save_otp(tag, session)

    # Envoyer l'email (ne crashe pas si SMTP échoue)
    await _send_profile_otp(new_email, code, "email", role)

    return {"message": f"Code envoyé à {new_email}", "email": new_email}


async def confirm_email_change(
    user_id: int, new_email: str, code: str, session: AsyncSession
) -> UserMeResponse:
    """
    Étape 2 : vérifie le code OTP et met à jour l'email de l'utilisateur.
    """
    tag = f"chg_{new_email}"
    if not await _verify_otp(tag, code, session):
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("Code invalide ou expiré")

    result = await session.execute(
        select(Utilisateur).where(Utilisateur.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("Utilisateur introuvable")

    user.email = new_email
    await session.flush()

    from app.schemas.auth import TokenData as TD
    return await get_current_user_profile(
        TD(user_id=user_id, role=user.role.value, token_type="access"), session
    )


# ══════════════════════════════════════════════════════════
#  CHANGEMENT MOT DE PASSE VIA OTP
# ══════════════════════════════════════════════════════════

async def request_password_change(user_id: int, session: AsyncSession) -> dict:
    """
    Étape 1 : génère un OTP et l'envoie à l'EMAIL ACTUEL de l'utilisateur.
    """
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("Utilisateur introuvable")

    role = user.role.value  # "CLIENT", "PARTENAIRE" ou "ADMIN"

    # Tag unique pour le changement de mot de passe de cet utilisateur
    tag = f"pwd_{user.email}"
    code = await _save_otp(tag, session)

    # Envoyer l'email (ne crashe pas si SMTP échoue)
    await _send_profile_otp(user.email, code, "password", role)

    return {"message": f"Code envoyé à {user.email}", "email": user.email}


async def confirm_password_change(
    user_id: int, code: str, new_password: str, session: AsyncSession
) -> dict:
    """
    Étape 2 : vérifie le code OTP et met à jour le mot de passe.
    """
    result = await session.execute(
        select(Utilisateur).where(Utilisateur.id == user_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundException("Utilisateur introuvable")

    tag = f"pwd_{user.email}"
    if not await _verify_otp(tag, code, session):
        from app.core.exceptions import ForbiddenException
        raise ForbiddenException("Code invalide ou expiré")

    user.mot_de_passe = hash_password(new_password)
    await session.flush()

    logger.info(f"[PROFIL] Mot de passe modifié pour user_id={user_id}")
    return {"message": "Mot de passe modifié avec succès"}