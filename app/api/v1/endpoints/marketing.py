"""
Endpoints Marketing — campagnes partenaires + validation admin.

  POST   /api/v1/marketing                      — Créer [PARTENAIRE]
  GET    /api/v1/marketing                      — Lister [ADMIN=tout | PARTENAIRE=les siennes]
  GET    /api/v1/marketing/{id}                 — Détail [ADMIN | PARTENAIRE (la sienne)]
  PUT    /api/v1/marketing/{id}                 — Modifier [PARTENAIRE si EN_ATTENTE]
  DELETE /api/v1/marketing/{id}                 — Supprimer [PARTENAIRE si EN_ATTENTE]
  POST   /api/v1/marketing/{id}/valider         — Accepter/Refuser [ADMIN]
  POST   /api/v1/marketing/{id}/activer         — Activer [ADMIN]
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    get_current_user,
    require_admin,
    require_partenaire,
)
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.marketing import (
    MarketingActionAdmin,
    MarketingActiverRequest,
    MarketingCreate,
    MarketingListResponse,
    MarketingResponse,
    MarketingUpdate,
)
import app.services.marketing_service as marketing_service

router = APIRouter(prefix="/marketing", tags=["Marketing"])


# ── Créer une campagne (partenaire) ───────────────────────────────────────────
@router.post(
    "",
    response_model=MarketingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une campagne marketing [PARTENAIRE]",
    description="Crée une nouvelle campagne avec statut **EN_ATTENTE**. Un admin devra la valider.",
)
async def create_campagne(
    data: MarketingCreate,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_partenaire),
) -> MarketingResponse:
    return await marketing_service.create_campagne(data, token.user_id, session)


# ── Lister les campagnes ──────────────────────────────────────────────────────
@router.get(
    "",
    response_model=MarketingListResponse,
    summary="Lister les campagnes [ADMIN=toutes | PARTENAIRE=les siennes]",
    description="""
- **ADMIN** : voit toutes les campagnes de tous les partenaires
- **PARTENAIRE** : voit uniquement ses propres campagnes
    """,
)
async def list_campagnes(
    statut: Optional[str] = Query(
        None,
        description="EN_ATTENTE | ACCEPTEE | REFUSEE | ACTIVE | EXPIREE"
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
) -> MarketingListResponse:
    # Admin voit tout, partenaire voit les siennes
    partenaire_id = None if token.role == "ADMIN" else token.user_id
    return await marketing_service.list_campagnes(
        session,
        statut=statut,
        partenaire_id=partenaire_id,
        page=page,
        per_page=per_page,
    )


# ── Détail d'une campagne ─────────────────────────────────────────────────────
@router.get(
    "/{marketing_id}",
    response_model=MarketingResponse,
    summary="Détail d'une campagne [ADMIN | PARTENAIRE (la sienne)]",
)
async def get_campagne(
    marketing_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
) -> MarketingResponse:
    return await marketing_service.get_campagne(
        marketing_id, token.user_id, token.role, session
    )


# ── Modifier une campagne (partenaire, seulement si EN_ATTENTE) ───────────────
@router.put(
    "/{marketing_id}",
    response_model=MarketingResponse,
    summary="Modifier une campagne [PARTENAIRE — seulement si EN_ATTENTE]",
)
async def update_campagne(
    marketing_id: int,
    data: MarketingUpdate,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_partenaire),
) -> MarketingResponse:
    return await marketing_service.update_campagne(
        marketing_id, data, token.user_id, session
    )


# ── Supprimer une campagne (partenaire, seulement si EN_ATTENTE) ──────────────
@router.delete(
    "/{marketing_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Supprimer une campagne [PARTENAIRE — seulement si EN_ATTENTE]",
)
async def delete_campagne(
    marketing_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_partenaire),
) -> None:
    await marketing_service.delete_campagne(marketing_id, token.user_id, session)


# ── Valider (admin → ACCEPTEE ou REFUSEE) ────────────────────────────────────
@router.post(
    "/{marketing_id}/valider",
    response_model=MarketingResponse,
    summary="Valider une campagne [ADMIN]",
    description="""
Accepte ou refuse une campagne EN_ATTENTE.

- `decision: "ACCEPTEE"` → la campagne peut ensuite être activée
- `decision: "REFUSEE"`  → la campagne est rejetée avec un commentaire optionnel

L'action est tracée dans l'historique (marketing_admin).
    """,
)
async def valider_campagne(
    marketing_id: int,
    data: MarketingActionAdmin,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_admin),
) -> MarketingResponse:
    return await marketing_service.valider_campagne(
        marketing_id, data, token.user_id, session
    )


# ── Activer (admin → ACTIVE, seulement si ACCEPTEE) ──────────────────────────
@router.post(
    "/{marketing_id}/activer",
    response_model=MarketingResponse,
    summary="Activer une campagne [ADMIN]",
    description="""
Active une campagne préalablement **ACCEPTEE**.

Le statut passe à **ACTIVE**. La campagne expirera automatiquement
lorsque sa `date_fin` sera dépassée (géré par PostgreSQL).
    """,
)
async def activer_campagne(
    marketing_id: int,
    data: MarketingActiverRequest,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_admin),
) -> MarketingResponse:
    return await marketing_service.activer_campagne(
        marketing_id, data, token.user_id, session
    )