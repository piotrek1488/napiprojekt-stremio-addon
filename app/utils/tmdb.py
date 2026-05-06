"""TMDB API — resolve IMDB ID to title + year."""

import os, httpx
from dotenv import load_dotenv

load_dotenv()
TMDB_API_KEY = os.getenv("TMDB_API_KEY")


async def get_movie_details(imdb_id: str) -> dict | None:
    if not TMDB_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.themoviedb.org/3/find/{imdb_id}",
                params={"api_key": TMDB_API_KEY, "external_source": "imdb_id", "language": "pl-PL"})
            data = resp.json()
            results = data.get("movie_results") or data.get("tv_results")
            if results:
                r = results[0]
                title_pl = r.get("title") or r.get("name") or ""
                title_orig = r.get("original_title") or r.get("original_name") or ""
                release = r.get("release_date") or r.get("first_air_date") or ""
                year = release.split("-")[0] if release else ""
                return {"title": title_pl, "original_title": title_orig, "year": year}
    except Exception as e:
        print(f"⚠️ TMDB: {e}")
    return None
