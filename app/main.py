import urllib.parse
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.providers.napiprojekt import scrape_napiprojekt
from app.providers.opensubtitles import search_opensubtitles
from app.utils.scoring import score_subtitles
from app.cache import subtitle_cache
from app.utils.tmdb import get_movie_details
import os
from dotenv import load_dotenv

load_dotenv() # Wczytuje plik .env

# Pobieramy base_url z .env, a jeśli go nie ma, używamy 127.0.0.1
port = int(os.getenv("PORT", 7000))
# Jeśli nie ma BASE_URL w .env, domyślnie używamy localhost
base_url = os.getenv("BASE_URL", "127.0.0.1")

app = FastAPI()

# Niezbędne dla Stremio!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montowanie plików statycznych (np. dla CSS/obrazków)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- FRONTEND ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Dynamiczne pobieranie hosta (obsługuje localhost, Render, własne domeny)
    host = request.headers.get("host", "127.0.0.1:7000")
    
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
            
        # Podmiana placeholderów w HTML
        rendered_content = content.replace("{public_url}", host)
        rendered_content = rendered_content.replace("{stremio_url}", f"stremio://{host}")
        
        return HTMLResponse(content=rendered_content)
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Błąd: Plik static/index.html nie istnieje!</h1>", 
            status_code=404
        )

# --- STREMIO ADDON LOGIC ---

MANIFEST = {
    "id": "org.stremio.addon.napiprojekt",
    "version": "1.0.0",
    "name": "NapiProjekt Stremio Addon",
    "description": "Polskie napisy z NapiProjekt, OpenSubtitles i systemem dopasowania.",
    "logo": f"{base_url}/static/icon.png",
    "background": "",
    "types": ["movie", "series"],
    "catalogs": [],
    "resources": ["subtitles"]
}

@app.get("/manifest.json")
async def get_manifest():
    return MANIFEST

# FIX: Dodano {extra:path}, aby FastAPI przyjmowało długie ciągi znaków z ukośnikami
@app.get("/subtitles/{type}/{id}/{extra:path}")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, extra: str = None):
    # 1. Oczyszczanie ID (obsługa tt12345, tt12345.json oraz tt12345:1:1)
    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id
    
    print(f"✅ Zapytanie: {type} | ID: {imdb_id} | Extra: {extra}")

    # 2. Sprawdzamy Cache (używamy clean_id, żeby uniknąć problemów z .json)
    cache_key = f"{type}_{clean_id}_{extra}"
    if cache_key in subtitle_cache:
        print("🚀 [CACHE] Zwracam z pamięci podręcznej")
        return {"subtitles": subtitle_cache[cache_key]}
        
    all_subtitles = []

    # 3. Mapowanie tytułu przez TMDB (Kluczowe dla NapiProjekt)
    movie_info = await get_movie_details(imdb_id)
    # Jeśli TMDB zawiedzie, używamy ID jako zapytania ratunkowego
    search_query = movie_info["full_query"] if movie_info and "full_query" in movie_info else imdb_id
    
    print(f"🔍 Szukam napisów dla: {search_query}")
    
    # 4. Scrapowanie NapiProjekt
    try:
        napi_results = await scrape_napiprojekt(search_query)
        all_subtitles.extend(napi_results)
    except Exception as e:
        print(f"❌ Błąd NapiProjekt: {e}")
    
    # 5. Fallback do OpenSubtitles (jeśli mało wyników)
    if len(all_subtitles) < 2:
        try:
            os_results = await search_opensubtitles(imdb_id)
            all_subtitles.extend(os_results)
        except Exception as e:
            print(f"❌ Błąd OpenSubtitles: {e}")
        
    # 6. Release matching (wyciąganie nazwy pliku z parametrów Stremio)
    release_name = ""
    if extra:
        # Extra często wygląda tak: filename=Lord.of.the.Rings.mkv&videoSize=...
        # Musimy to zdekodować
        try:
            # Niektóre wersje Stremio nie dają 'filename=' na początku, tylko po prostu nazwę
            if "filename=" in extra:
                parsed_extra = urllib.parse.parse_qs(extra)
                release_name = parsed_extra.get("filename", [""])[0]
            else:
                release_name = extra.split("/")[-1] # Próba wyciągnięcia ostatniego członu
        except:
            release_name = ""
            
    # 7. Scoring (sortowanie po dopasowaniu do wersji)
    scored = score_subtitles(all_subtitles, release_name)
    
    # 8. Formatowanie pod Stremio
    stremio_subtitles = []
    for sub in scored:
        score = sub.get("score", 0)
        source = sub.get("source", "N/A")
        rel_name = sub.get("releaseName", "Unknown")
        
        stremio_subtitles.append({
            "id": sub["id"],
            "url": sub["url"],
            "lang": sub.get("lang", "pol"),
            "title": f"[{source}] {rel_name} (Match: {score}%)"
        })
        
    # Zapis w Cache i odpowiedź
    subtitle_cache[cache_key] = stremio_subtitles
    return {"subtitles": stremio_subtitles}