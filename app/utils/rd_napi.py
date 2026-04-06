"""
Real-Debrid → NapiProjekt bridge.

Flow:
  1. Get recent downloads from RD API
  2. Find matching file by video_size
  3. Download first 10MB from RD streaming URL
  4. Compute FULL 32-char MD5 (NapiProjekt hash)
  5. Download subtitles via napi_decoder
"""

import hashlib
import requests
import asyncio
from app.utils.napi_decoder import download_by_napi_hash


# --- 1. Get recent downloads from Real-Debrid ---

def get_rd_downloads(rd_token: str) -> list:
    try:
        r = requests.get(
            "https://api.real-debrid.com/rest/1.0/downloads",
            headers={"Authorization": f"Bearer {rd_token}"},
            timeout=10
        )
        if r.status_code != 200:
            print(f"⚠️ RD API returned {r.status_code}")
            return []
        return r.json()
    except Exception as e:
        print(f"❌ RD API error: {e}")
        return []


# --- 2. Find matching file by size ---

def find_matching_file(downloads: list, video_size: str) -> dict | None:
    for d in downloads:
        if str(d.get("filesize")) == str(video_size):
            return d
    return None


# --- 3. Compute PROPER NapiProjekt hash (MD5 of first 10MB) ---

def napi_hash_from_url(url: str) -> str | None:
    """
    Download first 10MB of video and compute FULL 32-char MD5 hash.

    BUG FIX: Previously used hexdigest()[:16] which truncated the hash!
    NapiProjekt requires the FULL 32-character MD5 hash.
    """
    try:
        headers = {"Range": "bytes=0-10485759"}  # first 10MB
        r = requests.get(url, headers=headers, timeout=30, stream=True)

        if r.status_code not in (200, 206):
            print(f"⚠️ Video download returned {r.status_code}")
            return None

        data = r.content
        if len(data) < 1024:
            print(f"⚠️ Video chunk too small: {len(data)} bytes")
            return None

        # FULL 32-char MD5 hash - NOT truncated!
        full_hash = hashlib.md5(data).hexdigest()
        print(f"📊 NapiProjekt hash: {full_hash} (from {len(data)} bytes)")
        return full_hash

    except Exception as e:
        print(f"❌ Hash computation error: {e}")
        return None


# --- 4. Download subtitles using proper napi_decoder ---

def fetch_napi_subtitles_sync(napi_hash: str) -> str | None:
    """
    Synchronous wrapper around async download_by_napi_hash.
    Uses the proper dl.php endpoint with subhash token.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context already - create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, download_by_napi_hash(napi_hash))
                return future.result(timeout=20)
        else:
            return asyncio.run(download_by_napi_hash(napi_hash))
    except Exception as e:
        print(f"❌ Napi fetch error: {e}")
        return None


# --- 5. MAIN: everything together ---

def get_napi_from_rd(rd_token: str, video_size: str) -> str | None:
    """
    Full pipeline: RD downloads → match by size → compute hash → download subs.
    """
    downloads = get_rd_downloads(rd_token)
    if not downloads:
        print("ℹ️ RD: brak pobrań")
        return None

    match = find_matching_file(downloads, video_size)
    if not match:
        print(f"ℹ️ RD: nie znaleziono pliku o rozmiarze {video_size}")
        return None

    download_url = match.get("download")
    if not download_url:
        print("ℹ️ RD: brak URL do pobrania")
        return None

    print(f"⚡ RD: pobieranie 10MB z {download_url[:60]}...")
    napi_hash = napi_hash_from_url(download_url)
    if not napi_hash:
        return None

    print(f"⚡ RD: szukam napisów dla hash {napi_hash}")
    return fetch_napi_subtitles_sync(napi_hash)
