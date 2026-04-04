import urllib.parse
import os
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# Importy Twoich modułów
from app.providers.napiprojekt import scrape_napiprojekt, fetch_by_hash
from app.providers.opensubtitles import search_opensubtitles
from app.utils.scoring import score_subtitles
from app.cache import subtitle_cache
from app.utils.tmdb import get_movie_details
from app.utils.napi_decoder import get_napi_subtitles_text
from app.utils.rd_napi import get_napi_from_rd

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# --- FRONTEND ---

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request):
    host = request.headers.get("host", "127.0.0.1:7000")
    protocol = "https" if "onrender.com" in host else "http"
    full_url = f"{protocol}://{host}"
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        rendered_content = content.replace("{public_url}", full_url)
        rendered_content = rendered_content.replace("{stremio_url}", f"stremio://{host}/manifest.json")
        return HTMLResponse(content=rendered_content)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Błąd: Plik static/index.html nie istnieje!</h1>", status_code=404)

# --- STREMIO MANIFEST ---

@app.get("/manifest.json")
async def get_manifest(request: Request):
    rd_token = request.query_params.get("rd_token", "")
    host = request.headers.get("host", "127.0.0.1:7000")
    protocol = "https" if "onrender.com" in host else "http"
    
    return {
        "id": "org.stremio.addon.napiprojekt.v2",
        "version": "1.0.11",
        "name": "NapiProjekt & OS PL",
        "description": "Polskie napisy z NapiProjekt oraz OpenSubtitles.",
        "logo": f"{base}/static/icon.png",
        "types": ["movie", "series"],
        "resources": [
            {
                "name": "subtitles",
                "types": ["movie", "series"],
                "id_prefixes": ["tt"]
            }
        ],
        "catalogs": [],
        "behaviorHints": {
            "configurable": True
        },
        "endpoints": [
            {
                "type": "subtitles",
                "url": f"{base}/subtitles/{{type}}/{{id}}.json?rd_token={rd_token}"
            }
        ]
    }

# --- GŁÓWNY ENDPOINT NAPISÓW ---

@app.get("/subtitles/{type}/{id}/{extra:path}")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, request: Request, extra: str = None):
    rd_token = request.query_params.get("rd_token")
    if rd_token:
        print("🔑 RD token detected")
    if not rd_token:
        return {"subtitles": []}
    # 1. Przygotowanie ID i hosta
    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id
    host_url = f"{request.url.scheme}://{request.url.netloc}"
    
    video_hash = ""
    release_name = ""
    video_size = ""

    # 2. Wyciąganie hasha i nazwy pliku
    if extra:
        clean_extra = extra.replace(".json", "")
        if "videoHash=" in clean_extra:
            parsed = urllib.parse.parse_qs(clean_extra)
            video_hash = parsed.get("videoHash", [""])[0]
            release_name = parsed.get("filename", [""])[0]
        if "videoSize=" in clean_extra:
            parsed = urllib.parse.parse_qs(clean_extra)
            video_size = parsed.get("videoSize", [""])[0]
    
    print(f"🎬 Zapytanie: {imdb_id} | Hash: {video_hash}")

    # 3. NOWA SEKCJA: Pobieranie danych o filmie i definicja search_query
    movie_info = await get_movie_details(imdb_id)
    if movie_info and "full_query" in movie_info:
        search_query = movie_info["full_query"]
    else:
        search_query = imdb_id # Fallback do tt1234567 jeśli TMDB zawiedzie

    # 4. Cache
    cache_key = f"{type}_{imdb_id}_{video_hash}"
    if cache_key in subtitle_cache:
        return {"subtitles": subtitle_cache[cache_key]}
        
    all_subtitles = []

    # Próbujemy wyciągnąć tytuł oryginalny (angielski)
    original_title = movie_info.get("original_title", "")
    polish_title = movie_info.get("title", "")

    # --- NOWY BLOK: Real-Debrid + Napi ---
    if rd_token and video_size:
        print("⚡ RD: szukam pliku po size:", video_size)

        try:
            napi_text = get_napi_from_rd(rd_token, video_size)

            if napi_text:
                print("✅ Napi znalezione przez RD!")

                return {
                    "subtitles": [
                        {
                            "id": "napi_rd",
                            "url": f"{host_url}/rd-napi.srt?rd_token={rd_token}&video_size={video_size}",
                            "lang": "pol",
                            "title": "[NAPI] Dopasowane (Real-Debrid) 🚀"
                        }
                    ]
                }
        except Exception as e:
            print("❌ RD/Napi error:", e)

