# app/services/video_campaign_claude_service.py
"""
Service Claude AI — génération contenu marketing d'une campagne vidéo VOYAGE.

Fonctionnement :
  1. Charge les vraies données du voyage depuis la BDD (titre, destination, durée, prix...)
  2. Claude génère : sujet email, description marketing, CTA, hashtags, script vidéo,
     prompt Replicate optimisé pour la destination réelle, variantes A/B
"""
import json
import logging
import os
from typing import Optional

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

logger = logging.getLogger(__name__)
CLAUDE_MODEL = "claude-opus-4-6"


def _claude_client() -> anthropic.AsyncAnthropic:
    """Même pattern que catalogue.py."""
    api_key = settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY manquant — ajoutez-le dans .env")
    return anthropic.AsyncAnthropic(api_key=api_key)


async def _charger_voyage(voyage_id: int, session: AsyncSession) -> Optional[dict]:
    """Charge les données réelles du voyage depuis la BDD."""
    try:
        from sqlalchemy import select
        from app.models.voyage import Voyage

        voyage = (await session.execute(
            select(Voyage).where(Voyage.id == voyage_id)
        )).scalar_one_or_none()

        if not voyage:
            return None

        places_restantes = max(0, voyage.capacite_max - (voyage.nb_inscrits or 0))

        return {
            "id":               voyage.id,
            "titre":            voyage.titre,
            "description":      voyage.description or "",
            "destination":      voyage.destination,
            "duree":            voyage.duree,
            "prix_base":        float(voyage.prix_base),
            "date_depart":      str(voyage.date_depart),
            "date_retour":      str(voyage.date_retour),
            "capacite_max":     voyage.capacite_max,
            "places_restantes": places_restantes,
        }
    except Exception as e:
        logger.warning(f"[CLAUDE] Erreur chargement voyage #{voyage_id} : {e}")
        return None

# Correction de la fonction _build_prompt dans video_campaign_claude_service.py
# Remplacer l'ancienne fonction _build_prompt par celle-ci :

