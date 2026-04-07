import urllib.parse
import os
import traceback
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.providers.opensubtitles import search_opensubtitles, download_opensubtitles_srt
from app.utils.scoring import score_subtitles
from app.cache import subtitle_cache
from app.utils.tmdb import get_movie_details
from app.utils.napi_decoder import download_by_napi_hash, get_napi_subtitles_text
from app.utils.rd_napi import get_napi_from_rd

load_dotenv()
with open("version", "r") as f:
    app_version = f.read().strip()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

def mask_token(t, s=4):
    if not t or len(t) <= s*2: return "*" * len(t) if t else ""
    return f"{t[:s]}{'*'*(len(t)-s*2)}{t[-s:]}"

@app.get("/version")
async def version():
    try:
        with open("version") as f: return PlainTextResponse(f.read().strip())
    except: return PlainTextResponse("?", status_code=404)

async def index(request: Request):
    host = request.headers.get("host", "127.0.0.1:7000")
    protocol = "https" if "onrender.com" in host else "http"
    full_url = f"{protocol}://{host}"
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace("{public_url}", full_url)
        content = content.replace("{stremio_url}", f"stremio://{host}/manifest.json")
        content = content.replace("{version_placeholder}", app_version)
        content = content.replace("{rd_token_prefill}", request.query_params.get("rd_token", ""))
        content = content.replace("{os_api_key_prefill}", request.query_params.get("os_api_key", ""))
        return HTMLResponse(content=content)
    except FileNotFoundError:
        return HTMLResponse("<h1>static/index.html not found</h1>", status_code=404)
app.add_api_route("/", index, methods=["GET", "HEAD"])
app.add_api_route("/configure", index, methods=["GET", "HEAD"])

