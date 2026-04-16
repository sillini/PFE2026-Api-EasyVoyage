#!/usr/bin/env python3
"""
Migration des vidéos Replicate → Cloudinary.
Usage : python migration_videos_cloudinary.py

CORRECTION : utilise asyncpg directement (pas SQLAlchemy ORM)
pour éviter le conflit async/sync sous Windows.
"""
import asyncio
import logging
import os
import json

import httpx
import asyncpg
from dotenv import load_dotenv

load_dotenv()

CLOUDINARY_CLOUD  = "dzfznxn0q"
CLOUDINARY_PRESET = os.getenv("CLOUDINARY_VIDEO_PRESET", "video_easyvoyage")

# Lire les paramètres de connexion depuis DATABASE_URL
# Format : postgresql+asyncpg://user:password@host:port/dbname
DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:malek123@localhost:5432/voyage_hotel"
)
# Convertir pour asyncpg (retirer le +asyncpg)
PG_DSN = DB_URL.replace("postgresql+asyncpg://", "postgresql://")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
#  UPLOAD CLOUDINARY (sans overwrite — preset non-signé)
# ══════════════════════════════════════════════════════════

async def upload_cloudinary(
    client: httpx.AsyncClient,
    video_url: str,
    public_id: str,
) -> str | None:
    if not video_url:
        return None
    if "cloudinary" in video_url:
        return video_url  # Déjà sur Cloudinary

    # Télécharger
    logger.info(f"  ↓ Téléchargement : {video_url[:70]}...")
    try:
        dl = await client.get(video_url, follow_redirects=True, timeout=120.0)
        if dl.status_code != 200:
            logger.warning(f"  ❌ HTTP {dl.status_code} — URL probablement expirée")
            return None
        if len(dl.content) < 1024:
            logger.warning(f"  ❌ Fichier vide ({len(dl.content)} octets) — URL expirée")
            return None
        logger.info(f"  ✅ {len(dl.content)//1024} Ko")
    except Exception as e:
        logger.warning(f"  ❌ Erreur téléchargement : {e}")
        return None

    # Upload Cloudinary — SANS overwrite (interdit avec preset non-signé)
    logger.info(f"  ↑ Upload Cloudinary (preset={CLOUDINARY_PRESET})...")
    try:
        resp = await client.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD}/video/upload",
            files={"file": (f"{public_id}.mp4", dl.content, "video/mp4")},
            data={
                "upload_preset": CLOUDINARY_PRESET,
                "public_id":     public_id,
            },
            timeout=180.0,
        )
        if resp.status_code == 200:
            url = resp.json().get("secure_url")
            if url:
                logger.info(f"  ✅ {url[:70]}")
                return url
        err = resp.json().get("error", {}).get("message", resp.text[:150])
        logger.warning(f"  ❌ Cloudinary HTTP {resp.status_code} : {err}")
        return None
    except Exception as e:
        logger.warning(f"  ❌ Exception upload : {e}")
        return None


# ══════════════════════════════════════════════════════════
#  MIGRATION
# ══════════════════════════════════════════════════════════

async def migrate():
    logger.info("=" * 55)
    logger.info("MIGRATION VIDÉOS → CLOUDINARY")
    logger.info(f"Preset      : {CLOUDINARY_PRESET}")
    logger.info(f"Base données: {PG_DSN[:50]}...")
    logger.info("=" * 55)

    # Connexion PostgreSQL directe via asyncpg
    try:
        conn = await asyncpg.connect(PG_DSN)
    except Exception as e:
        logger.error(f"❌ Connexion BDD échouée : {e}")
        logger.error("Vérifiez DATABASE_URL dans .env")
        return

    logger.info("✅ Connexion BDD OK")

    # Récupérer toutes les campagnes avec une vidéo
    rows = await conn.fetch("""
        SELECT id, titre, destination,
               video_url_landscape, video_url_portrait, video_url_square
        FROM voyage_hotel.video_campaign
        WHERE video_url_landscape IS NOT NULL
        ORDER BY id
    """)

    logger.info(f"Campagnes avec vidéo : {len(rows)}\n")

    if not rows:
        logger.info("Rien à migrer.")
        await conn.close()
        return

    migrees = deja = echecs = 0

    async with httpx.AsyncClient(timeout=300.0) as client:
        for row in rows:
            camp_id   = row["id"]
            titre     = row["titre"]
            dest      = row["destination"]
            logger.info(f"── Campagne #{camp_id} : {titre} ({dest})")

            updates = {}

            for col, suffix in [
                ("video_url_landscape", "landscape"),
                ("video_url_portrait",  "portrait"),
                ("video_url_square",    "square"),
            ]:
                url = row[col]
                if not url:
                    continue
                if "cloudinary" in url:
                    logger.info(f"  ↳ {col} : déjà Cloudinary ✅")
                    deja += 1
                    continue
                # Éviter de re-uploader si même URL pour plusieurs formats
                if url in updates.values():
                    updates[col] = list(updates.values())[-1]
                    continue

                new_url = await upload_cloudinary(
                    client, url, f"vc_{camp_id}_{suffix}"
                )
                if new_url:
                    updates[col] = new_url
                    migrees += 1
                else:
                    echecs += 1

            if updates:
                # Construire le thumbnail depuis la première URL disponible
                thumbnail = (
                    updates.get("video_url_landscape")
                    or updates.get("video_url_portrait")
                    or updates.get("video_url_square")
                    or row["video_url_landscape"]
                )
                updates["thumbnail_url"] = thumbnail

                # Construire la requête UPDATE dynamiquement
                set_clauses = ", ".join(
                    f"{col} = ${i+2}" for i, col in enumerate(updates.keys())
                )
                values = [camp_id] + list(updates.values())
                await conn.execute(
                    f"UPDATE voyage_hotel.video_campaign "
                    f"SET {set_clauses} WHERE id = $1",
                    *values,
                )
                logger.info(f"  → BDD mise à jour ✅ ({list(updates.keys())})")
            else:
                logger.info(f"  → Rien à mettre à jour")

    await conn.close()

    logger.info("")
    logger.info("=" * 55)
    logger.info(f"✅ Migrées vers Cloudinary : {migrees}")
    logger.info(f"✅ Déjà sur Cloudinary     : {deja}")
    logger.info(f"❌ URLs expirées (>24h)    : {echecs}")
    if echecs > 0:
        logger.info("   → Régénérez ces campagnes depuis l'interface")
    logger.info("=" * 55)


if __name__ == "__main__":
    asyncio.run(migrate())