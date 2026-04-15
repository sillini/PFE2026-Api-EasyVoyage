# app/services/video_campaign_replicate_service.py
"""
Service Replicate — génération vidéo via minimax/video-01 (Hailuo).

Le prompt vidéo est généré par Claude et décrit la destination réelle du voyage.
Aucune image utilisateur n'est utilisée — text-to-video pur.

Modèle   : minimax/video-01
Endpoint : POST /v1/models/minimax/video-01/predictions
Output   : vidéo MP4, 6 secondes, 720p, 25fps
Free tier: oui (runs limités, ajouter carte pour plus)
"""
import asyncio
import logging
import os
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

REPLICATE_API_URL = "https://api.replicate.com/v1"
POLL_INTERVAL     = 5    # secondes entre chaque vérification
POLL_TIMEOUT      = 600  # 10 minutes max (minimax prend 2-6 min)


def _get_api_key() -> str:
    """Même pattern que anthropic_api_key — minuscules."""
    key = getattr(settings, "replicate_api_key", "") or os.getenv("REPLICATE_API_KEY", "")
    if not key:
        raise ValueError("REPLICATE_API_KEY manquant — ajoutez-le dans .env")
    return key


def _headers() -> dict:
    return {
        "Authorization": f"Token {_get_api_key()}",
        "Content-Type":  "application/json",
    }


# ══════════════════════════════════════════════════════════
#  GÉNÉRATION VIDÉO — minimax/video-01
# ══════════════════════════════════════════════════════════

async def generer_video_minimax(prompt: str) -> Optional[str]:
    """
    Génère une vidéo 6s text-to-video via minimax/video-01.
    
    Args:
        prompt : Description anglaise du lieu — généré par Claude
    
    Returns:
        URL MP4 ou None si échec
    """
    payload = {
        "input": {
            "prompt":           prompt,
            "prompt_optimizer": True,   # Replicate améliore le prompt automatiquement
        }
    }

    logger.info(f"[MINIMAX] Création prédiction | prompt={prompt[:100]}...")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{REPLICATE_API_URL}/models/minimax/video-01/predictions",
            json=payload,
            headers=_headers(),
        )

        if resp.status_code not in (200, 201):
            logger.error(f"[MINIMAX] HTTP {resp.status_code} : {resp.text[:400]}")
            return None

        data    = resp.json()
        pred_id = data.get("id")
        status  = data.get("status", "")

        if not pred_id:
            logger.error(f"[MINIMAX] Pas d'id dans la réponse : {data}")
            return None

        logger.info(f"[MINIMAX] Prédiction créée : {pred_id} (statut initial={status})")

        # Réponse immédiate
        if status == "succeeded":
            url = _extract_url(data)
            logger.info(f"[MINIMAX] ✅ Vidéo immédiate : {url}")
            return url

        # Polling
        return await _poll(pred_id, client)


# ══════════════════════════════════════════════════════════
#  PIPELINE — appelé par video_campaign_service
# ══════════════════════════════════════════════════════════

async def generer_campagne_media(
    prompts_images: list,
    formats: list,
    destination: str,
    ton: str = "LUXE",
    hotel_id: Optional[int] = None,    # ignoré (voyages uniquement)
    voyage_id: Optional[int] = None,   # info seulement, pas utilisé ici
    session=None,                       # ignoré
) -> dict:
    """
    Génère la vidéo marketing via minimax/video-01 (text-to-video).

    Le prompt vient de Claude (stocké dans prompts_images[0]).
    Si absent, construit un prompt de fallback basé sur la destination.
    Aucune image utilisateur n'est nécessaire.
    """
    # ── Récupérer le prompt Replicate généré par Claude ───
    if prompts_images and prompts_images[0]:
        prompt = prompts_images[0]
        logger.info(f"[MINIMAX] Prompt Claude utilisé : {prompt[:100]}...")
    else:
        # Fallback si Claude n'a pas généré de prompt
        prompt = _fallback_prompt(destination, ton)
        logger.info(f"[MINIMAX] Prompt fallback pour '{destination}'")

    # ── Générer la vidéo ──────────────────────────────────
    video_url = await generer_video_minimax(prompt)

    if not video_url:
        raise ValueError(
            "La génération vidéo minimax/video-01 a échoué. "
            "Vérifiez votre REPLICATE_API_KEY et votre crédit Replicate "
            "(https://replicate.com/account/billing)."
        )

    logger.info(f"[MINIMAX] ✅ Vidéo générée pour '{destination}' : {video_url}")

    # Même URL pour tous les formats (minimax génère en 16:9 par défaut)
    return {
        "video_url_landscape": video_url,
        "video_url_portrait":  video_url,
        "video_url_square":    video_url,
        "thumbnail_url":       video_url,   # le frontend extraira la frame
        "images_urls":         [video_url],
    }


# ══════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════

