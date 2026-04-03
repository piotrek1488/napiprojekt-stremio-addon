import httpx
import urllib.parse
from bs4 import BeautifulSoup
from app.utils.retry import with_retry

# Definiujemy nagłówki na poziomie modułu, żeby były czytelne
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
    "Referer": "https://www.napiprojekt.pl/",
    "Connection": "keep-alive"
}

async def fetch_napiprojekt(query: str):
    # Bardzo ważne: bezpieczne kodowanie znaków (np. spacje -> %20, ł -> %C5%82)
    safe_query = urllib.parse.quote(query)
    url = f"https://www.napiprojekt.pl/szukaj?q={safe_query}"
    
    # Używamy headers=HEADERS, aby ominąć błąd 403
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        print(f"📡 Wysyłam zapytanie do Napi: {url}")
        
        response = await client.get(url, timeout=10.0)
        
        # Jeśli mimo to dostaniesz 403, rzuci wyjątek i uruchomi system retry
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # Selektor .movie-title (upewnij się, że taki istnieje na stronie)
        # NapiProjekt często używa linków wewnątrz divów o konkretnych klasach
        for idx, tag in enumerate(soup.select('.movie-title')): 
            title = tag.get_text(strip=True)
            link = tag.get('href')
            
            if link:
                # Budujemy pełny URL do podstrony z napisami
                full_url = link if link.startswith('http') else f"https://www.napiprojekt.pl{link}"
                
                results.append({
                    "id": f"napi_{idx}",
                    "url": full_url,
                    "lang": "pol",
                    "releaseName": title,
                    "source": "NapiProjekt"
                })
        
        print(f"✅ Znaleziono {len(results)} wyników w NapiProjekt")
        return results

async def scrape_napiprojekt(query: str):
    try:
        # Próba pobrania wyników z Twoim systemem retry
        return await with_retry(fetch_napiprojekt, query)
    except Exception as e:
        # Tutaj wyłapiemy 403 po wszystkich nieudanych próbach
        print(f"❌ Błąd krytyczny scrapera NapiProjekt: {e}")
        return []