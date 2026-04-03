import httpx
import urllib.parse
import hashlib
from bs4 import BeautifulSoup
from app.utils.retry import with_retry

HEADERS = {
    "User-Agent": "NapiProjekt/2.0.1.0", # Udajemy oficjalną aplikację NapiProjekt
    "Content-Type": "application/x-www-form-urlencoded"
}

async def fetch_by_hash(v_hash: str):
    if not v_hash:
        return []
    
    # API NapiProjekt wymaga specyficznego wyliczenia sumy kontrolnej dla zapytania
    # Wersja uproszczona, która często działa z ich oficjalnym endpointem:
    url = "http://napiprojekt.pl/api/api-napiprojekt3.php"
    
    # Przygotowanie danych zgodnie z protokołem (dodajemy parametry pomocnicze)
    data = {
        "download": "1",
        "vhash": v_hash,
        "mode": "1",
        "lang": "PL",
        "inf": "1" # Prosimy o dodatkowe informacje o pliku
    }
    
    try:
        async with httpx.AsyncClient() as client:
            # Udajemy oficjalny program NapiProjekt
            headers = {"User-Agent": "NapiProjekt/2.0.2.0"}
            resp = await client.post(url, data=data, headers=headers, timeout=5.0)
            
            # Napi API zwraca XML. Sprawdzamy czy sukces.
            if resp.status_code == 200 and "status=\"success\"" in resp.text:
                print(f"🎯 Sukces! Znaleziono napisy po videoHash: {v_hash}")
                # Tutaj zwracamy wynik. 
                # UWAGA: Aby napisy działały w Stremio, będziemy potrzebowali 
                # endpointu, który je pobierze i rozpakuje (Napi zwraca binarny XML).
                return [{
                    "id": f"napi_hash_{v_hash}",
                    "url": f"https://twoja-domena.com/proxy/napi/{v_hash}", 
                    "lang": "pol",
                    "releaseName": "Dopasowano idealnie (Hash)",
                    "source": "NapiProjekt-Hash",
                    "score": 100
                }]
    except Exception as e:
        print(f"⚠️ Błąd API Napi: {e}")
    return []

async def fetch_by_search(query: str):
    """Opcja 1: Klasyczny Scraping (z poprawką na 403)"""
    # Usuwamy znaki specjalne, które mogą triggerować firewall (np. dwukropek)
    clean_query = query.replace(":", "").replace("-", " ")
    safe_query = urllib.parse.quote(clean_query)
    url = f"https://www.napiprojekt.pl/szukaj?q={safe_query}"
    
    browser_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.napiprojekt.pl/"
    }

    async with httpx.AsyncClient(headers=browser_headers, follow_redirects=True) as client:
        print(f"📡 Fallback: Scrapowanie strony dla: {clean_query}")
        response = await client.get(url, timeout=8.0)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        for idx, tag in enumerate(soup.select('.movie-title')): 
            title = tag.get_text(strip=True)
            link = tag.get('href')
            if link:
                results.append({
                    "id": f"napi_web_{idx}",
                    "url": f"https://www.napiprojekt.pl{link}" if not link.startswith('http') else link,
                    "lang": "pol",
                    "releaseName": title,
                    "source": "NapiProjekt-Web"
                })
        return results

async def scrape_napiprojekt(query: str, v_hash: str = ""):
    # 1. PRÓBA PO HASHU (Rozwiązanie 2 - najbezpieczniejsze)
    if v_hash:
        print(f"🚀 Próba pobrania po hashu: {v_hash}")
        hash_results = await fetch_by_hash(v_hash)
        if hash_results:
            return hash_results

    # 2. PRÓBA PRZEZ SEARCH (Rozwiązanie 1 - jeśli hash zawiódł lub go brak)
    try:
        print(f"🔍 Hash niedostępny lub brak wyników. Szukam tekstowo: {query}")
        return await with_retry(fetch_by_search, query)
    except Exception as e:
        print(f"❌ Błąd krytyczny NapiProjekt: {e}")
        return []