"""
Real-Debrid → NapiProjekt bridge (fully async).

Flow:
  1. Search RD /downloads AND /torrents for matching video_size
  2. Get streaming URL
  3. Download first 10MB → compute MD5
  4. Download subtitles via napi_decoder
"""

import hashlib
import traceback
import httpx
from app.utils.napi_decoder import download_by_napi_hash


RD_API = "https://api.real-debrid.com/rest/1.0"


async def get_rd_downloads(rd_token: str) -> list:
    """Get recent downloads from RD."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{RD_API}/downloads",
                headers={"Authorization": f"Bearer {rd_token}"},
            )
            if r.status_code != 200:
                print(f"⚠️ RD /downloads returned {r.status_code}")
                return []
            data = r.json()
            print(f"📂 RD /downloads: {len(data)} elementów")
            return data
    except Exception as e:
        print(f"❌ RD /downloads error: {e}")
        return []


async def get_rd_torrents(rd_token: str) -> list:
    """Get active/recent torrents from RD (this is where streaming files live!)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{RD_API}/torrents",
                headers={"Authorization": f"Bearer {rd_token}"},
            )
            if r.status_code != 200:
                print(f"⚠️ RD /torrents returned {r.status_code}")
                return []
            data = r.json()
            print(f"📂 RD /torrents: {len(data)} elementów")
            return data
    except Exception as e:
        print(f"❌ RD /torrents error: {e}")
        return []


async def get_torrent_streaming_url(rd_token: str, torrent_id: str) -> str | None:
    """Get streaming/download URL for a specific torrent file."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get torrent info with file list
            r = await client.get(
                f"{RD_API}/torrents/info/{torrent_id}",
                headers={"Authorization": f"Bearer {rd_token}"},
            )
            if r.status_code != 200:
                return None

            info = r.json()
            links = info.get("links", [])
            if not links:
                return None

            # Unrestrict the first link to get direct download URL
            r2 = await client.post(
                f"{RD_API}/unrestrict/link",
                headers={"Authorization": f"Bearer {rd_token}"},
                data={"link": links[0]},
            )
            if r2.status_code != 200:
                return None

            return r2.json().get("download")

    except Exception as e:
        print(f"❌ RD torrent info error: {e}")
        return None


def find_by_size_in_downloads(downloads: list, video_size: str) -> dict | None:
    """Find matching file in /downloads by filesize."""
    for d in downloads:
        if str(d.get("filesize")) == str(video_size):
            return d
    return None


def find_by_size_in_torrents(torrents: list, video_size: str) -> dict | None:
    """Find matching torrent in /torrents by bytes."""
    for t in torrents:
        if str(t.get("bytes")) == str(video_size):
            return t
    return None


async def napi_hash_from_url(url: str) -> str | None:
    """Download first 10MB and compute full 32-char MD5."""
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {"Range": "bytes=0-10485759"}
            r = await client.get(url, headers=headers)

            if r.status_code not in (200, 206):
                print(f"⚠️ Video download returned {r.status_code}")
                return None

            data = r.content
            if len(data) < 1024:
                print(f"⚠️ Video chunk too small: {len(data)} bytes")
                return None

            full_hash = hashlib.md5(data).hexdigest()
            print(f"📊 NapiProjekt hash: {full_hash} (from {len(data)} bytes)")
            return full_hash

    except Exception as e:
        print(f"❌ Hash computation error: {e}")
        return None


async def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    """
    Full async pipeline:
      1. Check /downloads by filesize
      2. Check /torrents by bytes
      3. Get streaming URL → compute hash → download subs
    """
    try:
        # --- Try /downloads first ---
        downloads = await get_rd_downloads(rd_token)
        match = find_by_size_in_downloads(downloads, video_size)

        if match:
            download_url = match.get("download")
            if download_url:
                print(f"✅ RD: znaleziono w /downloads")
                return await _hash_and_fetch(download_url)

        # --- Try /torrents ---
        torrents = await get_rd_torrents(rd_token)
        tmatch = find_by_size_in_torrents(torrents, video_size)

        if tmatch:
            torrent_id = tmatch.get("id")
            print(f"✅ RD: znaleziono w /torrents (id={torrent_id})")
            stream_url = await get_torrent_streaming_url(rd_token, torrent_id)
            if stream_url:
                return await _hash_and_fetch(stream_url)
            else:
                print("⚠️ RD: nie udało się pobrać streaming URL z torrenta")

        # --- Log available sizes for debugging ---
        dl_sizes = [str(d.get("filesize")) for d in downloads[:5]]
        t_sizes = [str(t.get("bytes")) for t in torrents[:5]]
        print(f"ℹ️ RD: szukany size={video_size}")
        print(f"ℹ️ RD: dostępne /downloads sizes (top 5): {dl_sizes}")
        print(f"ℹ️ RD: dostępne /torrents sizes (top 5): {t_sizes}")

        return None

    except Exception as e:
        print(f"❌ RD pipeline error: {e}")
        traceback.print_exc()
        return None


async def _hash_and_fetch(video_url: str) -> str | None:
    """Download 10MB → hash → fetch subtitles."""
    print(f"⚡ RD: pobieranie 10MB z {video_url[:80]}...")
    napi_hash = await napi_hash_from_url(video_url)
    if not napi_hash:
        return None

    print(f"⚡ RD: szukam napisów dla hash {napi_hash}")
    return await download_by_napi_hash(napi_hash)
