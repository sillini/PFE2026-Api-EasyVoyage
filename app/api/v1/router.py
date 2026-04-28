"""
app/api/v1/router.py
"""
from fastapi import APIRouter

from app.api.v1.endpoints import auth
from app.api.v1.endpoints import voyages
from app.api.v1.endpoints import voyage_images
from app.api.v1.endpoints import hotels
from app.api.v1.endpoints import reservations
from app.api.v1.endpoints import factures
from app.api.v1.endpoints import factures_admin
from app.api.v1.endpoints import marketing
from app.api.v1.endpoints import partenaires
from app.api.v1.endpoints import hero_slides
from app.api.v1.endpoints import support
from app.api.v1.endpoints import clients
from app.api.v1.endpoints import favoris
from app.api.v1.endpoints import finances
from app.api.v1.endpoints import contacts
from app.api.v1.endpoints import finances_partenaire
from app.api.v1.endpoints import publication_facebook
from app.api.v1.endpoints import facebook_interactions
from app.api.v1.endpoints import catalogue
from app.api.v1.endpoints.demandes_partenaire import (
    public_router as demandes_public_router,
    admin_router  as demandes_admin_router,
)
from app.api.v1.endpoints import hotel_ai_analysis
from app.api.v1.endpoints import promotions
from app.api.v1.endpoints import fiscal
from app.api.v1.endpoints import video_campaign
from app.api.v1.endpoints import agent_ia                  # ← NOUVEAU
from app.api.v1.endpoints import agent_ia_client           # ← NOUVEAU
from app.api.v1.endpoints import agent_ia_partenaire 
from app.api.v1.endpoints import hotel_description_ai          # ← NOUVEAU
from app.api.v1.endpoints import chambre_description_ai 
from app.api.v1.endpoints import promotion_description_ai  
from app.api.v1.endpoints import hotel_ai_analysis_partenaire  

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(auth.router)
api_v1_router.include_router(voyages.router)
api_v1_router.include_router(voyage_images.router)
api_v1_router.include_router(hotels.router)
api_v1_router.include_router(reservations.router)

# ⚠️ factures_admin AVANT factures
api_v1_router.include_router(factures_admin.router)
api_v1_router.include_router(factures.router)

api_v1_router.include_router(marketing.router)
api_v1_router.include_router(partenaires.router)
api_v1_router.include_router(hero_slides.router)
api_v1_router.include_router(support.router)
api_v1_router.include_router(clients.router)
api_v1_router.include_router(demandes_public_router)
api_v1_router.include_router(demandes_admin_router)
api_v1_router.include_router(favoris.router)
api_v1_router.include_router(finances.router)
api_v1_router.include_router(contacts.router)
api_v1_router.include_router(finances_partenaire.router)

# ⚠️ facebook_interactions AVANT publication_facebook
api_v1_router.include_router(facebook_interactions.router)
api_v1_router.include_router(publication_facebook.router)

api_v1_router.include_router(catalogue.router)
api_v1_router.include_router(hotel_ai_analysis.router)
api_v1_router.include_router(promotions.router)
api_v1_router.include_router(fiscal.router)
api_v1_router.include_router(video_campaign.router)
api_v1_router.include_router(agent_ia.router)              # ← NOUVEAU
api_v1_router.include_router(agent_ia_client.router)  
api_v1_router.include_router(agent_ia_partenaire.router)

api_v1_router.include_router(hotel_description_ai.router)      # ← NOUVEAU
api_v1_router.include_router(chambre_description_ai.router)
api_v1_router.include_router(promotion_description_ai.router) 
api_v1_router.include_router(hotel_ai_analysis_partenaire.router)
