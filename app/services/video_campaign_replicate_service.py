# app/services/video_campaign_replicate_service.py — v3 FINAL
"""
Service Replicate + Cloudinary.
Preset : video_easyvoyage (Unsigned)
.env   : CLOUDINARY_VIDEO_PRESET=video_easyvoyage

IMPORTANT — Preset non-signé :
  Les paramètres autorisés sont UNIQUEMENT :
  upload_preset, public_id, folder, tags, context, metadata, source
  
  Interdits avec preset non-signé :
    - overwrite
    - resource_type  (Cloudinary le détecte automatiquement)
    - format
"""
import asyncio
import logging
import os
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

REPLICATE_API_URL = "https://api.replicate.com/v1"
CLOUDINARY_CLOUD  = "dzfznxn0q"

CLOUDINARY_VIDEO_PRESET = (
    os.getenv("CLOUDINARY_VIDEO_PRESET")
    or getattr(settings, "cloudinary_video_preset", "")
    or "video_easyvoyage"
)

POLL_INTERVAL = 5
POLL_TIMEOUT  = 600


def _replicate_key() -> str:
    key = getattr(settings, "replicate_api_key", "") or os.getenv("REPLICATE_API_KEY", "")
    if not key:
        raise ValueError("REPLICATE_API_KEY manquant")
    return key


def _replicate_headers() -> dict:
    return {
        "Authorization": f"Token {_replicate_key()}",
        "Content-Type":  "application/json",
    }


# ══════════════════════════════════════════════════════════
#  CLOUDINARY — upload binaire (preset non-signé)
# ══════════════════════════════════════════════════════════

async def _upload_cloudinary(
    client: httpx.AsyncClient,
    replicate_url: str,
    public_id: str,
) -> Optional[str]:
    """
    1. Télécharge le MP4 depuis Replicate en mémoire
    2. Upload sur Cloudinary — SANS overwrite ni resource_type
       (non autorisés avec preset non-signé)
    """
    # ── Téléchargement ────────────────────────────────────
    logger.info(f"[CLOUDINARY] Téléchargement : {replicate_url[:70]}...")
    try:
        dl = await client.get(replicate_url, follow_redirects=True, timeout=180.0)
        if dl.status_code != 200:
            logger.error(f"[CLOUDINARY] Téléchargement HTTP {dl.status_code}")
            return None
        video_bytes = dl.content
        if len(video_bytes) < 1024:
            logger.error("[CLOUDINARY] Fichier < 1Ko — URL Replicate expirée ?")
            return None
        logger.info(f"[CLOUDINARY] Téléchargé {len(video_bytes)//1024} Ko")
    except Exception as e:
        logger.error(f"[CLOUDINARY] Erreur téléchargement : {e}")
        return None

    # ── Upload ────────────────────────────────────────────
    # Avec preset non-signé : UNIQUEMENT upload_preset et public_id
    upload_url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD}/video/upload"
    logger.info(f"[CLOUDINARY] Upload → {upload_url} | preset={CLOUDINARY_VIDEO_PRESET}")

    try:
        resp = await client.post(
            upload_url,
            files={"file": (f"{public_id}.mp4", video_bytes, "video/mp4")},
            data={
                "upload_preset": CLOUDINARY_VIDEO_PRESET,
                "public_id":     public_id,
                # ← PAS de overwrite, resource_type, format
                #   (interdits avec preset non-signé)
            },
            timeout=180.0,
        )

        if resp.status_code == 200:
            url = resp.json().get("secure_url")
            if url:
                logger.info(f"[CLOUDINARY] ✅ {url[:80]}")
                return url
            logger.error(f"[CLOUDINARY] Pas de secure_url : {resp.json()}")
            return None

        try:
            err = resp.json().get("error", {}).get("message", resp.text[:200])
        except Exception:
            err = resp.text[:200]
        logger.error(f"[CLOUDINARY] HTTP {resp.status_code} : {err}")
        return None

    except Exception as e:
        logger.error(f"[CLOUDINARY] Exception upload : {e}")
        return None


