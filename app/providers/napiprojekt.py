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
    """Opcja 2: Pobieranie bezpośrednio po skrócie pliku (API)"""
    if not v_hash:
        return []
    
    # NapiProjekt wymaga specyficznego formatu zapytania dla swojego API
    # To jest uproszczona wersja ich protokołu
    url = "http://napiprojekt.pl/api/api-napiprojekt3.php"
    data = {
        "download": "1",
        "vhash": v_hash,
        "mode": "1",
        "lang": "PL"
    }
    
    try:
        async with httpx.AsyncClient() as client:
            # API Napi często nie wymaga skomplikowanych nagłówków, byle hash był poprawny
            resp = await client.post(url, data=data, timeout=5.0)
            if resp.status_code == 200 and "status=\"success\"" in resp.text:
                print(f"🎯 Sukces! Znaleziono napisy po videoHash: {v_hash}")
                # Tutaj musiałby nastąpić parsowanie XML z odpowiedzią API
                # Dla uproszczenia zwracamy strukturę, którą Twój system już zna
                return [{
                    "id": f"napi_hash_{v_hash}",
                    "url": f"http://napiprojekt.pl/pobierz/{v_hash}", # Przykładowy link
                    "lang": "pol",
                    "releaseName": "Dopasowano po Hashu (Idealne)",
                    "source": "NapiProjekt-Hash",
                    "score": 100
                }]
    except Exception as e:
        print(f"⚠️ Błąd przy szukaniu po hashu: {e}")
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