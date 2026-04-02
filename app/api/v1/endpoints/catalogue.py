# app/api/v1/endpoints/catalogue.py
from datetime import datetime, timezone
from typing import Optional
import json
import os

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import anthropic
from app.core.config import settings
from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.models.catalogue import Catalogue, StatutCatalogue
from app.models.contact import Contact
from app.schemas.auth import TokenData
from app.schemas.catalogue import (
    CatalogueGenererRequest,
    CatalogueModifierRequest,
    CatalogueEnvoyerRequest,
    CatalogueResponse,
    CatalogueListResponse,
)

router = APIRouter(prefix="/catalogues", tags=["Catalogues"])

N8N_WEBHOOK  = "http://localhost:5678/webhook/easyvoyage-catalogue"
API_BASE_URL = "http://localhost:8000"


def _abs_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return f"{API_BASE_URL}{url if url.startswith('/') else '/' + url}"




def _claude_client() -> anthropic.AsyncAnthropic:
    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY manquant")
    return anthropic.AsyncAnthropic(api_key=api_key)

# ══════════════════════════════════════════════════════════
#  PARTIE 1 — Générer avec IA
# ══════════════════════════════════════════════════════════
@router.post("/generer", response_model=CatalogueResponse, status_code=201)
async def generer_catalogue(
    data: CatalogueGenererRequest,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_admin),
):
    from app.models.hotel import Hotel
    from app.models.voyage import Voyage

    # ── Récupérer noms hôtels + voyages ──────────────────
    noms_hotels = []
    for hid in data.hotel_ids:
        h = await session.get(Hotel, hid)
        if h:
            noms_hotels.append(f"{h.nom} ({h.ville}, {h.etoiles} etoiles)")

    noms_voyages = []
    for vid in data.voyage_ids:
        v = await session.get(Voyage, vid)
        if v:
            noms_voyages.append(
                f"{v.titre} - {v.destination}, {v.duree}j, {float(v.prix_base):.0f} DT"
            )

    titre_ameliore      = data.titre
    description_ia_json = ""

    try:

        claude = _claude_client()

        prompt = (
        "Tu es expert marketing touristique pour EasyVoyage Tunisie.\n"
        "Reponds UNIQUEMENT avec du JSON valide sans backticks ni markdown.\n\n"
        "Format exact :\n"
        "{\n"
        "  \"sujet\": \"sujet email accrocheur max 60 caracteres\",\n"
        "  \"titre\": \"titre court professionnel max 40 caracteres\",\n"
        "  \"description\": \"description complete style catalogue marketing\"\n"
        "}\n\n"
        f"Titre propose par l admin : \"{data.titre}\"\n"
        f"Hotels selectionnes : {', '.join(noms_hotels) if noms_hotels else 'aucun'}\n"
        f"Voyages selectionnes : {', '.join(noms_voyages) if noms_voyages else 'aucun'}\n\n"
        "Instructions pour la description (style catalogue marketing professionnel) :\n"
        "- Redige en francais, fluide et attractif\n"
        "- Pour chaque hotel mentionne : localisation, ambiance, equipements (piscine, spa, wifi, restaurant), type de pension, activites proposees, public cible\n"
        "- Pour chaque voyage mentionne : destination, duree, points forts, activites incluses, public cible\n"
        "- Termine par une phrase d accroche incitant a reserver\n"
        "- Maximum 5 phrases au total, percutantes et professionnelles\n"
        "- Ameliore le titre admin si vague ou mal orthographie\n"
        "- Le sujet email doit donner envie d ouvrir le mail immediatement"
        )
        msg = await claude.messages.create(
            model="claude-sonnet-4-5",          # ← modèle correct
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )

        raw     = msg.content[0].text.strip()
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed  = json.loads(cleaned)

        titre_ameliore = parsed.get("titre",       data.titre)
        sujet_ia       = parsed.get("sujet",       data.titre)
        description_ia = parsed.get("description", "")

        description_ia_json = json.dumps({
            "sujet":       sujet_ia,
            "titre":       titre_ameliore,
            "description": description_ia,
        }, ensure_ascii=False)

        print(f"[CATALOGUE] Claude OK — titre: {titre_ameliore} | sujet: {sujet_ia}")

    except Exception as e:
        print(f"[CATALOGUE] Claude erreur: {e}")
        titre_ameliore      = data.titre
        description_ia_json = json.dumps({
            "sujet":       data.titre,
            "titre":       data.titre,
            "description": (
                f"Decouvrez notre selection de {len(data.hotel_ids)} hotel(s) "
                f"et {len(data.voyage_ids)} voyage(s) en Tunisie."
            ),
        }, ensure_ascii=False)

    cat = Catalogue(
        titre          = titre_ameliore,
        destinataires  = "tous",
        hotel_ids      = data.hotel_ids,
        voyage_ids     = data.voyage_ids,
        description_ia = description_ia_json,
        statut         = StatutCatalogue.BROUILLON,
        created_by     = token.user_id,
    )
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


