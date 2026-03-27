"""
Service Partenaires Admin — logique métier complète.

Flux d'invitation :
  1. invite()        → génère OTP 6 chiffres, envoie email au partenaire
  2. verify_otp()    → vérifie le code saisi par l'admin
  3. create()        → crée l'utilisateur + partenaire, envoie mdp par email

Index utilisés :
  - idx_otp_email              → recherche OTP par email
  - idx_utilisateur_email      → recherche partenaire par email
  - idx_utilisateur_nom        → recherche par nom
  - idx_partenaire_nom_entreprise → recherche par entreprise
  - idx_partenaire_statut      → filtre par statut
  - idx_partenaire_type        → filtre par type
"""
import random
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.exceptions import (
    ConflictException, ForbiddenException, NotFoundException
)
from app.models.hotel import Hotel
from app.models.invitation_otp import InvitationOTP
from app.models.utilisateur import Partenaire, Utilisateur
from app.schemas.partenaire import (
    CreatePartenaireRequest, CreatePartenaireResponse,
    HotelBriefResponse,
    InvitePartenaireResponse,
    PartenaireAdminResponse, PartenaireListResponse,
    VerifyOTPResponse,
)
from app.services.email_service import send_otp_email, send_welcome_partenaire_email


# ── Utilitaires ───────────────────────────────────────────
def _generate_otp() -> str:
    """Génère un code OTP à 6 chiffres."""
    return str(random.randint(100000, 999999))


def _generate_password(length: int = 10) -> str:
    """Génère un mot de passe sécurisé."""
    alphabet = string.ascii_letters + string.digits + "!@#$"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.isupper() for c in pwd) and
                any(c.islower() for c in pwd) and
                any(c.isdigit() for c in pwd)):
            return pwd


def _hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def _get_user_by_email(session: AsyncSession, email: str) -> Optional[Utilisateur]:
    r = await session.execute(select(Utilisateur).where(Utilisateur.email == email))
    return r.scalar_one_or_none()


async def _to_response(p: Partenaire, session: AsyncSession) -> PartenaireAdminResponse:
    """Construit la réponse complète d'un partenaire avec ses hôtels."""
    hotels_result = await session.execute(
        select(Hotel).where(Hotel.id_partenaire == p.id).order_by(Hotel.nom)
    )
    hotels = hotels_result.scalars().all()
    u = p.utilisateur

    return PartenaireAdminResponse(
        id=p.id,
        nom=u.nom,
        prenom=u.prenom,
        email=u.email,
        telephone=u.telephone,
        actif=u.actif,
        nom_entreprise=p.nom_entreprise,
        type_partenaire=p.type_partenaire,
        statut=p.statut,
        commission=float(p.commission),
        date_inscription=u.date_inscription,
        hotels=[
            HotelBriefResponse(
                id=h.id, nom=h.nom, etoiles=h.etoiles,
                pays=h.pays, actif=h.actif
            ) for h in hotels
        ],
    )


