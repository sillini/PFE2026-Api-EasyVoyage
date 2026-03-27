"""
Scheduler — appelle les fonctions PostgreSQL au démarrage et toutes les 24h :

  1. fn_terminer_reservations_echeues()
       → Passe CONFIRMEE → TERMINEE quand date_fin < aujourd'hui

  2. fn_expirer_campagnes_marketing()
       → Passe ACTIVE → EXPIREE quand date_fin < aujourd'hui
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from sqlalchemy import text

from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

INTERVAL_SECONDES = 24 * 60 * 60  # 24 heures


async def _executer_fonction(nom_fonction: str) -> int:
    """Appelle une fonction PostgreSQL et retourne le nombre de lignes affectées."""
    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(text(f"SELECT {nom_fonction}()"))
            count = result.scalar_one()
            await session.commit()
            if count > 0:
                logger.info(f"Scheduler [{nom_fonction}] : {count} ligne(s) mise(s) à jour")
            return count
        except Exception as e:
            await session.rollback()
            logger.error(f"Scheduler [{nom_fonction}] erreur : {e}")
            return 0


async def executer_taches_planifiees() -> None:
    """Exécute toutes les tâches PostgreSQL planifiées."""
    await _executer_fonction("voyage_hotel.fn_terminer_reservations_echeues")
    await _executer_fonction("voyage_hotel.fn_expirer_campagnes_marketing")


async def _scheduler_loop() -> None:
    """Boucle infinie : exécute les tâches puis attend 24h."""
    while True:
        await executer_taches_planifiees()
        await asyncio.sleep(INTERVAL_SECONDES)


@asynccontextmanager
async def lifespan_scheduler(app):
    """
    Context manager pour FastAPI lifespan.
    Lance le scheduler au démarrage, l'arrête à l'extinction.
    """
    logger.info("Scheduler démarré — exécution des tâches PostgreSQL...")
    task = asyncio.create_task(_scheduler_loop())

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        logger.info("Scheduler arrêté proprement.")