import os
import httpx
import logging
from dotenv import load_dotenv

load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

async def get_movie_details(imdb_id: str):
    """Mapuje IMDb ID na tytuły i rok."""
    if not TMDB_API_KEY:
        logging.error("Brak klucza TMDB_API_KEY!")
        return None

    async with httpx.AsyncClient() as client:
        try:
            url = f"https://api.themoviedb.org/3/find/{imdb_id}"
            params = {
                "api_key": TMDB_API_KEY,
                "external_source": "imdb_id",
                "language": "pl-PL"
            }
            
            response = await client.get(url, params=params, timeout=5.0)
            response.raise_for_status()
            data = response.json()

            results = data.get("movie_results") or data.get("tv_results")
            
            if results:
                res = results[0]
                title_pl = res.get("title") or res.get("name") or ""
                title_orig = res.get("original_title") or res.get("original_name") or ""
                release_date = res.get("release_date") or res.get("first_air_date") or ""
                year = release_date.split("-")[0] if release_date else ""
                
                print(f"🎬 TMDB: '{title_orig}' / '{title_pl}' ({year}) release_date={release_date}")
                
                return {
                    "title": title_pl,
                    "original_title": title_orig,
                    "year": year,
                    "release_date": release_date,
                    "full_query": f"{title_pl} {year}".strip()
                }
            else:
                print(f"⚠️ TMDB: brak wyników dla {imdb_id}")
        except Exception as e:
            logging.error(f"Błąd TMDB dla {imdb_id}: {e}")
            
    return None
