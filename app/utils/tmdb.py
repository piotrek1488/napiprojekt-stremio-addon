import os
import httpx
import logging
from dotenv import load_dotenv

# Wczytuje zmienne z pliku .env do środowiska procesów
load_dotenv()

# Pobiera klucz ze zmiennej środowiskowej
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

async def get_movie_details(imdb_id: str):
    """
    Mapuje IMDb ID na polski tytuł, oryginalny tytuł i rok.
    """
    if not TMDB_API_KEY:
        logging.error("Brak klucza TMDB_API_KEY!")
        return None

    async with httpx.AsyncClient() as client:
        try:
            url = f"https://api.themoviedb.org/3/find/{imdb_id}"
            params = {
                "api_key": TMDB_API_KEY,
                "external_source": "imdb_id",
                "language": "pl-PL" # Pobieramy polskie dane, ale oryginał też tam będzie
            }
            
            response = await client.get(url, params=params, timeout=3.0)
            response.raise_for_status()
            data = response.json()

            results = data.get("movie_results") or data.get("tv_results")
            
            if results:
                res = results[0]
                # Tytuł polski (zależny od language=pl-PL)
                title_pl = res.get("title") or res.get("name")
                
                # KLUCZOWA ZMIANA: Pobieramy tytuł oryginalny (zazwyczaj angielski)
                title_orig = res.get("original_title") or res.get("original_name")
                
                release_date = res.get("release_date") or res.get("first_air_date")
                year = release_date.split("-")[0] if release_date else ""
                
                return {
                    "title": title_pl,
                    "original_title": title_orig, # Teraz main.py to zobaczy!
                    "year": year,
                    "full_query": f"{title_pl} {year}".strip()
                }
        except Exception as e:
            logging.error(f"Błąd TMDB dla {imdb_id}: {e}")
            
    return None