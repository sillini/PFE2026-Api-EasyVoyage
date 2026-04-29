"""
app/services/admin_service.py
==============================
Service métier — Gestion des administrateurs (par le Super Admin).

Workflow d'invitation (en 3 étapes — identique aux partenaires) :
  1. invite_admin()        → génère OTP 6 chiffres + envoie email de vérification
  2. verify_otp()          → vérifie le code saisi
  3. create_admin()        → crée le compte admin + envoie email avec mot de passe

Lecture / gestion :
  - list_admins()          → liste paginée avec filtres
  - get_admin()            → détail d'un admin
  - toggle_admin()         → activer/désactiver
  - update_admin()         → modifier nom/prénom/téléphone
  - delete_admin()         → supprimer (cascade)

Règles de sécurité (CRITIQUE) :
  - Toutes ces opérations sont déjà protégées par require_super_admin
    côté endpoint, mais on AJOUTE une double vérif côté service
    pour les actions destructives (toggle/update/delete) :
      ✗ Un Super Admin ne peut PAS être désactivé/supprimé/modifié
        par cette interface (uniquement via SQL direct)
      ✗ Un Super Admin ne peut PAS se désactiver lui-même
"""
import logging
import random
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import (
    ConflictException, ForbiddenException, NotFoundException,
)
from app.models.invitation_otp import InvitationOTP
from app.models.utilisateur import Admin, RoleUtilisateur, Utilisateur
from app.schemas.admin import (
    AdminListResponse,
    AdminResponse,
    CreateAdminRequest,
    CreateAdminResponse,
    InviteAdminResponse,
    UpdateAdminRequest,
    VerifyAdminOTPResponse,
)
from app.services.email_service import (
    send_admin_otp_email,
    send_welcome_admin_email,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _generate_otp() -> str:
    """Génère un code OTP à 6 chiffres."""
    return str(random.randint(100000, 999999))


def _generate_password(length: int = 12) -> str:
    """Génère un mot de passe sécurisé (12 caractères, majus+minus+chiffres+spécial)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pwd) and
                any(c.islower() for c in pwd) and
                any(c.isdigit() for c in pwd) and
                any(c in "!@#$%&*" for c in pwd)):
            return pwd


def _hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def _get_user_by_email(session: AsyncSession, email: str) -> Optional[Utilisateur]:
    r = await session.execute(select(Utilisateur).where(Utilisateur.email == email))
    return r.scalar_one_or_none()


def _to_response(u: Utilisateur, a: Admin) -> AdminResponse:
    return AdminResponse(
        id                 = u.id,
        nom                = u.nom,
        prenom             = u.prenom,
        email              = u.email,
        telephone          = u.telephone,
        actif              = u.actif,
        is_super_admin     = a.is_super_admin if a else False,
        date_inscription   = u.date_inscription,
        derniere_connexion = u.derniere_connexion,
    )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 1 — INVITATION (envoi OTP)
# ══════════════════════════════════════════════════════════

async def invite_admin(
    email: str,
    invitant_prenom: str,
    invitant_nom: str,
    session: AsyncSession,
) -> InviteAdminResponse:
    """Envoie un OTP à l'email du futur administrateur."""

    # Email déjà utilisé ?
    existing = await _get_user_by_email(session, email)
    if existing:
        raise ConflictException(f"Un compte existe déjà avec l'email {email}")

    # Invalider les anciens OTP pour cet email
    old_otps = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == email,
            InvitationOTP.used == False,
        )
    )
    for otp in old_otps.scalars().all():
        otp.used = True
    await session.flush()

    # Créer le nouvel OTP
    code = _generate_otp()
    expire_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.OTP_EXPIRE_MINUTES
    )
    otp = InvitationOTP(email=email, code=code, expire_at=expire_at)
    session.add(otp)
    await session.flush()

    # Envoyer l'email
    invitant_full = f"{invitant_prenom} {invitant_nom}".strip() or "Le Super Administrateur"
    try:
        await send_admin_otp_email(email, code, invitant_full)
    except Exception as exc:
        logger.error(f"[ADMIN INVITE] ❌ Erreur envoi email à {email} : {exc}")
        # On ne re-lève pas → le code est en BDD, l'admin peut le récupérer dans les logs

    await session.commit()
    return InviteAdminResponse(
        message=f"Code de vérification envoyé à {email}",
        email=email,
    )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 2 — VÉRIFICATION DU CODE OTP
