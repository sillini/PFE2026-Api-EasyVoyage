# app/api/v1/endpoints/catalogue.py
"""
Endpoints Catalogues Email — version sans n8n.

Nouveautés vs version précédente :
  - /envoyer      → envoi direct via SMTP (catalogue_send_service)
  - /preview      → rendu HTML de l'email avant envoi
  - /compter      → nombre de destinataires selon filtres
  - /{id}/logs    → historique des envois (send_log)
  - /track/open   → pixel tracking d'ouverture
  - /track/click  → redirection + tracking clic
  - Filtres : type (client/visiteur/tous) + inscrit_depuis + nb_contacts
  - Envoi planifié (scheduled_at) via APScheduler
"""
from datetime import datetime, timezone
from typing import Optional
import json
import os

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import anthropic

from app.core.config import settings
from app.api.v1.dependencies import require_admin
from app.db.session import get_db
from app.models.catalogue import Catalogue, StatutCatalogue
from app.models.contact import Contact
from app.models.send_log import SendLog
from app.schemas.auth import TokenData
from app.schemas.catalogue import (
    CatalogueGenererRequest,
    CatalogueModifierRequest,
    CatalogueEnvoyerRequest,
    CatalogueResponse,
    CatalogueListResponse,
    CatalogueDetailResponse,
    SendLogResponse,
    DestinatairesFiltreRequest,
)

router = APIRouter(prefix="/catalogues", tags=["Catalogues"])
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
#  HELPERS — Filtrage contacts (table contact)
# ══════════════════════════════════════════════════════════

def _build_contact_query(destinataires: str, inscrit_depuis: Optional[datetime] = None):
    """Construit la requête SQLAlchemy pour filtrer les contacts."""
    q = select(Contact).order_by(Contact.created_at.desc())
    if destinataires in ("client", "visiteur"):
        q = q.where(Contact.type == destinataires)
    if inscrit_depuis:
        q = q.where(Contact.created_at >= inscrit_depuis)
    return q


# ══════════════════════════════════════════════════════════
#  PARTIE 1 — Générer avec Claude AI
# ══════════════════════════════════════════════════════════

