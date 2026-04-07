"""
NapiProjekt subtitle decoder.

Title search strategies (in order):
  1. api-napiprojekt3.php mode=3 — various parameter combos
     (NOT behind Cloudflare! Just need right params)
  2. CF bypass scraping (curl_cffi / cloudscraper)
  3. dl.php hash download (always works if you have hash)
"""

import io
import re
import traceback
import base64
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
import asyncio

import httpx
import py7zr

# CF bypass library
CF_LIB = None
try:
    from curl_cffi import requests as curl_requests
    CF_LIB = "curl_cffi"
    print("✅ curl_cffi loaded")
except ImportError:
    try:
        import cloudscraper
        CF_LIB = "cloudscraper"
        print("✅ cloudscraper loaded")
    except ImportError:
        print("⚠️ No CF bypass lib")

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"
NAPI_API_URL = "http://napiprojekt.pl/api/api-napiprojekt3.php"
NAPI_SEARCH_URL = "https://www.napiprojekt.pl/ajax/search_catalog.php"

_executor = ThreadPoolExecutor(max_workers=2)


# =====================================================
# 7z / SRT helpers
# =====================================================

def get_subhash(md5hash):
    idx = [0xe, 0x3, 0x6, 0x8, 0x2]
    mul = [2, 2, 5, 4, 3]
    add = [0, 0xd, 0x10, 0xb, 0x5]
    b = []
    for i in range(5):
        t = add[i] + int(md5hash[idx[i]], 16)
        v = int(md5hash[t:t + 2], 16)
        b.append(("%x" % (v * mul[i]))[-1])
    return ''.join(b)


def extract_7z(data):
    try:
        a = py7zr.SevenZipFile(io.BytesIO(data), mode='r', password=NAPI_PASSWORD)
        ex = a.read(a.getnames()); a.close()
        for n, bio in ex.items():
            raw = bio.read()
            for enc in ['utf-8', 'windows-1250', 'iso-8859-2', 'latin-1']:
                try:
                    t = raw.decode(enc)
                    if t.strip(): return ensure_srt(t)
                except: continue
    except Exception as e:
        print(f"❌ 7z: {e}")
    return None


def ensure_srt(text):
    text = text.strip()
    if re.match(r'^\d+\s*\r?\n\d{2}:\d{2}:\d{2}', text): return text
    if re.match(r'^\{\d+\}\{\d+\}', text):
        entries, c = [], 1
        for l in text.split('\n'):
            m = re.match(r'\{(\d+)\}\{(\d+)\}(.+)', l.strip())
            if not m: continue
            fps = 23.976
            s, e = int(m.group(1)), int(m.group(2))
            entries.append(f"{c}\n{_f2t(s,fps)} --> {_f2t(e,fps)}\n{m.group(3).replace('|',chr(10))}\n"); c += 1
        return '\n'.join(entries)
    return text


def _f2t(f, fps=23.976):
    ms = int(f / fps * 1000)
    return f"{ms//3600000:02d}:{(ms%3600000)//60000:02d}:{(ms%60000)//1000:02d},{ms%1000:03d}"


def _parse_api_response(resp_content, resp_text):
    """Try to extract SRT from API response (XML/7z/text)."""
    if "<content>" in resp_text:
        try:
            cn = ET.fromstring(resp_text).find(".//content")
            if cn is not None and cn.text:
                srt = extract_7z(base64.b64decode(cn.text))
                if srt: return srt
        except ET.ParseError: pass

    # Check for subtitle hashes in response
    hashes = re.findall(r'[a-f0-9]{32}', resp_text)
    if hashes:
        return {"hashes": hashes}  # Return hashes for caller to download

    if re.search(r'\d{2}:\d{2}:\d{2}', resp_text) and len(resp_text) > 200:
        return ensure_srt(resp_text)

    if resp_content[:2] in (b'7z', b'\x37\x7a'):
        return extract_7z(resp_content)

    return None


# =====================================================
# HASH DOWNLOAD: dl.php
# =====================================================

async def download_via_dl(napi_hash, language="PL"):
    if not napi_hash or len(napi_hash) != 32: return None
    subhash = get_subhash(napi_hash)
    params = {"v": "dreambox", "kolejka": "false", "nick": "", "pass": "",
              "napios": "Linux", "l": language.upper(), "f": napi_hash, "t": subhash}
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(NAPI_DL_URL, params=params)
            print(f"📡 dl.php [{napi_hash[:8]}...]: status={r.status_code} size={len(r.content)}b")
            if r.status_code != 200 or r.content[:4] == b'NPc0': return None
            srt = extract_7z(r.content)
            if srt: print(f"✅ dl.php: OK! ({len(srt)} zn)")
            return srt
    except Exception as e:
        print(f"❌ dl.php: {e}")
        return None


