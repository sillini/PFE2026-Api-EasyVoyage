"""
Service Marketing — logique métier complète.

Règles :
  - Seul un PARTENAIRE peut créer une campagne
  - Un partenaire ne peut modifier/supprimer que SES campagnes EN_ATTENTE
  - Seul un ADMIN peut valider (ACCEPTEE/REFUSEE) ou activer (ACTIVE)
  - EXPIREE : géré automatiquement par fn_expirer_campagnes_marketing() PostgreSQL
  - Chaque action admin est tracée dans marketing_admin
"""
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, ForbiddenException, NotFoundException
from app.models.marketing import Marketing, MarketingAdmin, StatutMarketing
from app.schemas.marketing import (
    MarketingActionAdmin,
    MarketingActiverRequest,
    MarketingCreate,
    MarketingListResponse,
    MarketingResponse,
    MarketingUpdate,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _get_marketing_or_404(
    marketing_id: int, session: AsyncSession
) -> Marketing:
    result = await session.execute(
        select(Marketing)
        .options(selectinload(Marketing.actions_admin))
        .where(Marketing.id == marketing_id)
    )
    camp = result.scalar_one_or_none()
    if not camp:
        raise NotFoundException(f"Campagne {marketing_id} introuvable")
    return camp


def _build_response(camp: Marketing) -> MarketingResponse:
    return MarketingResponse.model_validate(camp)


# ═══════════════════════════════════════════════════════════
#  CRÉER UNE CAMPAGNE (partenaire)
# ═══════════════════════════════════════════════════════════
async def create_campagne(
    data: MarketingCreate, partenaire_id: int, session: AsyncSession
) -> MarketingResponse:
    camp = Marketing(
        nom=data.nom,
        type=data.type,
        budget=data.budget,
        segment_cible=data.segment_cible,
        contenu=data.contenu,
        date_debut=data.date_debut,
        date_fin=data.date_fin,
        id_partenaire=partenaire_id,
        statut=StatutMarketing.EN_ATTENTE,
    )
    session.add(camp)
    await session.flush()

    result = await session.execute(
        select(Marketing)
        .options(selectinload(Marketing.actions_admin))
        .where(Marketing.id == camp.id)
    )
    return _build_response(result.scalar_one())


# ═══════════════════════════════════════════════════════════
#  LISTE DES CAMPAGNES
# ═══════════════════════════════════════════════════════════
async def list_campagnes(
    session: AsyncSession,
    statut: Optional[str] = None,
    partenaire_id: Optional[int] = None,   # None = admin voit tout
    page: int = 1,
    per_page: int = 10,
) -> MarketingListResponse:

    query = select(Marketing).options(selectinload(Marketing.actions_admin))

    if statut:
        query = query.where(Marketing.statut == StatutMarketing(statut))
    if partenaire_id is not None:
        query = query.where(Marketing.id_partenaire == partenaire_id)

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Marketing.date_demande.desc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    campagnes = result.scalars().all()

    return MarketingListResponse(
        total=total, page=page, per_page=per_page,
        items=[_build_response(c) for c in campagnes],
    )


# ═══════════════════════════════════════════════════════════
#  DÉTAIL
# ═══════════════════════════════════════════════════════════
async def get_campagne(
    marketing_id: int, partenaire_id: int, role: str, session: AsyncSession
) -> MarketingResponse:
    camp = await _get_marketing_or_404(marketing_id, session)
    if role == "PARTENAIRE" and camp.id_partenaire != partenaire_id:
        raise ForbiddenException("Cette campagne ne vous appartient pas")
    return _build_response(camp)


# ═══════════════════════════════════════════════════════════
#  MODIFIER (partenaire — seulement si EN_ATTENTE)
# ═══════════════════════════════════════════════════════════
async def update_campagne(
    marketing_id: int,
    data: MarketingUpdate,
    partenaire_id: int,
    session: AsyncSession,
) -> MarketingResponse:
    camp = await _get_marketing_or_404(marketing_id, session)

    if camp.id_partenaire != partenaire_id:
        raise ForbiddenException("Cette campagne ne vous appartient pas")
    if camp.statut != StatutMarketing.EN_ATTENTE:
        raise ConflictException(
            f"Impossible de modifier une campagne avec le statut '{camp.statut.value}'. "
            "Seules les campagnes EN_ATTENTE sont modifiables."
        )

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(camp, field, value)

    await session.flush()
    await session.refresh(camp)
    return _build_response(camp)


# ═══════════════════════════════════════════════════════════
#  SUPPRIMER (partenaire — seulement si EN_ATTENTE)
# ═══════════════════════════════════════════════════════════
async def delete_campagne(
    marketing_id: int, partenaire_id: int, session: AsyncSession
) -> None:
    camp = await _get_marketing_or_404(marketing_id, session)

    if camp.id_partenaire != partenaire_id:
        raise ForbiddenException("Cette campagne ne vous appartient pas")
    if camp.statut != StatutMarketing.EN_ATTENTE:
        raise ConflictException(
            "Impossible de supprimer une campagne qui n'est plus EN_ATTENTE"
        )

    await session.delete(camp)
    await session.flush()


# ═══════════════════════════════════════════════════════════
#  VALIDER (admin → ACCEPTEE ou REFUSEE)
# ═══════════════════════════════════════════════════════════
async def valider_campagne(
    marketing_id: int,
    data: MarketingActionAdmin,
    admin_id: int,
    session: AsyncSession,
) -> MarketingResponse:
    camp = await _get_marketing_or_404(marketing_id, session)

    if camp.statut != StatutMarketing.EN_ATTENTE:
        raise ConflictException(
            f"Impossible de valider une campagne avec le statut '{camp.statut.value}'. "
            "Seules les campagnes EN_ATTENTE peuvent être validées."
        )

    # Changer le statut
    camp.statut = StatutMarketing(data.decision)

    # Tracer l'action admin
    action = MarketingAdmin(
        id_marketing=camp.id,
        id_admin=admin_id,
        commentaire=data.commentaire,
    )
    session.add(action)
    await session.flush()

    result = await session.execute(
        select(Marketing)
        .options(selectinload(Marketing.actions_admin))
        .where(Marketing.id == camp.id)
    )
    return _build_response(result.scalar_one())


# ═══════════════════════════════════════════════════════════
#  ACTIVER (admin → ACTIVE, seulement si ACCEPTEE)
# ═══════════════════════════════════════════════════════════
async def activer_campagne(
    marketing_id: int,
    data: MarketingActiverRequest,
    admin_id: int,
    session: AsyncSession,
) -> MarketingResponse:
    camp = await _get_marketing_or_404(marketing_id, session)

    if camp.statut != StatutMarketing.ACCEPTEE:
        raise ConflictException(
            f"Impossible d'activer une campagne avec le statut '{camp.statut.value}'. "
            "Seules les campagnes ACCEPTEE peuvent être activées."
        )

    camp.statut = StatutMarketing.ACTIVE

    # Tracer l'action admin
    action = MarketingAdmin(
        id_marketing=camp.id,
        id_admin=admin_id,
        commentaire=data.commentaire or "Campagne activée",
    )
    session.add(action)
    await session.flush()

    result = await session.execute(
        select(Marketing)
        .options(selectinload(Marketing.actions_admin))
        .where(Marketing.id == camp.id)
    )
    return _build_response(result.scalar_one())