import urllib.parse
import os
import traceback
import unicodedata
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from fastapi.responses import PlainTextResponse

from app.providers.napiprojekt import scrape_napiprojekt, fetch_by_hash
from app.providers.opensubtitles import search_opensubtitles, download_opensubtitles_srt
from app.utils.scoring import score_subtitles
from app.cache import subtitle_cache
from app.utils.tmdb import get_movie_details
from app.utils.napi_decoder import get_napi_subtitles_text
from app.utils.rd_napi import get_napi_from_rd

load_dotenv()
with open("version", "r") as f:
    app_version = f.read().strip()

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

def mask_token(token: str, show=4) -> str:
    if not token or len(token) <= show * 2:
        return "*" * len(token)
    return f"{token[:show]}{'*' * (len(token)-show*2)}{token[-show:]}"

@app.get("/version")
async def version():
    try:
        with open("version", "r") as f:
            content = f.read().strip()
        return PlainTextResponse(content)
    except FileNotFoundError:
        return PlainTextResponse("Plik version nie istnieje", status_code=404)

async def index(request: Request):
    host = request.headers.get("host", "127.0.0.1:7000")
    protocol = "https" if "onrender.com" in host else "http"
    full_url = f"{protocol}://{host}"
    rd_token = request.query_params.get("rd_token") or ""
    os_api_key = request.query_params.get("os_api_key") or ""
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        rendered_content = content.replace("{public_url}", full_url)
        rendered_content = rendered_content.replace("{stremio_url}", f"stremio://{host}/manifest.json")
        rendered_content = rendered_content.replace("{version_placeholder}", app_version)
        rendered_content = rendered_content.replace("{rd_token_prefill}", rd_token)
        rendered_content = rendered_content.replace("{os_api_key_prefill}", os_api_key)
        return HTMLResponse(content=rendered_content)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Błąd: Plik static/index.html nie istnieje!</h1>", status_code=404)
app.add_api_route("/", index, methods=["GET", "HEAD"])
app.add_api_route("/configure", index, methods=["GET", "HEAD"])

