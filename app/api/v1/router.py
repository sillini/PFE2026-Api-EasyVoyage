"""
API v1 main router — tous les modules.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth
from app.api.v1.endpoints import voyages
from app.api.v1.endpoints import voyage_images
from app.api.v1.endpoints import hotels
from app.api.v1.endpoints import reservations
from app.api.v1.endpoints import factures
from app.api.v1.endpoints import marketing
from app.api.v1.endpoints import partenaires
from app.api.v1.endpoints import hero_slides
from app.api.v1.endpoints import support
from app.api.v1.endpoints import clients
from app.api.v1.endpoints.demandes_partenaire import (
    public_router as demandes_public_router,
    admin_router  as demandes_admin_router,
)

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(auth.router)
api_v1_router.include_router(voyages.router)
api_v1_router.include_router(voyage_images.router)
api_v1_router.include_router(hotels.router)
api_v1_router.include_router(reservations.router)
api_v1_router.include_router(factures.router)
api_v1_router.include_router(marketing.router)
api_v1_router.include_router(partenaires.router)
api_v1_router.include_router(hero_slides.router)
api_v1_router.include_router(support.router)
api_v1_router.include_router(clients.router)
api_v1_router.include_router(demandes_public_router)
api_v1_router.include_router(demandes_admin_router)