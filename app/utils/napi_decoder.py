"""
NapiProjekt subtitle decoder — hash-based only.

NapiProjekt has NO title search API. The only way to get subtitles
is to provide the MD5 hash of the first 10MB of the video file.

Two endpoints:
  A) dl.php + subhash token (subliminal-style)
  B) api-napiprojekt3.php mode=1 (QNapi-style)
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


async def download_via_dl(napi_hash: str, language: str = "PL") -> str | None:
    """Method A: dl.php + subhash."""
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
    """Method B: api-napiprojekt3.php mode=1."""
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
            resp = await client.post(NAPI_API_URL, data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "other"})
            print(f"📡 API mode=1: status={resp.status_code} size={len(resp.content)}b")
            if resp.status_code != 200 or len(resp.content) < 100:
                return None

            text = resp.text
            # XML with base64 7z
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
            # Plain text SRT
            if re.search(r'\d{2}:\d{2}:\d{2}', text) and len(text) > 200:
                print(f"✅ API (text): OK!")
                return ensure_srt_format(text)
            # Raw 7z
            if resp.content[:2] in (b'7z', b'\x37\x7a'):
                srt = extract_7z_to_srt(resp.content)
                if srt:
                    print(f"✅ API (7z): OK!")
                    return srt

            print(f"ℹ️ API: nieznany format (first 60b: {resp.content[:60]})")
            return None
    except Exception as e:
        print(f"❌ API mode=1: {e}")
        return None


async def download_by_napi_hash(napi_hash: str, file_size: int = 0, language: str = "PL") -> str | None:
    """Try both methods."""
    if not napi_hash or len(napi_hash) != 32:
        print(f"⚠️ Invalid hash: '{napi_hash}'")
        return None

    print(f"🎯 Napi: pobieranie po hash {napi_hash}")
    result = await download_via_dl(napi_hash, language)
    if result:
        return result
    result = await download_via_api(napi_hash, file_size, language)
    if result:
        return result
    print(f"ℹ️ Napi: brak napisów dla {napi_hash}")
    return None


async def get_napi_subtitles_text(napi_hash: str = None, **kwargs) -> str | None:
    """Main entry point. Only hash-based — NapiProjekt has no title search API."""
    if napi_hash and len(napi_hash) == 32:
        return await download_by_napi_hash(napi_hash)
    return None
