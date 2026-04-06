import httpx


async def search_opensubtitles(imdb_id: str, os_api_key: str):
    """
    Search OpenSubtitles. Returns file_id (for download API), NOT webpage URL.
    """
    print(f"📡 Zapytanie do OpenSubtitles dla ID: {imdb_id}")

    url = f"https://api.opensubtitles.com/api/v1/subtitles?imdb_id={imdb_id}&languages=pl"

    headers = {
        "Api-Key": os_api_key,
        "User-Agent": "StremioPolishAddon"
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            response = await client.get(url, timeout=10.0)

            if response.status_code == 200:
                data = response.json()
                print(f"DEBUG OS: Odebrano {len(data.get('data', []))} elementów z API")

                results = []
                for item in data.get("data", [])[:10]:
                    attributes = item.get("attributes", {})
                    files = attributes.get("files", [])

                    # Potrzebujemy file_id do pobrania prawdziwego SRT
                    if files:
                        file_id = files[0].get("file_id")
                        if file_id:
                            results.append({
                                "id": f"os_{item.get('id')}",
                                "file_id": file_id,  # to jest klucz do download API
                                "lang": "pol",
                                "releaseName": attributes.get("release") or "OpenSubtitles",
                                "source": "OpenSubtitles"
                            })

                print(f"✅ Sukces: Znaleziono {len(results)} napisów w OpenSubtitles")
                return results
            else:
                print(f"⚠️ OpenSubtitles zwrócił status: {response.status_code}")

    except Exception as e:
        print(f"❌ Błąd OpenSubtitles: {e}")

    return []


async def download_opensubtitles_srt(file_id: int, os_api_key: str) -> str | None:
    """
    Download actual SRT content from OpenSubtitles using file_id.
    Uses the /download endpoint to get a temporary download link, then fetches SRT.
    """
    headers = {
        "Api-Key": os_api_key,
        "User-Agent": "StremioPolishAddon",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Step 1: Get temporary download link
            resp = await client.post(
                "https://api.opensubtitles.com/api/v1/download",
                headers=headers,
                json={"file_id": file_id},
            )

            if resp.status_code != 200:
                print(f"⚠️ OS download API returned {resp.status_code}: {resp.text[:200]}")
                return None

            data = resp.json()
            dl_link = data.get("link")
            if not dl_link:
                print("⚠️ OS: brak linku do pobrania")
                return None

            # Step 2: Download actual SRT file
            print(f"📥 OS: pobieram SRT z {dl_link[:60]}...")
            srt_resp = await client.get(dl_link, timeout=10.0)
            if srt_resp.status_code == 200:
                return srt_resp.text
            else:
                print(f"⚠️ OS SRT download failed: {srt_resp.status_code}")
                return None

    except Exception as e:
        print(f"❌ OS download error: {e}")
        return None
