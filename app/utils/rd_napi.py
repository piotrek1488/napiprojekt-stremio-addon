"""
Real-Debrid → NapiProjekt bridge (fully async).

Key insight: Stremio sends videoSize = size of the VIDEO FILE being played.
  - RD /downloads → filesize = individual file size ✓ (direct match possible)
  - RD /torrents → bytes = TOTAL torrent size ✗ (folder of files!)
  - RD /torrents/info/{id} → files[].bytes = individual file sizes ✓

So we need to drill into each torrent to find the matching file.
"""

import hashlib
import traceback
import httpx
from app.utils.napi_decoder import download_by_napi_hash


RD_API = "https://api.real-debrid.com/rest/1.0"


async def _rd_get(client: httpx.AsyncClient, path: str, rd_token: str):
    """Helper for RD API GET requests."""
    r = await client.get(
        f"{RD_API}{path}",
        headers={"Authorization": f"Bearer {rd_token}"},
    )
    return r


async def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    """
    Find the video file in RD matching video_size, compute NapiProjekt hash, download subs.
    """
    target_size = str(video_size)
    print(f"🔎 RD: szukam pliku o rozmiarze {target_size}")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:

            # === 1. Check /downloads (direct links) ===
            r = await _rd_get(client, "/downloads", rd_token)
            if r.status_code == 200:
                downloads = r.json()
                print(f"📂 RD /downloads: {len(downloads)} elementów")

                for d in downloads:
                    if str(d.get("filesize")) == target_size:
                        dl_url = d.get("download")
                        if dl_url:
                            print(f"✅ RD: znaleziono match w /downloads! filesize={d.get('filesize')}")
                            return await _hash_and_fetch(dl_url)
            else:
                print(f"⚠️ RD /downloads: HTTP {r.status_code}")

            # === 2. Check /torrents → drill into each for file sizes ===
            r = await _rd_get(client, "/torrents", rd_token)
            if r.status_code != 200:
                print(f"⚠️ RD /torrents: HTTP {r.status_code}")
                return None

            torrents = r.json()
            print(f"📂 RD /torrents: {len(torrents)} elementów")

            # Check recent torrents (limit to 20 to avoid too many API calls)
            for torrent in torrents[:20]:
                torrent_id = torrent.get("id")
                torrent_name = torrent.get("filename", "?")

                # Quick skip: if torrent total size is smaller than target, skip
                torrent_bytes = torrent.get("bytes", 0)
                if torrent_bytes and int(torrent_bytes) < int(target_size):
                    continue

                # Get detailed info with file list
                info_r = await _rd_get(client, f"/torrents/info/{torrent_id}", rd_token)
                if info_r.status_code != 200:
                    continue

                info = info_r.json()
                files = info.get("files", [])
                links = info.get("links", [])

                # Check each file in the torrent
                for f in files:
                    file_bytes = f.get("bytes", 0)
                    file_path = f.get("path", "")
                    file_selected = f.get("selected", 0)

                    if str(file_bytes) == target_size and file_selected == 1:
                        print(f"✅ RD: znaleziono match w torrencie '{torrent_name}'!")
                        print(f"   Plik: {file_path} ({file_bytes} bytes)")

                        # Unrestrict the first link to get download URL
                        if links:
                            unrestrict_r = await client.post(
                                f"{RD_API}/unrestrict/link",
                                headers={"Authorization": f"Bearer {rd_token}"},
                                data={"link": links[0]},
                            )
                            if unrestrict_r.status_code == 200:
                                dl_url = unrestrict_r.json().get("download")
                                if dl_url:
                                    print(f"🔗 RD: unrestricted URL ready")
                                    return await _hash_and_fetch(dl_url)
                            else:
                                print(f"⚠️ RD unrestrict: HTTP {unrestrict_r.status_code}")

            # === Debug: log what sizes we DID find ===
            print(f"ℹ️ RD: nie znaleziono pliku o rozmiarze {target_size}")
            dl_sizes = [str(d.get("filesize", "?")) for d in (downloads if r.status_code == 200 else [])[:5]]
            print(f"ℹ️ RD: /downloads sizes (top 5): {dl_sizes}")

            return None

    except Exception as e:
        print(f"❌ RD pipeline error: {e}")
        traceback.print_exc()
        return None


async def _hash_and_fetch(video_url: str) -> str | None:
    """Download first 10MB → MD5 hash → fetch NapiProjekt subtitles."""
    try:
        print(f"⚡ RD: pobieranie 10MB z {video_url[:80]}...")

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {"Range": "bytes=0-10485759"}
            r = await client.get(video_url, headers=headers)

            if r.status_code not in (200, 206):
                print(f"⚠️ RD video download: HTTP {r.status_code}")
                return None

            data = r.content
            if len(data) < 1024:
                print(f"⚠️ RD video chunk too small: {len(data)} bytes")
                return None

            # FULL 32-char MD5 hash
            napi_hash = hashlib.md5(data).hexdigest()
            file_size = len(data)
            print(f"📊 NapiProjekt hash: {napi_hash} (from {len(data)} bytes)")

        # Download subtitles
        print(f"⚡ Napi: szukam napisów dla hash {napi_hash}")
        return await download_by_napi_hash(napi_hash, file_size)

    except Exception as e:
        print(f"❌ Hash/fetch error: {e}")
        traceback.print_exc()
        return None
