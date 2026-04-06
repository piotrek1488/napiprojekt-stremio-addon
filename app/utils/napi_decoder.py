"""
NapiProjekt subtitle decoder / downloader.

Methods:
  1. Hash-based via dl.php with subhash token (subliminal-style)
  2. Hash-based via api-napiprojekt3.php mode=1 (QNapi-style)
  3. Title search via api-napiprojekt3.php mode=3 (may or may not work from cloud)
"""

import io
import re
import traceback
import base64
import xml.etree.ElementTree as ET

import httpx
import py7zr

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"
NAPI_API_URL = "http://napiprojekt.pl/api/api-napiprojekt3.php"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"


def get_subhash(md5hash: str) -> str:
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
    try:
        archive = py7zr.SevenZipFile(io.BytesIO(data), mode='r', password=NAPI_PASSWORD)
        filenames = archive.getnames()
        if not filenames:
            return None
        extracted = archive.read(filenames)
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
        return None
    except Exception as e:
        print(f"❌ 7z error: {e}")
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


def _convert_microdvd(text, fps=23.976):
    entries, c = [], 1
    for line in text.strip().split('\n'):
        m = re.match(r'\{(\d+)\}\{(\d+)\}(.+)', line.strip())
        if not m: continue
        sf, ef = int(m.group(1)), int(m.group(2))
        entries.append(f"{c}\n{_f2t(sf,fps)} --> {_f2t(ef,fps)}\n{m.group(3).replace('|',chr(10))}\n")
        c += 1
    return '\n'.join(entries)


def _convert_tmplayer(text):
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
# METHOD A: dl.php + subhash (subliminal/qnapi style)
# =====================================================

async def download_via_dl(napi_hash: str, language: str = "PL") -> str | None:
    if not napi_hash or len(napi_hash) != 32:
        return None

    subhash = get_subhash(napi_hash)
    params = {
        "v": "dreambox", "kolejka": "false", "nick": "", "pass": "",
        "napios": "Linux", "l": language.upper(), "f": napi_hash, "t": subhash,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(NAPI_DL_URL, params=params)
            print(f"📡 dl.php: status={resp.status_code} size={len(resp.content)}b")

            if resp.status_code != 200:
                return None
            if resp.content[:4] == b'NPc0':
                print(f"ℹ️ dl.php: brak napisów")
                return None

            srt = extract_7z_to_srt(resp.content)
            if srt:
                print(f"✅ dl.php: OK! ({len(srt)} znaków)")
            return srt
    except Exception as e:
        print(f"❌ dl.php error: {e}")
        return None


# =====================================================
# METHOD B: api-napiprojekt3.php mode=1 (QNapi style)
# =====================================================

async def download_via_api(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    if not napi_hash or len(napi_hash) != 32:
        return None

    data = {
        "mode": "1",
        "client": "NapiProjektPython",
        "client_ver": "2.2.0.2399",
        "downloaded_subtitles_id": napi_hash,
        "downloaded_subtitles_txt": "1",
        "downloaded_subtitles_lang": language.upper(),
    }
    if file_size:
        data["file_size"] = str(file_size)

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                NAPI_API_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "other"}
            )
            print(f"📡 API mode=1: status={resp.status_code} size={len(resp.content)}b")

            if resp.status_code != 200 or len(resp.content) < 100:
                print(f"ℹ️ API mode=1: brak napisów (response too short or error)")
                return None

            text = resp.text
            content = resp.content

            # Try XML with base64-encoded 7z
            if "<content>" in text:
                try:
                    root = ET.fromstring(text)
                    cn = root.find(".//content")
                    if cn is not None and cn.text:
                        compressed = base64.b64decode(cn.text)
                        srt = extract_7z_to_srt(compressed)
                        if srt:
                            print(f"✅ API mode=1 (XML/7z): OK! ({len(srt)} znaków)")
                            return srt
                except ET.ParseError:
                    pass

            # Try plain text SRT
            if re.search(r'\d{2}:\d{2}:\d{2}', text):
                print(f"✅ API mode=1 (text): OK!")
                return ensure_srt_format(text)

            # Try raw 7z
            if content[:2] in (b'7z', b'\x37\x7a'):
                srt = extract_7z_to_srt(content)
                if srt:
                    print(f"✅ API mode=1 (raw 7z): OK!")
                    return srt

            print(f"ℹ️ API mode=1: nie rozpoznano formatu (first 80b: {content[:80]})")
            return None
    except Exception as e:
        print(f"❌ API mode=1 error: {e}")
        return None


