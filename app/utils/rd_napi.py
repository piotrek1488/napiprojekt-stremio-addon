"""
Real-Debrid → NapiProjekt bridge.

Checks /downloads and ALL /torrents (drilling into file lists).
Supports fuzzy size matching (0.5% tolerance) for edge cases.
"""

import hashlib
import traceback
import httpx
from app.utils.napi_decoder import download_by_napi_hash

RD_API = "https://api.real-debrid.com/rest/1.0"


async def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    target = int(video_size)
    tolerance = target * 0.005  # 0.5% fuzzy match
    print(f"🔎 RD: szukam pliku o rozmiarze {target} (tolerancja ±{int(tolerance)})")

    exact_match_url = None
    fuzzy_match_url = None
    fuzzy_match_diff = float('inf')
    fuzzy_match_info = ""

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            auth = {"Authorization": f"Bearer {rd_token}"}

            # === 1. /downloads ===
            r = await client.get(f"{RD_API}/downloads", headers=auth)
            downloads = r.json() if r.status_code == 200 else []
            print(f"📂 RD /downloads: {len(downloads)} elementów")

            for d in downloads:
                fs = d.get("filesize", 0)
                if not fs:
                    continue
                fs = int(fs)
                diff = abs(fs - target)

                if fs == target:
                    print(f"  ✅ EXACT match w /downloads: {d.get('filename','?')[:50]} ({fs})")
                    exact_match_url = d.get("download")
                    break
                elif diff < tolerance and diff < fuzzy_match_diff:
                    fuzzy_match_diff = diff
                    fuzzy_match_url = d.get("download")
                    fuzzy_match_info = f"/downloads: {d.get('filename','?')[:50]} ({fs}, diff={diff})"

            if exact_match_url:
                return await _hash_and_fetch(exact_match_url)

            # === 2. /torrents — check ALL of them ===
            r = await client.get(f"{RD_API}/torrents", headers=auth)
            torrents = r.json() if r.status_code == 200 else []
            print(f"📂 RD /torrents: {len(torrents)} elementów, sprawdzam WSZYSTKIE...")

            for torrent in torrents:  # ALL torrents, no limit
                tid = torrent.get("id")
                tname = torrent.get("filename", "?")[:50]

                info_r = await client.get(f"{RD_API}/torrents/info/{tid}", headers=auth)
                if info_r.status_code != 200:
                    continue

                info = info_r.json()
                files = info.get("files", [])
                links = info.get("links", [])

                # Build map: selected file index → link index
                selected_files = [f for f in files if f.get("selected") == 1]

                for sel_idx, f in enumerate(selected_files):
                    fb = int(f.get("bytes", 0))
                    fp = f.get("path", "?")
                    if not fb:
                        continue

                    diff = abs(fb - target)

                    if fb == target:
                        print(f"  ✅ EXACT match! torrent='{tname}' file='{fp}' ({fb})")
                        url = await _unrestrict_file(client, auth, links, sel_idx)
                        if url:
                            return await _hash_and_fetch(url)

                    elif diff < tolerance and diff < fuzzy_match_diff:
                        fuzzy_match_diff = diff
                        fuzzy_match_info = f"torrent '{tname}' file '{fp}' ({fb}, diff={diff})"
                        # Store info to unrestrict later if needed
                        fuzzy_match_url = (links, sel_idx)

            # === 3. No exact match — try fuzzy ===
            if fuzzy_match_url:
                print(f"  🔸 Użycie FUZZY match: {fuzzy_match_info}")
                if isinstance(fuzzy_match_url, tuple):
                    links, idx = fuzzy_match_url
                    url = await _unrestrict_file(client, auth, links, idx)
                    if url:
                        return await _hash_and_fetch(url)
                elif isinstance(fuzzy_match_url, str):
                    return await _hash_and_fetch(fuzzy_match_url)

            print(f"ℹ️ RD: brak matcha dla size={target}")
            return None

    except Exception as e:
        print(f"❌ RD error: {e}")
        traceback.print_exc()
        return None


async def _unrestrict_file(client, auth, links, file_idx):
    """Unrestrict the correct link for a file inside a torrent."""
    if not links:
        print(f"  ⚠️ Brak linków do unrestrictu")
        return None

    link_idx = min(file_idx, len(links) - 1)
    ur = await client.post(
        f"{RD_API}/unrestrict/link",
        headers=auth,
        data={"link": links[link_idx]},
    )
    if ur.status_code == 200:
        url = ur.json().get("download")
        if url:
            print(f"  🔗 Unrestricted OK")
            return url
    print(f"  ⚠️ Unrestrict failed: HTTP {ur.status_code}")
    return None


async def _hash_and_fetch(video_url: str) -> str | None:
    """Download first 10MB → MD5 → NapiProjekt."""
    try:
        print(f"⚡ Pobieranie 10MB z {video_url[:80]}...")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            r = await client.get(video_url, headers={"Range": "bytes=0-10485759"})
            if r.status_code not in (200, 206):
                print(f"⚠️ Video download: HTTP {r.status_code}")
                return None
            data = r.content
            if len(data) < 1024:
                print(f"⚠️ Chunk too small: {len(data)}b")
                return None

            napi_hash = hashlib.md5(data).hexdigest()
            print(f"📊 NapiProjekt hash: {napi_hash} ({len(data)} bytes)")

        return await download_by_napi_hash(napi_hash, len(data))
    except Exception as e:
        print(f"❌ Hash/fetch error: {e}")
        traceback.print_exc()
        return None