# ══════════════════════════════════════════════════════════
#  MODIFIER UN CATALOGUE
# ══════════════════════════════════════════════════════════
@router.put("/{catalogue_id}", response_model=CatalogueResponse)
async def modifier_catalogue(
    catalogue_id: int,
    data: CatalogueModifierRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")
    if cat.statut != StatutCatalogue.BROUILLON:
        raise HTTPException(400, "Seul un catalogue BROUILLON peut etre modifie")

    if data.titre          is not None: cat.titre          = data.titre
    if data.description_ia is not None: cat.description_ia = data.description_ia
    if data.hotel_ids      is not None: cat.hotel_ids      = data.hotel_ids
    if data.voyage_ids     is not None: cat.voyage_ids     = data.voyage_ids

    await session.commit()
    await session.refresh(cat)
    return cat


# ══════════════════════════════════════════════════════════
#  CONSULTER — détail enrichi
# ══════════════════════════════════════════════════════════
@router.get("/{catalogue_id}/detail")
async def get_catalogue_detail(
    catalogue_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    from app.models.hotel import Hotel
    from app.models.voyage import Voyage
    from app.models.image import Image

    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")

    hotels_detail = []
    for hid in (cat.hotel_ids or []):
        h = await session.get(Hotel, hid)
        if not h: continue
        img = (await session.execute(
            select(Image).where(Image.id_hotel == hid)
            .where(Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none()
        if not img:
            img = (await session.execute(
                select(Image).where(Image.id_hotel == hid).limit(1)
            )).scalar_one_or_none()
        hotels_detail.append({
            "id":        h.id,
            "nom":       h.nom,
            "ville":     h.ville   or "",
            "etoiles":   h.etoiles or 0,
            "image_url": _abs_url(img.url) if img else "",
        })

    voyages_detail = []
    for vid in (cat.voyage_ids or []):
        v = await session.get(Voyage, vid)
        if not v: continue
        img = (await session.execute(
            select(Image).where(Image.id_voyage == vid)
            .where(Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none()
        if not img:
            img = (await session.execute(
                select(Image).where(Image.id_voyage == vid).limit(1)
            )).scalar_one_or_none()
        voyages_detail.append({
            "id":          v.id,
            "titre":       v.titre,
            "destination": v.destination or "",
            "duree":       v.duree       or 0,
            "prix_base":   float(v.prix_base) if v.prix_base else 0,
            "image_url":   _abs_url(img.url) if img else "",
        })

    return {
        "id":             cat.id,
        "titre":          cat.titre,
        "description_ia": cat.description_ia,
        "destinataires":  cat.destinataires,
        "statut":         cat.statut,
        "nb_envoyes":     cat.nb_envoyes,
        "created_at":     cat.created_at,
        "envoye_at":      cat.envoye_at,
        "hotel_ids":      cat.hotel_ids,
        "voyage_ids":     cat.voyage_ids,
        "hotels":         hotels_detail,
        "voyages":        voyages_detail,
    }


# ══════════════════════════════════════════════════════════
#  ENVOYER
# ══════════════════════════════════════════════════════════
@router.post("/{catalogue_id}/envoyer", response_model=CatalogueResponse)
async def envoyer_catalogue(
    catalogue_id: int,
    data: CatalogueEnvoyerRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    from app.models.hotel import Hotel
    from app.models.voyage import Voyage
    from app.models.image import Image

    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")

    # ── Contacts filtrés + limités ────────────────────────
    q_contacts = select(Contact).order_by(Contact.created_at.desc())
    if data.destinataires in ("client", "visiteur"):
        q_contacts = q_contacts.where(Contact.type == data.destinataires)
    q_contacts   = q_contacts.limit(data.nb_contacts)
    contacts     = (await session.execute(q_contacts)).scalars().all()
    contacts_data = [
        {
            "email": c.email,
            "nom":   f"{c.prenom or ''} {c.nom or ''}".strip() or c.email,
            "type":  c.type,
        }
        for c in contacts
    ]

    # ── Hôtels enrichis ───────────────────────────────────
    hotels_data = []
    for hid in (cat.hotel_ids or []):
        h = await session.get(Hotel, hid)
        if not h: continue
        img = (await session.execute(
            select(Image).where(Image.id_hotel == hid)
            .where(Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none()
        if not img:
            img = (await session.execute(
                select(Image).where(Image.id_hotel == hid).limit(1)
            )).scalar_one_or_none()
        hotels_data.append({
            "id":          h.id,
            "nom":         h.nom,
            "ville":       h.ville       or "Tunisie",
            "pays":        h.pays        or "Tunisie",
            "etoiles":     h.etoiles     or 0,
            "adresse":     h.adresse     or "",
            "description": h.description or "",
            "note":        float(h.note_moyenne) if h.note_moyenne else 0,
            "image_url":   _abs_url(img.url) if img else "",
        })

    # ── Voyages enrichis ──────────────────────────────────
    voyages_data = []
    for vid in (cat.voyage_ids or []):
        v = await session.get(Voyage, vid)
        if not v: continue
        img = (await session.execute(
            select(Image).where(Image.id_voyage == vid)
            .where(Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none()
        if not img:
            img = (await session.execute(
                select(Image).where(Image.id_voyage == vid).limit(1)
            )).scalar_one_or_none()
        voyages_data.append({
            "id":          v.id,
            "titre":       v.titre,
            "destination": v.destination or "",
            "duree":       v.duree        or 0,
            "prix_base":   float(v.prix_base) if v.prix_base else 0,
            "description": v.description  or "",
            "date_depart": str(v.date_depart),
            "date_retour": str(v.date_retour),
            "places":      max(0, v.capacite_max - v.nb_inscrits),
            "image_url":   _abs_url(img.url) if img else "",
        })

    # ── Extraire sujet depuis description_ia ─────────────
    email_sujet = cat.titre
    try:
        parsed_desc = json.loads(cat.description_ia or "{}")
        email_sujet = parsed_desc.get("sujet", cat.titre)
    except Exception:
        pass

    # ── Appel n8n ─────────────────────────────────────────
    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(N8N_WEBHOOK, json={
                "destinataires":  data.destinataires,
                "email_sujet":    email_sujet,          # ← sujet Claude
                "description_ia": cat.description_ia or "",
                "hotel_ids":      cat.hotel_ids   or [],
                "voyage_ids":     cat.voyage_ids  or [],
                "hotels":         hotels_data,
                "voyages":        voyages_data,
                "contacts":       contacts_data,
                "nb_envoyes":     len(contacts_data),
            }, timeout=30.0)
            n8n_ok = res.status_code < 400
    except Exception as e:
        print(f"[CATALOGUE] n8n erreur: {e}")
        n8n_ok = False

    cat.destinataires = data.destinataires
    cat.nb_envoyes    = len(contacts_data)
    cat.statut        = StatutCatalogue.ENVOYE if n8n_ok else StatutCatalogue.ECHOUE
    cat.envoye_at     = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(cat)
    return cat


# ── Lister ────────────────────────────────────────────────
@router.get("", response_model=CatalogueListResponse)
async def list_catalogues(
    statut:   Optional[str] = Query(None),
    page:     int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=100),
    session:  AsyncSession = Depends(get_db),
    _:        TokenData = Depends(require_admin),
):
    q = select(Catalogue).order_by(Catalogue.created_at.desc())
    if statut:
        q = q.where(Catalogue.statut == statut)
    total = (await session.execute(
        select(func.count()).select_from(q.subquery())
    )).scalar() or 0
    items = (await session.execute(
        q.offset((page - 1) * per_page).limit(per_page)
    )).scalars().all()
    return CatalogueListResponse(total=total, page=page, per_page=per_page, items=items)


# ── Détail simple ─────────────────────────────────────────
@router.get("/{catalogue_id}", response_model=CatalogueResponse)
async def get_catalogue(
    catalogue_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")
    return cat


# ── Supprimer ─────────────────────────────────────────────
@router.delete("/{catalogue_id}", status_code=204)
async def delete_catalogue(
    catalogue_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")
    await session.delete(cat)
    await session.commit()