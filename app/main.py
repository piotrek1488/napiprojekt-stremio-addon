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
from dotenv import load_dotenv

load_dotenv() # Wczytuje plik .env

app = FastAPI()

# Niezbędne dla Stremio!
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montowanie plików statycznych
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- FRONTEND ---

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request):
    host = request.headers.get("host", "127.0.0.1:7000")
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        rendered_content = content.replace("{public_url}", host)
        rendered_content = rendered_content.replace("{stremio_url}", f"stremio://{host}")
        return HTMLResponse(content=rendered_content)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Błąd: Plik static/index.html nie istnieje!</h1>", status_code=404)

# --- STREMIO ADDON LOGIC ---

@app.get("/manifest.json")
async def get_manifest(request: Request):
    # Dynamiczne logo, żeby zawsze działało (Lokalnie i na Renderze)
    host = request.headers.get("host", "127.0.0.1:7000")
    protocol = "https" if "onrender.com" in host else "http"
    
    return {
        "id": "org.stremio.addon.napiprojekt",
        "version": "1.0.3",
        "name": "NapiProjekt Stremio Addon",
        "description": "Polskie napisy z NapiProjekt, OpenSubtitles i systemem dopasowania.",
        "logo": f"{protocol}://{host}/static/icon.png",
        "types": ["movie", "series"],
        "resources": [
            {
            "name": "subtitles",
            "types": ["movie", "series"],
            "id_prefixes": ["tt"]
            }
        ],
        "catalogs": []
    }

@app.get("/subtitles/{type}/{id}/{extra:path}")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, extra: str = None):
    # 1. Oczyszczanie ID
    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id
    
    print(f"✅ Zapytanie: {type} | ID: {imdb_id} | Extra: {extra}")

    # --- LOGIKA WYCIĄGANIA HASHA (Teraz poprawnie wewnątrz funkcji) ---
    video_hash = ""
    release_name = ""

    if extra:
        # KLUCZOWA POPRAWKA: usuwamy .json z całego ciągu extra, zanim go przeparsujemy
        clean_extra = extra.replace(".json", "")
        parsed_extra = urllib.parse.parse_qs(clean_extra)
        if "videoHash" in parsed_extra:
            video_hash = parsed_extra["videoHash"][0]
            print(f"🔑 Znaleziono videoHash: {video_hash}")
        if "filename" in parsed_extra:
            release_name = parsed_extra["filename"][0]

    # 2. Sprawdzamy Cache
    cache_key = f"{type}_{clean_id}_{video_hash}"
    if cache_key in subtitle_cache:
        print("🚀 [CACHE] Zwracam z pamięci podręcznej")
        return {"subtitles": subtitle_cache[cache_key]}
        
    all_subtitles = []

    # 3. TMDB
    movie_info = await get_movie_details(imdb_id)
    search_query = movie_info["full_query"] if movie_info else imdb_id
    print(f"🔍 Szukam napisów dla: {search_query}")
    
    # 4. Scrapowanie NapiProjekt (z przekazaniem v_hash)
    try:
        napi_results = await scrape_napiprojekt(search_query, v_hash=video_hash)
        all_subtitles.extend(napi_results)
    except Exception as e:
        print(f"❌ Błąd NapiProjekt: {e}")
    
    # 5. Fallback do OpenSubtitles
    if len(all_subtitles) < 2:
        try:
            os_results = await search_opensubtitles(imdb_id)
            all_subtitles.extend(os_results)
        except Exception as e:
            print(f"❌ Błąd OpenSubtitles: {e}")
        
    # 6. Finalne ustalenie release_name do scoringu
    if not release_name and extra:
        try:
            release_name = extra.split("/")[-1] if "/" in extra else extra
        except:
            release_name = ""
            
    # 7. Scoring
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
        
    subtitle_cache[cache_key] = stremio_subtitles
    return {"subtitles": stremio_subtitles}