def _fallback_prompt(destination: str, ton: str) -> str:
    """
    Prompt de secours si Claude n'a pas généré de replicate_prompt.
    Décrit la destination géographique tunisienne de façon cinématographique.
    """
    dest_lower = destination.lower()

    # Descriptions géographiques par destination tunisienne
    geo = {
        "djerba":     "Djerba island Tunisia, white and blue architecture, clear turquoise Mediterranean sea, traditional fishing boats, palm trees along the coast, Houmt Souk market",
        "sousse":     "Sousse Tunisia, ancient medina with UNESCO heritage, golden sandy beach, historic ribat fortress by the sea, traditional Andalusian architecture",
        "tunis":      "Tunis Tunisia capital city, grand Zitouna mosque, vibrant medina souks, Bardo national museum, Carthage archaeological ruins by the sea, modern city skyline",
        "hammamet":   "Hammamet Tunisia, pristine white sandy beach resort, jasmine flower gardens, medieval medina kasbah, clear blue Mediterranean waters, coastal luxury resort",
        "monastir":   "Monastir Tunisia, iconic ribat fortress on the sea, white medina streets, palm-lined marina, beautiful mosque, sunny Mediterranean coastline",
        "douz":       "Douz Tunisia gateway to the Sahara desert, endless golden sand dunes at sunset, traditional Bedouin tents, camel caravan silhouette, dramatic desert sky",
        "tozeur":     "Tozeur Tunisia, lush date palm oasis in the desert, traditional chequered brick architecture, salt lake Chott el-Jerid, dramatic desert landscape at golden hour",
        "tabarka":    "Tabarka Tunisia, dramatic rocky coastline, ancient Genoese fortress on rocky island, clear turquoise sea, green pine forest hills, coral reef waters",
        "kairouan":   "Kairouan Tunisia, majestic Great Mosque UNESCO site, historic medina carpet souks, ancient city walls, traditional Islamic architecture, desert light",
        "sfax":       "Sfax Tunisia, historic medina ramparts, traditional olive groves, authentic Tunisian port city, traditional architecture, southern coastal panorama",
        "nabeul":     "Nabeul Tunisia Cap Bon peninsula, colorful pottery workshops, jasmine and rose fields, white sandy beach, traditional crafts market, citrus orchards",
        "bizerte":    "Bizerte Tunisia northernmost point Africa, ancient Kasbah fort, picturesque fishing harbor, medina, lagoon and sea meeting, historic old port",
        "matmata":    "Matmata Tunisia, unique troglodyte underground cave dwellings, traditional Berber architecture, dramatic desert landscape, ancient culture, rocky terrain",
        "gabès":      "Gabes Tunisia, coastal oasis city, palm tree forest by the sea, traditional market, unique geography of palm grove meeting Mediterranean",
    }

    geo_desc = next(
        (v for k, v in geo.items() if k in dest_lower),
        f"{destination} Tunisia, authentic beautiful travel destination, traditional architecture, natural landscapes, Mediterranean atmosphere"
    )

    camera_style = {
        "LUXE":       "slow cinematic dolly shot, luxury travel, golden hour warm light, high-end cinematography",
        "AVENTURE":   "dynamic tracking drone shot, vibrant saturated colors, energetic camera movement, adventure travel",
        "FAMILLE":    "smooth gentle pan, warm sunlight, welcoming atmosphere, family travel photography",
        "ROMANTIQUE": "soft gentle zoom, sunset warm colors, intimate romantic atmosphere, dreamy soft focus",
        "AFFAIRES":   "clean steady establishing shot, professional atmosphere, modern and elegant, business travel",
    }.get(ton, "cinematic travel photography, beautiful natural lighting")

    return (
        f"Cinematic travel video advertisement of {geo_desc}, "
        f"{camera_style}, "
        "6 seconds video, no text overlay, no people faces, "
        "ultra high quality, travel marketing, beautiful composition, "
        "professional color grading"
    )


async def _poll(pred_id: str, client: httpx.AsyncClient) -> Optional[str]:
    """Poll toutes les 5s jusqu'à succeeded/failed."""
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        try:
            resp = await client.get(
                f"{REPLICATE_API_URL}/predictions/{pred_id}",
                headers=_headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            data   = resp.json()
            status = data.get("status", "")

            logger.info(f"[MINIMAX] {pred_id} → {status} ({elapsed}s)")

            if status == "succeeded":
                url = _extract_url(data)
                if url:
                    logger.info(f"[MINIMAX] ✅ Succès : {url}")
                    return url
                logger.error(f"[MINIMAX] succeeded mais output vide : {data}")
                return None

            if status == "failed":
                logger.error(f"[MINIMAX] ❌ Échec : {data.get('error', 'inconnu')}")
                return None

            if status == "canceled":
                logger.warning(f"[MINIMAX] Annulée : {pred_id}")
                return None

            # starting / processing → continuer

        except httpx.TimeoutException:
            logger.warning(f"[MINIMAX] Timeout requête poll à {elapsed}s")
        except Exception as e:
            logger.error(f"[MINIMAX] Erreur poll : {type(e).__name__} — {e}")
            return None

    logger.error(f"[MINIMAX] Timeout global {POLL_TIMEOUT}s pour {pred_id}")
    return None


def _extract_url(data: dict) -> Optional[str]:
    """Extrait l'URL MP4 depuis la réponse Replicate."""
    output = data.get("output")
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, list) and output:
        first = output[0]
        if isinstance(first, str) and first.startswith("http"):
            return first
    logger.warning(f"[MINIMAX] Output inattendu : {type(output)} = {output}")
    return None