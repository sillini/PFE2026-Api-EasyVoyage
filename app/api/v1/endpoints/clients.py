"""
app/api/v1/endpoints/clients.py
=================================
Endpoints Admin — Gestion des clients.

Routes :
  GET   /admin/clients              → Liste paginée avec filtres + search
  GET   /admin/clients/{id}         → Détail client
  PATCH /admin/clients/{id}/toggle  → Activer / désactiver
  GET   /admin/clients/{id}/reservations → Réservations du client (enrichies)
"""
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.schemas.auth import TokenData
from app.models.utilisateur import Utilisateur, Client, RoleUtilisateur
from app.models.reservation import Reservation, Facture, StatutReservation
from app.models.hotel import Chambre, Hotel
from app.models.voyage import Voyage
from app.core.exceptions import NotFoundException

router = APIRouter(prefix="/admin/clients", tags=["Admin — Clients"])


# ── Schemas ───────────────────────────────────────────────
class ClientResponse(BaseModel):
    id:                 int
    nom:                str
    prenom:             str
    email:              str
    telephone:          Optional[str]
    actif:              bool
    date_inscription:   datetime
    derniere_connexion: Optional[datetime]
    nb_reservations:    int = 0
    total_depense:      float = 0.0

    model_config = {"from_attributes": True}


class ClientListResponse(BaseModel):
    total:    int
    page:     int
    per_page: int
    items:    List[ClientResponse]


class ToggleClientRequest(BaseModel):
    actif: bool


class ClientResaItem(BaseModel):
    id:                  int
    date_reservation:    str
    date_debut:          str
    date_fin:            str
    nb_nuits:            int
    statut:              str
    total_ttc:           float
    type_resa:           str
    hotel_nom:           Optional[str] = None
    hotel_ville:         Optional[str] = None
    voyage_titre:        Optional[str] = None
    voyage_destination:  Optional[str] = None
    numero_facture:      Optional[str] = None
    statut_facture:      Optional[str] = None


# ── Liste clients ─────────────────────────────────────────
@router.get("", response_model=ClientListResponse, summary="Liste des clients [ADMIN]")
async def list_clients(
    search:  Optional[str] = Query(None, description="Nom, prénom, email"),
    actif:   Optional[str] = Query(None, description="true | false"),
    page:    int           = Query(1, ge=1),
    per_page:int           = Query(20, ge=1, le=100),
    session: AsyncSession  = Depends(get_db),
    _: TokenData           = Depends(require_admin),
):
    query = (
        select(Utilisateur)
        .join(Client, Client.id == Utilisateur.id)
        .where(Utilisateur.role == RoleUtilisateur.CLIENT)
        .order_by(Utilisateur.date_inscription.desc())
    )

    if search:
        like = f"%{search}%"
        from sqlalchemy import or_
        query = query.where(
            or_(
                Utilisateur.nom.ilike(like),
                Utilisateur.prenom.ilike(like),
                Utilisateur.email.ilike(like),
            )
        )

    if actif is not None:
        actif_bool = str(actif).lower() not in ("false", "0", "no")
        query = query.where(Utilisateur.actif == actif_bool)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total   = (await session.execute(count_q)).scalar_one()

    offset  = (page - 1) * per_page
    result  = await session.execute(query.offset(offset).limit(per_page))
    users   = result.scalars().all()

    items = []
    for u in users:
        # Compter les réservations et le total dépensé
        resa_r = await session.execute(
            select(func.count(Reservation.id), func.coalesce(func.sum(Reservation.total_ttc), 0))
            .where(Reservation.id_client == u.id)
        )
        row = resa_r.one()
        items.append(ClientResponse(
            id=u.id, nom=u.nom, prenom=u.prenom, email=u.email,
            telephone=u.telephone, actif=u.actif,
            date_inscription=u.date_inscription,
            derniere_connexion=u.derniere_connexion,
            nb_reservations=row[0] or 0,
            total_depense=float(row[1] or 0),
        ))

    return ClientListResponse(total=total, page=page, per_page=per_page, items=items)