@router.post("/generer", response_model=CatalogueResponse, status_code=201)
async def generer_catalogue(
    data: CatalogueGenererRequest,
    session: AsyncSession = Depends(get_db),
    token: TokenData = Depends(require_admin),
):
    from app.models.hotel  import Hotel, Chambre, Tarif
    from app.models.voyage import Voyage
    # ── FIX 1 : get_promotions_catalogue_admin (sans filtre actif=True) ──
    from app.services.promotion_service import (
        get_promotions_catalogue_admin,
        calculer_prix_promo,
    )
    from datetime import date
    from sqlalchemy import select, func

    if not data.hotel_ids and not data.voyage_ids:
        raise HTTPException(400, "Sélectionnez au moins un hôtel ou un voyage")

    # ══════════════════════════════════════════════════════
    #  1. Prix min par hôtel (une seule requête SQL)
    # ══════════════════════════════════════════════════════
    today = date.today()
    prix_by_hotel: dict = {}

    if data.hotel_ids:
        rows = (await session.execute(
            select(Chambre.id_hotel, func.min(Tarif.prix).label("prix_min"))
            .join(Tarif, Tarif.id_chambre == Chambre.id)
            .where(
                Chambre.id_hotel.in_(data.hotel_ids),
                Chambre.actif    == True,
                Tarif.date_debut <= today,
                Tarif.date_fin   >= today,
            )
            .group_by(Chambre.id_hotel)
        )).all()
        prix_by_hotel = {r.id_hotel: float(r.prix_min) for r in rows}

    # ══════════════════════════════════════════════════════
    #  2. FIX 1 — Promotions sans filtre actif (catalogue admin)
    # ══════════════════════════════════════════════════════
    promos_by_hotel: dict = {}
    if data.hotel_ids:
        promos_by_hotel = await get_promotions_catalogue_admin(
            data.hotel_ids, session
        )

    print(f"[CATALOGUE] prix_by_hotel={prix_by_hotel}")
    print(f"[CATALOGUE] promos_by_hotel keys={list(promos_by_hotel.keys())}")

    # ══════════════════════════════════════════════════════
    #  3. Construire les blocs texte pour Claude
    # ══════════════════════════════════════════════════════
    blocs_hotels = []
    for hid in data.hotel_ids:
        h = await session.get(Hotel, hid)
        if not h:
            continue

        prix_min = prix_by_hotel.get(hid)
        promo    = promos_by_hotel.get(hid)

        bloc = (
            f"- {h.nom} ({h.ville}, {h.etoiles}★"
            + (f", note {float(h.note_moyenne):.1f}/5" if h.note_moyenne else "")
            + ")"
        )

        if prix_min:
            bloc += f"\n  Prix : {prix_min:.0f} DT/nuit"

        if promo is not None and prix_min:
            try:
                pct         = float(promo.pourcentage)
                prix_promo  = calculer_prix_promo(prix_min, pct)
                titre_promo = promo.titre or "Offre spéciale"
                date_fin    = promo.date_fin.strftime("%d/%m/%Y") if promo.date_fin else "—"

                # ── FIX 2 : plus d'accès à type_promotion (champ supprimé) ──
                bloc += (
                    f"\n  🔥 PROMOTION ACTIVE : {titre_promo}"
                    f"\n     Réduction : -{pct:.0f}%"
                    f"\n     Prix promo : {prix_promo:.0f} DT/nuit"
                    f" (au lieu de {prix_min:.0f} DT)"
                    f"\n     Valable jusqu'au : {date_fin}"
                )
                print(f"[CATALOGUE] Hôtel {h.nom} → promo -{pct}% ajoutée au prompt")
            except Exception as e:
                print(f"[CATALOGUE] Erreur lecture promo hôtel {hid}: {e}")

        if h.description:
            bloc += f"\n  Description : {h.description[:200]}"

        blocs_hotels.append(bloc)

    blocs_voyages = []
    for vid in data.voyage_ids:
        v = await session.get(Voyage, vid)
        if not v:
            continue
        places = max(0, v.capacite_max - v.nb_inscrits) if v.capacite_max else None
        bloc = (
            f"- {v.titre} → {v.destination}"
            f"\n  Durée : {v.duree}j | Prix : {float(v.prix_base):.0f} DT/pers"
            f"\n  Départ : {v.date_depart.strftime('%d/%m/%Y')}"
        )
        if places is not None and places <= 5:
            bloc += f"\n  ⚠️ DERNIÈRES PLACES : {places} restante{'s' if places > 1 else ''}"
        if v.description:
            bloc += f"\n  Description : {v.description[:150]}"
        blocs_voyages.append(bloc)

    hotels_text  = "\n".join(blocs_hotels)  or "aucun"
    voyages_text = "\n".join(blocs_voyages) or "aucun"
    has_promos   = bool(promos_by_hotel)

    promo_note = (
        "\n- IMPORTANT : il y a des promotions actives. "
        "Mets clairement en avant les prix avant/après réduction. "
        "Utilise un ton urgent et incitatif pour inciter à réserver vite."
    ) if has_promos else ""

    # ══════════════════════════════════════════════════════
    #  4. Appel Claude
    # ══════════════════════════════════════════════════════
    titre_ameliore      = data.titre
    description_ia_json = ""

    try:
        claude = _claude_client()

        prompt = (
            "Tu es expert marketing touristique pour EasyVoyage Tunisie.\n"
            "Réponds UNIQUEMENT avec du JSON valide, sans backticks ni markdown.\n\n"
            "Format exact :\n"
            '{\n'
            '  "sujet": "sujet email accrocheur max 70 caracteres",\n'
            '  "titre": "titre court professionnel max 50 caracteres",\n'
            '  "description": "description complete style catalogue marketing 3 a 5 phrases"\n'
            '}\n\n'
            f'Titre proposé par l\'admin : "{data.titre}"\n\n'
            f"HÔTELS :\n{hotels_text}\n\n"
            f"VOYAGES :\n{voyages_text}\n\n"
            "Instructions :\n"
            "- Rédige en français, style catalogue marketing professionnel\n"
            "- Pour chaque hôtel : nom, localisation, ambiance\n"
            "- Si un hôtel a une PROMOTION ACTIVE : cite le prix original ET "
            "le prix promo et mets en valeur la réduction\n"
            "- Pour chaque voyage : destination, durée, prix par personne\n"
            "- Si des places sont limitées sur un voyage, crée de l'urgence\n"
            "- Le sujet email doit donner envie d'ouvrir immédiatement\n"
            "- Améliore le titre si vague ou mal orthographié"
            f"{promo_note}"
        )

        msg = await claude.messages.create(
            model      = "claude-opus-4-6",
            max_tokens = 700,
            messages   = [{"role": "user", "content": prompt}],
        )

        raw     = msg.content[0].text.strip()
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        parsed  = json.loads(cleaned)

        titre_ameliore = parsed.get("titre", data.titre)
        sujet_ia       = parsed.get("sujet", data.titre)
        desc_ia        = parsed.get("description", "")

        description_ia_json = json.dumps(
            {"sujet": sujet_ia, "titre": titre_ameliore, "description": desc_ia},
            ensure_ascii=False,
        )
        print(f"[CATALOGUE] Claude OK — titre: {titre_ameliore} | promos: {has_promos}")

    except Exception as e:
        print(f"[CATALOGUE] Claude erreur: {e}")
        titre_ameliore      = data.titre
        description_ia_json = json.dumps({
            "sujet":       data.titre,
            "titre":       data.titre,
            "description": (
                f"Découvrez notre sélection de {len(data.hotel_ids)} hôtel(s) "
                f"et {len(data.voyage_ids)} voyage(s) en Tunisie."
            ),
        }, ensure_ascii=False)

    # ══════════════════════════════════════════════════════
    #  5. Créer le catalogue en base
    # ══════════════════════════════════════════════════════
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
    if cat.statut not in (StatutCatalogue.BROUILLON, StatutCatalogue.ECHOUE):
        raise HTTPException(400, "Seul un catalogue BROUILLON ou ECHOUE peut être modifié")

    if data.titre          is not None: cat.titre          = data.titre
    if data.description_ia is not None: cat.description_ia = data.description_ia
    if data.hotel_ids      is not None: cat.hotel_ids      = data.hotel_ids
    if data.voyage_ids     is not None: cat.voyage_ids     = data.voyage_ids

    cat.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(cat)
    return cat


