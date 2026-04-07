"""
NapiProjekt subtitle decoder.

Two modes:
  1. Hash-based: MD5 → dl.php (no Cloudflare)
  2. Title-based: cloudscraper → scrape napiprojekt.pl (bypasses Cloudflare)
                  → extract hashes → download via dl.php

cloudscraper handles Cloudflare JS challenges automatically.
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

# cloudscraper is synchronous (uses requests), we run it in a thread pool
try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
    print("✅ cloudscraper loaded")
except ImportError:
    HAS_CLOUDSCRAPER = False
    print("⚠️ cloudscraper not installed — title search disabled")

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"
NAPI_API_URL = "http://napiprojekt.pl/api/api-napiprojekt3.php"

# Thread pool for sync cloudscraper calls
_executor = ThreadPoolExecutor(max_workers=2)


def get_subhash(md5hash: str) -> str:
    idx = [0xe, 0x3, 0x6, 0x8, 0x2]
    mul = [2, 2, 5, 4, 3]
    add = [0, 0xd, 0x10, 0xb, 0x5]
    b = []
    for i in range(len(idx)):
        t = add[i] + int(md5hash[idx[i]], 16)
        v = int(md5hash[t:t + 2], 16)
        b.append(("%x" % (v * mul[i]))[-1])
    return ''.join(b)


def extract_7z_to_srt(data: bytes) -> str | None:
    try:
        archive = py7zr.SevenZipFile(io.BytesIO(data), mode='r', password=NAPI_PASSWORD)
        extracted = archive.read(archive.getnames())
        archive.close()
        for name, bio in extracted.items():
            raw = bio.read()
            for enc in ['utf-8', 'windows-1250', 'iso-8859-2', 'latin-1']:
                try:
                    text = raw.decode(enc)
                    if text.strip():
                        return ensure_srt_format(text)
                except (UnicodeDecodeError, ValueError):
                    continue
    except Exception as e:
        print(f"❌ 7z error: {e}")
    return None


def ensure_srt_format(text: str) -> str:
    text = text.strip()
    if re.match(r'^\d+\s*\r?\n\d{2}:\d{2}:\d{2}', text):
        return text
    if re.match(r'^\{\d+\}\{\d+\}', text):
        return _microdvd(text)
    if re.match(r'^\d{1,2}:\d{2}:\d{2}[=:]', text):
        return _tmplayer(text)
    return text


def _microdvd(text, fps=23.976):
    entries, c = [], 1
    for line in text.strip().split('\n'):
        m = re.match(r'\{(\d+)\}\{(\d+)\}(.+)', line.strip())
        if not m: continue
        s, e = int(m.group(1)), int(m.group(2))
        entries.append(f"{c}\n{_f2t(s,fps)} --> {_f2t(e,fps)}\n{m.group(3).replace('|',chr(10))}\n")
        c += 1
    return '\n'.join(entries)


def _tmplayer(text):
    entries, c = [], 1
    for line in text.strip().split('\n'):
        m = re.match(r'(\d{1,2}):(\d{2}):(\d{2})[=:](.+)', line.strip())
        if not m: continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        entries.append(f"{c}\n{h:02d}:{mi:02d}:{s:02d},000 --> {h:02d}:{mi:02d}:{min(s+2,59):02d},000\n{m.group(4).replace('|',chr(10))}\n")
        c += 1
    return '\n'.join(entries)


def _f2t(frame, fps):
    ms = int(frame / fps * 1000)
    return f"{ms//3600000:02d}:{(ms%3600000)//60000:02d}:{(ms%60000)//1000:02d},{ms%1000:03d}"


# =====================================================
# HASH DOWNLOAD: dl.php (no Cloudflare)
# =====================================================

async def download_via_dl(napi_hash: str, language: str = "PL") -> str | None:
    subhash = get_subhash(napi_hash)
    params = {
        "v": "dreambox", "kolejka": "false", "nick": "", "pass": "",
        "napios": "Linux", "l": language.upper(), "f": napi_hash, "t": subhash,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(NAPI_DL_URL, params=params)
            print(f"📡 dl.php: status={resp.status_code} size={len(resp.content)}b")
            if resp.status_code != 200 or resp.content[:4] == b'NPc0':
                return None
            srt = extract_7z_to_srt(resp.content)
            if srt:
                print(f"✅ dl.php: OK! ({len(srt)} zn)")
            return srt
    except Exception as e:
        print(f"❌ dl.php: {e}")
        return None


async def download_via_api(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    data = {
        "mode": "1", "client": "NapiProjektPython", "client_ver": "2.2.0.2399",
        "downloaded_subtitles_id": napi_hash, "downloaded_subtitles_txt": "1",
        "downloaded_subtitles_lang": language.upper(),
    }
    if file_size:
        data["file_size"] = str(file_size)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(NAPI_API_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "other"})
            print(f"📡 API mode=1: status={resp.status_code} size={len(resp.content)}b")
            if resp.status_code != 200 or len(resp.content) < 100:
                return None
            text = resp.text
            if "<content>" in text:
                try:
                    root = ET.fromstring(text)
                    cn = root.find(".//content")
                    if cn is not None and cn.text:
                        srt = extract_7z_to_srt(base64.b64decode(cn.text))
                        if srt:
                            print(f"✅ API (XML/7z): OK! ({len(srt)} zn)")
                            return srt
                except ET.ParseError:
                    pass
            if re.search(r'\d{2}:\d{2}:\d{2}', text) and len(text) > 200:
                return ensure_srt_format(text)
            if resp.content[:2] in (b'7z', b'\x37\x7a'):
                srt = extract_7z_to_srt(resp.content)
                if srt: return srt
            return None
    except Exception as e:
        print(f"❌ API mode=1: {e}")
        return None


async def download_by_napi_hash(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    if not napi_hash or len(napi_hash) != 32:
        return None
    print(f"🎯 Napi: hash download {napi_hash}")
    result = await download_via_dl(napi_hash, language)
    if result: return result
    result = await download_via_api(napi_hash, file_size, language)
    if result: return result
    return None


# =====================================================
# TITLE SEARCH: cloudscraper → scrape → dl.php
# =====================================================

def _cloudscraper_search(title: str, year: str = "") -> list[dict]:
    """
    Synchronous function — runs in thread pool.
    Uses cloudscraper to bypass Cloudflare on www.napiprojekt.pl
    """
    if not HAS_CLOUDSCRAPER:
        return []

    query = f"{title} {year}".strip() if year else title
    results = []

    try:
        scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'linux',
                'desktop': True,
            }
        )

        # Search on napiprojekt.pl
        search_url = "https://www.napiprojekt.pl/ajax/search_catalog.php"
        resp = scraper.get(
            search_url,
            params={"queryString": query, "queryKind": "0"},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://www.napiprojekt.pl/",
            },
            timeout=20,
        )

        print(f"🌐 cloudscraper search '{query}': status={resp.status_code} size={len(resp.text)}ch")

        if resp.status_code != 200:
            print(f"⚠️ cloudscraper: HTTP {resp.status_code}")
            # Log first 200 chars for debugging
            print(f"⚠️ Body: {resp.text[:200]}")
            return results

        html = resp.text
        if len(html) < 10:
            print("⚠️ cloudscraper: empty response")
            return results

        print(f"🔎 Search HTML preview: {html[:200]}")

        # Parse napisy-NNNNN-Title-(Year) links
        pattern = r'href="[^"]*napisy[^"]*-(\d+)-([^"]+)"'
        for napi_id, slug in re.findall(pattern, html):
            ym = re.search(r'\((\d{4})\)', slug)
            results.append({
                "napi_id": napi_id,
                "title": slug.replace('-', ' ').strip(),
                "year": ym.group(1) if ym else "",
                "url": f"https://www.napiprojekt.pl/napisy1,1,1-dla-{napi_id}-{slug}",
            })

        print(f"🔍 Znaleziono {len(results)} wyników")

    except Exception as e:
        print(f"❌ cloudscraper search error: {e}")
        traceback.print_exc()

    return results


def _cloudscraper_get_hashes(napi_url: str) -> list[str]:
    """
    Synchronous — scrape movie page for subtitle hashes.
    """
    if not HAS_CLOUDSCRAPER:
        return []

    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'linux', 'desktop': True}
        )
        resp = scraper.get(napi_url, timeout=20)
        print(f"🌐 cloudscraper page: status={resp.status_code} size={len(resp.text)}ch")

        if resp.status_code != 200:
            return []

        found = re.findall(r'napiprojekt:([a-f0-9]{32})', resp.text)
        hashes = list(dict.fromkeys(found))  # deduplicate
        print(f"🔗 Znaleziono {len(hashes)} hashy na stronie")
        return hashes

    except Exception as e:
        print(f"❌ cloudscraper page error: {e}")
        return []


async def search_by_title(title: str, year: str = "", language: str = "PL") -> str | None:
    """
    Title-based search using cloudscraper (Cloudflare bypass).
    Runs synchronous cloudscraper in thread pool to not block async loop.
    """
    if not HAS_CLOUDSCRAPER:
        print("⚠️ cloudscraper not installed — pip install cloudscraper")
        return None

    loop = asyncio.get_event_loop()

    # Step 1: Search for movie
    print(f"🔍 cloudscraper: szukam '{title}' ({year})...")
    results = await loop.run_in_executor(_executor, _cloudscraper_search, title, year)

    if not results:
        print("ℹ️ cloudscraper: brak wyników")
        return None

    # Prefer exact year match
    if year:
        exact = [r for r in results if r["year"] == year]
        rest = [r for r in results if r["year"] != year]
        results = exact + rest

    # Step 2: For each result, scrape hashes and try to download
    for result in results[:3]:
        print(f"🔗 Próbuję: {result['title']} ({result['year']})")
        hashes = await loop.run_in_executor(_executor, _cloudscraper_get_hashes, result["url"])

        for h in hashes[:5]:
            srt = await download_via_dl(h, language)
            if srt:
                print(f"✅ Napisy znalezione! hash={h}")
                return srt

    print("ℹ️ cloudscraper: żaden hash nie zwrócił napisów")
    return None


# =====================================================
# Main entry point
# =====================================================

async def get_napi_subtitles_text(
    napi_hash: str = None,
    title: str = None,
    year: str = "",
    file_size: int = 0,
    language: str = "PL",
) -> str | None:
    """
    Main function called by main.py.
    1. Hash-based download (if hash provided)
    2. Title-based search via cloudscraper (Cloudflare bypass)
    """
    if napi_hash and len(napi_hash) == 32:
        return await download_by_napi_hash(napi_hash, file_size, language)

    if title:
        return await search_by_title(title, year, language)

    return None
