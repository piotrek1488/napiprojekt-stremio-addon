import httpx

async def search_opensubtitles(imdb_id: str):
    print(f"📡 Pobieram prawdziwe napisy z OpenSubtitles dla ID: {imdb_id}")
    
    # Używamy publicznego API opensubtitles.com (wymaga User-Agent!)
    # Uwaga: darmowe API bez klucza ma limity, ale na testy wystarczy.
    url = f"https://rest.opensubtitles.org/search/imdbid-{imdb_id}/sublanguageid-pol"
    
    headers = {
        "User-Agent": "TemporaryUserAgent", # OpenSubtitles wymaga jakiegokolwiek UA
        "X-User-Agent": "TemporaryUserAgent"
    }

    try:
        async with httpx.AsyncClient(headers=headers) as client:
            response = await client.get(url, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                results = []
                
                # API OpenSubtitles zwraca listę obiektów
                for item in data[:5]: # Bierzemy 5 pierwszych wyników
                    results.append({
                        "id": f"os_{item.get('IDSubtitle')}",
                        # WAŻNE: Link musi prowadzić bezpośrednio do pliku .srt
                        "url": item.get("SubDownloadLink").replace(".gz", ""), 
                        "lang": "pol",
                        "releaseName": item.get("MovieReleaseName") or "OpenSubtitles Release",
                        "source": "OpenSubtitles"
                    })
                
                print(f"✅ Znaleziono {len(results)} napisów w OpenSubtitles")
                return results
    except Exception as e:
        print(f"❌ Błąd podczas komunikacji z OpenSubtitles: {e}")
        
    return []