def _build_prompt(
    destination: str,
    ton: str,
    segment: str,
    voyage_info: Optional[dict],
) -> str:
    """Construit le prompt Claude avec les vraies données du voyage."""

    ton_desc = {
        "LUXE":       "élégant, exclusif, premium, vocabulaire sophistiqué",
        "AVENTURE":   "dynamique, excitant, audacieux, verbes d'action",
        "FAMILLE":    "chaleureux, rassurant, joyeux, inclusif",
        "ROMANTIQUE": "poétique, évocateur, émotionnel",
        "AFFAIRES":   "professionnel, efficace, confort",
    }.get(ton, "universel")

    segment_note = {
        "client":   "CLIENT fidèle — ton chaleureux, valoriser la fidélité.",
        "visiteur": "VISITEUR non-converti — accentuer le prix et créer l'urgence.",
        "tous":     "Public mixte — équilibre émotion et prix.",
    }.get(segment, "")

    # ── Bloc voyage avec les vraies données ──────────────
    voyage_bloc = ""
    if voyage_info:
        v = voyage_info
        urgence = ""
        if v["places_restantes"] <= 5 and v["places_restantes"] > 0:
            urgence = f"\n⚠️ URGENCE : seulement {v['places_restantes']} place(s) restante(s) !"
        elif v["places_restantes"] == 0:
            urgence = "\n⚠️ COMPLET — ne pas promouvoir ce voyage."

        voyage_bloc = (
            f"\nDONNÉES RÉELLES DU VOYAGE :\n"
            f"  Titre       : {v['titre']}\n"
            f"  Destination : {v['destination']}\n"
            f"  Description : {v['description'] or 'Non renseignée'}\n"
            f"  Durée       : {v['duree']} jours\n"
            f"  Prix/pers.  : {v['prix_base']} DT\n"
            f"  Départ      : {v['date_depart']}\n"
            f"  Retour      : {v['date_retour']}\n"
            f"  Places rest.: {v['places_restantes']}\n"
            f"{urgence}"
        )

    # ── Description géographique pour le prompt Replicate ─
    geo_hints = {
        "djerba":    "Djerba island Tunisia, white-washed buildings, turquoise Mediterranean sea, palm trees, traditional medina",
        "sousse":    "Sousse Tunisia, historic medina UNESCO, golden sandy beach, ribat fortress by the sea",
        "tunis":     "Tunis Tunisia capital, grand Zitouna mosque, vibrant medina souks, Carthage ruins by the sea",
        "hammamet":  "Hammamet Tunisia, pristine white sandy beach resort, jasmine gardens, medieval medina kasbah",
        "monastir":  "Monastir Tunisia, iconic ribat fortress on the sea, white medina streets, palm-lined marina",
        "douz":      "Douz Tunisia gateway to Sahara, endless golden sand dunes at sunset, camel caravan silhouette",
        "tozeur":    "Tozeur Tunisia, lush date palm oasis in the desert, traditional brick architecture, salt lake",
        "tabarka":   "Tabarka Tunisia, dramatic rocky coastline, ancient Genoese fortress, clear turquoise sea",
        "kairouan":  "Kairouan Tunisia, majestic Great Mosque UNESCO, historic medina carpet souks, ancient city walls",
        "sfax":      "Sfax Tunisia, historic medina ramparts, traditional olive groves, authentic southern port city",
        "nabeul":    "Nabeul Tunisia Cap Bon, colorful pottery workshops, jasmine fields, white sandy beach",
        "bizerte":   "Bizerte Tunisia, ancient Kasbah fort, picturesque fishing harbor, lagoon meeting the sea",
        "matmata":   "Matmata Tunisia, unique troglodyte underground cave dwellings, Berber architecture, rocky desert",
        "gabès":     "Gabes Tunisia, coastal oasis city, palm tree forest by the sea, traditional market",
    }

    dest_lower = destination.lower()
    geo_desc = next(
        (v for k, v in geo_hints.items() if k in dest_lower),
        f"{destination} Tunisia, authentic travel destination, beautiful landscapes, Mediterranean atmosphere"
    )

    # ── Style caméra selon le ton — résolu AVANT la f-string ──
    camera_style = {
        "LUXE":       "golden hour luxury, slow cinematic dolly shot",
        "AVENTURE":   "dramatic vibrant colors, dynamic tracking shot",
        "FAMILLE":    "warm sunny atmosphere, smooth gentle pan",
        "ROMANTIQUE": "sunset romantic light, soft gentle zoom",
        "AFFAIRES":   "clean professional steady shot, elegant",
    }.get(ton, "cinematic travel shot")

    # ── Exemple de replicate_prompt déjà résolu ───────────
    replicate_prompt_example = (
        f"Cinematic travel video of {geo_desc}, "
        f"{camera_style}, "
        "6 seconds, high quality travel advertisement, "
        "no text overlay, no people faces, ultra HD"
    )

    return (
        "Tu es expert marketing touristique pour EasyVoyage Tunisie.\n"
        "Réponds UNIQUEMENT avec du JSON valide, sans backticks ni markdown.\n\n"
        f"DESTINATION : {destination}\n"
        f"TON         : {ton} ({ton_desc})\n"
        f"SEGMENT     : {segment_note}\n"
        f"{voyage_bloc}\n\n"
        "Génère le contenu marketing dans ce JSON exact :\n"
        "{\n"
        '  "sujet_email": "sujet accrocheur max 70 caractères, emoji possible",\n'
        '  "description_marketing": "3-4 phrases premium basées sur les VRAIES données du voyage. Mentionne la destination, la durée, le prix réel en DT.",\n'
        '  "cta_texte": "Texte bouton max 30 caractères",\n'
        '  "hashtags": "#EasyVoyage #Tunisie #Travel et 5 autres hashtags pertinents",\n'
        '  "script_video": {\n'
        '    "scene_1": {"duree": "2s", "visuel": "Vue aérienne ou panoramique de la destination réelle", "voix_off": "max 12 mots accrocheurs"},\n'
        '    "scene_2": {"duree": "2s", "visuel": "Attraction principale ou paysage emblématique", "voix_off": "max 12 mots"},\n'
        '    "scene_3": {"duree": "1s", "visuel": "Prix et durée du voyage en gros plan", "voix_off": "Prix et durée en 8 mots max"},\n'
        '    "scene_4": {"duree": "1s", "visuel": "Logo EasyVoyage sur fond destination", "voix_off": "EasyVoyage — Réservez maintenant"}\n'
        "  },\n"
        # ← CORRECTION : f-string avec variable pré-résolue, sans dict.get() imbriqué
        f'  "replicate_prompt": "{replicate_prompt_example}",\n'
        '  "ab_variante_sujet": "Sujet email alternatif, angle marketing différent",\n'
        '  "ab_variante_cta": "CTA alternatif différent"\n'
        "}\n\n"
        "RÈGLES IMPORTANTES :\n"
        "- description_marketing : VRAIES données (destination, durée, prix réel en DT)\n"
        "- replicate_prompt : améliore le prompt fourni en exemple, reste en ANGLAIS\n"
        "- Si urgence places → intègre-la dans description_marketing et cta_texte\n"
        "- Tout en français sauf replicate_prompt\n"
        "- NE RECOPIE PAS les exemples tels quels, génère du contenu RÉEL"
    )