# ── Détail client ─────────────────────────────────────────
@router.get("/{client_id}", response_model=ClientResponse, summary="Détail d'un client [ADMIN]")
async def get_client(
    client_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    result = await session.execute(
        select(Utilisateur)
        .join(Client, Client.id == Utilisateur.id)
        .where(Utilisateur.id == client_id, Utilisateur.role == RoleUtilisateur.CLIENT)
    )
    u = result.scalar_one_or_none()
    if not u:
        raise NotFoundException(f"Client {client_id} introuvable")

    resa_r = await session.execute(
        select(func.count(Reservation.id), func.coalesce(func.sum(Reservation.total_ttc), 0))
        .where(Reservation.id_client == u.id)
    )
    row = resa_r.one()

    return ClientResponse(
        id=u.id, nom=u.nom, prenom=u.prenom, email=u.email,
        telephone=u.telephone, actif=u.actif,
        date_inscription=u.date_inscription,
        derniere_connexion=u.derniere_connexion,
        nb_reservations=row[0] or 0,
        total_depense=float(row[1] or 0),
    )


# ── Toggle actif / inactif ────────────────────────────────
@router.patch("/{client_id}/toggle", response_model=ClientResponse, summary="Activer / désactiver un client [ADMIN]")
async def toggle_client(
    client_id: int,
    data: ToggleClientRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    result = await session.execute(
        select(Utilisateur)
        .join(Client, Client.id == Utilisateur.id)
        .where(Utilisateur.id == client_id, Utilisateur.role == RoleUtilisateur.CLIENT)
    )
    u = result.scalar_one_or_none()
    if not u:
        raise NotFoundException(f"Client {client_id} introuvable")

    u.actif = data.actif
    await session.flush()

    resa_r = await session.execute(
        select(func.count(Reservation.id), func.coalesce(func.sum(Reservation.total_ttc), 0))
        .where(Reservation.id_client == u.id)
    )
    row = resa_r.one()

    return ClientResponse(
        id=u.id, nom=u.nom, prenom=u.prenom, email=u.email,
        telephone=u.telephone, actif=u.actif,
        date_inscription=u.date_inscription,
        derniere_connexion=u.derniere_connexion,
        nb_reservations=row[0] or 0,
        total_depense=float(row[1] or 0),
    )


# ── Réservations d'un client ──────────────────────────────
@router.get("/{client_id}/reservations", summary="Réservations enrichies d'un client [ADMIN]")
async def get_client_reservations(
    client_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData          = Depends(require_admin),
):
    # Vérifier que le client existe
    chk = await session.execute(
        select(Utilisateur).where(Utilisateur.id == client_id, Utilisateur.role == RoleUtilisateur.CLIENT)
    )
    if not chk.scalar_one_or_none():
        raise NotFoundException(f"Client {client_id} introuvable")

    result = await session.execute(
        select(Reservation)
        .options(
            selectinload(Reservation.lignes_chambres),
            selectinload(Reservation.facture),
        )
        .where(Reservation.id_client == client_id)
        .order_by(Reservation.date_reservation.desc())
    )
    resas = result.scalars().all()

    items = []
    for r in resas:
        hotel_nom = hotel_ville = voyage_titre = voyage_dest = None

        if r.id_voyage:
            v_r = await session.execute(select(Voyage).where(Voyage.id == r.id_voyage))
            v   = v_r.scalar_one_or_none()
            voyage_titre = v.titre       if v else f"Voyage #{r.id_voyage}"
            voyage_dest  = v.destination if v else "—"
            type_r = "voyage"
        else:
            if r.lignes_chambres:
                ch_r = await session.execute(select(Chambre).where(Chambre.id == r.lignes_chambres[0].id_chambre))
                ch   = ch_r.scalar_one_or_none()
                if ch:
                    h_r = await session.execute(select(Hotel).where(Hotel.id == ch.id_hotel))
                    h   = h_r.scalar_one_or_none()
                    if h:
                        hotel_nom   = h.nom
                        hotel_ville = h.ville
            type_r = "hotel"

        items.append(ClientResaItem(
            id                 = r.id,
            date_reservation   = r.date_reservation.strftime("%d/%m/%Y %H:%M"),
            date_debut         = str(r.date_debut),
            date_fin           = str(r.date_fin),
            nb_nuits           = (r.date_fin - r.date_debut).days,
            statut             = r.statut.value,
            total_ttc          = float(r.total_ttc),
            type_resa          = type_r,
            hotel_nom          = hotel_nom,
            hotel_ville        = hotel_ville,
            voyage_titre       = voyage_titre,
            voyage_destination = voyage_dest,
            numero_facture     = r.facture.numero       if r.facture else None,
            statut_facture     = r.facture.statut.value if r.facture else None,
        ))

    return {"total": len(items), "items": items}