# ══════════════════════════════════════════════════════════
#  REPLICATE — minimax/video-01
# ══════════════════════════════════════════════════════════

async def _generer_replicate(client: httpx.AsyncClient, prompt: str) -> Optional[str]:
    payload = {
        "input": {
            "prompt":           prompt,
            "prompt_optimizer": True,
        }
    }
    resp = await client.post(
        f"{REPLICATE_API_URL}/models/minimax/video-01/predictions",
        json=payload,
        headers=_replicate_headers(),
        timeout=60.0,
    )
    if resp.status_code not in (200, 201):
        logger.error(f"[MINIMAX] HTTP {resp.status_code} : {resp.text[:300]}")
        return None

    data    = resp.json()
    pred_id = data.get("id")
    if not pred_id:
        return None

    logger.info(f"[MINIMAX] Prédiction {pred_id}")

    if data.get("status") == "succeeded":
        return _extract_url(data)

    # Polling
    elapsed = 0
    while elapsed < POLL_TIMEOUT:
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        try:
            pr = await client.get(
                f"{REPLICATE_API_URL}/predictions/{pred_id}",
                headers=_replicate_headers(),
                timeout=30.0,
            )
            pr.raise_for_status()
            d      = pr.json()
            status = d.get("status", "")
            logger.info(f"[MINIMAX] {pred_id} → {status} ({elapsed}s)")
            if status == "succeeded":
                return _extract_url(d)
            if status in ("failed", "canceled"):
                logger.error(f"[MINIMAX] {status} : {d.get('error', '')}")
                return None
        except Exception as e:
            logger.error(f"[MINIMAX] Poll error : {e}")
            return None

    logger.error(f"[MINIMAX] Timeout {POLL_TIMEOUT}s")
    return None


# ══════════════════════════════════════════════════════════
#  PIPELINE
# ══════════════════════════════════════════════════════════

async def generer_campagne_media(
    prompts_images: list,
    formats: list,
    destination: str,
    ton: str = "LUXE",
    hotel_id: Optional[int] = None,
    voyage_id: Optional[int] = None,
    session=None,
) -> dict:
    base_prompt = (
        prompts_images[0]
        if prompts_images and prompts_images[0]
        else _fallback_prompt(destination, ton)
    )

    safe = destination.lower().replace(" ", "_").replace(",", "")[:25]

    tasks_def = {}
    if not formats or "LANDSCAPE" in formats:
        tasks_def["LANDSCAPE"] = (base_prompt, f"vc_{safe}_landscape")
    if "PORTRAIT" in formats:
        tasks_def["PORTRAIT"]  = (
            base_prompt + ", vertical 9:16 portrait, mobile",
            f"vc_{safe}_portrait",
        )
    if "SQUARE" in formats:
        tasks_def["SQUARE"]    = (
            base_prompt + ", square 1:1 format, social media",
            f"vc_{safe}_square",
        )

    logger.info(
        f"[PIPELINE] '{destination}' | formats={list(tasks_def.keys())} | "
        f"preset={CLOUDINARY_VIDEO_PRESET}"
    )

    result = {
        "video_url_landscape": None,
        "video_url_portrait":  None,
        "video_url_square":    None,
        "thumbnail_url":       None,
        "images_urls":         [],
    }

    async with httpx.AsyncClient(timeout=300.0) as client:

        async def _gen_one(fmt: str, prompt: str, public_id: str):
            logger.info(f"[PIPELINE] ▶ {fmt} Replicate...")
            replicate_url = await _generer_replicate(client, prompt)
            if not replicate_url:
                logger.error(f"[PIPELINE] ❌ {fmt} Replicate échoué")
                return fmt, None

            logger.info(f"[PIPELINE] ✅ {fmt} Replicate OK → Cloudinary...")
            cloudinary_url = await _upload_cloudinary(client, replicate_url, public_id)

            if cloudinary_url:
                return fmt, cloudinary_url

            logger.warning(
                f"[PIPELINE] ⚠️  {fmt} Cloudinary échoué — URL Replicate temporaire"
            )
            return fmt, replicate_url

        tasks   = [_gen_one(f, p, pid) for f, (p, pid) in tasks_def.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, Exception):
            logger.error(f"[PIPELINE] Exception : {res}")
            continue
        fmt, url = res
        if url:
            if fmt == "LANDSCAPE": result["video_url_landscape"] = url
            elif fmt == "PORTRAIT": result["video_url_portrait"]  = url
            elif fmt == "SQUARE":   result["video_url_square"]    = url

    result["thumbnail_url"] = (
        result["video_url_landscape"]
        or result["video_url_portrait"]
        or result["video_url_square"]
    )
    result["images_urls"] = [
        u for u in [
            result["video_url_landscape"],
            result["video_url_portrait"],
            result["video_url_square"],
        ] if u
    ]

    if not result["thumbnail_url"]:
        raise ValueError("Aucune vidéo générée — vérifiez REPLICATE_API_KEY")

    src = "Cloudinary ✅" if "cloudinary" in (result["thumbnail_url"] or "") else "Replicate ⚠️"
    logger.info(f"[PIPELINE] Terminé '{destination}' — {src}")
    return result


