import httpx
from bs4 import BeautifulSoup
from app.utils.retry import with_retry

async def fetch_napiprojekt(query: str):
    async with httpx.AsyncClient() as client:
        url = f"https://www.napiprojekt.pl/szukaj?q={query}"
        response = await client.get(url, timeout=5.0)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        
        # Przykład scrapowania (symulacja klas z NapiProjekt, w praktyce klasy HTML mogą być inne)
        for idx, tag in enumerate(soup.select('.movie-title')): 
            title = tag.get_text(strip=True)
            link = tag.get('href')
            if link:
                results.append({
                    "id": f"napi_{idx}",
                    "url": f"https://www.napiprojekt.pl{link}",
                    "lang": "pol",
                    "releaseName": title,
                    "source": "NapiProjekt"
                })
        return results

async def scrape_napiprojekt(query: str):
    try:
        # Próba pobrania wyników z systemem retry
        return await with_retry(fetch_napiprojekt, query)
    except Exception as e:
        print(f"Błąd krytyczny scrapera NapiProjekt: {e}")
        return []