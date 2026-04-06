"""
NapiProjekt subtitle decoder / downloader.

Uses api-napiprojekt3.php with mode=1 (same as QNapi client).
NO scraping of napiprojekt.pl website (blocked by Cloudflare).

The ONLY way to get subtitles from NapiProjekt is:
  1. Have the actual video file (or streaming URL)
  2. Compute MD5 of first 10MB
  3. Send hash to api-napiprojekt3.php
"""

import io
import re
import traceback
import hashlib

import httpx
import py7zr

NAPI_PASSWORD = "iBlm8NTigvru0Jr0"

# Two endpoints that work without Cloudflare:
NAPI_API_URL = "http://napiprojekt.pl/api/api-napiprojekt3.php"
NAPI_DL_URL = "http://napiprojekt.pl/unit_napisy/dl.php"


def get_subhash(md5hash: str) -> str:
    """Compute verification token for dl.php endpoint."""
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
            for enc in ['utf-8', 'windows-1250', 'iso-8859-2', 'latin-1']:
                try:
                    text = raw.decode(enc)
                    if text.strip():
                        return ensure_srt_format(text)
                except (UnicodeDecodeError, ValueError):
                    continue
        return None
    except Exception as e:
        print(f"❌ 7z extraction error: {e}")
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
# METHOD A: api-napiprojekt3.php mode=1 (like QNapi)
# =====================================================

async def download_via_api(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    """
    Download subtitles using api-napiprojekt3.php (same as QNapi).
    This endpoint is NOT behind Cloudflare.
    """
    if not napi_hash or len(napi_hash) != 32:
        print(f"⚠️ Invalid napi hash: '{napi_hash}'")
        return None

    data = {
        "mode": "1",
        "client": "NapiProjektPython",
        "client_ver": "2.2.0.2399",
        "downloaded_subtitles_id": napi_hash,
        "downloaded_subtitles_txt": "1",
        "downloaded_subtitles_lang": language.upper(),
    }

    # QNapi also sends these when available
    if file_size:
        data["downloaded_subtitles_id"] = napi_hash
        data["file_size"] = str(file_size)

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "other",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(NAPI_API_URL, data=data, headers=headers)
            print(f"📡 Napi API: status={resp.status_code}, size={len(resp.content)} bytes")

            if resp.status_code != 200:
                print(f"⚠️ Napi API: HTTP {resp.status_code}")
                return None

            content = resp.content

            # Check if response contains subtitles
            # API returns XML with status, or raw subtitle data
            text = resp.text

            # If response is very short or contains "not found" indicator
            if len(content) < 100:
                print(f"ℹ️ Napi API: odpowiedź za krótka ({len(content)} bytes) - brak napisów")
                return None

            # Check if it's XML with subtitle content
            if "<content>" in text:
                # Extract base64 content from XML
                import base64
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(text)
                    content_node = root.find(".//content")
                    if content_node is not None and content_node.text:
                        compressed = base64.b64decode(content_node.text)
                        srt = extract_7z_to_srt(compressed)
                        if srt:
                            print(f"✅ Napi API (XML/7z): napisy pobrane! ({len(srt)} znaków)")
                            return srt
                except ET.ParseError:
                    pass

            # Check if response is plain text subtitle (mode=1 with txt=1)
            if text.strip().startswith("1\n") or text.strip().startswith("1\r\n"):
                # Looks like SRT already
                print(f"✅ Napi API (plain text): napisy pobrane! ({len(text)} znaków)")
                return ensure_srt_format(text)

            # Check if it's a 7z archive directly
            if content[:2] == b'7z' or content[:6] == b"7z\xbc\xaf'\x1c":
                srt = extract_7z_to_srt(content)
                if srt:
                    print(f"✅ Napi API (7z): napisy pobrane! ({len(srt)} znaków)")
                    return srt

            # Try treating entire response as subtitle text
            for enc in ['utf-8', 'windows-1250', 'iso-8859-2']:
                try:
                    decoded = content.decode(enc)
                    if re.search(r'\d{2}:\d{2}:\d{2}', decoded):
                        print(f"✅ Napi API (decoded {enc}): napisy pobrane!")
                        return ensure_srt_format(decoded)
                except:
                    continue

            print(f"ℹ️ Napi API: nie rozpoznano formatu odpowiedzi (first 100 bytes: {content[:100]})")
            return None

    except Exception as e:
        print(f"❌ Napi API error: {e}")
        traceback.print_exc()
        return None


# =====================================================
# METHOD B: dl.php with subhash (subliminal-style)
# =====================================================

async def download_via_dl(napi_hash: str, language: str = "PL") -> str | None:
    """
    Download subtitles using dl.php endpoint.
    Also NOT behind Cloudflare.
    """
    if not napi_hash or len(napi_hash) != 32:
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

            if resp.status_code != 200:
                return None

            if resp.content[:4] == b'NPc0':
                print(f"ℹ️ Napi dl.php: brak napisów dla hash {napi_hash}")
                return None

            srt = extract_7z_to_srt(resp.content)
            if srt:
                print(f"✅ Napi dl.php: napisy pobrane! ({len(srt)} znaków)")
            return srt

    except Exception as e:
        print(f"❌ Napi dl.php error: {e}")
        return None


# =====================================================
# Main entry: try both methods
# =====================================================

async def download_by_napi_hash(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    """Try api-napiprojekt3.php first, then dl.php as fallback."""

    # Method A: QNapi-style API
    print(f"🎯 Napi: próba api-napiprojekt3.php dla hash {napi_hash}")
    result = await download_via_api(napi_hash, file_size, language)
    if result:
        return result

    # Method B: dl.php with subhash
    print(f"🎯 Napi: próba dl.php dla hash {napi_hash}")
    result = await download_via_dl(napi_hash, language)
    if result:
        return result

    print(f"ℹ️ Napi: brak napisów dla hash {napi_hash} (oba endpointy)")
    return None


async def get_napi_subtitles_text(
    napi_hash: str = None,
    title: str = None,
    year: str = "",
    file_size: int = 0,
    language: str = "PL",
) -> str | None:
    """
    Main entry point called by main.py.

    NOTE: Title-based search is DISABLED because napiprojekt.pl
    is behind Cloudflare and blocks requests from cloud servers.
    The ONLY way to get NapiProjekt subtitles is via hash from RD.
    """
    if napi_hash and len(napi_hash) == 32:
        return await download_by_napi_hash(napi_hash, file_size, language)

    if title:
        print(f"⚠️ Napi: title search disabled (Cloudflare 403). Tytuł: '{title}'")
        # Cannot search by title — Cloudflare blocks it from cloud servers
        return None

    return None
