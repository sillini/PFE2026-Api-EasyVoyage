"""
Service Factures — récupération et génération PDF.

Opérations :
  - get_facture()        : détail d'une facture
  - list_factures()      : toutes les factures (admin)
  - generer_pdf()        : génère le PDF bytes prêt à télécharger
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.hotel import Chambre
from app.models.reservation import Facture, LigneReservationChambre, Reservation
from app.models.utilisateur import Utilisateur
from app.models.voyage import Voyage
from app.schemas.reservation import FactureResponse
from app.utils.pdf_generator import generer_facture_pdf


# ── Helpers ───────────────────────────────────────────────────────────────────
async def _get_facture_or_404(facture_id: int, session: AsyncSession) -> Facture:
    result = await session.execute(
        select(Facture)
        .options(
            selectinload(Facture.paiements),
            selectinload(Facture.reservation)
            .selectinload(Reservation.lignes_chambres),
        )
        .where(Facture.id == facture_id)
    )
    facture = result.scalar_one_or_none()
    if not facture:
        raise NotFoundException(f"Facture {facture_id} introuvable")
    return facture


def _check_access(facture: Facture, client_id: int, role: str) -> None:
    if role == "CLIENT" and facture.reservation.id_client != client_id:
        raise ForbiddenException("Cette facture ne vous appartient pas")


# ── Détail d'une facture ──────────────────────────────────────────────────────
async def get_facture(
    facture_id: int, client_id: int, role: str, session: AsyncSession
) -> FactureResponse:
    facture = await _get_facture_or_404(facture_id, session)
    _check_access(facture, client_id, role)
    return FactureResponse.model_validate(facture)


# ── Liste toutes les factures (admin) ─────────────────────────────────────────
async def list_factures(
    session: AsyncSession,
    statut: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> dict:
    from sqlalchemy import func
    from app.models.reservation import StatutFacture

    query = select(Facture).options(selectinload(Facture.paiements))

    if statut:
        query = query.where(Facture.statut == StatutFacture(statut))

    count_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Facture.date_emission.desc()).offset(offset).limit(per_page)

    result = await session.execute(query)
    factures = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [FactureResponse.model_validate(f) for f in factures],
    }


# ── Générer le PDF ────────────────────────────────────────────────────────────
async def generer_pdf(
    facture_id: int, client_id: int, role: str, session: AsyncSession
) -> bytes:
    facture = await _get_facture_or_404(facture_id, session)
    _check_access(facture, client_id, role)

    reservation = facture.reservation

    # ── Infos client ──────────────────────────────────────
    result_user = await session.execute(
        select(Utilisateur).where(Utilisateur.id == reservation.id_client)
    )
    user = result_user.scalar_one_or_none()
    client_nom      = user.nom if user else "—"
    client_prenom   = user.prenom if user else "—"
    client_email    = user.email if user else "—"
    client_telephone = user.telephone if user else None

    # ── Calcul nb nuits ───────────────────────────────────
    nb_nuits = (reservation.date_fin - reservation.date_debut).days

    # ── Prestations ───────────────────────────────────────
    prestations = []

    if reservation.id_voyage:
        # Voyage
        result_v = await session.execute(
            select(Voyage).where(Voyage.id == reservation.id_voyage)
        )
        voyage = result_v.scalar_one_or_none()
        if voyage:
            prestations.append({
                "type":        "voyage",
                "titre":       voyage.titre,
                "destination": voyage.destination,
                "prix":        float(reservation.total_ttc),
            })
    else:
        # Chambres
        for ligne in reservation.lignes_chambres:
            result_ch = await session.execute(
                select(Chambre).where(Chambre.id == ligne.id_chambre)
            )
            chambre = result_ch.scalar_one_or_none()
            prestations.append({
                "type":         "chambre",
                "description":  chambre.description if chambre else f"Chambre #{ligne.id_chambre}",
                "nb_nuits":     nb_nuits,
                "prix_unitaire": float(ligne.prix_unitaire),
                "quantite":     ligne.quantite,
            })

    # ── Générer le PDF ────────────────────────────────────
    pdf_bytes = generer_facture_pdf(
        numero_facture=facture.numero,
        date_emission=facture.date_emission,
        statut_facture=facture.statut.value,
        client_nom=client_nom,
        client_prenom=client_prenom,
        client_email=client_email,
        client_telephone=client_telephone,
        date_debut=reservation.date_debut.strftime("%d/%m/%Y"),
        date_fin=reservation.date_fin.strftime("%d/%m/%Y"),
        nb_nuits=nb_nuits,
        prestations=prestations,
        total_ttc=float(reservation.total_ttc),
    )

    return pdf_bytes