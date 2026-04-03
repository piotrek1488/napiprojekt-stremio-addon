import urllib.parse
import os
from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.providers.napiprojekt import scrape_napiprojekt
from app.providers.opensubtitles import search_opensubtitles
from app.utils.scoring import score_subtitles
from app.cache import subtitle_cache
from app.utils.tmdb import get_movie_details

app = FastAPI()

# Niezbędne, aby Stremio mogło odbierać odpowiedzi!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Pobieramy aktualny adres serwera (np. 127.0.0.1:8000)
    host = request.headers.get("host", "127.0.0.1:8000")
    
    try:
        # Pamiętaj, aby plik index.html był w folderze static/
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Podmieniamy nasz placeholder na rzeczywisty adres hosta
        rendered_content = content.replace("{public_url}", host)
        # Podmieniamy stremio_url na specjalny link dla aplikacji
        rendered_content = rendered_content.replace("{stremio_url}", f"stremio://{host}")
        
        return HTMLResponse(content=rendered_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Błąd: Plik static/index.html nie istnieje!</h1>", 
            status_code=404
        )

MANIFEST = {
    "id": "org.stremio.addon.napiprojekt",
    "version": "1.0.0",
    "name": "NapiProjekt Stremio Addon (Python)",
    "description": "Zaawansowany dodatek: scraping NapiProjekt, cache i fallback.",
    "types": ["movie", "series"],
    "catalogs": [],
    "resources": ["subtitles"]
}

@app.get("/manifest.json")
async def get_manifest():
    return MANIFEST

# Stremio pyta o napisy dla wideo z extra parametrami (np. filename)
@app.get("/subtitles/{type}/{id}/{extra}.json")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, extra: str = None):
    imdb_id = id.split(":")[0] if ":" in id else id
    print(f"Żądanie od Stremio: type={type}, id={id}")
    
    # 1. Sprawdzamy w Cache
    cache_key = f"{type}_{id}_{extra}"
    if cache_key in subtitle_cache:
        print("Zwracam z pamięci podręcznej!")
        return {"subtitles": subtitle_cache[cache_key]}
        
    all_subtitles = []

    # 2. Inteligentne mapowanie tytułu przez TMDB
    movie_info = await get_movie_details(imdb_id)
    search_query = movie_info["full_query"] if movie_info else imdb_id
    
    print(f"Szukam dla: {search_query}")
    
    # 3. Scrapowanie NapiProjekt
    napi_results = await scrape_napiprojekt(search_query)
    all_subtitles.extend(napi_results)
    
    # 4. Fallback do innych źródeł, gdy NapiProjekt zwróci mało
    if len(all_subtitles) < 3:
        os_results = await search_opensubtitles(id)
        all_subtitles.extend(os_results)
        
    # 5. Release matching i dopasowywanie (Scoring)
    release_name = ""
    if extra:
        # Dekodowanie np. "filename=Oppenheimer.2023.1080p.mkv"
        parsed_extra = urllib.parse.parse_qs(extra)
        if "filename" in parsed_extra:
            release_name = parsed_extra["filename"][0]
            
    scored = score_subtitles(all_subtitles, release_name)
    
    # 6. Przygotowanie formatu dla Stremio
    stremio_subtitles = []
    for sub in scored:
        score = sub.get("score", 0)
        stremio_subtitles.append({
            "id": sub["id"],
            "url": sub["url"],
            "lang": sub["lang"],
            "title": f"[{sub['source']}] {sub['releaseName']} (Waga: {score})"
        })
        
    # Zapis w Cache i odpowiedź
    subtitle_cache[cache_key] = stremio_subtitles
    return {"subtitles": stremio_subtitles}