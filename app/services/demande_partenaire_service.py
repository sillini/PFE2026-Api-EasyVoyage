"""
Service métier — Demandes d'inscription partenaire.
"""
import secrets
import string
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demande_partenaire import DemandePartenaire, StatutDemande
from app.schemas.demande_partenaire import (
    DemandePartenaireCreate,
    DemandePartenairePublicResponse,
    DemandePartenaireResponse,
    DemandeListResponse,
    TraiterDemandeRequest,
    TraiterDemandeResponse,
)
from app.core.exceptions import NotFoundException, BadRequestException


# ═══════════════════════════════════════════════════════════
#  SOUMISSION PUBLIQUE
# ═══════════════════════════════════════════════════════════

async def soumettre_demande(
    data: DemandePartenaireCreate,
    session: AsyncSession,
) -> DemandePartenairePublicResponse:
    """
    Un visiteur soumet une demande depuis la landing page.
    Vérification : pas de demande EN_ATTENTE avec le même email.
    """
    result = await session.execute(
        select(DemandePartenaire).where(
            DemandePartenaire.email == data.email,
            DemandePartenaire.statut == StatutDemande.EN_ATTENTE,
        )
    )
    existante = result.scalar_one_or_none()
    if existante:
        raise BadRequestException(
            "Une demande est déjà en cours de traitement pour cet email. "
            "Veuillez patienter ou contacter notre support."
        )

    demande = DemandePartenaire(
        nom=data.nom,
        prenom=data.prenom,
        email=data.email,
        telephone=data.telephone,
        nom_entreprise=data.nom_entreprise,
        type_partenaire=data.type_partenaire,
        site_web=data.site_web,
        adresse=data.adresse,
        message=data.message,
        statut=StatutDemande.EN_ATTENTE,
    )
    session.add(demande)
    await session.flush()
    await session.refresh(demande)

    return DemandePartenairePublicResponse(
        id=demande.id,
        statut=demande.statut.value,
        message=(
            "Votre demande a bien été reçue ! Notre équipe l'examinera "
            "dans les plus brefs délais et vous contactera par email."
        ),
    )


# ═══════════════════════════════════════════════════════════
#  LISTE ADMIN
# ═══════════════════════════════════════════════════════════

async def list_demandes(
    session: AsyncSession,
    statut: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> DemandeListResponse:
    query = select(DemandePartenaire).order_by(DemandePartenaire.created_at.desc())

    if statut:
        query = query.where(DemandePartenaire.statut == statut)

    if search:
        like = f"%{search}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                DemandePartenaire.nom.ilike(like),
                DemandePartenaire.prenom.ilike(like),
                DemandePartenaire.email.ilike(like),
                DemandePartenaire.nom_entreprise.ilike(like),
            )
        )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_q)).scalar_one()

    offset = (page - 1) * per_page
    result = await session.execute(query.offset(offset).limit(per_page))
    items = result.scalars().all()

    return DemandeListResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=[DemandePartenaireResponse.model_validate(d) for d in items],
    )


# ═══════════════════════════════════════════════════════════
#  DÉTAIL ADMIN
# ═══════════════════════════════════════════════════════════

async def get_demande(demande_id: int, session: AsyncSession) -> DemandePartenaireResponse:
    result = await session.execute(
        select(DemandePartenaire).where(DemandePartenaire.id == demande_id)
    )
    demande = result.scalar_one_or_none()
    if not demande:
        raise NotFoundException(f"Demande {demande_id} introuvable")
    return DemandePartenaireResponse.model_validate(demande)


# ═══════════════════════════════════════════════════════════
#  TRAITEMENT ADMIN (CONFIRMER / ANNULER)
# ═══════════════════════════════════════════════════════════

async def traiter_demande(
    demande_id: int,
    data: TraiterDemandeRequest,
    session: AsyncSession,
) -> TraiterDemandeResponse:
    result = await session.execute(
        select(DemandePartenaire).where(DemandePartenaire.id == demande_id)
    )
    demande = result.scalar_one_or_none()
    if not demande:
        raise NotFoundException(f"Demande {demande_id} introuvable")

    if demande.statut != StatutDemande.EN_ATTENTE:
        raise BadRequestException(
            f"Cette demande a déjà été traitée (statut: {demande.statut.value})"
        )

    action = data.action.upper()
    if action not in ("CONFIRMER", "ANNULER"):
        raise BadRequestException("L'action doit être CONFIRMER ou ANNULER")

    demande.note_admin = data.note_admin
    demande.traite_at = datetime.now(timezone.utc)

    if action == "ANNULER":
        demande.statut = StatutDemande.ANNULEE
        await session.flush()
        return TraiterDemandeResponse(
            id=demande.id,
            statut=demande.statut.value,
            message="Demande annulée avec succès.",
        )

    # ── CONFIRMER ──────────────────────────────────────────
    # On marque juste la demande comme confirmée.
    # La création du compte se fait ensuite via le wizard
    # d'invitation (InvitationWizard) côté frontend.
    demande.statut = StatutDemande.CONFIRMEE
    await session.flush()

    return TraiterDemandeResponse(
        id=demande.id,
        statut=demande.statut.value,
        message=(
            f"Demande confirmée. Vous allez être redirigé vers le wizard "
            f"d'invitation pour finaliser la création du compte de {demande.email}."
        ),
        partenaire_id=None,
    )