@app.get("/manifest.json")
async def get_manifest(request: Request):
    host = request.headers.get("host", "127.0.0.1:7000")
    protocol = "https" if "onrender.com" in host else "http"
    base = f"{protocol}://{host}"
    return {
        "id": "org.stremio.addon.napiprojekt",
        "version": app_version,
        "name": "NapiProjekt Addon",
        "description": "Polskie napisy z NapiProjekt + OpenSubtitles.",
        "logo": f"{base}/static/icon.png",
        "types": ["movie", "series"],
        "resources": [{"name": "subtitles", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "catalogs": [],
        "behaviorHints": {"configurable": True},
        "config": [
            {"name": "rd_token", "type": "string", "title": "Real-Debrid Token", "default": ""},
            {"name": "os_api_key", "type": "string", "title": "OpenSubtitles API Key", "default": ""}
        ],
        "endpoints": [{"type": "subtitles", "url": f"{base}/subtitles/{{type}}/{{id}}.json?rd_token={{rd_token}}&os_api_key={{os_api_key}}"}]
    }

# --- SUBTITLE ENDPOINT ---

@app.get("/subtitles/{type}/{id}/{extra:path}")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, request: Request, extra: str = None):
    os_api_key = request.query_params.get("os_api_key")
    rd_token = request.query_params.get("rd_token")
    if not rd_token:
        return {"subtitles": []}
    print("🔑 RD token detected")

    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id
    host_url = f"{request.url.scheme}://{request.url.netloc}"

    video_hash, release_name, video_size = "", "", ""
    if extra:
        parsed = urllib.parse.parse_qs(extra.replace(".json", ""))
        video_hash = parsed.get("videoHash", [""])[0]
        release_name = parsed.get("filename", [""])[0]
        video_size = parsed.get("videoSize", [""])[0]

    print(f"🎬 Zapytanie: {imdb_id} | Hash: {video_hash} | Size: {video_size}")

    movie_info = await get_movie_details(imdb_id)
    original_title = ""
    polish_title = ""
    year = ""
    if movie_info:
        original_title = movie_info.get("original_title", "")
        polish_title = movie_info.get("title", "")
        year = movie_info.get("year", "")
    print(f"📋 Film: {original_title} / {polish_title} ({year})")

    cache_key = f"{type}_{imdb_id}_{video_hash}"
    if cache_key in subtitle_cache:
        print(f"💾 Cache hit")
        return {"subtitles": subtitle_cache[cache_key]}

    all_subtitles = []

    # ===================================================
    # 1️⃣ NAPIPROJEKT via Real-Debrid (hash = best match)
    # ===================================================
    napi_found = False
    if rd_token and video_size:
        print(f"⚡ [1/3] RD+Napi: szukam pliku po size {video_size}")
        try:
            napi_text = await get_napi_from_rd(rd_token, video_size)
            if napi_text:
                print("✅ NAPI PRZEZ RD! 🚀")
                srt_key = f"rd_{imdb_id}_{video_size}"
                subtitle_cache[srt_key] = napi_text
                all_subtitles.append({
                    "id": "napi_rd",
                    "url": f"{host_url}/serve-srt/{srt_key}.srt",
                    "lang": "pol",
                    "title": f"[NAPI] {original_title or polish_title} (RD) 🚀"
                })
                napi_found = True
        except Exception as e:
            print(f"❌ RD/Napi: {e}")
            traceback.print_exc()

    # ===================================================
    # 2️⃣ NAPIPROJEKT via title scraping (cloudscraper)
    #    Only if RD didn't find it
    # ===================================================
    if not napi_found and (original_title or polish_title):
        print(f"🔍 [2/3] Napi: title search (cloudscraper)...")
        try:
            titles_to_try = []
            if original_title:
                titles_to_try.append(original_title)
            if polish_title and polish_title != original_title:
                titles_to_try.append(polish_title)

            for search_title in titles_to_try:
                napi_text = await get_napi_subtitles_text(title=search_title, year=year)
                if napi_text:
                    print(f"✅ NAPI PRZEZ SCRAPING! 🎯 ({search_title})")
                    srt_key = f"napi_title_{imdb_id}"
                    subtitle_cache[srt_key] = napi_text
                    all_subtitles.append({
                        "id": f"napi_title_{imdb_id}",
                        "url": f"{host_url}/serve-srt/{srt_key}.srt",
                        "lang": "pol",
                        "title": f"[NAPI] {search_title} 🎯"
                    })
                    napi_found = True
                    break
        except Exception as e:
            print(f"❌ Napi scraping: {e}")
            traceback.print_exc()

    # ===================================================
    # 3️⃣ OPENSUBTITLES fallback
    # ===================================================
    if os_api_key:
        print(f"📡 [3/3] OpenSubtitles...")
        try:
            os_results = await search_opensubtitles(imdb_id, os_api_key)
            for sub in os_results[:5]:
                fid = sub.get("file_id")
                if not fid: continue
                srt_text = await download_opensubtitles_srt(fid, os_api_key)
                if srt_text:
                    srt_key = f"os_{fid}"
                    subtitle_cache[srt_key] = srt_text
                    all_subtitles.append({
                        "id": sub["id"],
                        "url": f"{host_url}/serve-srt/{srt_key}.srt",
                        "lang": "pol",
                        "title": f"[OS] {sub.get('releaseName', '?')}"
                    })
            print(f"✅ OS: {sum(1 for s in all_subtitles if s['id'].startswith('os_'))} napisów")
        except Exception as e:
            print(f"❌ OS: {e}")
            traceback.print_exc()

    stremio_subtitles = score_subtitles(all_subtitles, release_name)
    subtitle_cache[cache_key] = stremio_subtitles
    print(f"📤 Zwracam {len(stremio_subtitles)} napisów")
    return {"subtitles": stremio_subtitles}

# --- SRT PROXY ---

@app.get("/serve-srt/{cache_key}.srt")
async def serve_srt(cache_key: str):
    srt_text = subtitle_cache.get(cache_key)
    if not srt_text:
        return Response(content="Not found", status_code=404)
    return Response(content=srt_text, media_type="text/plain; charset=utf-8",
        headers={"Content-Type": "text/plain; charset=utf-8", "Access-Control-Allow-Origin": "*"})

# --- DEBUG ---

@app.get("/debug/napi")
async def debug_napi(request: Request):
    """
    /debug/napi?hash=<32hex>
    /debug/napi?title=Joker&year=2019
    /debug/napi?rd_token=XXX&video_size=123456
    """
    h = request.query_params.get("hash")
    title = request.query_params.get("title")
    year = request.query_params.get("year", "")
    rd = request.query_params.get("rd_token")
    vs = request.query_params.get("video_size")

    if h and len(h) == 32:
        srt = await download_by_napi_hash(h)
        return {"method": "hash", "hash": h, "found": srt is not None, "length": len(srt) if srt else 0,
                "preview": srt[:200] if srt else None}
    elif title:
        srt = await get_napi_subtitles_text(title=title, year=year)
        return {"method": "title_cloudscraper", "title": title, "year": year,
                "found": srt is not None, "length": len(srt) if srt else 0,
                "preview": srt[:200] if srt else None}
    elif rd and vs:
        srt = await get_napi_from_rd(rd, vs)
        return {"method": "rd", "video_size": vs, "found": srt is not None, "length": len(srt) if srt else 0}
    else:
        return {"error": "Podaj ?hash=<32hex> lub ?title=Joker&year=2019 lub ?rd_token=X&video_size=Y",
                "cloudscraper_available": True}

@app.get("/debug/rd-files")
async def debug_rd_files(request: Request):
    import httpx
    rd = request.query_params.get("rd_token")
    if not rd: return {"error": "Podaj ?rd_token=XXX"}
    async with httpx.AsyncClient(timeout=15) as client:
        auth = {"Authorization": f"Bearer {rd}"}
        r = await client.get(f"{RD_API}/downloads", headers=auth)
        downloads = [{"filename": d.get("filename","?")[:60], "filesize": d.get("filesize")} for d in (r.json() if r.status_code == 200 else [])]
        r = await client.get(f"{RD_API}/torrents", headers=auth)
        torrents = [{"filename": t.get("filename","?")[:60], "bytes": t.get("bytes"), "id": t.get("id")} for t in (r.json() if r.status_code == 200 else [])]
    return {"downloads": downloads, "torrents": torrents}

RD_API = "https://api.real-debrid.com/rest/1.0"

# --- LEGACY ---

@app.get("/fetch-napi/{v_hash}.srt")
async def fetch_napi_proxy(v_hash: str):
    srt = await download_by_napi_hash(v_hash) if len(v_hash) == 32 else None
    if srt: return Response(content=srt, media_type="text/plain; charset=utf-8")
    return Response(content="Not found", status_code=404)

@app.get("/rd-napi.srt")
async def rd_napi(request: Request):
    rd, vs = request.query_params.get("rd_token"), request.query_params.get("video_size")
    if not rd or not vs: return Response(content="Missing params", status_code=400)
    srt = await get_napi_from_rd(rd, vs)
    if srt: return Response(content=srt, media_type="text/plain; charset=utf-8")
    return Response(content="Not found", status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)
