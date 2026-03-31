# app/services/contact_service.py
"""
Synchronisation Python des contacts — complément aux triggers PostgreSQL.
À appeler dans les endpoints après chaque création réussie.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.contact import Contact


async def upsert_contact(
    session: AsyncSession,
    *,
    email: str,
    telephone: str | None,
    nom: str | None,
    prenom: str | None,
    type: str,       # 'client' ou 'visiteur'
    source_id: int | None = None,
) -> None:
    """Insère le contact si l'email n'existe pas encore. Silencieux sinon."""
    result = await session.execute(
        select(Contact).where(Contact.email == email)
    )
    existing = result.scalar_one_or_none()

    if existing is None:
        session.add(Contact(
            email=email,
            telephone=telephone,
            nom=nom,
            prenom=prenom,
            type=type,
            source_id=source_id,
        ))
        # Pas de commit ici — le caller gère la transaction