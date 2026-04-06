"""
NapiProjekt subtitle decoder / downloader.

Two modes:
  1. Hash-based: MD5 hash (32 chars) → dl.php with subhash token → 7z → SRT
  2. Title-based: scrape napiprojekt.pl → get subtitle hashes → download via mode 1
"""

import io
import re
import logging

import httpx
import py7zr

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"
NAPI_SEARCH_URL = "https://www.napiprojekt.pl/ajax/search_catalog.php"

logger = logging.getLogger(__name__)


def get_subhash(md5hash: str) -> str:
    """
    Compute NapiProjekt verification token from MD5 hash.
    This is the 'f()' function from qnapi/subliminal - required by dl.php.
    Without this token, NapiProjekt returns 403!
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
    """
    Extract subtitle from 7z archive data (password: iBlm8NTigvru0Jr0).
    Returns decoded text as UTF-8 string.
    """
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
        logger.error(f"7z extraction error: {e}")
        return None


def ensure_srt_format(text: str) -> str:
    """Ensure subtitle is valid SRT. Convert MicroDVD/TMPlayer if needed."""
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
        st = _f2t(sf, fps)
        et = _f2t(ef, fps)
        entries.append(f"{counter}\n{st} --> {et}\n{content}\n")
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
    """
    Download subtitles using a proper NapiProjekt MD5 hash.
    Uses dl.php + subhash token (the key to avoiding 403!).
    """
    if not napi_hash or len(napi_hash) != 32:
        print(f"⚠️ Invalid napi hash: {napi_hash} (need 32 hex chars)")
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
            resp.raise_for_status()

            if resp.content[:4] == b'NPc0':
                print(f"ℹ️ Napi: brak napisów dla hash {napi_hash}")
                return None

            srt = extract_7z_to_srt(resp.content)
            if srt:
                print(f"✅ Napi: napisy pobrane dla hash {napi_hash}")
            return srt

    except Exception as e:
        print(f"❌ Napi download error: {e}")
        return None


# =====================================================
# MODE 2: Search by title → scrape hashes → download
# =====================================================

async def search_by_title(title: str, year: str = "") -> list[dict]:
    """Search napiprojekt.pl by title."""
    query = f"{title} {year}".strip() if year else title
    results = []
    try:
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
            if resp.status_code != 200:
                return results

            pattern = r'href="[^"]*napisy[^"]*-(\d+)-([^"]+)"'
            for napi_id, slug in re.findall(pattern, resp.text):
                ym = re.search(r'\((\d{4})\)', slug)
                results.append({
                    "napi_id": napi_id,
                    "title": slug.replace('-', ' ').strip(),
                    "year": ym.group(1) if ym else "",
                    "url": f"https://www.napiprojekt.pl/napisy1,1,1-dla-{napi_id}-{slug}",
                })
            print(f"🔍 Napi search '{query}': {len(results)} wyników")
    except Exception as e:
        print(f"❌ Napi search error: {e}")
    return results


async def scrape_hashes_from_page(napi_url: str) -> list[str]:
    """Scrape subtitle hashes (napiprojekt:HASH) from a movie page."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(napi_url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            })
            if resp.status_code != 200:
                return []
            found = re.findall(r'napiprojekt:([a-f0-9]{32})', resp.text)
            hashes = list(dict.fromkeys(found))
            print(f"🔗 Znaleziono {len(hashes)} hashy na stronie")
            return hashes
    except Exception as e:
        print(f"❌ Scrape error: {e}")
        return []


async def download_by_title(title: str, year: str = "", language: str = "PL") -> str | None:
    """Full title-based flow: search → scrape hashes → try downloading each."""
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
# Main entry point (called by main.py endpoints)
# =====================================================

async def get_napi_subtitles_text(
    napi_hash: str = None,
    title: str = None,
    year: str = "",
    language: str = "PL",
) -> str | None:
    """
    Main function called by main.py.
    - napi_hash (32 chars): download directly
    - title: search + scrape + download
    """
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
