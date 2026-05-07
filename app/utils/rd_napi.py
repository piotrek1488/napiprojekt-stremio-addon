"""
Real-Debrid → NapiProjekt bridge.

Finds video file on RD by exact videoSize match.
If torrent has no links (files not selected), auto-selects them.
"""

import hashlib, traceback, asyncio
import httpx
from app.utils.napi_decoder import download_by_hash

RD_API = "https://api.real-debrid.com/rest/1.0"


async def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    target = str(video_size)
    print(f"🔎 RD: szukam pliku o rozmiarze {target}")

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            auth = {"Authorization": f"Bearer {rd_token}"}

            # === 1. /downloads ===
            r = await client.get(f"{RD_API}/downloads", headers=auth)
            downloads = r.json() if r.status_code == 200 else []
            print(f"📂 RD /downloads: {len(downloads)} elementów")

            for d in downloads:
                if str(d.get("filesize")) == target:
                    url = d.get("download")
                    if url:
                        print(f"  ✅ MATCH w /downloads: {d.get('filename','?')[:60]}")
                        return await _hash_and_fetch(url)

            # === 2. /torrents → drill into ALL ===
            r = await client.get(f"{RD_API}/torrents", headers=auth)
            torrents = r.json() if r.status_code == 200 else []
            print(f"📂 RD /torrents: {len(torrents)} elementów")

            for torrent in torrents:
                tid = torrent.get("id")
                tname = torrent.get("filename", "?")[:50]

                try:
                    info_r = await client.get(f"{RD_API}/torrents/info/{tid}", headers=auth)
                except Exception:
                    continue
                if info_r.status_code != 200:
                    continue

                info = info_r.json()
                files = info.get("files", [])
                links = info.get("links", [])
                status = info.get("status", "")
                selected = [f for f in files if f.get("selected") == 1]

                # Skip broken torrents
                if status in ("error", "magnet_error", "virus", "dead"):
                    continue

                for idx, f in enumerate(selected):
                    fb = f.get("bytes", 0)
                    if str(fb) != target:
                        continue

                    fp = f.get("path", "?")
                    print(f"  ✅ MATCH w torrencie '{tname}'")
                    print(f"     Plik: {fp} ({fb} bytes)")

                    # No links? Need to select files first
                    if not links:
                        print(f"  🔄 Brak linków — wybieram pliki na RD...")
                        links = await _select_files_and_get_links(client, auth, tid)
                        if not links:
                            print(f"  ⚠️ Nie udało się wygenerować linków")
                            continue

                    link_idx = min(idx, len(links) - 1)
                    try:
                        ur = await client.post(
                            f"{RD_API}/unrestrict/link",
                            headers=auth,
                            data={"link": links[link_idx]},
                        )
                        if ur.status_code == 200:
                            dl_url = ur.json().get("download")
                            if dl_url:
                                return await _hash_and_fetch(dl_url)
                        else:
                            print(f"  ⚠️ Unrestrict: HTTP {ur.status_code}")
                    except Exception as e:
                        print(f"  ⚠️ Unrestrict error: {e}")

            print(f"ℹ️ RD: brak pliku o rozmiarze {target}")
            return None

    except Exception as e:
        print(f"❌ RD error: {e}")
        traceback.print_exc()
        return None


async def _select_files_and_get_links(client, auth, torrent_id, file_ids=None, max_wait=60):
    """Select files in a torrent and wait for links to be generated."""
    try:
        # Get current torrent info
        info_r = await client.get(f"{RD_API}/torrents/info/{torrent_id}", headers=auth)
        if info_r.status_code != 200:
            return []
        info = info_r.json()
        status = info.get("status", "?")
        print(f"  🔄 Torrent status: {status}")

        # If already has links, return them
        if info.get("links"):
            return info["links"]

        # Determine which files to select
        if file_ids:
            files_param = ",".join(str(fid) for fid in file_ids)
        else:
            # Select all files — use their IDs from the files array
            all_ids = [str(f.get("id")) for f in info.get("files", []) if f.get("id")]
            files_param = ",".join(all_ids) if all_ids else "all"

        print(f"  🔄 Selecting files: {files_param[:50]}")
        r = await client.post(
            f"{RD_API}/torrents/selectFiles/{torrent_id}",
            headers=auth,
            data={"files": files_param},
        )
        print(f"  🔄 selectFiles: HTTP {r.status_code}")

        if r.status_code not in (200, 202, 204):
            return []

        # Poll for links (large files may take a while)
        for wait in range(max_wait):
            await asyncio.sleep(2)
            info_r = await client.get(f"{RD_API}/torrents/info/{torrent_id}", headers=auth)
            if info_r.status_code == 200:
                info = info_r.json()
                links = info.get("links", [])
                new_status = info.get("status", "?")
                if links:
                    print(f"  ✅ {len(links)} linków gotowych (po {(wait+1)*2}s, status={new_status})")
                    return links
                if wait % 5 == 4:
                    print(f"  ⏳ Czekam... ({(wait+1)*2}s, status={new_status})")

        print(f"  ⚠️ Timeout — linki nie pojawiły się po {max_wait*2}s")
        return []

    except Exception as e:
        print(f"  ⚠️ selectFiles error: {e}")
        return []


async def _hash_and_fetch(video_url: str) -> str | None:
    try:
        print(f"⚡ Pobieranie 10MB...")
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
            print(f"📊 Hash: {napi_hash} ({len(data)} bytes)")
        return await download_by_hash(napi_hash)
    except Exception as e:
        print(f"❌ Hash error: {e}")
        traceback.print_exc()
        return None


async def get_rd_files(rd_token: str) -> dict:
    """Debug: list all RD files with sizes."""
    async with httpx.AsyncClient(timeout=15) as client:
        auth = {"Authorization": f"Bearer {rd_token}"}
        r = await client.get(f"{RD_API}/downloads", headers=auth)
        downloads = [{"filename": d.get("filename","?")[:80], "filesize": d.get("filesize")}
                     for d in (r.json() if r.status_code == 200 else [])]
        r = await client.get(f"{RD_API}/torrents", headers=auth)
        torrents = []
        for t in (r.json() if r.status_code == 200 else []):
            entry = {"filename": t.get("filename","?")[:80], "bytes": t.get("bytes"), "id": t.get("id")}
            try:
                info_r = await client.get(f"{RD_API}/torrents/info/{t.get('id')}", headers=auth)
                if info_r.status_code == 200:
                    info = info_r.json()
                    entry["links_count"] = len(info.get("links", []))
                    entry["status"] = info.get("status", "?")
                    entry["files"] = [{"path": f.get("path","?")[:80], "bytes": f.get("bytes"), "selected": f.get("selected")}
                                      for f in info.get("files", []) if f.get("selected") == 1]
            except: pass
            torrents.append(entry)
    return {"downloads": downloads, "torrents": torrents}
