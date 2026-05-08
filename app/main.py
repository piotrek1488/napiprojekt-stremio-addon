"""
Stremio Subtitle Addon — NapiProjekt (via Real-Debrid) + OpenSubtitles

Flow:
  1. Find video file on RD by videoSize
  2. Download 10MB → MD5 hash → NapiProjekt dl.php → subtitles
  3. Fallback: OpenSubtitles download API
  4. Serve cached SRT via /serve-srt/ endpoint
"""

import urllib.parse, os, traceback, re, time
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import logging

from app.providers.opensubtitles import search_opensubtitles, download_opensubtitles_srt
from app.utils.scoring import score_subtitles
from app.cache import subtitle_cache
from app.utils.tmdb import get_movie_details
from app.utils.napi_decoder import download_by_hash
from app.utils.rd_napi import get_napi_from_rd, get_rd_files

load_dotenv()
with open("version", "r") as f:
    app_version = f.read().strip()

MASK_PARAMS = ["rd_token", "os_api_key"]

def mask(token: str, show: int = 4) -> str:
    if not token or len(token) <= show * 2: return "***"
    return f"{token[:show]}...{token[-show:]}"

def mask_url(url: str) -> str:
    for param in MASK_PARAMS:
        url = re.sub(
            rf'({param}=)([A-Za-z0-9_\-]{{4}})([A-Za-z0-9_\-]+)',
            lambda m: f"{m.group(1)}{m.group(2)}...",
            url
        )
    return url


class TokenMaskFilter(logging.Filter):
    def filter(self, record):
        # uvicorn access log args: (client_addr, method, path, http_version, status_code)
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            args[2] = mask_url(str(args[2]))  # mask path (index 2)
            record.args = tuple(args)
        elif isinstance(record.args, tuple) and len(record.args) > 0:
            record.args = tuple(mask_url(str(a)) if isinstance(a, str) else a for a in record.args)
        return True


# Apply filter to uvicorn access logger at import time
_filter = TokenMaskFilter()
for _logger_name in ("uvicorn.access", "uvicorn"):
    logging.getLogger(_logger_name).addFilter(_filter)

def parse_user_config(request: Request, userdata: str = "") -> dict:
    """
    Parse user config from both sources:
    - Query params: ?rd_token=X&os_api_key=Y (custom install / index.html)
    - Path segment: /rd_token=X&os_api_key=Y/manifest.json (Stremio store)
    """
    config = {}

    # From path segment (Stremio store format)
    if userdata:
        try:
            decoded = urllib.parse.unquote(userdata)
            parsed = urllib.parse.parse_qs(decoded)
            config = {k: v[0] for k, v in parsed.items()}
        except Exception:
            pass

    # Query params override path segment
    for key in ["rd_token", "os_api_key", "os_fallback", "always_os"]:
        val = request.query_params.get(key)
        if val is not None:
            config[key] = val

    return config

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


def mask(token: str, show: int = 4) -> str:
    if not token or len(token) <= show * 2: return "***"
    return f"{token[:show]}...{token[-show:]}"




async def index(request: Request):
    host = request.headers.get("host", "127.0.0.1:8081")
    protocol = "https" if request.url.scheme == "https" or "duckdns" in host or "onrender" in host else "http"
    full_url = f"{protocol}://{host}"
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            content = f.read()
        for old, new in [("{public_url}", full_url), ("{stremio_url}", f"stremio://{host}/manifest.json"),
                         ("{version_placeholder}", app_version),
                         ("{rd_token_prefill}", request.query_params.get("rd_token", "")),
                         ("{os_api_key_prefill}", request.query_params.get("os_api_key", ""))]:
            content = content.replace(old, new)
        return HTMLResponse(content=content)
    except FileNotFoundError:
        return HTMLResponse("<h1>static/index.html not found</h1>", status_code=404)

app.add_api_route("/", index, methods=["GET", "HEAD"])
app.add_api_route("/configure", index, methods=["GET", "HEAD"])

@app.get("/version")
async def version():
    return PlainTextResponse(app_version)


# --- MANIFEST ---

@app.get("/manifest.json")
@app.get("/{userdata}/manifest.json")
async def get_manifest(request: Request):
    host = request.headers.get("host", "127.0.0.1:8081")
    protocol = "https" if request.url.scheme == "https" or "duckdns" in host or "127.0.0.1" in host else "http"
    base = f"{protocol}://{host}"
    return {
        "id": "org.stremio.addon.napiprojekt",
        "version": app_version,
        "name": "NapiProjekt Addon",
        "description": "Polskie napisy z NapiProjekt (via RD) + OpenSubtitles. Dodatek wymaga konta Real-Debrid",
        "logo": f"{base}/static/icon.png",
        "types": ["movie", "series"],
        "resources": [{"name": "subtitles", "types": ["movie", "series"], "idPrefixes": ["tt"]}],
        "catalogs": [],
        "behaviorHints": {"configurable": True},
        "config": [
            {"key": "rd_token", "type": "password", "title": "Real-Debrid Token", "required": True},
            {"key": "os_api_key", "type": "password", "title": "OpenSubtitles API Key (opcjonalny)", "required": False},
            {"key": "os_fallback", "type": "checkbox", "title": "Fallback do OpenSubtitles gdy brak napisów w NapiProjekt", "default": "checked"},
            {"key": "always_os", "type": "checkbox", "title": "Zawsze szukaj w OpenSubtitles (niezależnie od NapiProjekt)"},
        ],
        "stremioAddonsConfig": {
            "issuer": "https://stremio-addons.net",
            "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0..8GEfZoX-pSQeyE7PK2z-Mw.wq9pv8MPz-jU21FOWy5xl1EpMWudBExSGXZAyIpbLT5Rv2qyhkv2XzeAe14tbBNreBIWMR-iydnQPaoZrP0VI6JACi-AWaRPvuFC_UOrjtP4s54WeTwq3uYYIhGHvjdC.Ffb2OILY1gnVYz4SwCeAVQ"
        },
    }


