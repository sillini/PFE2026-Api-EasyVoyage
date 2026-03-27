"""
Endpoints Hôtels — CRUD complet + chambres + tarifs + images + avis.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    get_current_user,
    require_admin,
    require_admin_or_partenaire,
    require_client,
)
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.schemas.hotel import (
    AvisCreate, AvisListResponse, AvisResponse,
    ChambreCreate, ChambreListResponse, ChambreResponse, ChambreUpdate,
    ChambreDisponibiliteResponse, HotelDisponibilitesResponse,
    HotelAdminUpdate, HotelCreate, HotelListResponse, HotelResponse, HotelUpdate,
    TarifCreate, TarifUpdate, TarifListResponse, TarifResponse,
    TypeChambreResponse, TypeReservationResponse,
    HotelFeaturedUpdate, VilleVedetteCreate, VilleVedetteUpdate, VilleVedetteResponse,
)
from app.schemas.image import ImageCreate, ImageListResponse, ImageResponse, ImageUpdateType
import app.services.hotel_service as hotel_service
import app.services.image_service as image_service

router = APIRouter(prefix="/hotels", tags=["Hôtels"])


# ═══════════════════════════════════════════════════════════
#  RÉFÉRENTIELS (types chambre / réservation)
# ═══════════════════════════════════════════════════════════
@router.get("/types-chambre", response_model=list[TypeChambreResponse])
async def list_types_chambre(session: AsyncSession = Depends(get_db)):
    return await hotel_service.list_types_chambre(session)


@router.get("/types-reservation", response_model=list[TypeReservationResponse])
async def list_types_reservation(session: AsyncSession = Depends(get_db)):
    return await hotel_service.list_types_reservation(session)


# ═══════════════════════════════════════════════════════════
#  HOTELS
# ═══════════════════════════════════════════════════════════
@router.get("", response_model=HotelListResponse, summary="Liste des hôtels")
async def list_hotels(
    ville:            Optional[str]   = Query(None, description="Filtrer par ville tunisienne"),
    nom:              Optional[str]   = Query(None),
    etoiles_min:      Optional[int]   = Query(None, ge=1, le=5),
    etoiles_max:      Optional[int]   = Query(None, ge=1, le=5),
    note_min:         Optional[float] = Query(None, ge=0, le=5),
    actif_only:       Optional[str]   = Query("true"),
    partenaire_nom:   Optional[str]   = Query(None),
    partenaire_email: Optional[str]   = Query(None),
    page:     int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    actif_bool = str(actif_only).lower() not in ("false", "0", "no")
    return await hotel_service.list_hotels(
        session, ville=ville, nom=nom,
        etoiles_min=etoiles_min, etoiles_max=etoiles_max,
        note_min=note_min, actif_only=actif_bool,
        partenaire_nom=partenaire_nom, partenaire_email=partenaire_email,
        page=page, per_page=per_page,
    )


# ── Routes statiques AVANT /{hotel_id} ──────────────────────
# Public — hôtels mis en avant
@router.get("/featured", response_model=HotelListResponse,
            summary="Hôtels mis en avant (landing page)")
async def get_featured_hotels(session: AsyncSession = Depends(get_db)):
    return await hotel_service.list_hotels_en_avant(session)

# Public — villes vedettes
@router.get("/villes-vedettes", response_model=list,
            summary="Villes vedettes actives (landing page)")
async def get_villes_vedettes(session: AsyncSession = Depends(get_db)):
    return await hotel_service.list_villes_vedettes(session, actif_only=True)

# Admin — toggle mis_en_avant
@router.patch("/admin/{hotel_id}/featured", response_model=HotelResponse,
              summary="Mettre en avant / retirer [ADMIN]")
async def toggle_featured(
    hotel_id: int, data: HotelFeaturedUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await hotel_service.toggle_mis_en_avant(hotel_id, data.mis_en_avant, session)

# Admin — CRUD villes vedettes
@router.get("/admin/villes-vedettes", response_model=list,
            summary="Toutes les villes vedettes [ADMIN]")
async def admin_list_villes(
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await hotel_service.list_villes_vedettes(session, actif_only=False)

@router.post("/admin/villes-vedettes", response_model=VilleVedetteResponse,
             status_code=201, summary="Ajouter une ville vedette [ADMIN]")
async def admin_create_ville(
    data: VilleVedetteCreate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await hotel_service.create_ville_vedette(data, session)

@router.put("/admin/villes-vedettes/{ville_id}", response_model=VilleVedetteResponse,
            summary="Modifier une ville vedette [ADMIN]")
async def admin_update_ville(
    ville_id: int, data: VilleVedetteUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await hotel_service.update_ville_vedette(ville_id, data, session)

@router.delete("/admin/villes-vedettes/{ville_id}", status_code=204,
               summary="Supprimer une ville vedette [ADMIN]")
async def admin_delete_ville(
    ville_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    await hotel_service.delete_ville_vedette(ville_id, session)

# ── Route dynamique /{hotel_id} APRÈS les routes statiques ──
@router.get("/{hotel_id}", response_model=HotelResponse, summary="Détail d'un hôtel")
async def get_hotel(hotel_id: int, session: AsyncSession = Depends(get_db)):
    return await hotel_service.get_hotel(hotel_id, session)


@router.post("", response_model=HotelResponse, status_code=status.HTTP_201_CREATED,
             summary="Créer un hôtel [PARTENAIRE] — enregistre l'id_partenaire automatiquement")
async def create_hotel(
    data: HotelCreate,
    session: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_partenaire),
):
    id_partenaire = current_user.user_id if current_user.role == "PARTENAIRE" else None
    return await hotel_service.create_hotel(data, session, id_partenaire=id_partenaire)


@router.put("/{hotel_id}", response_model=HotelResponse,
            summary="Modifier un hôtel [PARTENAIRE] — modification complète")
async def update_hotel(
    hotel_id: int, data: HotelUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await hotel_service.update_hotel(hotel_id, data, session)


@router.patch("/{hotel_id}/toggle", response_model=HotelResponse,
              summary="Activer/désactiver un hôtel [ADMIN] — admin uniquement")
async def admin_toggle_hotel(
    hotel_id: int, data: HotelAdminUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    return await hotel_service.admin_toggle_hotel(hotel_id, data.actif, session)


@router.delete("/{hotel_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer un hôtel [ADMIN] (soft delete)")
async def delete_hotel(
    hotel_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    await hotel_service.delete_hotel(hotel_id, session)


# ═══════════════════════════════════════════════════════════
#  CHAMBRES
# ═══════════════════════════════════════════════════════════
@router.get("/{hotel_id}/chambres", response_model=ChambreListResponse,
            summary="Chambres d'un hôtel")
async def list_chambres(
    hotel_id: int,
    capacite_min: Optional[int] = Query(None, ge=1),
    capacite_max: Optional[int] = Query(None, ge=1),
    id_type_chambre: Optional[int] = Query(None),
    prix_min: Optional[float] = Query(None, ge=0),
    prix_max: Optional[float] = Query(None, ge=0),
    session: AsyncSession = Depends(get_db),
):
    return await hotel_service.list_chambres(
        hotel_id, session,
        capacite_min=capacite_min, capacite_max=capacite_max,
        id_type_chambre=id_type_chambre,
        prix_min=prix_min, prix_max=prix_max,
    )


@router.get("/{hotel_id}/chambres/{chambre_id}", response_model=ChambreResponse,
            summary="Détail d'une chambre")
async def get_chambre(
    hotel_id: int, chambre_id: int, session: AsyncSession = Depends(get_db)
):
    return await hotel_service.get_chambre(hotel_id, chambre_id, session)


@router.post("/{hotel_id}/chambres", response_model=ChambreResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Ajouter une chambre [ADMIN | PARTENAIRE]")
async def create_chambre(
    hotel_id: int, data: ChambreCreate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await hotel_service.create_chambre(hotel_id, data, session)


@router.put("/{hotel_id}/chambres/{chambre_id}", response_model=ChambreResponse,
            summary="Modifier une chambre [ADMIN | PARTENAIRE]")
async def update_chambre(
    hotel_id: int, chambre_id: int, data: ChambreUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await hotel_service.update_chambre(hotel_id, chambre_id, data, session)


@router.delete("/{hotel_id}/chambres/{chambre_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer une chambre [ADMIN]")
async def delete_chambre(
    hotel_id: int, chambre_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    await hotel_service.delete_chambre(hotel_id, chambre_id, session)


@router.get(
    "/{hotel_id}/disponibilites",
    response_model=HotelDisponibilitesResponse,
    summary="Disponibilités de toutes les chambres [ADMIN | PARTENAIRE]",
    description="""