# =====================================================
# METHOD C: api-napiprojekt3.php mode=3 (title search)
# This endpoint is on napiprojekt.pl (no www), so might
# bypass Cloudflare that blocks www.napiprojekt.pl
# =====================================================

async def search_via_api(title: str, year: str = "", language: str = "PL") -> str | None:
    """
    Try api-napiprojekt3.php with mode=3 for title-based search.
    Returns SRT text or None.
    """
    search_query = title
    if year:
        search_query = f"{title} {year}"

    data = {
        "mode": "3",
        "client": "NapiProjektPython",
        "client_ver": "2.2.0.2399",
        "search_title": search_query,
        "search_year": year,
        "downloaded_subtitles_lang": language.upper(),
        "the": "end",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                NAPI_API_URL, data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "NapiProjekt/2.2.0.2399 (Windows NT)",
                }
            )
            print(f"📡 API mode=3 search '{search_query}': status={resp.status_code} size={len(resp.content)}b")
            print(f"📡 API mode=3 response preview: {resp.text[:300]}")

            if resp.status_code != 200:
                print(f"⚠️ API mode=3: HTTP {resp.status_code}")
                return None

            text = resp.text

            # Check if response contains subtitles
            if "<content>" in text:
                try:
                    root = ET.fromstring(text)
                    cn = root.find(".//content")
                    if cn is not None and cn.text:
                        compressed = base64.b64decode(cn.text)
                        srt = extract_7z_to_srt(compressed)
                        if srt:
                            print(f"✅ API mode=3: napisy znalezione! ({len(srt)} znaków)")
                            return srt
                except ET.ParseError as e:
                    print(f"⚠️ API mode=3: XML parse error: {e}")

            # Check for hash references in response
            hashes = re.findall(r'[a-f0-9]{32}', text)
            if hashes:
                print(f"🔗 API mode=3: znaleziono {len(hashes)} hashy, próbuję pobrać...")
                for h in hashes[:3]:
                    srt = await download_via_dl(h, language)
                    if srt:
                        return srt

            # Check if it's a direct subtitle response
            if re.search(r'\d{2}:\d{2}:\d{2}', text) and len(text) > 200:
                print(f"✅ API mode=3 (direct text): OK!")
                return ensure_srt_format(text)

            print(f"ℹ️ API mode=3: brak napisów w odpowiedzi")
            return None

    except Exception as e:
        print(f"❌ API mode=3 error: {e}")
        traceback.print_exc()
        return None


# =====================================================
# Combined hash download (try both methods)
# =====================================================

async def download_by_napi_hash(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    if not napi_hash or len(napi_hash) != 32:
        print(f"⚠️ Invalid hash: '{napi_hash}'")
        return None

    print(f"🎯 Napi hash download: {napi_hash}")

    # Try dl.php first (simpler, proven)
    result = await download_via_dl(napi_hash, language)
    if result:
        return result

    # Fallback to API mode=1
    result = await download_via_api(napi_hash, file_size, language)
    if result:
        return result

    print(f"ℹ️ Napi: brak napisów dla hash {napi_hash}")
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
    """Main function called by main.py."""

    # Direct hash download
    if napi_hash and len(napi_hash) == 32:
        return await download_by_napi_hash(napi_hash, file_size, language)

    # Title search via API mode=3
    if title:
        print(f"🔍 Napi: title search via API mode=3 for '{title}' ({year})")
        result = await search_via_api(title, year, language)
        if result:
            return result

    return None