# --- SUBTITLES ---

@app.get("/{userdata}/subtitles/{type}/{id}/{extra:path}")
@app.get("/{userdata}/subtitles/{type}/{id}.json")
@app.get("/subtitles/{type}/{id}/{extra:path}")
@app.get("/subtitles/{type}/{id}.json")
async def get_subtitles(type: str, id: str, request: Request, extra: str = None, userdata: str = ""):
    cfg = parse_user_config(request, userdata)
    os_api_key = cfg.get("os_api_key")
    rd_token = cfg.get("rd_token")
    os_fallback = cfg.get("os_fallback", "true").lower() == "true"
    always_os = cfg.get("always_os", "false").lower() == "true"
    if not rd_token:
        return {"subtitles": []}

    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id

    print(f"🔑 RD: {mask(rd_token)} | OS: {mask(os_api_key)} | fallback={os_fallback} | always_os={always_os}")

    clean_id = id.replace(".json", "")
    imdb_id = clean_id.split(":")[0] if ":" in clean_id else clean_id

    # Build host URL — always with scheme and port
    host_url = os.getenv("BASE_URL", "").strip().rstrip("/")
    if not host_url:
        fwd_proto = request.headers.get("x-forwarded-proto", "")
        fwd_host = request.headers.get("x-forwarded-host", "")
        if fwd_proto and fwd_host:
            host_url = f"{fwd_proto}://{fwd_host}"
        else:
            raw = f"{request.url.scheme}://{request.url.netloc}"
            host_url = raw

    # Ensure scheme is present
    if host_url and not host_url.startswith("http"):
        host_url = f"https://{host_url}"

    print(f"🔗 Host URL: {host_url}")

    # Parse extra params
    video_hash, release_name, video_size = "", "", ""
    if extra:
        parsed = urllib.parse.parse_qs(extra.replace(".json", ""))
        video_hash = parsed.get("videoHash", [""])[0]
        release_name = parsed.get("filename", [""])[0]
        video_size = parsed.get("videoSize", [""])[0]

    print(f"🎬 {imdb_id} | size={video_size} | hash={video_hash}")

    # First cold request from Stremio has no videoSize yet
    # Return empty to avoid duplicating OS results when Stremio merges both responses
    if not video_size:
        print(f"⏭️ Cold request (no videoSize) — zwracam pustą listę")
        return {"subtitles": []}

    # TMDB title (for display)
    movie_info = await get_movie_details(imdb_id)
    title = movie_info.get("original_title", "") if movie_info else ""
    print(f"📋 {title}" if title else "📋 (no TMDB)")

    # Cache key — include videoSize so cold request (no size) is separate
    cache_key = f"{type}_{imdb_id}_{video_hash}_{video_size}"
    if cache_key in subtitle_cache:
        print(f"💾 Cache hit")
        return {"subtitles": subtitle_cache[cache_key]}

    all_subs = []

    # === 1. NapiProjekt via Real-Debrid ===
    if rd_token and video_size:
        # Check if we already have NAPI for this file (from previous request)
        srt_key = f"rd_{imdb_id}_{video_size}"
        existing_napi = subtitle_cache.get(srt_key)
        if existing_napi:
            print(f"✅ NAPI (cached) 🚀")
            all_subs.append({
                "id": f"NapiProjekt • {title or imdb_id}",
                "url": f"{host_url}/serve-srt/{srt_key}.srt",
                "lang": "pol",
            })
        else:
            print(f"⚡ [1/2] RD+Napi")
            try:
                napi_text = await get_napi_from_rd(rd_token, video_size)
                if napi_text:
                    print("✅ NAPI 🚀")
                    subtitle_cache[srt_key] = napi_text
                    all_subs.append({
                        "id": f"NapiProjekt • {title or imdb_id}",
                        "url": f"{host_url}/serve-srt/{srt_key}.srt",
                        "lang": "pol",
                    })
            except Exception as e:
                print(f"❌ RD/Napi: {e}")
                traceback.print_exc()

    # === 2. OpenSubtitles ===
    # always_os=true  → szukaj zawsze
    # os_fallback=true → szukaj tylko gdy brak NAPI
    # oba false       → nie szukaj w OS
    napi_found = bool(all_subs)
    use_os = os_api_key and (always_os or (os_fallback and not napi_found))
    if use_os:
        print(f"📡 [2/2] OpenSubtitles ({'zawsze' if always_os else 'fallback - brak NAPI'})")
        try:
            os_results = await search_opensubtitles(imdb_id, os_api_key)
            for sub in os_results[:5]:
                fid = sub.get("file_id")
                if not fid: continue
                srt_key_os = f"os_{fid}"
                srt_text = subtitle_cache.get(srt_key_os) or await download_opensubtitles_srt(fid, os_api_key)
                if srt_text:
                    subtitle_cache[srt_key_os] = srt_text
                    release = sub.get('releaseName', '?')
                    all_subs.append({
                        "id": f"OpenSubtitles • {release}",
                        "url": f"{host_url}/serve-srt/{srt_key_os}.srt",
                        "lang": "pol",
                    })
        except Exception as e:
            print(f"❌ OS: {e}")
    elif not use_os and os_api_key:
        print(f"📡 [2/2] OpenSubtitles pominięte (NAPI znalazło napisy)")

    result = score_subtitles(all_subs, release_name)
    subtitle_cache[cache_key] = result
    print(f"📤 {len(result)} napisów")
    return {"subtitles": result}


