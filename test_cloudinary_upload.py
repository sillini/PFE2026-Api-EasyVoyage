#!/usr/bin/env python3
"""
Test upload Cloudinary — preset non-signé (sans overwrite).
Usage : python test_cloudinary_upload.py [url_video_replicate]
"""
import asyncio
import sys
import httpx

CLOUDINARY_CLOUD  = "dzfznxn0q"
CLOUDINARY_PRESET = "video_easyvoyage"

# URL de test : petit MP4 public accessible
TEST_URLS = [
    "https://www.w3schools.com/html/mov_bbb.mp4",
    "https://media.w3.org/2010/05/sintel/trailer.mp4",
    "https://filesamples.com/samples/video/mp4/sample_640x360.mp4",
]

async def main():
    # Si une URL Replicate est passée en argument, l'utiliser
    if len(sys.argv) > 1:
        TEST_URLS.insert(0, sys.argv[1])
        print(f"URL fournie : {sys.argv[1][:80]}")

    print(f"Cloud  : {CLOUDINARY_CLOUD}")
    print(f"Preset : {CLOUDINARY_PRESET}")
    print()

    async with httpx.AsyncClient(timeout=60.0) as client:

        # Trouver une URL de test téléchargeable
        video_bytes = None
        for url in TEST_URLS:
            print(f"Téléchargement : {url[:70]}...")
            try:
                dl = await client.get(url, follow_redirects=True, timeout=30.0)
                if dl.status_code == 200 and len(dl.content) > 1024:
                    video_bytes = dl.content
                    print(f"  → ✅ {len(video_bytes)//1024} Ko")
                    break
                else:
                    print(f"  → ❌ HTTP {dl.status_code}")
            except Exception as e:
                print(f"  → ❌ {e}")

        if not video_bytes:
            print("\n❌ Aucune URL de test accessible")
            print("   Passez une URL Replicate valide en argument :")
            print("   python test_cloudinary_upload.py https://replicate.delivery/...")
            return

        print()
        print("Upload Cloudinary (sans overwrite — preset non-signé)...")
        resp = await client.post(
            f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD}/video/upload",
            files={"file": ("test_video.mp4", video_bytes, "video/mp4")},
            data={
                "upload_preset": CLOUDINARY_PRESET,
                "public_id":     "test_video_diagnostic",
                # PAS de overwrite ni resource_type — preset non-signé
            },
            timeout=120.0,
        )

        d = resp.json()
        if resp.status_code == 200 and d.get("secure_url"):
            print(f"\n✅ SUCCÈS !")
            print(f"   URL : {d['secure_url']}")
            print(f"\n→ Tout est OK. Redémarrez le serveur.")
        else:
            err = d.get("error", {}).get("message", str(d)[:300])
            print(f"\n❌ ERREUR HTTP {resp.status_code} : {err}")

asyncio.run(main())