@app.get("/manifest.json")
async def get_manifest(request: Request):
    try:
        rd_token = request.query_params.get("rd_token") or ""
        os_api_key = request.query_params.get("os_api_key") or ""
        host = request.headers.get("host", "127.0.0.1:7000")
        protocol = "https" if "onrender.com" in host else "http"
        base = f"{protocol}://{host}"
        print("📦 Manifest request | token:", mask_token(rd_token)) if rd_token else print("📦 Manifest request | token: NONE")

        return {
            "id": "org.stremio.addon.napiprojekt",
            "version": f"{app_version}",
            "name": "NapiProjekt Addon",
            "description": "Polskie napisy z NapiProjekt oraz OpenSubtitles.",
            "logo": f"{base}/static/icon.png",
            "types": ["movie", "series"],
            "resources": [{"name": "subtitles", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
            "catalogs": [],
            "behaviorHints": {"configurable": True},
            "config": [
                {"name": "rd_token", "type": "string", "title": "Real-Debrid Token", "description": "Twój token Real-Debrid", "default": ""},
                {"name": "os_api_key", "type": "string", "title": "OpenSubtitles API Key", "description": "Twój klucz API do OpenSubtitles", "default": ""}
            ],
            "endpoints": [{"type": "subtitles", "url": f"{base}/subtitles/{{type}}/{{id}}.json?rd_token={{rd_token}}&os_api_key={{os_api_key}}"}]
        }
    except Exception as e:
        traceback.print_exc()
        return {"error": "manifest failed"}

# --- GŁÓWNY ENDPOINT NAPISÓW ---

@app.get("/subtitles/{type}/{id}/{extra:path}")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, request: Request, extra: str = None):
    os_api_key = request.query_params.get("os_api_key")
    rd_token = request.query_params.get("rd_token")
    if rd_token:
        print("🔑 RD token detected")
    if not rd_token:
        return {"subtitles": []}

    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id
    host_url = f"{request.url.scheme}://{request.url.netloc}"

    video_hash = ""
    release_name = ""
    video_size = ""

    if extra:
        clean_extra = extra.replace(".json", "")
        parsed = urllib.parse.parse_qs(clean_extra)
        video_hash = parsed.get("videoHash", [""])[0]
        release_name = parsed.get("filename", [""])[0]
        video_size = parsed.get("videoSize", [""])[0]

    print(f"🎬 Zapytanie: {imdb_id} | Hash: {video_hash} | Size: {video_size}")

    # TMDB lookup
    movie_info = await get_movie_details(imdb_id)
    original_title = ""
    polish_title = ""
    year = ""
    if movie_info:
        original_title = movie_info.get("original_title", "")
        polish_title = movie_info.get("title", "")
        if movie_info.get("release_date"):
            year = movie_info["release_date"][:4]
        elif movie_info.get("year"):
            year = str(movie_info["year"])

    print(f"📋 Film: {original_title} / {polish_title} ({year})")

    cache_key = f"{type}_{imdb_id}_{video_hash}"
    if cache_key in subtitle_cache:
        print(f"💾 Cache hit: {cache_key}")
        return {"subtitles": subtitle_cache[cache_key]}

    all_subtitles = []

    # 1️⃣ NAPI RD (Real-Debrid) — now fully async
    if rd_token and video_size:
        print(f"⚡ RD+Napi: szukam pliku po size {video_size}")
        try:
            napi_text = await get_napi_from_rd(rd_token, video_size)
            if napi_text:
                print("✅ Napi znalezione przez RD! 🚀")
                srt_key = f"rd_{imdb_id}_{video_size}"
                subtitle_cache[srt_key] = napi_text
                all_subtitles.append({
                    "id": "napi_rd",
                    "url": f"{host_url}/serve-srt/{srt_key}.srt",
                    "lang": "pol",
                    "title": "[NAPI] Dopasowane (Real-Debrid) 🚀"
                })
        except Exception as e:
            print(f"❌ RD/Napi error: {e}")
            traceback.print_exc()

    # 2️⃣ NAPI przez tytuł — skip duplicate if titles identical
    if not all_subtitles and (original_title or polish_title):
        print(f"🔍 Napi: szukam po tytule...")
        try:
            titles_to_try = []
            if original_title:
                titles_to_try.append(original_title)
            if polish_title and polish_title != original_title:
                titles_to_try.append(polish_title)

            for search_title in titles_to_try:
                print(f"🔍 Napi: próbuję tytuł '{search_title}' ({year})")
                napi_text = await get_napi_subtitles_text(title=search_title, year=year)
                if napi_text:
                    print(f"✅ Napi znalezione po tytule: {search_title}")
                    srt_key = f"napi_title_{imdb_id}"
                    subtitle_cache[srt_key] = napi_text
                    all_subtitles.append({
                        "id": f"napi_title_{imdb_id}",
                        "url": f"{host_url}/serve-srt/{srt_key}.srt",
                        "lang": "pol",
                        "title": f"[NAPI] {search_title} 🔍"
                    })
                    break
        except Exception as e:
            print(f"❌ Napi title error: {e}")
            traceback.print_exc()

    # 3️⃣ OpenSubtitles fallback — download real SRT, serve through proxy
    if os_api_key:
        try:
            os_results = await search_opensubtitles(imdb_id, os_api_key)
            for sub in os_results[:5]:
                file_id = sub.get("file_id")
                if not file_id:
                    continue
                srt_text = await download_opensubtitles_srt(file_id, os_api_key)
                if srt_text:
                    srt_key = f"os_{file_id}"
                    subtitle_cache[srt_key] = srt_text
                    all_subtitles.append({
                        "id": sub["id"],
                        "url": f"{host_url}/serve-srt/{srt_key}.srt",
                        "lang": "pol",
                        "title": f"[OS] {sub.get('releaseName', 'Unknown')}"
                    })
            print(f"✅ OpenSubtitles: dodano {sum(1 for s in all_subtitles if s['id'].startswith('os_'))} napisów")
        except Exception as e:
            print(f"❌ OpenSubtitles error: {e}")
            traceback.print_exc()

    stremio_subtitles = score_subtitles(all_subtitles, release_name)
    subtitle_cache[cache_key] = stremio_subtitles
    print(f"📤 Zwracam {len(stremio_subtitles)} napisów dla {imdb_id}")
    return {"subtitles": stremio_subtitles}

# --- SRT PROXY ---

@app.get("/serve-srt/{cache_key}.srt")
async def serve_srt(cache_key: str):
    srt_text = subtitle_cache.get(cache_key)
    if not srt_text:
        print(f"⚠️ SRT not in cache: {cache_key}")
        return Response(content="Subtitle not found or expired", status_code=404)
    return Response(
        content=srt_text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Type": "text/plain; charset=utf-8", "Access-Control-Allow-Origin": "*"}
    )

# --- LEGACY ---

@app.get("/fetch-napi/{v_hash}.srt")
async def fetch_napi_proxy(v_hash: str):
    subs_text = await get_napi_subtitles_text(napi_hash=v_hash)
    if subs_text:
        return Response(content=subs_text, media_type="text/plain; charset=utf-8")
    return Response(content="Nie znaleziono napisów.", status_code=404)

@app.get("/fetch-napi-title/{title}.srt")
async def fetch_napi_title_proxy(title: str):
    decoded_title = unicodedata.normalize("NFC", urllib.parse.unquote(title, encoding="utf-8"))
    subs_text = await get_napi_subtitles_text(title=decoded_title)
    if subs_text:
        return Response(content=subs_text, media_type="text/plain; charset=utf-8")
    return Response(content="Nie znaleziono napisów.", status_code=404)

@app.get("/rd-napi.srt")
async def rd_napi(request: Request):
    rd_token = request.query_params.get("rd_token")
    video_size = request.query_params.get("video_size")
    if not rd_token or not video_size:
        return Response(content="Brak danych", status_code=400)
    subs = await get_napi_from_rd(rd_token, video_size)
    if subs:
        return Response(content=subs, media_type="text/plain; charset=utf-8")
    return Response(content="Brak napisów", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)
