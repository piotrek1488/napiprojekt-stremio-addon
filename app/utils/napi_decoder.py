"""
NapiProjekt subtitle decoder / downloader.

Two modes:
  1. Hash-based: MD5 hash (32 chars) → dl.php with subhash token → 7z → SRT
  2. Title-based: scrape napiprojekt.pl → get subtitle hashes → download via mode 1
"""

import io
import re
import traceback

import httpx
import py7zr

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"
NAPI_SEARCH_URL = "https://www.napiprojekt.pl/ajax/search_catalog.php"


def get_subhash(md5hash: str) -> str:
    """
    Compute NapiProjekt verification token from MD5 hash.
    Required by dl.php — without it you get 403!
    """
    idx = [0xe, 0x3, 0x6, 0x8, 0x2]
    mul = [2, 2, 5, 4, 3]
    add = [0, 0xd, 0x10, 0xb, 0x5]
    b = []
    for i in range(len(idx)):
        a = add[i]
        m = mul[i]
        j = idx[i]
        t = a + int(md5hash[j], 16)
        v = int(md5hash[t:t + 2], 16)
        b.append(("%x" % (v * m))[-1])
    return ''.join(b)


def extract_7z_to_srt(data: bytes) -> str | None:
    """Extract subtitle from 7z archive (password: iBlm8NTigvru0Jr0)."""
    try:
        archive = py7zr.SevenZipFile(io.BytesIO(data), mode='r', password=NAPI_PASSWORD)
        filenames = archive.getnames()
        if not filenames:
            return None
        extracted = archive.read(filenames)
        archive.close()

        for name, bio in extracted.items():
            raw = bio.read()
            for encoding in ['utf-8', 'windows-1250', 'iso-8859-2', 'latin-1']:
                try:
                    text = raw.decode(encoding)
                    if text.strip():
                        return ensure_srt_format(text)
                except (UnicodeDecodeError, ValueError):
                    continue
        return None
    except Exception as e:
        print(f"❌ 7z extraction error: {e}")
        traceback.print_exc()
        return None


def ensure_srt_format(text: str) -> str:
    text = text.strip()
    if re.match(r'^\d+\s*\r?\n\d{2}:\d{2}:\d{2}', text):
        return text
    if text.startswith('{') and re.match(r'^\{\d+\}\{\d+\}', text):
        return _convert_microdvd(text)
    if re.match(r'^\d{1,2}:\d{2}:\d{2}[=:]', text):
        return _convert_tmplayer(text)
    return text


def _convert_microdvd(text: str, fps: float = 23.976) -> str:
    entries, counter = [], 1
    for line in text.strip().split('\n'):
        m = re.match(r'\{(\d+)\}\{(\d+)\}(.+)', line.strip())
        if not m:
            continue
        sf, ef = int(m.group(1)), int(m.group(2))
        content = m.group(3).replace('|', '\n')
        entries.append(f"{counter}\n{_f2t(sf, fps)} --> {_f2t(ef, fps)}\n{content}\n")
        counter += 1
    return '\n'.join(entries)


def _convert_tmplayer(text: str) -> str:
    entries, counter = [], 1
    for line in text.strip().split('\n'):
        m = re.match(r'(\d{1,2}):(\d{2}):(\d{2})[=:](.+)', line.strip())
        if not m:
            continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        content = m.group(4).replace('|', '\n')
        entries.append(f"{counter}\n{h:02d}:{mi:02d}:{s:02d},000 --> {h:02d}:{mi:02d}:{min(s+2,59):02d},000\n{content}\n")
        counter += 1
    return '\n'.join(entries)


def _f2t(frame: int, fps: float) -> str:
    ms = int(frame / fps * 1000)
    return f"{ms//3600000:02d}:{(ms%3600000)//60000:02d}:{(ms%60000)//1000:02d},{ms%1000:03d}"


# =====================================================
# MODE 1: Download by NapiProjekt MD5 hash (32 chars)
# =====================================================