# ═══════════════════════════════════════════════════════════
#  ÉTAPE 1 — Invitation (envoi OTP)
# ═══════════════════════════════════════════════════════════
async def invite_partenaire(
    email: str, admin_prenom: str, admin_nom: str, session: AsyncSession
) -> InvitePartenaireResponse:
    """Envoie un OTP à l'email du futur partenaire."""

    # Vérifier que l'email n'est pas déjà utilisé
    existing = await _get_user_by_email(session, email)
    if existing:
        raise ConflictException(f"Un compte existe déjà avec l'email {email}")

    # Invalider les anciens OTP pour cet email
    old_otps = await session.execute(
        select(InvitationOTP).where(
            InvitationOTP.email == email,
            InvitationOTP.used == False
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
    admin_full = f"{admin_prenom} {admin_nom}"
    await send_otp_email(email, code, admin_full)

    return InvitePartenaireResponse(
        message=f"Code de vérification envoyé à {email}",
        email=email,
    )


# ═══════════════════════════════════════════════════════════
#  ÉTAPE 2 — Vérification du code OTP
# ═══════════════════════════════════════════════════════════
async def verify_otp(
    email: str, code: str, session: AsyncSession
) -> VerifyOTPResponse:
    """Vérifie le code OTP saisi par l'admin."""
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
        return VerifyOTPResponse(
            valid=False,
            message="Code invalide ou expiré. Veuillez renvoyer l'invitation.",
        )

    return VerifyOTPResponse(
        valid=True,
        message="Code vérifié avec succès. Vous pouvez créer le compte.",
    )


# ═══════════════════════════════════════════════════════════
#  ÉTAPE 3 — Création du compte partenaire
# ═══════════════════════════════════════════════════════════
async def create_partenaire(
    data: CreatePartenaireRequest, session: AsyncSession
) -> CreatePartenaireResponse:
    """Crée le compte partenaire après vérification OTP."""
    now = datetime.now(timezone.utc)

    # Vérifier OTP encore valide
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

    # Vérifier email toujours libre
    if await _get_user_by_email(session, data.email):
        raise ConflictException("Un compte existe déjà avec cet email.")

    # Générer mot de passe temporaire
    password = _generate_password()

    # Créer utilisateur
    from app.models.utilisateur import RoleUtilisateur
    user = Utilisateur(
        nom=data.nom,
        prenom=data.prenom,
        email=data.email,
        telephone=data.telephone,
        mot_de_passe=_hash_password(password),
        role=RoleUtilisateur.PARTENAIRE,
        actif=True,
    )
    session.add(user)
    await session.flush()

    # Créer partenaire
    partenaire = Partenaire(
        id=user.id,
        nom_entreprise=data.nom_entreprise,
        type_partenaire=data.type_partenaire,
        statut="ACTIF",
        commission=0.0,
    )
    session.add(partenaire)

    # Marquer OTP comme utilisé
    otp.used = True
    await session.flush()

    # Envoyer email de bienvenue avec mot de passe
    await send_welcome_partenaire_email(data.email, data.prenom, data.nom, password)

    return CreatePartenaireResponse(
        id=user.id,
        nom=data.nom,
        prenom=data.prenom,
        email=data.email,
        nom_entreprise=data.nom_entreprise,
        type_partenaire=data.type_partenaire,
        statut="ACTIF",
        message=f"Compte créé. Un email avec les identifiants a été envoyé à {data.email}",
    )


# ═══════════════════════════════════════════════════════════
#  LISTE PARTENAIRES
# ═══════════════════════════════════════════════════════════
async def list_partenaires(
    session: AsyncSession,
    search: Optional[str] = None,
    nom_entreprise: Optional[str] = None,
    type_partenaire: Optional[str] = None,
    statut: Optional[str] = None,
    actif_only: Optional[bool] = None,
    page: int = 1,
    per_page: int = 20,
) -> PartenaireListResponse:
    """Liste paginée avec filtres — utilise les index PostgreSQL."""

    query = (
        select(Partenaire)
        .join(Utilisateur, Utilisateur.id == Partenaire.id)
        .options(selectinload(Partenaire.utilisateur))
    )

    # Recherche globale (nom, prénom, email) — utilise idx_utilisateur_nom + idx_utilisateur_email
    if search:
        s = f"%{search}%"
        query = query.where(
            func.unaccent(Utilisateur.nom).ilike(s)
            | func.unaccent(Utilisateur.prenom).ilike(s)
            | Utilisateur.email.ilike(s)
        )

    # Filtre par nom d'entreprise — idx_partenaire_nom_entreprise
    if nom_entreprise:
        query = query.where(
            func.unaccent(Partenaire.nom_entreprise).ilike(f"%{nom_entreprise}%")
        )

    # Filtre par type — idx_partenaire_type
    if type_partenaire:
        query = query.where(Partenaire.type_partenaire == type_partenaire)

    # Filtre par statut — idx_partenaire_statut
    if statut:
        query = query.where(Partenaire.statut == statut)

    # Filtre actif/inactif — idx_utilisateur_actif
    if actif_only is not None:
        query = query.where(Utilisateur.actif == actif_only)

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Utilisateur.nom.asc(), Utilisateur.prenom.asc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    partenaires = result.scalars().all()

    items = [await _to_response(p, session) for p in partenaires]

    return PartenaireListResponse(
        total=total, page=page, per_page=per_page, items=items
    )


# ═══════════════════════════════════════════════════════════
#  DÉTAIL PARTENAIRE
# ═══════════════════════════════════════════════════════════
async def get_partenaire(
    partenaire_id: int, session: AsyncSession
) -> PartenaireAdminResponse:
    result = await session.execute(
        select(Partenaire)
        .options(selectinload(Partenaire.utilisateur))
        .where(Partenaire.id == partenaire_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise NotFoundException(f"Partenaire {partenaire_id} introuvable")
    return await _to_response(p, session)


# ═══════════════════════════════════════════════════════════
#  TOGGLE ACTIF / INACTIF
# ═══════════════════════════════════════════════════════════
async def toggle_partenaire(
    partenaire_id: int, actif: bool, session: AsyncSession
) -> PartenaireAdminResponse:
    result = await session.execute(
        select(Partenaire)
        .options(selectinload(Partenaire.utilisateur))
        .where(Partenaire.id == partenaire_id)
    )
    p = result.scalar_one_or_none()
    if not p:
        raise NotFoundException(f"Partenaire {partenaire_id} introuvable")

    p.utilisateur.actif = actif
    # Synchroniser statut partenaire
    if actif:
        p.statut = "ACTIF"
    else:
        p.statut = "SUSPENDU"

    await session.flush()
    return await _to_response(p, session)