# ══════════════════════════════════════════════════════════

async def verify_otp(
    email: str, code: str, session: AsyncSession
) -> VerifyAdminOTPResponse:
    """Vérifie le code OTP saisi par le Super Admin."""
    now = datetime.now(timezone.utc)

    result = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == email,
            InvitationOTP.code == code,
            InvitationOTP.used == False,
            InvitationOTP.expire_at > now,
        )
    )
    otp = result.scalar_one_or_none()

    if not otp:
        return VerifyAdminOTPResponse(
            valid=False,
            message="Code invalide ou expiré. Veuillez renvoyer l'invitation.",
        )

    return VerifyAdminOTPResponse(
        valid=True,
        message="Code vérifié avec succès. Vous pouvez créer le compte.",
    )


# ══════════════════════════════════════════════════════════
#  ÉTAPE 3 — CRÉATION DU COMPTE ADMIN
# ══════════════════════════════════════════════════════════

async def create_admin(
    data: CreateAdminRequest, session: AsyncSession
) -> CreateAdminResponse:
    """Crée le compte admin après vérification OTP."""
    now = datetime.now(timezone.utc)

    # 1. Vérifier OTP encore valide
    result = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == data.email,
            InvitationOTP.code == data.code,
            InvitationOTP.used == False,
            InvitationOTP.expire_at > now,
        )
    )
    otp = result.scalar_one_or_none()
    if not otp:
        raise ForbiddenException("Code OTP invalide ou expiré.")

    # 2. Email toujours libre ?
    if await _get_user_by_email(session, data.email):
        raise ConflictException("Un compte existe déjà avec cet email.")

    # 3. Générer mot de passe temporaire
    password = _generate_password()

    # 4. Créer l'utilisateur
    user = Utilisateur(
        nom          = data.nom,
        prenom       = data.prenom,
        email        = data.email,
        telephone    = data.telephone,
        mot_de_passe = _hash_password(password),
        role         = RoleUtilisateur.ADMIN,
        actif        = True,
    )
    session.add(user)
    await session.flush()

    # 5. Créer la ligne admin (par défaut PAS Super Admin)
    admin = Admin(id=user.id, is_super_admin=False)
    session.add(admin)

    # 6. Marquer OTP comme utilisé
    otp.used = True
    await session.flush()

    # 7. Envoyer email de bienvenue avec mot de passe
    try:
        await send_welcome_admin_email(data.email, data.prenom, data.nom, password)
    except Exception as exc:
        logger.error(f"[ADMIN CREATE] ❌ Erreur envoi email bienvenue à {data.email} : {exc}")
        # On commit quand même : le compte est créé,
        # le Super Admin peut renvoyer le mot de passe manuellement.

    await session.commit()

    return CreateAdminResponse(
        id             = user.id,
        nom            = data.nom,
        prenom         = data.prenom,
        email          = data.email,
        is_super_admin = False,
        actif          = True,
        message        = f"Compte administrateur créé. Mot de passe envoyé à {data.email}.",
    )


# ══════════════════════════════════════════════════════════
#  LECTURE — Liste avec filtres
# ══════════════════════════════════════════════════════════

