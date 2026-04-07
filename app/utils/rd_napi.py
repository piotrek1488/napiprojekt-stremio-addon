"""
Real-Debrid → NapiProjekt bridge.

EXACT size match only. Fuzzy matching was matching WRONG files
(e.g. Dragon Ball instead of Joker) so it's disabled.

Limitation: NapiProjekt only works when the video file is in
your RD account (/downloads or /torrents). If you're streaming
via Torrentio and the file isn't saved in RD, this won't work
because the subtitle addon has no access to the streaming URL.
"""

import hashlib
import traceback
import httpx
from app.utils.napi_decoder import download_by_napi_hash

RD_API = "https://api.real-debrid.com/rest/1.0"


async def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    target = str(video_size)
    print(f"🔎 RD: szukam pliku o DOKŁADNYM rozmiarze {target}")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            auth = {"Authorization": f"Bearer {rd_token}"}

            # === 1. /downloads (exact match) ===
            r = await client.get(f"{RD_API}/downloads", headers=auth)
            downloads = r.json() if r.status_code == 200 else []
            print(f"📂 RD /downloads: {len(downloads)} elementów")

            for d in downloads:
                if str(d.get("filesize")) == target:
                    url = d.get("download")
                    if url:
                        fname = d.get("filename", "?")[:60]
                        print(f"  ✅ EXACT match w /downloads: {fname}")
                        return await _hash_and_fetch(url)

            # === 2. /torrents — drill into ALL for exact file match ===
            r = await client.get(f"{RD_API}/torrents", headers=auth)
            torrents = r.json() if r.status_code == 200 else []
            print(f"📂 RD /torrents: {len(torrents)} elementów")

            for torrent in torrents:
                tid = torrent.get("id")

                info_r = await client.get(f"{RD_API}/torrents/info/{tid}", headers=auth)
                if info_r.status_code != 200:
                    continue

                info = info_r.json()
                files = info.get("files", [])
                links = info.get("links", [])
                selected = [f for f in files if f.get("selected") == 1]

                for idx, f in enumerate(selected):
                    if str(f.get("bytes")) == target:
                        fp = f.get("path", "?")
                        tname = torrent.get("filename", "?")[:50]
                        print(f"  ✅ EXACT match w torrencie '{tname}'")
                        print(f"     Plik: {fp} ({f.get('bytes')} bytes)")

                        if links:
                            link_idx = min(idx, len(links) - 1)
                            ur = await client.post(
                                f"{RD_API}/unrestrict/link",
                                headers=auth,
                                data={"link": links[link_idx]},
                            )
                            if ur.status_code == 200:
                                dl_url = ur.json().get("download")
                                if dl_url:
                                    return await _hash_and_fetch(dl_url)

            print(f"ℹ️ RD: brak EXACT match dla size={target}")
            print(f"ℹ️ Jeśli streamujesz przez Torrentio, plik może nie być w Twoim RD.")
            return None

    except Exception as e:
        print(f"❌ RD error: {e}")
        traceback.print_exc()
        return None


async def _hash_and_fetch(video_url: str) -> str | None:
    try:
        print(f"⚡ Pobieranie 10MB...")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(video_url, headers={"Range": "bytes=0-10485759"})
            if r.status_code not in (200, 206):
                print(f"⚠️ HTTP {r.status_code}")
                return None
            data = r.content
            if len(data) < 1024:
                return None
            napi_hash = hashlib.md5(data).hexdigest()
            print(f"📊 Hash: {napi_hash} ({len(data)} bytes)")
        return await download_by_napi_hash(napi_hash, len(data))
    except Exception as e:
        print(f"❌ {e}")
        return None
