import httpx

async def search_opensubtitles(imdb_id: str, os_api_key: str):
    # Usuwamy 'tt', bo API OS czasami woli same cyfry
    numeric_id = imdb_id.replace("tt", "")
    print(f"📡 Zapytanie do OpenSubtitles dla ID: {numeric_id}")
    
    url = f"https://api.opensubtitles.com/api/v1/subtitles?imdb_id={numeric_id}&languages=pol"
    
    headers = {
        "Api-Key": os_api_key,
        "User-Agent": "StremioPolishAddon"
    }

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            response = await client.get(url, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                # LOGOWANIE SUROWYCH DANYCH - zobaczysz to w logach Rendera
                print(f"DEBUG OS: Odebrano {len(data.get('data', []))} elementów z API")
                
                results = []
                for item in data.get("data", [])[:10]:  # Bierzemy do 10 wyników
                    attributes = item.get("attributes", {})
                    download_link = attributes.get("url")
                    if download_link:
                        results.append({
                            "id": f"os_{item.get('id')}",
                            "url": download_link,
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