async def list_admins(
    session: AsyncSession,
    search: Optional[str] = None,
    actif_only: Optional[bool] = None,
    super_only: Optional[bool] = None,
    page: int = 1,
    per_page: int = 20,
) -> AdminListResponse:
    """Liste paginée des administrateurs."""
    query = (
        select(Utilisateur, Admin)
        .join(Admin, Admin.id == Utilisateur.id)
        .where(Utilisateur.role == RoleUtilisateur.ADMIN)
    )

    if search:
        s = f"%{search.lower()}%"
        query = query.where(
            or_(
                func.lower(Utilisateur.nom).like(s),
                func.lower(Utilisateur.prenom).like(s),
                func.lower(Utilisateur.email).like(s),
            )
        )

    if actif_only is not None:
        query = query.where(Utilisateur.actif == actif_only)

    if super_only is True:
        query = query.where(Admin.is_super_admin == True)
    elif super_only is False:
        query = query.where(Admin.is_super_admin == False)

    # Compter total
    total_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(total_q)).scalar_one()

    # Paginer
    query = (
        query
        .order_by(Admin.is_super_admin.desc(), Utilisateur.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    result = await session.execute(query)
    rows = result.all()

    items = [_to_response(u, a) for (u, a) in rows]

    return AdminListResponse(
        total=total, page=page, per_page=per_page, items=items
    )


# ══════════════════════════════════════════════════════════
#  LECTURE — Détail
# ══════════════════════════════════════════════════════════

async def get_admin(admin_id: int, session: AsyncSession) -> AdminResponse:
    result = await session.execute(
        select(Utilisateur, Admin)
        .join(Admin, Admin.id == Utilisateur.id)
        .where(Utilisateur.id == admin_id, Utilisateur.role == RoleUtilisateur.ADMIN)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundException(f"Administrateur {admin_id} introuvable")
    u, a = row
    return _to_response(u, a)


# ══════════════════════════════════════════════════════════
#  ACTIONS — Toggle / Update / Delete
# ══════════════════════════════════════════════════════════

async def _load_admin_or_404(admin_id: int, session: AsyncSession) -> tuple[Utilisateur, Admin]:
    result = await session.execute(
        select(Utilisateur, Admin)
        .join(Admin, Admin.id == Utilisateur.id)
        .where(Utilisateur.id == admin_id, Utilisateur.role == RoleUtilisateur.ADMIN)
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundException(f"Administrateur {admin_id} introuvable")
    return row[0], row[1]


async def toggle_admin(
    admin_id: int,
    actif: bool,
    current_super_admin_id: int,
    session: AsyncSession,
) -> AdminResponse:
    """Active/désactive un admin. RÈGLES :
      - Pas soi-même
      - Pas un Super Admin
    """
    if admin_id == current_super_admin_id:
        raise ForbiddenException("Vous ne pouvez pas vous désactiver vous-même")

    user, admin = await _load_admin_or_404(admin_id, session)

    if admin.is_super_admin:
        raise ForbiddenException(
            "Un Super Administrateur ne peut pas être désactivé via l'interface. "
            "Cette action doit être faite directement en base."
        )

    user.actif = actif
    await session.commit()
    await session.refresh(user)
    return _to_response(user, admin)


async def update_admin(
    admin_id: int,
    data: UpdateAdminRequest,
    current_super_admin_id: int,
    session: AsyncSession,
) -> AdminResponse:
    """Modifie nom/prénom/téléphone d'un admin. RÈGLES :
      - Le Super Admin peut se modifier lui-même
      - Le Super Admin ne peut pas modifier un AUTRE Super Admin (sécurité)
    """
    user, admin = await _load_admin_or_404(admin_id, session)

    if admin.is_super_admin and admin_id != current_super_admin_id:
        raise ForbiddenException(
            "Vous ne pouvez pas modifier un autre Super Administrateur."
        )

    if data.nom is not None:        user.nom       = data.nom
    if data.prenom is not None:     user.prenom    = data.prenom
    if data.telephone is not None:  user.telephone = data.telephone

    await session.commit()
    await session.refresh(user)
    return _to_response(user, admin)


async def delete_admin(
    admin_id: int,
    current_super_admin_id: int,
    session: AsyncSession,
) -> dict:
    """Supprime DÉFINITIVEMENT un admin. RÈGLES :
      - Pas soi-même
      - Pas un Super Admin
    """
    if admin_id == current_super_admin_id:
        raise ForbiddenException("Vous ne pouvez pas vous supprimer vous-même")

    user, admin = await _load_admin_or_404(admin_id, session)

    if admin.is_super_admin:
        raise ForbiddenException(
            "Un Super Administrateur ne peut pas être supprimé via l'interface."
        )

    # Cascade : suppression de Utilisateur supprime aussi la ligne admin
    # (FK avec ondelete=CASCADE). L'admin ne possède aucune autre donnée critique
    # (ni partenaire, ni hôtel, ni réservation côté admin), donc safe.
    await session.delete(user)
    await session.commit()

    return {
        "message": f"Administrateur #{admin_id} supprimé avec succès",
        "id": admin_id,
    }