Retourne le statut de disponibilité de toutes les chambres actives d'un hôtel
pour une période donnée.

Une chambre est **indisponible** si elle possède au moins une réservation
avec statut **CONFIRMEE** qui chevauche la période demandée.
    """,
)
async def get_hotel_disponibilites(
    hotel_id: int,
    date_debut: date = Query(..., description="Date de début (YYYY-MM-DD)"),
    date_fin: date   = Query(..., description="Date de fin (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    if date_fin <= date_debut:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="date_fin doit être après date_debut")
    return await hotel_service.get_hotel_disponibilites(hotel_id, date_debut, date_fin, session)


@router.get(
    "/{hotel_id}/chambres/{chambre_id}/disponibilite",
    response_model=ChambreDisponibiliteResponse,
    summary="Disponibilité d'une chambre [ADMIN | PARTENAIRE]",
    description="Vérifie si une chambre spécifique est disponible sur une période donnée.",
)
async def get_chambre_disponibilite(
    hotel_id: int,
    chambre_id: int,
    date_debut: date = Query(..., description="Date de début (YYYY-MM-DD)"),
    date_fin: date   = Query(..., description="Date de fin (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    if date_fin <= date_debut:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="date_fin doit être après date_debut")
    return await hotel_service.get_chambre_disponibilite(hotel_id, chambre_id, date_debut, date_fin, session)


# ═══════════════════════════════════════════════════════════
#  TARIFS
# ═══════════════════════════════════════════════════════════
@router.get("/{hotel_id}/chambres/{chambre_id}/tarifs", response_model=TarifListResponse,
            summary="Tarifs d'une chambre")
async def list_tarifs(
    hotel_id: int, chambre_id: int, session: AsyncSession = Depends(get_db)
):
    return await hotel_service.list_tarifs(hotel_id, chambre_id, session)


@router.post("/{hotel_id}/chambres/{chambre_id}/tarifs", response_model=TarifResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Ajouter un tarif [ADMIN | PARTENAIRE]")
async def create_tarif(
    hotel_id: int, chambre_id: int, data: TarifCreate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await hotel_service.create_tarif(hotel_id, chambre_id, data, session)


@router.put("/{hotel_id}/chambres/{chambre_id}/tarifs/{tarif_id}",
            response_model=TarifResponse,
            summary="Modifier un tarif [ADMIN | PARTENAIRE]")
async def update_tarif(
    hotel_id: int, chambre_id: int, tarif_id: int, data: TarifUpdate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await hotel_service.update_tarif(hotel_id, chambre_id, tarif_id, data, session)


@router.delete("/{hotel_id}/chambres/{chambre_id}/tarifs/{tarif_id}",
               status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer un tarif [ADMIN]")
async def delete_tarif(
    hotel_id: int, chambre_id: int, tarif_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    await hotel_service.delete_tarif(hotel_id, chambre_id, tarif_id, session)


# ═══════════════════════════════════════════════════════════
#  IMAGES
# ═══════════════════════════════════════════════════════════
@router.get("/{hotel_id}/images", response_model=ImageListResponse,
            summary="Images d'un hôtel")
async def list_images(hotel_id: int, session: AsyncSession = Depends(get_db)):
    return await image_service.list_images_hotel(hotel_id, session)


@router.post("/{hotel_id}/images", response_model=ImageResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Ajouter une image [ADMIN | PARTENAIRE]")
async def add_image(
    hotel_id: int, data: ImageCreate,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await image_service.add_image_hotel(hotel_id, data, session)


@router.patch("/{hotel_id}/images/{image_id}", response_model=ImageResponse,
              summary="Changer le type d'une image [ADMIN | PARTENAIRE]")
async def update_image_type(
    hotel_id: int, image_id: int, data: ImageUpdateType,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin_or_partenaire),
):
    return await image_service.update_image_type_hotel(hotel_id, image_id, data, session)


@router.delete("/{hotel_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer une image [ADMIN]")
async def delete_image(
    hotel_id: int, image_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    await image_service.delete_image_hotel(hotel_id, image_id, session)


# ═══════════════════════════════════════════════════════════
#  AVIS
# ═══════════════════════════════════════════════════════════
@router.get("/{hotel_id}/avis", response_model=AvisListResponse,
            summary="Avis d'un hôtel")
async def list_avis(hotel_id: int, session: AsyncSession = Depends(get_db)):
    return await hotel_service.list_avis(hotel_id, session)


@router.post("/{hotel_id}/avis", response_model=AvisResponse,
             status_code=status.HTTP_201_CREATED,
             summary="Laisser un avis [CLIENT]",
             description="Un client ne peut laisser qu'un seul avis par hôtel.")
async def create_avis(
    hotel_id: int, data: AvisCreate,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_client),
):
    return await hotel_service.create_avis(hotel_id, data, token.user_id, session)


@router.delete("/{hotel_id}/avis/{avis_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Supprimer un avis [CLIENT (le sien) | ADMIN]")
async def delete_avis(
    hotel_id: int, avis_id: int,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(get_current_user),
):
    await hotel_service.delete_avis(hotel_id, avis_id, token.user_id, token.role, session)