# 5. NapiProjekt: Hash + Title (English & Polish)
    napi_results = []
    
    if video_hash:
        napi_results.append({
            "id": f"napi_h_{video_hash}",
            "url": f"{host_url}/fetch-napi/{video_hash}.srt",
            "lang": "pol",
            "title": "󠀠[NAPI] Dopasowane (Hash) 🎯"
        })
    
    # Szukanie po tytule ORYGINALNYM (największa skuteczność)
    if original_title:
        safe_orig = urllib.parse.quote(original_title)
        napi_results.append({
            "id": f"napi_t_orig_{safe_orig}",
            "url": f"{host_url}/fetch-napi-title/{safe_orig}.srt",
            "lang": "pol",
            "title": f"󠀠[NAPI] Szukaj: {original_title} 🔍"
        })

    # Szukanie po tytule POLSKIM (jako backup)
    if polish_title and polish_title != original_title:
        safe_pl = urllib.parse.quote(polish_title)
        napi_results.append({
            "id": f"napi_t_pl_{safe_pl}",
            "url": f"{host_url}/fetch-napi-title/{safe_pl}.srt",
            "lang": "pol",
            "title": f"󠀠[NAPI] Szukaj: {polish_title} 🔍"
        })
    
    all_subtitles.extend(napi_results)

    # 6. PRÓBA 2: OpenSubtitles (Fallback)
    try:
        os_results = await search_opensubtitles(imdb_id)
        all_subtitles.extend(os_results)
    except Exception as e:
        print(f"❌ Błąd OpenSubtitles: {e}")

    # 7. Scoring i Formatowanie
    scored = score_subtitles(all_subtitles, release_name)
    
    stremio_subtitles = []
    for sub in scored:
        stremio_subtitles.append({
            "id": sub["id"],
            "url": sub["url"],
            "lang": "pol",
            "title": f"[{sub.get('source', 'N/A')}] {sub.get('releaseName', 'Unknown')} ({sub.get('score', 0)}%)"
        })
        
    subtitle_cache[cache_key] = stremio_subtitles
    return {"subtitles": stremio_subtitles}

# --- PROXY: POBIERANIE, DEKODOWANIE I ROZPAKOWYWANIE ---

@app.get("/fetch-napi/{v_hash}.srt")
async def fetch_napi_proxy(v_hash: str):
    """
    Ten endpoint jest wywoływany przez Stremio, gdy użytkownik wybierze napisy NapiProjekt.
    Pobiera XML, rozpakowuje 7zip hasłem i zwraca czysty tekst SRT.
    """
    print(f"📡 Proxy: Pobieram napisy dla hasha {v_hash}")
    subs_text = await get_napi_subtitles_text(v_hash)
    
    if subs_text:
        return Response(
            content=subs_text,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename={v_hash}.srt",
                "Content-Type": "text/plain; charset=utf-8"
            }
        )
    return Response(content="Nie znaleziono napisów lub błąd dekodowania.", status_code=404)

@app.get("/fetch-napi-title/{title}.srt")
async def fetch_napi_title_proxy(title: str):
    decoded_title = urllib.parse.unquote(title)
    print(f"📡 Proxy: Szukam napisów po tytule: {decoded_title}")
    
    # Wywołujemy decoder z parametrem title zamiast hash
    subs_text = await get_napi_subtitles_text(title=decoded_title)
    
    if subs_text:
        return Response(
            content=subs_text,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=napi_search.srt",
                "Content-Type": "text/plain; charset=utf-8"
            }
        )
    return Response(content="Nie znaleziono napisów dla tego tytułu.", status_code=404)

@app.get("/rd-napi.srt")
async def rd_napi(request: Request):
    rd_token = request.query_params.get("rd_token")
    video_size = request.query_params.get("video_size")

    if not rd_token or not video_size:
        return Response(content="Brak danych", status_code=400)

    subs = get_napi_from_rd(rd_token, video_size)

    if subs:
        return Response(
            content=subs,
            media_type="text/plain",
            headers={"Content-Type": "text/plain; charset=utf-8"}
        )

    return Response(content="Brak napisów", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)