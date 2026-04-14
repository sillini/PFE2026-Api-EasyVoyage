# app/services/catalogue_send_service.py
"""
Service d'envoi de catalogues emails — remplace complètement n8n.
Les promotions actives des hôtels sont chargées et affichées
visuellement dans l'email HTML (badge rouge + prix barré).
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, date

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalogue import Catalogue, StatutCatalogue
from app.models.send_log   import SendLog
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

MAX_RETRIES  = 3
BATCH_SIZE   = 20
BATCH_DELAY  = 2.0
RETRY_DELAYS = [30, 60, 120]
BASE_URL     = "http://localhost:8000"


# ══════════════════════════════════════════════════════════
#  POINT D'ENTRÉE PRINCIPAL
# ══════════════════════════════════════════════════════════

async def send_catalogue(
    catalogue_id: int,
    contacts: list[dict],
    session: AsyncSession,
) -> dict:
    cat = await session.get(Catalogue, catalogue_id)
    if not cat:
        raise ValueError(f"Catalogue {catalogue_id} introuvable")

    sujet, description = _parse_description_ia(cat)
    hotels_data, voyages_data = await _load_items_with_promos(cat, session)

    html_base = _build_html_email(
        titre       = cat.titre,
        sujet       = sujet,
        description = description,
        hotels      = hotels_data,
        voyages     = voyages_data,
    )

    cat.statut = StatutCatalogue.EN_COURS
    await session.commit()

    envoyes = 0
    echecs  = 0

    for i in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[i:i + BATCH_SIZE]
        for contact in batch:
            ok = await _send_to_contact(cat, contact, html_base, sujet, session)
            if ok: envoyes += 1
            else:  echecs  += 1
        if i + BATCH_SIZE < len(contacts):
            await asyncio.sleep(BATCH_DELAY)

    cat.nb_envoyes = envoyes
    cat.nb_echecs  = echecs
    cat.statut     = StatutCatalogue.ENVOYE if envoyes > 0 else StatutCatalogue.ECHOUE
    cat.envoye_at  = datetime.now(timezone.utc)
    await session.commit()

    logger.info(f"[CATALOGUE {catalogue_id}] {envoyes} envoyés, {echecs} échecs")
    return {"envoyes": envoyes, "echecs": echecs}


# ══════════════════════════════════════════════════════════
#  ENVOI UNITAIRE AVEC RETRY
# ══════════════════════════════════════════════════════════

async def _send_to_contact(cat, contact, html_base, sujet, session):
    log = SendLog(
        catalogue_id = cat.id,
        email        = contact["email"],
        nom          = contact.get("nom", ""),
        statut       = "pending",
    )
    session.add(log)
    await session.flush()

    html = _personalize(html_base, contact)
    if cat.tracking_enabled:
        pixel = (
            f'<img src="{BASE_URL}/api/v1/track/open/{log.id}" '
            f'width="1" height="1" style="display:none!important" alt="" />'
        )
        html = html.replace("</body>", f"{pixel}</body>")

    for attempt in range(MAX_RETRIES):
        try:
            await send_email(contact["email"], sujet, html)
            log.statut  = "sent"
            log.sent_at = datetime.now(timezone.utc)
            await session.flush()
            return True
        except Exception as exc:
            log.retry_count = attempt + 1
            log.error_msg   = str(exc)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAYS[attempt])

    log.statut = "failed"
    await session.flush()
    return False


# ══════════════════════════════════════════════════════════
#  CHARGEMENT ENRICHI DES HÔTELS + PROMOTIONS
# ══════════════════════════════════════════════════════════

async def _load_items_with_promos(cat: Catalogue, session: AsyncSession):
    """
    Charge hôtels ET voyages avec :
      - images
      - prix minimum par chambre (tarifs actifs aujourd'hui)
      - promotion active (titre, %, prix promo calculé, date fin)
    """
    from app.models.hotel   import Hotel, Chambre, Tarif
    from app.models.voyage  import Voyage
    from app.models.image   import Image
    from app.services.promotion_service import (
        get_promotions_actives_multi_hotels,
        calculer_prix_promo,
    )

    today = date.today()

    # ── Prix min par hôtel (une requête) ──────────────────
    hotel_ids = cat.hotel_ids or []
    prix_by_hotel: dict = {}
    if hotel_ids:
        rows = (await session.execute(
            select(Chambre.id_hotel, func.min(Tarif.prix).label("pmin"))
            .join(Tarif, Tarif.id_chambre == Chambre.id)
            .where(
                Chambre.id_hotel.in_(hotel_ids),
                Chambre.actif    == True,
                Tarif.date_debut <= today,
                Tarif.date_fin   >= today,
            )
            .group_by(Chambre.id_hotel)
        )).all()
        prix_by_hotel = {r.id_hotel: float(r.pmin) for r in rows}

    # ── Promotions actives (une requête) ──────────────────
    promos_by_hotel: dict = {}
    if hotel_ids:
        promos_by_hotel = await get_promotions_actives_multi_hotels(hotel_ids, session)

    # ── Hôtels enrichis ───────────────────────────────────
    hotels = []
    for hid in hotel_ids:
        h = await session.get(Hotel, hid)
        if not h:
            continue

        img = (await session.execute(
            select(Image).where(Image.id_hotel == hid, Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none() or (await session.execute(
            select(Image).where(Image.id_hotel == hid).limit(1)
        )).scalar_one_or_none()

        prix_min = prix_by_hotel.get(hid)
        promo    = promos_by_hotel.get(hid)

        # Données promotion sécurisées
        promo_data = None
        if promo is not None and prix_min:
            try:
                pct         = float(promo.pourcentage)
                prix_promo  = calculer_prix_promo(prix_min, pct)
                raw_type    = promo.type_promotion
                type_val    = raw_type.value if hasattr(raw_type, "value") else str(raw_type)
                type_emoji  = {"STANDARD": "🎁", "EARLY_BOOKING": "⏰", "LAST_MINUTE": "⚡"}.get(type_val, "🔥")
                date_fin_str = promo.date_fin.strftime("%d/%m/%Y") if promo.date_fin else None
                promo_data  = {
                    "titre":      promo.titre or "Offre spéciale",
                    "pct":        pct,
                    "prix_avant": prix_min,
                    "prix_apres": prix_promo,
                    "type_emoji": type_emoji,
                    "date_fin":   date_fin_str,
                }
            except Exception as e:
                logger.warning(f"[CATALOGUE] Promo hôtel {hid} ignorée: {e}")

        hotels.append({
            "nom":         h.nom,
            "ville":       h.ville         or "Tunisie",
            "etoiles":     h.etoiles        or 0,
            "description": (h.description  or "")[:200],
            "note":        float(h.note_moyenne) if h.note_moyenne else 0,
            "image_url":   _abs_url(img.url) if img else "",
            "prix_min":    prix_min,
            "promo":       promo_data,   # None si pas de promo
        })

    # ── Voyages ───────────────────────────────────────────
    voyages = []
    for vid in (cat.voyage_ids or []):
        v = await session.get(Voyage, vid)
        if not v:
            continue
        img = (await session.execute(
            select(Image).where(Image.id_voyage == vid, Image.type == "PRINCIPALE").limit(1)
        )).scalar_one_or_none() or (await session.execute(
            select(Image).where(Image.id_voyage == vid).limit(1)
        )).scalar_one_or_none()
        voyages.append({
            "titre":       v.titre,
            "destination": v.destination or "",
            "duree":       v.duree        or 0,
            "prix_base":   float(v.prix_base) if v.prix_base else 0,
            "date_depart": str(v.date_depart),
            "places":      max(0, v.capacite_max - v.nb_inscrits),
            "image_url":   _abs_url(img.url) if img else "",
        })

    return hotels, voyages


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _parse_description_ia(cat):
    try:
        p = json.loads(cat.description_ia or "{}")
        return p.get("sujet", cat.titre), p.get("description", "")
    except Exception:
        return cat.titre, ""


def _abs_url(url):
    if not url: return ""
    return url if url.startswith("http") else f"{BASE_URL}/{url.lstrip('/')}"


def _personalize(html, contact):
    prenom = contact.get("prenom") or ""
    nom    = contact.get("nom")    or ""
    return (
        html
        .replace("{{PRENOM}}", prenom)
        .replace("{{NOM}}", nom)
        .replace("{{EMAIL}}", contact.get("email", ""))
        .replace("{{PRENOM_NOM}}", f"{prenom} {nom}".strip() or contact.get("email", ""))
    )


# ══════════════════════════════════════════════════════════
#  GÉNÉRATEUR HTML — avec bloc promo visuel
# ══════════════════════════════════════════════════════════

def _build_html_email(titre, sujet, description, hotels, voyages):

    def _stars(n):
        return "★" * n + "☆" * (5 - n)

    def _hotel_block(h):
        img_tag = ""
        if h.get("image_url"):
            img_tag = f"""
            <tr><td style="padding:0;position:relative;">
              <img src="{h['image_url']}" alt="{h['nom']}"
                   width="560" style="width:100%;max-width:560px;height:210px;object-fit:cover;display:block"/>
            </td></tr>"""

        # ── Badge promo flottant sur l'image ─────────────
        promo_overlay = ""
        if h.get("promo"):
            p = h["promo"]
            promo_overlay = f"""
            <tr><td style="padding:0;">
              <div style="background:#E8392A;color:#fff;padding:8px 16px;
                          font-size:13px;font-weight:800;text-align:center;
                          letter-spacing:0.3px;">
                {p['type_emoji']} OFFRE LIMITÉE &nbsp;·&nbsp;
                <span style="font-size:18px;font-weight:900;">-{int(p['pct'])}%</span>
                &nbsp;·&nbsp; {p['titre']}
                {f"&nbsp;·&nbsp; jusqu'au {p['date_fin']}" if p.get('date_fin') else ""}
              </div>
            </td></tr>"""

        # ── Prix normal ou barré + promo ──────────────────
        prix_html = ""
        if h.get("promo") and h.get("prix_min"):
            p = h["promo"]
            prix_html = f"""
              <div style="display:flex;align-items:center;gap:10px;margin:10px 0 16px;">
                <span style="font-size:13px;color:#94A3B8;text-decoration:line-through;
                             text-decoration-color:#E8392A;">
                  {int(p['prix_avant'])} DT/nuit
                </span>
                <span style="font-size:22px;font-weight:900;color:#E8392A;">
                  {int(p['prix_apres'])} DT/nuit
                </span>
                <span style="background:#FEE2E2;color:#991B1B;font-size:11px;font-weight:800;
                             padding:3px 8px;border-radius:20px;">
                  -{int(p['pct'])}% de réduction
                </span>
              </div>"""
        elif h.get("prix_min"):
            prix_html = f"""
              <div style="margin:10px 0 16px;">
                <span style="font-size:18px;font-weight:800;color:#0F2235;">
                  À partir de {int(h['prix_min'])} DT/nuit
                </span>
              </div>"""

        desc_html = ""
        if h.get("description"):
            desc_html = f'<p style="font-size:13px;color:#4A5568;line-height:1.6;margin:0 0 14px;">{h["description"]}</p>'

        note_html = ""
        if h.get("note", 0) > 0:
            note_html = f'<span style="color:#27AE60;font-weight:700;font-size:12px;">⭐ {h["note"]:.1f}/5</span>'

        return f"""
        <tr><td style="padding:0 0 28px 0;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid #E4ECF5;border-radius:12px;
                        overflow:hidden;background:#fff;
                        box-shadow:0 2px 12px rgba(0,0,0,.06);">
            {img_tag}
            {promo_overlay}
            <tr><td style="padding:20px 24px;">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px;">
                <div style="font-size:20px;font-weight:800;color:#0F2235;">{h['nom']}</div>
                {note_html}
              </div>
              <div style="font-size:12px;color:#C4973A;margin-bottom:10px;">
                {_stars(h['etoiles'])}
                <span style="color:#8A9BB0;margin-left:6px;">📍 {h['ville']}</span>
              </div>
              {prix_html}
              {desc_html}
              <a href="https://easyvoyage.tn"
                 style="display:inline-block;background:#C4973A;color:#fff;
                        text-decoration:none;padding:10px 24px;border-radius:8px;
                        font-size:13px;font-weight:700;">
                Réserver maintenant →
              </a>
            </td></tr>
          </table>
        </td></tr>"""

    def _voyage_block(v):
        img_tag = ""
        if v.get("image_url"):
            img_tag = f"""
            <tr><td style="padding:0">
              <img src="{v['image_url']}" alt="{v['titre']}"
                   width="560" style="width:100%;max-width:560px;height:200px;object-fit:cover;display:block"/>
            </td></tr>"""

        places_badge = ""
        if 0 < v.get("places", 999) <= 5:
            places_badge = f"""<span style="background:#FEECEC;color:#C0392B;font-size:11px;
                font-weight:700;padding:3px 10px;border-radius:20px;margin-left:8px;">
                🔥 {v['places']} place{'s' if v['places']>1 else ''} restante{'s' if v['places']>1 else ''}</span>"""

        return f"""
        <tr><td style="padding:0 0 24px 0;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid #E4ECF5;border-radius:12px;overflow:hidden;background:#fff;
                        box-shadow:0 2px 12px rgba(0,0,0,.06);">
            {img_tag}
            <tr><td style="padding:20px 24px;">
              <div style="font-size:20px;font-weight:800;color:#0F2235;margin-bottom:6px;">
                {v['titre']}
              </div>
              <div style="font-size:12px;color:#8A9BB0;margin-bottom:12px;">
                ✈️ {v['destination']} &nbsp;·&nbsp; 🗓 {v['duree']} jours
                &nbsp;·&nbsp; Départ le {v['date_depart']}
                {places_badge}
              </div>
              <div style="font-size:22px;font-weight:900;color:#C4973A;margin-bottom:16px;">
                À partir de <span>{int(v['prix_base'])} DT</span>/personne
              </div>
              <a href="https://easyvoyage.tn"
                 style="display:inline-block;background:#0F2235;color:#fff;
                        text-decoration:none;padding:10px 24px;border-radius:8px;
                        font-size:13px;font-weight:700;">
                Réserver →
              </a>
            </td></tr>
          </table>
        </td></tr>"""

    hotels_html  = "".join(_hotel_block(h)  for h in hotels)
    voyages_html = "".join(_voyage_block(v) for v in voyages)

    # ── Bandeau global promos (si au moins 1 hôtel en promo) ──
    hotels_en_promo = [h for h in hotels if h.get("promo")]
    promo_banner = ""
    if hotels_en_promo:
        noms = " · ".join(h["nom"] for h in hotels_en_promo)
        pcts = " / ".join(f"-{int(h['promo']['pct'])}%" for h in hotels_en_promo)
        promo_banner = f"""
      <!-- BANDEAU PROMO GLOBAL -->
      <tr><td style="background:linear-gradient(135deg,#E8392A,#C0392B);
                     padding:14px 40px;text-align:center;">
        <div style="font-size:13px;font-weight:800;color:#fff;letter-spacing:0.3px;">
          🔥 PROMOTIONS ACTIVES : {pcts} sur {noms}
        </div>
        <div style="font-size:11px;color:rgba(255,255,255,.8);margin-top:4px;">
          Offres à durée limitée — Réservez maintenant !
        </div>
      </td></tr>"""

    section_hotels = f"""
    <tr><td style="padding:0 0 8px;">
      <div style="font-size:16px;font-weight:800;color:#0F2235;margin-bottom:16px;">
        🏨 Nos hôtels sélectionnés
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{hotels_html}</table>
    </td></tr>""" if hotels else ""

    section_voyages = f"""
    <tr><td style="padding:0 0 8px;">
      <div style="font-size:16px;font-weight:800;color:#0F2235;margin-bottom:16px;">
        ✈️ Nos voyages du moment
      </div>
      <table width="100%" cellpadding="0" cellspacing="0">{voyages_html}</table>
    </td></tr>""" if voyages else ""

    desc_block = ""
    if description:
        desc_block = f"""
        <tr><td style="padding:0 0 24px;">
          <p style="font-size:14px;color:#4A5568;line-height:1.7;margin:0;">{description}</p>
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{sujet}</title>
</head>
<body style="margin:0;padding:0;background:#F4F6F8;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F4F6F8;">
  <tr><td align="center" style="padding:32px 16px;">
    <table width="600" cellpadding="0" cellspacing="0"
           style="max-width:600px;width:100%;background:#fff;
                  border-radius:16px;overflow:hidden;
                  box-shadow:0 4px 24px rgba(0,0,0,.08);">

      <!-- EN-TÊTE -->
      <tr><td style="background:#0F2235;padding:28px 40px;text-align:center;">
        <h1 style="color:#fff;font-size:28px;margin:0;letter-spacing:1px;">EasyVoyage</h1>
        <p style="color:rgba(255,255,255,.55);font-size:11px;margin:6px 0 0;
                  text-transform:uppercase;letter-spacing:2px;">
          Catalogues & Offres exclusives
        </p>
      </td></tr>

      <!-- TITRE -->
      <tr><td style="background:linear-gradient(135deg,#C4973A,#E8B84B);
                     padding:18px 40px;text-align:center;">
        <p style="color:#fff;font-size:20px;font-weight:800;margin:0;">{titre}</p>
      </td></tr>

      {promo_banner}

      <!-- CORPS -->
      <tr><td style="padding:32px 40px;">
        <table width="100%" cellpadding="0" cellspacing="0">

          <!-- Salutation -->
          <tr><td style="padding:0 0 18px;">
            <p style="font-size:15px;color:#0F2235;font-weight:700;margin:0;">
              Bonjour {{{{PRENOM_NOM}}}} 👋
            </p>
          </td></tr>

          {desc_block}
          {section_hotels}
          {section_voyages}

          <!-- CTA -->
          <tr><td style="padding:8px 0 0;text-align:center;">
            <a href="https://easyvoyage.tn"
               style="display:inline-block;background:#C4973A;color:#fff;
                      text-decoration:none;padding:15px 40px;border-radius:10px;
                      font-size:15px;font-weight:800;">
              Voir toutes nos offres →
            </a>
          </td></tr>

        </table>
      </td></tr>

      <!-- PIED DE PAGE -->
      <tr><td style="background:#F8FAFC;padding:18px 40px;text-align:center;
                     border-top:1px solid #EEF2F7;">
        <p style="color:#B0BEC8;font-size:11px;margin:0 0 6px;">
          EasyVoyage — Votre partenaire de voyage en Tunisie
        </p>
        <p style="color:#C8D0DA;font-size:10px;margin:0;">
          <a href="https://easyvoyage.tn/unsubscribe?email={{{{EMAIL}}}}"
             style="color:#B0BEC8;">Se désabonner</a>
        </p>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""