# ══════════════════════════════════════════════════════════
#  FALLBACK PROMPT + EXTRACT URL
# ══════════════════════════════════════════════════════════

def _fallback_prompt(destination: str, ton: str) -> str:
    dest_lower = destination.lower()
    geo = {
        "djerba":   "Djerba island Tunisia, white buildings, turquoise Mediterranean sea, palm trees",
        "sousse":   "Sousse Tunisia, historic medina UNESCO, golden sandy beach, ribat fortress",
        "tunis":    "Tunis Tunisia, Zitouna mosque, vibrant medina souks, Carthage ruins",
        "hammamet": "Hammamet Tunisia, white sandy beach resort, jasmine gardens, medieval kasbah",
        "monastir": "Monastir Tunisia, ribat fortress by the sea, white medina, palm-lined marina",
        "douz":     "Douz Tunisia Sahara desert, golden sand dunes at sunset, camel caravan",
        "tozeur":   "Tozeur Tunisia, date palm oasis, traditional brick architecture, salt lake",
        "tabarka":  "Tabarka Tunisia, rocky coastline, Genoese fortress, turquoise sea",
        "kairouan": "Kairouan Tunisia, Great Mosque UNESCO, historic medina, ancient city walls",
        "sfax":     "Sfax Tunisia, historic medina ramparts, olive groves, southern port city",
        "nabeul":   "Nabeul Tunisia, pottery workshops, jasmine fields, sandy beach, Cap Bon",
        "bizerte":  "Bizerte Tunisia, ancient Kasbah, fishing harbor, lagoon and sea",
        "matmata":  "Matmata Tunisia, troglodyte cave dwellings, Berber architecture, rocky desert",
    }
    geo_desc = next(
        (v for k, v in geo.items() if k in dest_lower),
        f"{destination} Tunisia, authentic travel destination, Mediterranean atmosphere"
    )
    camera = {
        "LUXE":       "slow cinematic dolly shot, golden hour luxury",
        "AVENTURE":   "dynamic tracking shot, vibrant colors",
        "FAMILLE":    "smooth gentle pan, warm sunlight",
        "ROMANTIQUE": "soft zoom, sunset romantic light",
        "AFFAIRES":   "clean steady shot, professional elegant",
    }.get(ton, "cinematic travel shot")
    return (
        f"Cinematic travel video of {geo_desc}, "
        f"{camera}, 6 seconds, no text overlay, no faces, "
        "ultra HD travel advertisement"
    )


def _extract_url(data: dict) -> Optional[str]:
    output = data.get("output")
    if isinstance(output, str) and output.startswith("http"):
        return output
    if isinstance(output, list) and output:
        return output[0]
    return None