async def download_by_napi_hash(napi_hash: str, language: str = "PL") -> str | None:
    if not napi_hash or len(napi_hash) != 32:
        print(f"⚠️ Invalid napi hash: '{napi_hash}' (need 32 hex chars)")
        return None

    subhash = get_subhash(napi_hash)
    params = {
        "v": "dreambox",
        "kolejka": "false",
        "nick": "",
        "pass": "",
        "napios": "Linux",
        "l": language.upper(),
        "f": napi_hash,
        "t": subhash,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(NAPI_DL_URL, params=params)
            print(f"📡 Napi dl.php: status={resp.status_code}, size={len(resp.content)} bytes")
            resp.raise_for_status()

            if resp.content[:4] == b'NPc0':
                print(f"ℹ️ Napi: brak napisów dla hash {napi_hash}")
                return None

            srt = extract_7z_to_srt(resp.content)
            if srt:
                print(f"✅ Napi: napisy pobrane! ({len(srt)} znaków)")
            else:
                print(f"❌ Napi: nie udało się rozpakować 7z")
            return srt

    except Exception as e:
        print(f"❌ Napi dl.php error: {e}")
        traceback.print_exc()
        return None


# =====================================================
# MODE 2: Search by title → scrape hashes → download
# =====================================================

async def search_by_title(title: str, year: str = "") -> list[dict]:
    query = f"{title} {year}".strip() if year else title
    results = []
    try:
        print(f"🌐 Napi: wysyłam request do {NAPI_SEARCH_URL} query='{query}'")
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(
                NAPI_SEARCH_URL,
                params={"queryString": query, "queryKind": "0"},
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": "https://www.napiprojekt.pl/",
                }
            )
            print(f"🌐 Napi search response: status={resp.status_code}, size={len(resp.text)} chars")

            if resp.status_code != 200:
                print(f"⚠️ Napi search: HTTP {resp.status_code}")
                print(f"⚠️ Response body: {resp.text[:500]}")
                return results

            html = resp.text
            if len(html) < 10:
                print(f"⚠️ Napi search: pusta odpowiedź")
                return results

            # Log first 300 chars of response for debugging
            print(f"🔎 Napi search response preview: {html[:300]}")

            pattern = r'href="[^"]*napisy[^"]*-(\d+)-([^"]+)"'
            for napi_id, slug in re.findall(pattern, html):
                ym = re.search(r'\((\d{4})\)', slug)
                results.append({
                    "napi_id": napi_id,
                    "title": slug.replace('-', ' ').strip(),
                    "year": ym.group(1) if ym else "",
                    "url": f"https://www.napiprojekt.pl/napisy1,1,1-dla-{napi_id}-{slug}",
                })

            print(f"🔍 Napi search '{query}': {len(results)} wyników")
            if results:
                print(f"🔍 Pierwszy wynik: {results[0]}")

    except httpx.ConnectError as e:
        print(f"❌ Napi search: CANNOT CONNECT to napiprojekt.pl! {e}")
    except httpx.TimeoutException as e:
        print(f"❌ Napi search: TIMEOUT connecting to napiprojekt.pl! {e}")
    except Exception as e:
        print(f"❌ Napi search error: {e}")
        traceback.print_exc()

    return results


async def scrape_hashes_from_page(napi_url: str) -> list[str]:
    try:
        print(f"🌐 Napi: scraping {napi_url}")
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(napi_url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            })
            print(f"🌐 Napi page: status={resp.status_code}, size={len(resp.text)} chars")
            if resp.status_code != 200:
                return []
            found = re.findall(r'napiprojekt:([a-f0-9]{32})', resp.text)
            hashes = list(dict.fromkeys(found))
            print(f"🔗 Znaleziono {len(hashes)} hashy na stronie")
            if hashes:
                print(f"🔗 Pierwszy hash: {hashes[0]}")
            return hashes

    except httpx.ConnectError as e:
        print(f"❌ Napi scrape: CANNOT CONNECT! {e}")
    except httpx.TimeoutException as e:
        print(f"❌ Napi scrape: TIMEOUT! {e}")
    except Exception as e:
        print(f"❌ Napi scrape error: {e}")
        traceback.print_exc()
    return []


async def download_by_title(title: str, year: str = "", language: str = "PL") -> str | None:
    results = await search_by_title(title, year)

    if year and results:
        exact = [r for r in results if r["year"] == year]
        rest = [r for r in results if r["year"] != year]
        results = exact + rest

    for result in results[:3]:
        hashes = await scrape_hashes_from_page(result["url"])
        for h in hashes[:5]:
            srt = await download_by_napi_hash(h, language)
            if srt:
                return srt
    return None


# =====================================================
# Main entry point
# =====================================================

async def get_napi_subtitles_text(
    napi_hash: str = None,
    title: str = None,
    year: str = "",
    language: str = "PL",
) -> str | None:
    if napi_hash and len(napi_hash) == 32:
        print(f"🎯 Napi: próba pobrania po hash {napi_hash}")
        result = await download_by_napi_hash(napi_hash, language)
        if result:
            return result

    if title:
        print(f"🔍 Napi: szukam po tytule '{title}' ({year})")
        result = await download_by_title(title, year, language)
        if result:
            return result

    return None