async def generer_contenu(
    destination: str,
    ton: str,
    segment: str,
    voyage_id: Optional[int] = None,
    session: Optional[AsyncSession] = None,
    # Paramètres legacy ignorés (hotel_info, voyage_info dict)
    hotel_info: Optional[dict] = None,
    voyage_info: Optional[dict] = None,
) -> dict:
    """
    Génère le contenu marketing complet via Claude.
    Charge automatiquement les données du voyage depuis la BDD si voyage_id fourni.
    """
    # Charger les vraies données du voyage
    voyage_data = None
    if voyage_id and session:
        voyage_data = await _charger_voyage(voyage_id, session)
        if voyage_data:
            logger.info(
                f"[CLAUDE] Voyage #{voyage_id} chargé : "
                f"'{voyage_data['titre']}' → {voyage_data['destination']}"
            )
        else:
            logger.warning(f"[CLAUDE] Voyage #{voyage_id} introuvable en BDD")
    elif voyage_info:
        # Compatibilité avec l'ancien format dict
        voyage_data = voyage_info

    # Utiliser la destination réelle du voyage si disponible
    dest_effective = voyage_data["destination"] if voyage_data else destination

    claude  = _claude_client()
    prompt  = _build_prompt(dest_effective, ton, segment, voyage_data)

    logger.info(f"[CLAUDE] Génération pour '{dest_effective}' ton={ton} voyage_id={voyage_id}")

    msg = await claude.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw     = msg.content[0].text.strip()
    cleaned = raw.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"[CLAUDE] JSON invalide : {e} | début={raw[:300]}")
        raise ValueError(f"Réponse Claude non-parseable : {e}")

    logger.info(f"[CLAUDE] ✅ Contenu généré pour '{dest_effective}'")

    return {
        "sujet_email":           parsed.get("sujet_email",           f"Découvrez {dest_effective}"),
        "description_marketing": parsed.get("description_marketing", ""),
        "cta_texte":             parsed.get("cta_texte",             "Réserver maintenant"),
        "hashtags":              parsed.get("hashtags",              "#EasyVoyage #Tunisie"),
        "script_video":          _format_script(parsed.get("script_video", {})),
        "prompts_images":        [parsed.get("replicate_prompt", "")]
                                 if parsed.get("replicate_prompt") else [],
        "ab_variante_sujet":     parsed.get("ab_variante_sujet",     ""),
        "ab_variante_cta":       parsed.get("ab_variante_cta",       ""),
    }


def _format_script(script_raw: dict) -> str:
    if not script_raw:
        return ""
    lines = []
    for k, s in script_raw.items():
        num = k.replace("scene_", "Scène ")
        lines.append(f"[{num} — {s.get('duree', '')}]")
        lines.append(f"  Visuel   : {s.get('visuel', '')}")
        lines.append(f"  Voix off : {s.get('voix_off', '')}")
        lines.append("")
    return "\n".join(lines)