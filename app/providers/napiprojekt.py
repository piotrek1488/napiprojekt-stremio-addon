import httpx
from app.utils.retry import with_retry

async def fetch_by_hash(v_hash: str, host_url: str):
    """
    Tworzy wynik dla Stremio wskazujący na nasze wewnętrzne proxy /fetch-napi/
    """
    if not v_hash:
        return []

    # Zwracamy listę z jednym, idealnie dopasowanym wynikiem
    # Stremio wywoła 'url' dopiero, gdy użytkownik kliknie w te napisy
    return [{
        "id": f"napi_{v_hash}",
        "url": f"{host_url}/fetch-napi/{v_hash}.srt",
        "lang": "pol",
        "releaseName": "NapiProjekt (Match 100%)",
        "source": "NAPI",
        "score": 100
    }]

async def scrape_napiprojekt(query: str, v_hash: str = "", host_url: str = "http://127.0.0.1:7000"):
    """
    Główna funkcja wywoływana przez main.py.
    Ignorujemy 'query' (tekstowe szukanie), bo NapiProjekt blokuje boty na stronie WWW.
    Skupiamy się wyłącznie na v_hash i oficjalnym API.
    """
    if v_hash:
        print(f"🚀 Generuję link NapiProjekt dla hasha: {v_hash}")
        return await fetch_by_hash(v_hash, host_url)
    
    # Jeśli nie ma hasha, nie szukamy w Napi (unikamy 403 Forbidden)
    print("🔍 Brak videoHash - NapiProjekt pominięty (szukanie tekstowe zablokowane)")
    return []