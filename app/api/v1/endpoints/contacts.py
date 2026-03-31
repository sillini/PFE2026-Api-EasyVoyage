# app/api/v1/endpoints/contacts.py
"""
Routes :
  GET  /contacts          → Liste paginée des contacts [ADMIN]
  GET  /contacts/stats    → Statistiques globales      [ADMIN]
  GET  /contacts/{id}     → Détail d'un contact        [ADMIN]
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.models.contact import Contact
from app.schemas.auth import TokenData
from app.schemas.contact import ContactListResponse, ContactResponse, ContactStatsResponse

router = APIRouter(prefix="/contacts", tags=["Contacts"])


# ══════════════════════════════════════════════════════════
#  LISTE PAGINÉE
# ══════════════════════════════════════════════════════════
@router.get(
    "",
    response_model=ContactListResponse,
    summary="Liste unifiée des contacts — clients + visiteurs [ADMIN]",
)
async def list_contacts(
    type:     Optional[str] = Query(None, description="Filtrer par type : 'client' ou 'visiteur'"),
    search:   Optional[str] = Query(None, description="Recherche sur email, nom ou prénom"),
    page:     int           = Query(1,  ge=1),
    per_page: int           = Query(20, ge=1, le=100),
    session:  AsyncSession  = Depends(get_db),
    _:        TokenData     = Depends(require_admin),
) -> ContactListResponse:

    q = select(Contact)

    if type:
        q = q.where(Contact.type == type)

    if search:
        term = f"%{search.lower()}%"
        q = q.where(
            Contact.email.ilike(term)  |
            Contact.nom.ilike(term)    |
            Contact.prenom.ilike(term)
        )

    # Compte total
    total_res = await session.execute(
        select(func.count()).select_from(q.subquery())
    )
    total = total_res.scalar() or 0

    # Compte par type (sur la requête filtrée)
    counts_res = await session.execute(
        select(Contact.type, func.count().label("n"))
        .select_from(q.subquery())
        .group_by(Contact.type)
    )
    counts = {row.type: row.n for row in counts_res.all()}

    # Page courante
    items_res = await session.execute(
        q.order_by(Contact.created_at.desc())
         .offset((page - 1) * per_page)
         .limit(per_page)
    )
    items = items_res.scalars().all()

    return ContactListResponse(
        total        = total,
        page         = page,
        per_page     = per_page,
        nb_clients   = counts.get("client",   0),
        nb_visiteurs = counts.get("visiteur", 0),
        items        = items,
    )


# ══════════════════════════════════════════════════════════
#  STATISTIQUES
# ══════════════════════════════════════════════════════════
@router.get(
    "/stats",
    response_model=ContactStatsResponse,
    summary="Statistiques contacts [ADMIN]",
)
async def contact_stats(
    session: AsyncSession = Depends(get_db),
    _:       TokenData    = Depends(require_admin),
) -> ContactStatsResponse:

    rows = (await session.execute(
        select(Contact.type, func.count().label("n"))
        .group_by(Contact.type)
    )).all()

    counts = {row.type: row.n for row in rows}

    return ContactStatsResponse(
        total        = sum(counts.values()),
        nb_clients   = counts.get("client",   0),
        nb_visiteurs = counts.get("visiteur", 0),
    )


# ══════════════════════════════════════════════════════════
#  DÉTAIL
# ══════════════════════════════════════════════════════════
@router.get(
    "/{contact_id}",
    response_model=ContactResponse,
    summary="Détail d'un contact [ADMIN]",
)
async def get_contact(
    contact_id: int,
    session:    AsyncSession = Depends(get_db),
    _:          TokenData    = Depends(require_admin),
) -> ContactResponse:

    result = await session.execute(
        select(Contact).where(Contact.id == contact_id)
    )
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    return contact