async def download_by_napi_hash(napi_hash, file_size=0, language="PL"):
    if not napi_hash or len(napi_hash) != 32: return None
    print(f"🎯 Napi hash: {napi_hash}")
    return await download_via_dl(napi_hash, language)


# =====================================================
# API MODE=3 TITLE SEARCH (no Cloudflare!)
# =====================================================

async def search_via_api_bruteforce(title: str, year: str = "", language: str = "PL") -> str | None:
    """
    Try api-napiprojekt3.php with multiple parameter combinations.
    This endpoint is NOT behind Cloudflare (returns 200, not 403).
    We just need to find the right parameter names.
    """
    print(f"🔬 API bruteforce search: '{title}' ({year})")

    # Different parameter combos to try
    combos = [
        # Combo 1: Original NapiProjekt client style
        {
            "mode": "3",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "search_title": title,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
        # Combo 2: With year
        {
            "mode": "3",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "search_title": f"{title} ({year})" if year else title,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
        # Combo 3: film_title param
        {
            "mode": "3",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "film_title": title,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
        # Combo 4: title param
        {
            "mode": "3",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "title": title,
            "year": year,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
        # Combo 5: mode=2 (maybe different mode?)
        {
            "mode": "2",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "search_title": title,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
        # Combo 6: QNapi-style
        {
            "mode": "3",
            "client": "QNapi",
            "client_ver": "2.2.0",
            "search_title": title,
            "downloaded_subtitles_lang": language.upper(),
        },
        # Combo 7: search with year as separate param
        {
            "mode": "3",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "search_title": title,
            "search_year": year,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
        # Combo 8: Polish title with 'szukaj' param
        {
            "mode": "3",
            "client": "NapiProjekt",
            "client_ver": "2.2.0.2399",
            "szukaj": title,
            "downloaded_subtitles_lang": language.upper(),
            "the": "end",
        },
    ]

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "NapiProjekt/2.2.0.2399 (Windows NT)",
    }

    found_hashes = []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for i, data in enumerate(combos):
                try:
                    resp = await client.post(NAPI_API_URL, data=data, headers=headers)
                    body = resp.text
                    size = len(resp.content)

                    # Skip empty/minimal responses
                    if size <= 100:
                        print(f"  #{i+1} mode={data.get('mode')}: {size}b (empty)")
                        continue

                    print(f"  #{i+1} mode={data.get('mode')}: {size}b ← INTERESTING!")
                    print(f"       Preview: {body[:200]}")

                    # Try to parse
                    result = _parse_api_response(resp.content, body)
                    if isinstance(result, str):
                        print(f"  ✅ Combo #{i+1} returned subtitles!")
                        return result
                    elif isinstance(result, dict) and "hashes" in result:
                        found_hashes.extend(result["hashes"])
                        print(f"  🔗 Combo #{i+1} returned {len(result['hashes'])} hashes")

                except Exception as e:
                    print(f"  #{i+1}: error {e}")
                    continue

    except Exception as e:
        print(f"❌ API bruteforce error: {e}")

    # Try downloading found hashes
    if found_hashes:
        unique = list(dict.fromkeys(found_hashes))
        print(f"🔗 Próbuję {len(unique)} znalezionych hashy...")
        for h in unique[:5]:
            srt = await download_via_dl(h, language)
            if srt:
                return srt

    return None


# =====================================================
# CF BYPASS SCRAPING (curl_cffi / cloudscraper)
# =====================================================

def _cf_get(url, params=None, headers=None, timeout=20):
    if CF_LIB == "curl_cffi":
        from curl_cffi import requests as cr
        r = cr.get(url, params=params, headers=headers or {}, impersonate="chrome", timeout=timeout)
        return r.status_code, r.text
    elif CF_LIB == "cloudscraper":
        import cloudscraper
        s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'linux', 'desktop': True})
        r = s.get(url, params=params, headers=headers or {}, timeout=timeout)
        return r.status_code, r.text
    else:
        import requests
        r = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
        return r.status_code, r.text


def _sync_search(title, year=""):
    if not CF_LIB: return []
    query = f"{title} {year}".strip() if year else title
    try:
        status, html = _cf_get(NAPI_SEARCH_URL,
            params={"queryString": query, "queryKind": "0"},
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": "https://www.napiprojekt.pl/"})
        print(f"🌐 [{CF_LIB}] search '{query}': status={status} size={len(html)}ch")
        if status != 200:
            if "Just a moment" in html[:200]:
                print(f"⚠️ CF challenge not bypassed")
            return []
        results = []
        for napi_id, slug in re.findall(r'href="[^"]*napisy[^"]*-(\d+)-([^"]+)"', html):
            ym = re.search(r'\((\d{4})\)', slug)
            results.append({"napi_id": napi_id, "year": ym.group(1) if ym else "",
                            "url": f"https://www.napiprojekt.pl/napisy1,1,1-dla-{napi_id}-{slug}"})
        print(f"🔍 Znaleziono {len(results)} wyników")
        return results
    except Exception as e:
        print(f"❌ CF search: {e}")
        return []


def _sync_hashes(url):
    if not CF_LIB: return []
    try:
        status, html = _cf_get(url)
        if status != 200: return []
        h = list(dict.fromkeys(re.findall(r'napiprojekt:([a-f0-9]{32})', html)))
        print(f"🔗 {len(h)} hashy ze strony")
        return h
    except Exception as e:
        print(f"❌ CF page: {e}")
        return []


async def search_via_scraping(title, year="", language="PL"):
    if not CF_LIB:
        print("⚠️ Brak CF bypass lib")
        return None
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(_executor, _sync_search, title, year)
    if not results: return None
    if year:
        exact = [r for r in results if r["year"] == year]
        rest = [r for r in results if r["year"] != year]
        results = exact + rest
    for r in results[:3]:
        hashes = await loop.run_in_executor(_executor, _sync_hashes, r["url"])
        for h in hashes[:5]:
            srt = await download_via_dl(h, language)
            if srt: return srt
    return None


# =====================================================
# DEBUG: raw API responses for all combos
# =====================================================

async def debug_api_search(title: str, year: str = "") -> list[dict]:
    """Returns raw API responses for debugging."""
    combos = [
        {"label": "mode=3 search_title", "data": {"mode": "3", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "search_title": title, "downloaded_subtitles_lang": "PL", "the": "end"}},
        {"label": "mode=3 search_title+year", "data": {"mode": "3", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "search_title": f"{title} ({year})" if year else title, "downloaded_subtitles_lang": "PL", "the": "end"}},
        {"label": "mode=3 film_title", "data": {"mode": "3", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "film_title": title, "downloaded_subtitles_lang": "PL", "the": "end"}},
        {"label": "mode=3 title+year", "data": {"mode": "3", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "title": title, "year": year, "downloaded_subtitles_lang": "PL", "the": "end"}},
        {"label": "mode=2 search_title", "data": {"mode": "2", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "search_title": title, "downloaded_subtitles_lang": "PL", "the": "end"}},
        {"label": "mode=3 QNapi", "data": {"mode": "3", "client": "QNapi", "client_ver": "2.2.0", "search_title": title, "downloaded_subtitles_lang": "PL"}},
        {"label": "mode=3 szukaj", "data": {"mode": "3", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "szukaj": title, "downloaded_subtitles_lang": "PL", "the": "end"}},
        {"label": "mode=31", "data": {"mode": "31", "client": "NapiProjekt", "client_ver": "2.2.0.2399", "search_title": title, "downloaded_subtitles_lang": "PL", "the": "end"}},
    ]

    results = []
    headers = {"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "NapiProjekt/2.2.0.2399 (Windows NT)"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        for combo in combos:
            try:
                resp = await client.post(NAPI_API_URL, data=combo["data"], headers=headers)
                results.append({
                    "label": combo["label"],
                    "status": resp.status_code,
                    "size": len(resp.content),
                    "body": resp.text[:500],
                })
            except Exception as e:
                results.append({"label": combo["label"], "error": str(e)})

    return results


# =====================================================
# Main entry point
# =====================================================

async def get_napi_subtitles_text(napi_hash=None, title=None, year="", file_size=0, language="PL"):
    # Hash download
    if napi_hash and len(napi_hash) == 32:
        return await download_by_napi_hash(napi_hash, file_size, language)

    if not title:
        return None

    # Strategy 1: API mode=3 bruteforce (no CF, fast)
    print(f"🔬 [1/2] API bruteforce search...")
    result = await search_via_api_bruteforce(title, year, language)
    if result:
        return result

    # Strategy 2: CF bypass scraping (slower, may fail)
    print(f"🌐 [2/2] CF bypass scraping...")
    result = await search_via_scraping(title, year, language)
    if result:
        return result

    print(f"ℹ️ Napi: brak napisów dla '{title}' ({year})")
    return None
