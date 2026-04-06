"""
Real-Debrid → NapiProjekt bridge (fully async).

Stremio sends videoSize = size of the VIDEO FILE being played.
RD /torrents → bytes = TOTAL torrent size (wrong!)
RD /torrents/info/{id} → files[].bytes = individual file sizes (correct!)
"""

import hashlib
import traceback
import httpx
from app.utils.napi_decoder import download_by_napi_hash


RD_API = "https://api.real-debrid.com/rest/1.0"


async def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    target = str(video_size)
    print(f"🔎 RD: szukam pliku o rozmiarze {target}")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            auth = {"Authorization": f"Bearer {rd_token}"}

            # === 1. Check /downloads ===
            r = await client.get(f"{RD_API}/downloads", headers=auth)
            downloads = r.json() if r.status_code == 200 else []
            print(f"📂 RD /downloads: {len(downloads)} elementów")

            for d in downloads:
                if str(d.get("filesize")) == target:
                    url = d.get("download")
                    if url:
                        print(f"✅ RD /downloads: MATCH! filesize={d.get('filesize')}")
                        return await _hash_and_fetch(url)

            # === 2. Check /torrents - drill into EACH one ===
            r = await client.get(f"{RD_API}/torrents", headers=auth)
            torrents = r.json() if r.status_code == 200 else []
            print(f"📂 RD /torrents: {len(torrents)} elementów, sprawdzam każdy...")

            checked = 0
            for torrent in torrents[:30]:  # check up to 30
                tid = torrent.get("id")
                tname = torrent.get("filename", "?")[:50]
                tbytes = torrent.get("bytes", 0)

                # Skip if total torrent is smaller than target file
                if tbytes and int(tbytes) < int(target) * 0.9:
                    continue

                checked += 1
                # Get detailed file list
                info_r = await client.get(f"{RD_API}/torrents/info/{tid}", headers=auth)
                if info_r.status_code != 200:
                    print(f"  ⚠️ torrent {tid}: info returned {info_r.status_code}")
                    continue

                info = info_r.json()
                files = info.get("files", [])
                links = info.get("links", [])

                # Log all files in this torrent for debugging
                video_files = [f for f in files if f.get("selected") == 1]
                if not video_files:
                    video_files = files  # if none selected, check all

                for f in video_files:
                    fb = f.get("bytes", 0)
                    fp = f.get("path", "?")
                    fsel = f.get("selected", 0)

                    # Exact match
                    if str(fb) == target:
                        print(f"  ✅ MATCH! torrent='{tname}' file='{fp}' bytes={fb}")

                        if not links:
                            print(f"  ⚠️ Brak linków do unrestrictu!")
                            continue

                        # Find which link corresponds to this file
                        # If there are multiple links, try to match by index
                        # For single-file torrents, use first link
                        link_to_use = links[0]

                        # For multi-file torrents, try to find the right link
                        selected_files = [sf for sf in files if sf.get("selected") == 1]
                        if len(selected_files) > 1 and len(links) > 1:
                            # Find index of our file among selected files
                            sel_idx = 0
                            for sf in selected_files:
                                if sf.get("bytes") == fb and sf.get("path") == fp:
                                    break
                                sel_idx += 1
                            if sel_idx < len(links):
                                link_to_use = links[sel_idx]

                        # Unrestrict to get direct download URL
                        ur = await client.post(
                            f"{RD_API}/unrestrict/link",
                            headers=auth,
                            data={"link": link_to_use},
                        )
                        if ur.status_code == 200:
                            dl_url = ur.json().get("download")
                            if dl_url:
                                print(f"  🔗 Unrestricted OK!")
                                return await _hash_and_fetch(dl_url)
                        else:
                            print(f"  ⚠️ Unrestrict failed: {ur.status_code}")

                    # Log near-matches for debugging (within 5%)
                    elif fb and abs(int(fb) - int(target)) < int(target) * 0.05:
                        print(f"  🔸 NEAR match: torrent='{tname}' file='{fp}' bytes={fb} (diff={int(fb)-int(target)})")

            print(f"ℹ️ RD: sprawdzono {checked} torrentów, nie znaleziono exact match dla size={target}")

            # Debug: show sizes of first few downloads
            dl_sizes = [(d.get("filename", "?")[:30], d.get("filesize")) for d in downloads[:3]]
            print(f"ℹ️ RD /downloads (top 3): {dl_sizes}")

            return None

    except Exception as e:
        print(f"❌ RD pipeline error: {e}")
        traceback.print_exc()
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
                print(f"⚠️ Video chunk too small: {len(data)} bytes")
                return None

            napi_hash = hashlib.md5(data).hexdigest()
            print(f"📊 NapiProjekt hash: {napi_hash} (from {len(data)} bytes)")

        return await download_by_napi_hash(napi_hash, len(data))

    except Exception as e:
        print(f"❌ Hash/fetch error: {e}")
        traceback.print_exc()
        return None