# ══════════════════════════════════════════════════════════
#  PREVIEW — Rendu HTML avant envoi
# ══════════════════════════════════════════════════════════

@router.get("/{catalogue_id}/preview")
async def preview_catalogue(
    catalogue_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    Retourne le HTML final de l'email avec un contact fictif.
    Affiche les promotions actives exactement comme dans l'email réel.
    """
    from app.services.catalogue_send_service import (
        _parse_description_ia,
        _load_items_with_promos,
        _build_html_email,
        _personalize,
    )

    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")

    sujet, description     = _parse_description_ia(cat)
    hotels, voyages        = await _load_items_with_promos(cat, session)

    html = _build_html_email(
        titre       = cat.titre,
        sujet       = sujet,
        description = description,
        hotels      = hotels,
        voyages     = voyages,
    )

    contact_demo = {
        "prenom": "Jean",
        "nom":    "Dupont",
        "email":  "demo@easyvoyage.tn",
    }
    html_preview = _personalize(html, contact_demo)

    return {"html": html_preview, "sujet": sujet, "titre": cat.titre}


# ══════════════════════════════════════════════════════════
#  COMPTER LES DESTINATAIRES (avant envoi)
# ══════════════════════════════════════════════════════════

@router.post("/destinataires/compter")
async def compter_destinataires(
    data: DestinatairesFiltreRequest,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    """
    Retourne le nombre de contacts qui correspondent aux filtres.
    Utilisé pour afficher "X emails seront envoyés" dans le modal.
    """
    q = select(func.count(Contact.id))
    if data.destinataires in ("client", "visiteur"):
        q = q.where(Contact.type == data.destinataires)
    if data.inscrit_depuis:
        q = q.where(Contact.created_at >= data.inscrit_depuis)

    total = (await session.execute(q)).scalar_one()
    return {
        "total":      total,
        "nb_envoyes": min(total, data.nb_contacts),
    }


# ══════════════════════════════════════════════════════════
#  ENVOYER — Remplace complètement n8n
# ══════════════════════════════════════════════════════════

@router.post("/{catalogue_id}/envoyer", response_model=CatalogueResponse)
async def envoyer_catalogue(
    catalogue_id: int,
    data: CatalogueEnvoyerRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")
    if cat.statut == StatutCatalogue.EN_COURS:
        raise HTTPException(409, "Un envoi est déjà en cours pour ce catalogue")

    # ════════════════════════════════════════════════════
    #  RÉSOLUTION DES CONTACTS — deux modes
    # ════════════════════════════════════════════════════

    if data.contact_ids:
        # ── MODE MANUEL : IDs explicites fournis par le frontend ──
        contacts_list = []
        for cid in data.contact_ids:
            c = await session.get(Contact, cid)
            if c:
                contacts_list.append(c)

        if not contacts_list:
            raise HTTPException(400, "Aucun contact valide dans la sélection")

        print(f"[CATALOGUE] Mode MANUEL — {len(contacts_list)} contacts sélectionnés : "
              f"{[c.email for c in contacts_list]}")

    else:
        # ── MODE AUTOMATIQUE : filtre par type + limite ──
        q = select(Contact).order_by(Contact.created_at.desc())

        if data.destinataires in ("client", "visiteur"):
            q = q.where(Contact.type == data.destinataires)

        if data.inscrit_depuis:
            q = q.where(Contact.created_at >= data.inscrit_depuis)

        q = q.limit(data.nb_contacts)
        contacts_list = (await session.execute(q)).scalars().all()

        if not contacts_list:
            raise HTTPException(400, "Aucun contact ne correspond aux critères")

        print(f"[CATALOGUE] Mode AUTO ({data.destinataires}) — {len(contacts_list)} contacts")

    # ── Construire la liste normalisée ────────────────────
    contacts_data = [
        {
            "email":  c.email,
            "nom":    c.nom    or "",
            "prenom": c.prenom or "",
            "type":   c.type,
        }
        for c in contacts_list
    ]

    # ── Log de contrôle ───────────────────────────────────
    print(f"[CATALOGUE] Emails destinataires finaux : "
          f"{[d['email'] for d in contacts_data]}")

    # ── Envoi planifié ────────────────────────────────────
    if data.scheduled_at and data.scheduled_at > datetime.now(timezone.utc):
        cat.statut           = StatutCatalogue.PLANIFIE
        cat.scheduled_at     = data.scheduled_at
        cat.destinataires    = data.destinataires
        cat.tracking_enabled = data.tracking_enabled
        await session.commit()
        await session.refresh(cat)
        return cat

    # ── Envoi immédiat en arrière-plan ────────────────────
    from app.services.catalogue_send_service import send_catalogue
    from app.db.session import AsyncSessionLocal

    cat.destinataires    = data.destinataires if not data.contact_ids else "manuel"
    cat.tracking_enabled = data.tracking_enabled
    await session.commit()
    await session.refresh(cat)

    async def _run():
        async with AsyncSessionLocal() as bg_session:
            await send_catalogue(
                catalogue_id = catalogue_id,
                contacts     = contacts_data,
                session      = bg_session,
            )

    background_tasks.add_task(_run)
    return cat


# ══════════════════════════════════════════════════════════
#  LOGS D'ENVOI — Historique par catalogue
# ══════════════════════════════════════════════════════════

@router.get("/{catalogue_id}/logs", response_model=list[SendLogResponse])
async def get_send_logs(
    catalogue_id: int,
    statut: Optional[str] = Query(None, description="pending | sent | failed"),
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")

    q = select(SendLog).where(SendLog.catalogue_id == catalogue_id).order_by(SendLog.created_at.desc())
    if statut:
        q = q.where(SendLog.statut == statut)

    logs = (await session.execute(q)).scalars().all()
    return logs


# ══════════════════════════════════════════════════════════
#  TRACKING — Ouvertures & Clics
# ══════════════════════════════════════════════════════════

@router.get("/track/open/{log_id}", include_in_schema=False)
async def track_open(
    log_id: int,
    session: AsyncSession = Depends(get_db),
):
    """Pixel transparent 1×1 — enregistre l'ouverture."""
    log = await session.get(SendLog, log_id)
    if log and not log.opened_at:
        log.opened_at = datetime.now(timezone.utc)
        await session.commit()

    gif = (
        b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
        b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00'
        b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
    )
    return Response(
        content     = gif,
        media_type  = "image/gif",
        headers     = {
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma":        "no-cache",
        },
    )


@router.get("/track/click/{log_id}", include_in_schema=False)
async def track_click(
    log_id: int,
    url:    str = Query(...),
    session: AsyncSession = Depends(get_db),
):
    """Enregistre le clic et redirige vers l'URL cible."""
    log = await session.get(SendLog, log_id)
    if log and not log.clicked_at:
        log.clicked_at = datetime.now(timezone.utc)
        await session.commit()
    return RedirectResponse(url=url, status_code=302)


# ══════════════════════════════════════════════════════════
#  CONSULTER — Détail enrichi
# ══════════════════════════════════════════════════════════

@router.get("/{catalogue_id}/detail")
async def get_catalogue_detail(
    catalogue_id: int,
    session: AsyncSession = Depends(get_db),
    _: TokenData = Depends(require_admin),
):
    from app.models.hotel  import Hotel
    from app.models.voyage import Voyage
    from app.models.image  import Image

    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise HTTPException(404, "Catalogue introuvable")

    hotels_detail = []
    for hid in (cat.hotel_ids or []):
        h = await session.get(Hotel, hid)
        if not h:
            continue
        img = (await session.execute(
            select(Image).where(Image.id_hotel == hid, Image.type == "PRINCIPALE").limit(1)
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
        if not v:
            continue
        img = (await session.execute(
            select(Image).where(Image.id_voyage == vid, Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none()
        if not img:
            img = (await session.execute(
                select(Image).where(Image.id_voyage == vid).limit(1)
            )).scalar_one_or_none()
        voyages_detail.append({
            "id":          v.id,
            "titre":       v.titre,
            "destination": v.destination or "",
            "duree":       v.duree        or 0,
            "prix_base":   float(v.prix_base) if v.prix_base else 0,
            "image_url":   _abs_url(img.url) if img else "",
        })

    # Logs résumés
    logs = (await session.execute(
        select(SendLog)
        .where(SendLog.catalogue_id == catalogue_id)
        .order_by(SendLog.created_at.desc())
        .limit(50)
    )).scalars().all()

    logs_summary = {
        "total":   len(logs),
        "envoyes": sum(1 for l in logs if l.statut == "sent"),
        "echecs":  sum(1 for l in logs if l.statut == "failed"),
        "ouverts": sum(1 for l in logs if l.opened_at),
    }

    return {
        "id":               cat.id,
        "titre":            cat.titre,
        "description_ia":   cat.description_ia,
        "destinataires":    cat.destinataires,
        "statut":           cat.statut,
        "nb_envoyes":       cat.nb_envoyes,
        "nb_echecs":        cat.nb_echecs,
        "scheduled_at":     cat.scheduled_at,
        "tracking_enabled": cat.tracking_enabled,
        "created_at":       cat.created_at,
        "envoye_at":        cat.envoye_at,
        "hotel_ids":        cat.hotel_ids,
        "voyage_ids":       cat.voyage_ids,
        "hotels":           hotels_detail,
        "voyages":          voyages_detail,
        "logs_summary":     logs_summary,
    }


# ══════════════════════════════════════════════════════════
#  LISTER
# ══════════════════════════════════════════════════════════

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
    if cat.statut == StatutCatalogue.EN_COURS:
        raise HTTPException(409, "Impossible de supprimer un catalogue en cours d'envoi")
    await session.delete(cat)
    await session.commit()