# --- SRT PROXY ---

@app.get("/serve-srt/{cache_key}.srt")
async def serve_srt(cache_key: str):
    srt_text = subtitle_cache.get(cache_key)
    if not srt_text:
        return Response(content="Not found", status_code=404)
    return Response(content=srt_text, media_type="text/plain; charset=utf-8",
        headers={"Content-Type": "text/plain; charset=utf-8", "Access-Control-Allow-Origin": "*"})


# --- DEBUG ---

@app.get("/debug/rd-files")
async def debug_rd(request: Request):
    """List all RD files with sizes. Usage: /debug/rd-files?rd_token=XXX"""
    rd_token = request.query_params.get("rd_token")
    if not rd_token:
        return JSONResponse({"error": "?rd_token=XXX"})
    return JSONResponse(await get_rd_files(rd_token))


@app.get("/debug/napi-raw")
async def debug_napi_raw(request: Request):
    """Show raw NapiProjekt response before conversion. ?hash=<32hex>"""
    import httpx
    from app.utils.napi_decoder import get_subhash, NAPI_DL_URL, _extract_subtitle
    h = request.query_params.get("hash")
    if not h or len(h) != 32:
        return JSONResponse({"error": "?hash=<32 hex chars>"})

    subhash = get_subhash(h)
    params = {"v": "dreambox", "kolejka": "false", "nick": "", "pass": "",
              "napios": "Linux", "l": "PL", "f": h, "t": subhash}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(NAPI_DL_URL, params=params)

    content = resp.content
    # Try to decode raw without conversion
    raw_text = None
    for enc in ['utf-8', 'windows-1250', 'iso-8859-2', 'latin-1']:
        try:
            raw_text = content.decode(enc)
            break
        except: continue

    first_lines = raw_text[:500] if raw_text else None
    # Check for FPS in first line (MicroDVD format)
    fps_info = None
    if raw_text:
        import re
        m = re.match(r'^\{(\d+)\}\{(\d+)\}(.+)', raw_text.strip())
        if m and m.group(1) == "1" and m.group(2) == "1":
            fps_info = f"FPS w nagłówku: {m.group(3)}"
        sq = re.match(r'^\[(\d+)\]\[(\d+)\](.+)', raw_text.strip())
        if sq and sq.group(1) == "1" and sq.group(2) == "1":
            fps_info = f"FPS w nagłówku: {sq.group(3)}"

    return JSONResponse({
        "hash": h,
        "status": resp.status_code,
        "size": len(content),
        "format_marker": content[:4].hex(),
        "fps_header": fps_info,
        "raw_preview": first_lines[:400] if first_lines else None
    })
    """Test NapiProjekt hash. Usage: /debug/napi?hash=<32hex>"""
    h = request.query_params.get("hash")
    if not h or len(h) != 32:
        return JSONResponse({"error": "?hash=<32 hex chars>"})
    srt = await download_by_hash(h)
    return JSONResponse({"hash": h, "found": srt is not None, "length": len(srt) if srt else 0,
                         "preview": srt[:200] if srt else None})


@app.get("/debug/rd-napi")
async def debug_rd_napi(request: Request):
    """Full pipeline test. Usage: /debug/rd-napi?rd_token=X&video_size=Y"""
    rd_token = request.query_params.get("rd_token")
    video_size = request.query_params.get("video_size")
    if not rd_token or not video_size:
        return JSONResponse({"error": "?rd_token=X&video_size=Y"})
    srt = await get_napi_from_rd(rd_token, video_size)
    return JSONResponse({"video_size": video_size, "found": srt is not None,
                         "length": len(srt) if srt else 0})


# --- LEGACY ---

@app.get("/fetch-napi/{v_hash}.srt")
async def fetch_napi_proxy(v_hash: str):
    srt = await download_by_hash(v_hash) if len(v_hash) == 32 else None
    if srt: return Response(content=srt, media_type="text/plain; charset=utf-8")
    return Response(content="Not found", status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
