"""OpenSubtitles API — search + download real SRT files."""

import httpx


async def search_opensubtitles(imdb_id: str, os_api_key: str) -> list:
    """Search OpenSubtitles for Polish subtitles. Returns file_id for download."""
    headers = {"Api-Key": os_api_key, "User-Agent": "StremioNapiAddon"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
            resp = await client.get(
                f"https://api.opensubtitles.com/api/v1/subtitles?imdb_id={imdb_id}&languages=pl")
            if resp.status_code != 200:
                print(f"⚠️ OS: HTTP {resp.status_code}")
                return []
            results = []
            for item in resp.json().get("data", [])[:10]:
                attrs = item.get("attributes", {})
                files = attrs.get("files", [])
                if files and files[0].get("file_id"):
                    results.append({
                        "id": f"os_{item.get('id')}",
                        "file_id": files[0]["file_id"],
                        "releaseName": attrs.get("release") or "OpenSubtitles",
                    })
            print(f"📡 OS: {len(results)} napisów dla {imdb_id}")
            return results
    except Exception as e:
        print(f"❌ OS search: {e}")
        return []


async def download_opensubtitles_srt(file_id: int, os_api_key: str) -> str | None:
    """Download actual SRT content from OpenSubtitles."""
    headers = {"Api-Key": os_api_key, "User-Agent": "StremioNapiAddon", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.opensubtitles.com/api/v1/download",
                headers=headers, json={"file_id": file_id})
            if resp.status_code != 200:
                return None
            dl_link = resp.json().get("link")
            if not dl_link:
                return None
            srt_resp = await client.get(dl_link, timeout=10.0)
            return srt_resp.text if srt_resp.status_code == 200 else None
    except Exception as e:
        print(f"❌ OS download: {e}")
        return None
